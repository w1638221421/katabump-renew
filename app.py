#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import os
import time
import subprocess
import requests
from seleniumbase import SB

# 从环境变量获取账号密码和 企业微信 配置
EMAIL        = os.environ.get("KATABUMP_EMAIL") or ""    # 登录邮箱
PASSWORD     = os.environ.get("KATABUMP_PASSWORD") or "" # 账号密码

# ===== 企业微信通知配置（两种方式任选其一）=====
# 方式一（推荐）：群机器人 Webhook，填完整地址或只填 key
WECOM_WEBHOOK   = (os.environ.get("WECOM_WEBHOOK") or "").strip()
WECOM_KEY       = (os.environ.get("WECOM_KEY") or "").strip()

# 方式二：自建应用消息推送（需企业微信管理后台创建应用）
WECOM_CORPID    = (os.environ.get("WECOM_CORPID") or "").strip()
WECOM_CORPSECRET= (os.environ.get("WECOM_CORPSECRET") or "").strip()
WECOM_AGENTID   = (os.environ.get("WECOM_AGENTID") or "").strip()
WECOM_TOUSER    = (os.environ.get("WECOM_TOUSER") or "@all").strip()  # 成员账号，多个用 | 分隔

# 群机器人 @ 手机号（可选，多个用英文逗号分隔）
WECOM_MENTION_MOBILE = (os.environ.get("WECOM_MENTION_MOBILE") or "").strip()

BASE_URL = "https://dashboard.katabump.com"  # 网站链接
WECOM_API = "https://qyapi.weixin.qq.com/cgi-bin"

#  企业微信推送模块
def _masked_email() -> str:
    """邮箱脱敏：保留用户名前2位和后2位，中间用****代替"""
    if '@' in EMAIL:
        name, domain = EMAIL.split('@', 1)
        if len(name) > 4:
            return f"{name[:2]}****{name[-2:]}@{domain}"
        return f"{name}@{domain}"
    return EMAIL[:2] + '****' if EMAIL else '****'


def _wecom_webhook_url() -> str:
    """兼容三种写法：完整 webhook 地址 / 仅 key / 老式 ?key=xxx"""
    raw = WECOM_WEBHOOK or WECOM_KEY
    if not raw:
        return ""
    if raw.startswith("http"):
        return raw
    # 只填了 key 的情况
    return f"{WECOM_API}/webhook/send?key={raw}"


def _status_color(status_icon: str) -> str:
    if status_icon in ("✅",):
        return "info"
    if status_icon in ("⚠️", "⏳", "🔔"):
        return "warning"
    return "comment"


def _truncate_bytes(text: str, limit: int) -> str:
    """按字节截断，避免超出企业微信 4096 字节的消息上限"""
    raw = text.encode("utf-8")
    if len(raw) <= limit:
        return text
    return raw[:limit].decode("utf-8", "ignore") + "..."


def _build_wecom_markdown(status_icon, status_text, detail=""):
    """构造企业微信 markdown 消息体，返回 (markdown文本, 纯文本版)"""
    local_time = time.gmtime(time.time() + 8 * 3600)
    current_time_str = time.strftime("%Y-%m-%d %H:%M:%S", local_time)
    masked_email = _masked_email()
    color = _status_color(status_icon)
    detail = _truncate_bytes((detail or "").strip(), 600)

    md = (
        f"## 🇫🇷 katabump 续期通知\n"
        f"> 状态：<font color=\"{color}\">{status_icon} {status_text}</font>\n"
        f"**👤 续期账户：** {masked_email}\n"
        f"**⏱️ 续期时间：** {current_time_str}"
    )
    if detail:
        md += f"\n**📋 详情：** {detail}"

    plain = (
        f"katabump 续期通知\n"
        f"{status_icon} {status_text}\n"
        f"👤 续期账户: {masked_email}\n"
        f"⏱️ 续期时间: {current_time_str}"
    )
    if detail:
        plain += f"\n📋 详情: {detail}"
    return md, plain


def _wecom_get_token() -> str:
    """获取自建应用 access_token（有效期 7200s，进程内缓存）"""
    now = time.time()
    cached = getattr(_wecom_get_token, "_cache", None)
    if cached and cached[1] > now:
        return cached[0]
    r = requests.get(
        f"{WECOM_API}/gettoken",
        params={"corpid": WECOM_CORPID, "corpsecret": WECOM_CORPSECRET},
        timeout=10,
    )
    data = r.json()
    if data.get("errcode") != 0:
        raise RuntimeError(f"gettoken 失败: {data}")
    token = data["access_token"]
    _wecom_get_token._cache = (token, now + int(data.get("expires_in", 7200)) - 300)
    return token


def _send_by_webhook(md_text: str, plain_text: str):
    url = _wecom_webhook_url()
    mentions = [m.strip() for m in WECOM_MENTION_MOBILE.split(",") if m.strip()]
    if mentions:
        # 群机器人的 markdown 消息不支持 @ 成员，需要 @ 时改用 text 消息
        payload = {
            "msgtype": "text",
            "text": {"content": plain_text, "mentioned_mobile_list": mentions},
        }
    else:
        payload = {"msgtype": "markdown", "markdown": {"content": md_text}}

    r = requests.post(url, json=payload, timeout=10)
    try:
        data = r.json() if r.text else {}
    except ValueError:
        data = {}
    if data.get("errcode") == 0:
        print("📩 企业微信（群机器人）通知发送成功！")
        return True
    print(f"⚠️ 企业微信（群机器人）通知发送失败: {data or r.text[:200]}")
    return False


def _send_by_app(md_text: str):
    if not WECOM_AGENTID.isdigit():
        print(f"⚠️ WECOM_AGENTID 必须是数字，当前值: {WECOM_AGENTID!r}")
        return False
    token = _wecom_get_token()
    payload = {
        "touser": WECOM_TOUSER or "@all",
        "msgtype": "markdown",
        "agentid": int(WECOM_AGENTID),
        "markdown": {"content": md_text},
        "safe": 0,
        "duplicate_check_interval": 1800,
    }
    r = requests.post(f"{WECOM_API}/message/send", params={"access_token": token}, json=payload, timeout=10)
    try:
        data = r.json()
    except ValueError:
        data = {"errcode": -1, "errmsg": r.text[:200]}
    if data.get("errcode") == 0:
        print("📩 企业微信（应用消息）通知发送成功！")
        return True
    print(f"⚠️ 企业微信（应用消息）通知发送失败: {data}")
    return False


def send_wecom_message(status_icon, status_text, detail=""):
    """发送企业微信通知：优先群机器人 webhook，其次自建应用消息"""
    if not _wecom_webhook_url() and not (WECOM_CORPID and WECOM_CORPSECRET and WECOM_AGENTID):
        print("ℹ️ 未配置 WECOM_WEBHOOK（或 WECOM_KEY / 应用三件套），跳过企业微信推送。")
        return False

    md_text, plain_text = _build_wecom_markdown(status_icon, status_text, detail)
    try:
        if _wecom_webhook_url():
            return _send_by_webhook(md_text, plain_text)
        return _send_by_app(md_text)
    except Exception as e:
        print(f"⚠️ 企业微信通知发送异常: {e}")
        return False


#  页面注入脚本
_EXPAND_JS = """
(function() {
    var ts = document.querySelector('input[name="cf-turnstile-response"]');
    if (!ts) return 'no-turnstile';
    var el = ts;
    for (var i = 0; i < 20; i++) {
        el = el.parentElement;
        if (!el) break;
        var s = window.getComputedStyle(el);
        if (s.overflow === 'hidden' || s.overflowX === 'hidden' || s.overflowY === 'hidden')
            el.style.overflow = 'visible';
        el.style.minWidth = 'max-content';
    }
    document.querySelectorAll('iframe').forEach(function(f){
        if (f.src && f.src.includes('challenges.cloudflare.com')) {
            f.style.width = '300px'; f.style.height = '65px';
            f.style.minWidth = '300px';
            f.style.visibility = 'visible'; f.style.opacity = '1';
        }
    });
    return 'done';
})()
"""

_EXISTS_JS = """
(function(){
    return document.querySelector('input[name="cf-turnstile-response"]') !== null;
})()
"""

_SOLVED_JS = """
(function(){
    var i = document.querySelector('input[name="cf-turnstile-response"]');
    return !!(i && i.value && i.value.length > 20);
})()
"""

_WININFO_JS = """
(function(){
    return {
        sx: window.screenX || 0,
        sy: window.screenY || 0,
        oh: window.outerHeight,
        ih: window.innerHeight
    };
})()
"""

# ===== 自动续期相关 =====

# 在模态框内查找 iframe 并展开，返回点击坐标
_ALTCHA_EXPAND_JS = """
(function() {
    var modal = document.querySelector('div.modal.show') || document;
    var iframes = modal.querySelectorAll('iframe');
    for (var i = 0; i < iframes.length; i++) {
        var r = iframes[i].getBoundingClientRect();
        if (r.width > 0 && r.height > 0) {
            iframes[i].style.width  = '300px';
            iframes[i].style.height = '150px';
            iframes[i].style.minWidth  = '300px';
            iframes[i].style.minHeight = '150px';
            iframes[i].style.visibility = 'visible';
            iframes[i].style.opacity = '1';
            var el = iframes[i];
            for (var j = 0; j < 10; j++) {
                el = el.parentElement;
                if (!el) break;
                el.style.overflow = 'visible';
            }
            var r2 = iframes[i].getBoundingClientRect();
            return { cx: Math.round(r2.x + 30), cy: Math.round(r2.y + r2.height / 2) };
        }
    }
    return null;
})()
"""

# 检测 ALTCHA 是否已验证通过
_ALTCHA_SOLVED_JS = """
(function(){
    var modal = document.querySelector('div.modal.show') || document;
    // hidden input 有值
    var inputs = modal.querySelectorAll('input[type="hidden"]');
    for (var i = 0; i < inputs.length; i++) {
        var n = (inputs[i].name || '').toLowerCase();
        if ((n.includes('altcha') || n.includes('captcha')) &&
            inputs[i].value && inputs[i].value.length > 20) return true;
    }
    // checkbox 变为 disabled
    var cbs = modal.querySelectorAll('input[type="checkbox"]');
    for (var j = 0; j < cbs.length; j++) {
        if (cbs[j].disabled) return true;
    }
    // widget data-state 属性
    var w = modal.querySelector('[data-state="verified"],.altcha--verified,.altcha-verified');
    if (w) return true;
    return false;
})()
"""

#  底层输入工具
def js_fill_input(sb, selector: str, text: str):
    safe_text = text.replace('\\', '\\\\').replace('"', '\\"')
    sb.execute_script(f"""
    (function(){{
        var el = document.querySelector('{selector}');
        if (!el) return;
        var nativeInputValueSetter = Object.getOwnPropertyDescriptor(window.HTMLInputElement.prototype, "value").set;
        if (nativeInputValueSetter) {{
            nativeInputValueSetter.call(el, "{safe_text}");
        }} else {{
            el.value = "{safe_text}";
        }}
        el.dispatchEvent(new Event('input', {{ bubbles: true }}));
        el.dispatchEvent(new Event('change', {{ bubbles: true }}));
    }})()
    """)

def _activate_window():
    for cls in ["chrome", "chromium", "Chromium", "Chrome", "google-chrome"]:
        try:
            r = subprocess.run(["xdotool", "search", "--onlyvisible", "--class", cls], capture_output=True, text=True, timeout=3)
            wids = [w for w in r.stdout.strip().split("\n") if w.strip()]
            if wids:
                subprocess.run(["xdotool", "windowactivate", "--sync", wids[0]], timeout=3, stderr=subprocess.DEVNULL)
                time.sleep(0.2)
                return
        except Exception:
            pass
    try:
        subprocess.run(["xdotool", "getactivewindow", "windowactivate"], timeout=3, stderr=subprocess.DEVNULL)
    except Exception:
        pass

# def _xdotool_click(x: int, y: int):
#     _activate_window()
#     try:
#         subprocess.run(["xdotool", "mousemove", "--sync", str(x), str(y)], timeout=3, stderr=subprocess.DEVNULL)
#         time.sleep(0.15)
#         subprocess.run(["xdotool", "click", "1"], timeout=2, stderr=subprocess.DEVNULL)
#     except Exception:
#         os.system(f"xdotool mousemove {x} {y} click 1 2>/dev/null")

#  人机验证处理（使用 SeleniumBase 内置 uc_gui_click_captcha）
def handle_turnstile(sb) -> bool:
    print("🔍 处理 Cloudflare Turnstile 验证...")
    time.sleep(2)

    # 检查是否已静默通过
    if sb.execute_script(_SOLVED_JS):
        print("✅ 已静默通过")
        return True

    # 尝试展开 Turnstile（防止被父容器 overflow:hidden 裁剪）
    for _ in range(3):
        try: sb.execute_script(_EXPAND_JS)
        except Exception: pass
        time.sleep(0.5)

    # 使用 SeleniumBase 内置 uc_gui_click_captcha 处理 Turnstile
    # 该方法自动完成：检测验证码类型 → 定位 iframe → 计算坐标 → PyAutoGUI 平滑点击
    for attempt in range(6):
        if sb.execute_script(_SOLVED_JS):
            print(f"✅ Turnstile 通过（第 {attempt} 次尝试）")
            return True

        print(f"🖱️ 第 {attempt + 1} 次调用 uc_gui_click_captcha...")
        try:
            sb.uc_gui_click_captcha()
        except Exception as e:
            print(f"⚠️ uc_gui_click_captcha 调用异常: {e}")

        # 等待验证结果（最多 8 秒）
        for _ in range(16):
            time.sleep(0.5)
            if sb.execute_script(_SOLVED_JS):
                print(f"✅ Turnstile 通过（第 {attempt + 1} 次尝试）")
                return True

        print(f"⚠️ 第 {attempt + 1} 次未通过，重试...")

    print("  ❌ Turnstile 6 次均失败")
    return False

#  账户登录
def login(sb) -> bool:
    print(f"🌐 打开登录页面: {BASE_URL}/auth/login")
    sb.uc_open_with_reconnect(BASE_URL + "/auth/login", reconnect_time=8)
    time.sleep(8)

    # 先等待 Cloudflare 验证通过（最多等 30 秒）
    print("⏳ 等待 Cloudflare 验证通过...")
    cf_passed = False
    for i in range(30):
        page_src = sb.get_page_source() or ""
        if 'input[name="email"]' in page_src.lower() or 'name="email"' in page_src.lower():
            cf_passed = True
            print(f"✅ Cloudflare 验证已通过（{i+1}s）")
            break
        time.sleep(1)
    if not cf_passed:
        print("⚠️ Cloudflare 验证可能未通过，继续尝试...")

    try:
        sb.wait_for_element('input[type="email"]', timeout=15)
    except Exception:
        # 尝试大写选择器作为后备
        try:
            sb.wait_for_element('input[type="Email"]', timeout=5)
        except Exception:
            print("❌ 页面未加载出登录表单")
            cur_url = sb.get_current_url()
            page_title = sb.get_title() or ""
            print(f"  当前 URL: {cur_url}")
            print(f"  当前标题: {page_title}")
            sb.save_screenshot("login_load_fail.png")
            return False

    print("🍪 关闭可能的 Cookie 弹窗...")
    try:
        for btn in sb.find_elements("button"):
            if "Accept" in (btn.text or ""):
                btn.click()
                time.sleep(0.5)
                break
    except Exception:
        pass

    print(f"📧 填写邮箱...")
    js_fill_input(sb, 'input[type="email"]', EMAIL)
    time.sleep(1)
    
    print("🔑 填写密码...")
    js_fill_input(sb, 'input[type="password"]', PASSWORD)
    time.sleep(3)

    # 等待 Turnstile 验证框出现（最多 10 秒）
    print("⏳ 等待 Turnstile 验证框出现...")
    ts_found = False
    for i in range(10):
        if sb.execute_script(_EXISTS_JS):
            ts_found = True
            print(f"✅ 检测到 Turnstile（{i+1}s）")
            break
        time.sleep(1)

    if ts_found:
        if not handle_turnstile(sb):
            print("❌ 登录界面的 Turnstile 验证失败")
            sb.save_screenshot("login_turnstile_fail.png")
            return False
    else:
        print("ℹ️ 未检测到 Turnstile")

    print("🖱️ 敲击回车提交表单...")
    sb.press_keys('input[name="password"]', '\n')

    print("⏳ 等待登录跳转...")
    for _ in range(12):
        time.sleep(1)
        cur_url = sb.get_current_url().split('?')[0].lower()
        page_title = sb.get_title() or ""
        if cur_url.startswith(f"{BASE_URL}/dashboard") or "Dashboard | KataBump" in page_title.lower():
            break

    cur_url = sb.get_current_url().split('?')[0].lower()
    page_title = sb.get_title() or ""
    if cur_url.startswith(f"{BASE_URL}/dashboard") or "Dashboard | KataBump" in page_title.lower():
        print(f"✅ 登录成功！(URL: {sb.get_current_url()}, Title: {page_title})")
        return True
        
    print(f"❌ 登录失败，页面未跳转到账户页。(URL: {sb.get_current_url()}, Title: {page_title})")
    sb.save_screenshot("login_failed.png")
    return False

# ===== 自动续期流程 =====

def _read_alert(sb):
    """读取页面第一个 Bootstrap alert 的文本，找不到返回空串"""
    try:
        el = sb.find_element("div.alert", timeout=4)
        return (el.text or "").strip()
    except Exception:
        return ""


def _goto_server_detail(sb) -> bool:
    """在 Dashboard 首页查找并点击 See 进入服务器详情页"""
    print("\n🖥️  正在进入服务器续期页...")
    time.sleep(5)

    # 检查页面顶部是否已有"还无法续期"全局提示
    alert_text = _read_alert(sb)
    if alert_text and "can't renew" in alert_text.lower():
        print(f"ℹ️  页面顶部提示: {alert_text}")
        send_wecom_message("ℹ️", "⚠️ 未到续期时间", alert_text)
        return False

    # 多种选择器尝试查找 See 链接
    selectors = [
        'a[href*="/servers/edit?id="]',
        'td a[href*="/servers/edit"]',
        'table a[href*="/servers/edit"]',
        'table td a',
    ]

    see_link = None
    for sel in selectors:
        try:
            see_link = sb.find_element(sel, timeout=8)
            print(f"✅ 通过选择器找到链接: {sel}")
            break
        except Exception:
            continue

    # 选择器全部失败，尝试通过文本内容查找
    if see_link is None:
        print("⚠️ 选择器未命中，尝试文本匹配...")
        try:
            for a in sb.find_elements("a"):
                if (a.text or "").strip().lower() == "see":
                    see_link = a
                    print("✅ 通过文本 'See' 找到链接")
                    break
        except Exception:
            pass

    if see_link is None:
        # 打印调试信息帮助排查
        cur_url = sb.get_current_url()
        title = sb.get_title() or ""
        print(f"❌ 未找到 'See' 链接")
        print(f"当前 URL: {cur_url}")
        print(f"页面标题: {title}")
        try:
            links = sb.find_elements("a")
            print(f"     页面共 {len(links)} 个链接:")
            for a in links[:20]:
                href = a.get_attribute("href") or ""
                txt  = (a.text or "").strip()[:30]
                if href:
                    print(f"       - [{txt}] -> {href}")
        except Exception:
            pass
        sb.save_screenshot("servers_page_fail.png")
        return False

    print("🖱️  点击 'See' 进入服务器详情页...")
    see_link.click()
    time.sleep(5)
    print(f"📄 当前页面: {sb.get_current_url()}")
    return True


def _open_renew_modal(sb) -> bool:
    """滚动到 Renew 按钮并点击，打开模态框"""
    print("\n🔄 查找 Renew 按钮...")
    try:
        renew_btn = sb.find_element('button[data-bs-target="#renew-modal"]', timeout=10)
    except Exception:
        try:
            renew_btn = sb.find_element('button.btn.btn-outline-primary', timeout=5)
        except Exception:
            print("  ❌ 未找到 Renew 按钮")
            return False

    sb.execute_script("""
        (function(){
            var btn = document.querySelector('button[data-bs-target="#renew-modal"]')
                     || document.querySelector('button.btn.btn-outline-primary');
            if (btn) btn.scrollIntoView({behavior:'smooth',block:'center'});
        })()
    """)
    time.sleep(0.8)
    renew_btn.click()
    print("🖱️ 已点击 Renew 按钮，等待确认框...")
    time.sleep(3)

    try:
        sb.find_element('div.modal.show', timeout=5)
        print("✅ Renew 模态框已弹出")
        return True
    except Exception:
        print("⚠️ 模态框未弹出")
        return False


# def _solve_altcha(sb) -> bool:
#     """处理 ALTCHA 人机验证"""
#     print("\n🔐 处理 ALTCHA 人机验证...")
#     time.sleep(2)
#
#     # 先检查是否已自动通过
#     if sb.execute_script(_ALTCHA_SOLVED_JS):
#         print("✅ ALTCHA 已自动通过")
#         return True
#
#     # 展开模态框内 iframe 并获取坐标
#     coords = None
#     try:
#         coords = sb.execute_script(_ALTCHA_EXPAND_JS)
#     except Exception:
#         pass
#
#     if coords:
#         print(f"  📍 找到模态框内 iframe 坐标: ({coords['cx']}, {coords['cy']})")
#
#     # 最多尝试 3 轮
#     for attempt in range(3):
#         if sb.execute_script(_ALTCHA_SOLVED_JS):
#             print(f"✅ ALTCHA 验证通过（第 {attempt + 1} 轮）")
#             return True
#
#         # 策略 1: xdotool 物理点击 iframe 坐标
#         if coords:
#             try:
#                 wi = sb.execute_script(_WININFO_JS)
#             except Exception:
#                 wi = {"sx": 0, "sy": 0, "oh": 800, "ih": 768}
#             bar = wi["oh"] - wi["ih"]
#             ax  = coords["cx"] + wi["sx"]
#             ay  = coords["cy"] + wi["sy"] + bar
#             print(f"🖱️  ALTCHA点击复选框  ({ax}, {ay})")
#             _xdotool_click(ax, ay)
#
#         # 策略 2: SeleniumBase 原生点击模态框内 iframe 元素
#         try:
#             iframes = sb.find_elements('div.modal.show iframe')
#             for iframe in iframes:
#                 try:
#                     iframe.click()
#                     print("🖱️  SeleniumBase 点击模态框 iframe")
#                 except Exception:
#                     pass
#         except Exception:
#             pass
#
#         # 策略 3: JS 遍历模态框内所有可点击元素
#         sb.execute_script("""
#             (function(){
#                 var modal = document.querySelector('div.modal.show');
#                 if (!modal) return;
#                 // 点击 iframe
#                 var iframes = modal.querySelectorAll('iframe');
#                 for (var i = 0; i < iframes.length; i++) {
#                     iframes[i].click();
#                     iframes[i].dispatchEvent(new MouseEvent('click', {bubbles:true}));
#                 }
#                 // 点击含 checkbox 的 label
#                 var labels = modal.querySelectorAll('label');
#                 for (var j = 0; j < labels.length; j++) {
#                     var txt = (labels[j].textContent || '').toLowerCase();
#                     if (txt.includes('robot') || txt.includes('captcha') || txt.includes('verify'))
#                         labels[j].click();
#                 }
#                 // 点击 checkbox
#                 var cbs = modal.querySelectorAll('input[type="checkbox"]');
#                 for (var k = 0; k < cbs.length; k++) {
#                     if (!cbs[k].disabled) {
#                         cbs[k].click();
#                         cbs[k].dispatchEvent(new MouseEvent('click', {bubbles:true}));
#                     }
#                 }
#             })()
#         """)
#
#         # 等待验证结果
#         for _ in range(6):
#             time.sleep(1)
#             if sb.execute_script(_ALTCHA_SOLVED_JS):
#                 print(f"✅ ALTCHA 验证通过（第 {attempt + 1} 轮）")
#                 return True
#
#         print(f"  ⚠️ 第 {attempt + 1} 轮未通过，重试...")
#         # 重新获取坐标（iframe 可能已重新渲染）
#         try:
#             new_coords = sb.execute_script(_ALTCHA_EXPAND_JS)
#             if new_coords:
#                 coords = new_coords
#         except Exception:
#             pass
#
#     print("  ❌ ALTCHA 3 轮均失败")
#     return False


def _submit_renew(sb):
    """点击模态框内的 Renew 提交按钮"""
    print("🖱️  点击模态框中的 Renew 按钮...")
    try:
        submit = sb.find_element('div.modal-footer button.btn.btn-primary', timeout=10)
        submit.click()
    except Exception:
        sb.execute_script("""
            (function(){
                var m = document.querySelector('button.btn.btn-primary');
                if (!m) return;
                var bs = m.querySelectorAll('button');
                for (var i = 0; i < bs.length; i++)
                    if (/renew/i.test(bs[i].textContent)) bs[i].click();
            })()
        """)
    time.sleep(8)


def _check_renew_result(sb):
    """读取页面 alert 提示，判断续期结果并推送企业微信通知"""
    print("\n📋 检查续期结果...")
    alert_text = _read_alert(sb)
    if not alert_text:
        time.sleep(3)
        alert_text = _read_alert(sb)

    if alert_text:
        print(f"📩 页面提示: {alert_text}")
        low = alert_text.lower()
        if "can't renew" in low or "unable" in low:
            send_wecom_message("⏳", "未到续期时间", alert_text)
        elif any(kw in low for kw in ( "renewed", "success", "extended")):
            send_wecom_message("✅", "续期成功", alert_text)
        else:
            send_wecom_message("ℹ️", "续期操作已执行", alert_text)
    else:
        print("ℹ️ 未检测到明确的提示框，可能续期操作未生效")
        send_wecom_message("ℹ️", "续期操作已执行", "未检测到明确提示")


def renew_server(sb):
    """登录成功后调用：自动进入详情页 -> Renew -> ALTCHA -> 提交"""
    print("\n" + "#" * 25)
    print("  开始自动续期流程")
    print("#" * 25)

    if not _goto_server_detail(sb):
        return

    if not _open_renew_modal(sb):
        return

    # altcha_ok = _solve_altcha(sb)
    # if not altcha_ok:
    #     print("⚠️ ALTCHA 验证未通过，仍尝试提交 Renew...")

    _submit_renew(sb)
    _check_renew_result(sb)


#  脚本执行入口 (可选代理)
def main():
    print("#" * 25)
    print("   katabump 自动登录续期")
    print("#" * 25)

    IS_PROXY = os.environ.get("IS_PROXY", "false").lower() == "true"
    proxy_str = os.environ.get("PROXY_SERVER", "").strip() or "http://127.0.0.1:1081"
    sb_kwargs = {"uc": True, "headless": False}

    if IS_PROXY:
        print(f"🔗 挂载代理: {proxy_str}")
        sb_kwargs["proxy"] = proxy_str
    else:
        print("🌐 未使用代理，直连访问")
    
    print("🚀 启动浏览器...")
    with SB(**sb_kwargs) as sb:
        # print("✅ 浏览器已启动")
        try:
            sb.open("https://api.ip.sb/ip")
            print(f"📍  当前出口IP: {sb.get_text('body')}")
        except Exception:
            pass

        if login(sb):
            renew_server(sb)   # 登录成功后自动续期
        else:
            print("\n❌ 登录失败，终止后续续期操作。")
            send_wecom_message("❌", "登录失败", "未知")

def test_notify():
    """只发一条测试通知，用来验证企业微信配置是否正确：python3 app.py --test-notify"""
    print("🧪 发送企业微信测试通知...")
    ok = send_wecom_message("✅", "测试通知", "这是一条来自 katabump-renew 的测试消息")
    print("✅ 测试通知已发送" if ok else "❌ 测试通知发送失败，请检查环境变量配置")
    return 0 if ok else 1


if __name__ == "__main__":
    import sys
    if "--test-notify" in sys.argv:
        sys.exit(test_notify())
    main()
