#!/usr/bin/env python3
"""
FreezeHost AFK - 自动挂机赚币脚本（支持多实例）
使用 SeleniumBase UC 模式
"""
import os
import time
import platform
from seleniumbase import SB

# Discord Token - 从环境变量读取，支持多个（逗号分隔）
DISCORD_TOKEN = os.environ.get("DISCORD_TOKEN", "")

# WARP 代理地址（默认留空，避免未启动 WARP 时连接超时卡死；需要时通过环境变量传入）
WARP_PROXY = os.environ.get("WARP_PROXY", "").strip()

# 最大运行时长（分钟），0 = 无限
MAX_RUNTIME = int(os.environ.get("MAX_RUNTIME", "0"))

# 每个 session 赚币时长（秒）
SESSION_DURATION = 1200  # 20 分钟

# 实例编号（从环境变量获取）
INSTANCE_ID = int(os.environ.get("INSTANCE_ID", "0"))
LOG_FILE = os.environ.get("LOG_FILE", "")

global_start = 0.0


def log(msg):
    """带时间戳和实例编号的日志"""
    ts = time.strftime("%H:%M:%S")
    prefix = "[I%d]" % INSTANCE_ID if INSTANCE_ID else ""
    line = "[%s] %s %s" % (ts, prefix, msg)
    print(line, flush=True)
    if LOG_FILE:
        try:
            with open(LOG_FILE, "a") as f:
                f.write(line + "\n")
        except Exception:
            pass


def is_max_runtime_reached():
    return MAX_RUNTIME > 0 and (time.time() - global_start) > MAX_RUNTIME * 60


def wait_turnstile(sb, timeout=120):
    start = time.time()
    last_click = 0
    while time.time() - start < timeout:
        try:
            val = sb.execute_script(
                "return document.querySelector('[name=cf-turnstile-response]')?.value || '';"
            )
            if val and len(str(val)) > 20:
                return str(val)
        except Exception:
            pass
        now = time.time()
        if now - last_click > 5:
            try:
                sb.uc_gui_click_captcha()
                last_click = now
            except Exception:
                pass
        time.sleep(2)
    return None


def login_via_discord_token(sb, token):
    log("Opening FreezeHost...")
    sb.uc_open_with_reconnect("https://free.freezehost.pro", reconnect_time=5)
    time.sleep(5)

    # 如果已经处于登录状态，直接返回
    if sb.get_current_url().startswith("https://free.freezehost.pro") and not sb.is_element_present("#login-btn"):
        log("Already logged in!")
        return True

    try:
        sb.wait_for_element_visible("button#login-btn", timeout=10)
        sb.click("button#login-btn")
    except Exception:
        sb.execute_script("document.getElementById('login-btn')?.click();")
    time.sleep(3)

    try:
        sb.wait_for_element_visible("button#confirm-login", timeout=5)
        sb.click("button#confirm-login")
        log("Confirmed terms")
    except Exception:
        log("No terms dialog")
    time.sleep(3)

    if "discord.com" in sb.get_current_url():
        log("Inject token...")
        sb.execute_script("""(function(){
            var token = "%s";
            var f = document.createElement("iframe");
            f.style.display = "none";
            document.body.appendChild(f);
            try { f.contentWindow.localStorage.setItem("token", '"'+token+'"'); } catch(e) {}
            try { localStorage.setItem("token", '"'+token+'"'); } catch(e) {}
            document.body.removeChild(f);
        })();""" % token)

        log("Reload...")
        sb.driver.refresh()
        time.sleep(8)

        url = sb.get_current_url()
        if "discord.com/login" in url:
            log("Token invalid!")
            return False

        if "discord.com/oauth2" in url:
            log("Auto-authorize...")
            sb.execute_script("""(function(){
                document.querySelectorAll("button").forEach(function(btn){
                    if(btn.textContent.toLowerCase().includes("authorize")) btn.click();
                });
            })();""")
            time.sleep(5)

        for _ in range(20):
            url = sb.get_current_url()
            if url.startswith("https://free.freezehost.pro"):
                break
            time.sleep(2)

    url = sb.get_current_url()
    log("Login URL: %s" % url)
    # 确认域名正确且登录按钮已消失，避免假登录成功
    is_logged_in = url.startswith("https://free.freezehost.pro") and not sb.is_element_present("#login-btn")
    return is_logged_in


def click_start_afk(sb):
    log("Bypassing adblocker...")
    try:
        sb.execute_script("""
            if(typeof adblockerDetected !== 'undefined') adblockerDetected = false;
            var msg = document.getElementById('adblocker-message');
            if(msg) msg.style.display = 'none';
        """)
    except Exception:
        pass

    try:
        sb.execute_script("""
            var btn = document.getElementById('start-afk-btn');
            if(btn){ btn.disabled = false; btn.textContent = 'Start AFK Session'; }
        """)
    except Exception:
        pass

    for attempt in range(3):
        try:
            sb.wait_for_element_visible("#start-afk-btn", timeout=5)
            sb.click("#start-afk-btn")
            log("Clicked Start AFK!")
            time.sleep(3)
            ws_state = sb.execute_script(
                "return (typeof ws !== 'undefined' && ws) ? ws.readyState : -1;"
            )
            log("WebSocket state: %s" % ws_state)
            return True
        except Exception as e:
            log("Attempt %d: %s" % (attempt + 1, str(e)[:80]))
            try:
                sb.execute_script("""
                    if(typeof adblockerDetected !== 'undefined') adblockerDetected = false;
                    document.getElementById('start-afk-btn')?.click();
                """)
                time.sleep(3)
                ws_state = sb.execute_script(
                    "return (typeof ws !== 'undefined' && ws) ? ws.readyState : -1;"
                )
                log("JS click - WS state: %s" % ws_state)
                if ws_state in (0, 1):
                    return True
            except Exception:
                pass
    return False


def run_earn_session(sb, session_num, token):
    log("Loading /earn...")
    # 改用普通 open，减少 UC 反复断连导致的 ChromeDriver 崩溃
    sb.open("https://free.freezehost.pro/earn")
    time.sleep(10)

    url = sb.get_current_url()
    if not url.startswith("https://free.freezehost.pro") or sb.is_element_present("#login-btn"):
        log("Session expired, re-login...")
        if not login_via_discord_token(sb, token):
            return False
        sb.open("https://free.freezehost.pro/earn")
        time.sleep(10)

    log("Waiting Turnstile...")
    token_val = wait_turnstile(sb, timeout=120)
    if not token_val:
        log("Turnstile failed!")
        try:
            sb.save_screenshot("/tmp/fh_fail_%d_%d.png" % (INSTANCE_ID, session_num))
        except Exception:
            pass
        return False

    log("Turnstile OK! Token: %s..." % token_val[:30])

    if not click_start_afk(sb):
        log("WARNING: Start AFK button click failed!")

    log("Earning for %ds..." % SESSION_DURATION)
    start = time.time()
    while time.time() - start < SESSION_DURATION:
        try:
            url = sb.get_current_url()
            if not url.startswith("https://free.freezehost.pro"):
                log("Expired during earning")
                break
        except Exception:
            break

        if is_max_runtime_reached():
            log("Max runtime reached!")
            return None

        time.sleep(30)

    log("Session #%d done" % session_num)
    return True


def main():
    global global_start

    if not DISCORD_TOKEN:
        print("ERROR: DISCORD_TOKEN not set!")
        print("Set via: export DISCORD_TOKEN='your_token'")
        return

    # 支持多个 token（逗号分隔），按实例编号选
    tokens = [t.strip() for t in DISCORD_TOKEN.split(",") if t.strip()]
    token = tokens[INSTANCE_ID % len(tokens)]

    log("=" * 50)
    log("FreezeHost AFK - Instance #%d" % INSTANCE_ID)
    log("Token: %s...%s" % (token[:10], token[-5:]))
    log("Proxy: %s" % (WARP_PROXY or "none"))
    log("=" * 50)

    global_start = time.time()

    sb_options = {
        "uc": True,
        "test": True,
        "xvfb": platform.system().lower() == "linux",
        "chromium_arg": "--no-sandbox,--disable-dev-shm-usage,--disable-gpu,--window-size=1280,720",
    }

    if WARP_PROXY:
        sb_options["proxy"] = WARP_PROXY

    session = 0
    while not is_max_runtime_reached():
        try:
            with SB(**sb_options) as sb:
                if not login_via_discord_token(sb, token):
                    log("Login failed! Retrying in 15s...")
                    time.sleep(15)
                    continue
                log("Login OK!")

                while not is_max_runtime_reached():
                    session += 1
                    log("")
                    log("=== Session #%d ===" % session)

                    result = run_earn_session(sb, session, token)
                    if result is None:
                        return
                    if not result:
                        log("Session failed, retrying...")

                    time.sleep(5)
        except Exception as e:
            # 捕获 ChromeDriver 崩溃 / ConnectionRefusedError，自动拉起新浏览器实例
            log("Browser/Driver crashed: %s" % str(e)[:150])
            if is_max_runtime_reached():
                break
            log("Restarting browser in 10s...")
            time.sleep(10)

    log("Done!")


if __name__ == "__main__":
    main()
