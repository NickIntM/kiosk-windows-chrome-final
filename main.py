import sys
import os
import time
import tempfile
import traceback
import logging
import subprocess
import threading
from selenium import webdriver
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.chrome.options import Options
from selenium.common.exceptions import WebDriverException


# ---------------- Logging ----------------
def setup_logger(enable_log=True):
    base_dir = (
        os.path.dirname(sys.executable)
        if getattr(sys, 'frozen', False)
        else os.path.dirname(os.path.abspath(__file__))
    )
    log_file = os.path.join(base_dir, "debug_log.txt")

    logger = logging.getLogger()

    if not enable_log:
        logger.setLevel(logging.CRITICAL + 1)
        logger.addHandler(logging.NullHandler())
        return log_file

    logger.setLevel(logging.DEBUG)
    fmt = logging.Formatter("%(asctime)s [%(levelname)s] %(message)s")

    fh = logging.FileHandler(log_file, mode="w", encoding="utf-8")
    fh.setLevel(logging.DEBUG)
    fh.setFormatter(fmt)

    ch = logging.StreamHandler(sys.stdout)
    ch.setLevel(logging.DEBUG)
    ch.setFormatter(fmt)

    logger.addHandler(fh)
    logger.addHandler(ch)

    for noisy in ("urllib3", "urllib3.connectionpool", "selenium.webdriver.remote.remote_connection"):
        logging.getLogger(noisy).setLevel(logging.WARNING)

    logging.info("=== ΕΚΚΙΝΗΣΗ ΠΡΟΓΡΑΜΜΑΤΟΣ ===")
    logging.info(f"Log αρχείο: {log_file}")
    return log_file


# ---------------- Utilities ----------------
def resource_path(relative_path):
    base_path = getattr(sys, 'frozen', False) and sys._MEIPASS or os.path.dirname(__file__)
    return os.path.join(base_path, relative_path)


def _path_to_url(path):
    """Μετατρέπει local path σε file:// URL. http/https/file URLs επιστρέφονται ως έχουν."""
    path = path.strip()
    if path.lower().startswith(("http://", "https://", "file://")):
        return path
    path = path.replace('\\', '/')
    if not path.startswith("/"):
        path = "/" + path
    return "file://" + path


def load_url():
    """
    Διαβάζει το πρώτο URL ή local path από το urls.txt.
    Αν δεν υπάρχει το αρχείο, χρησιμοποιεί το default_url.
    """
    default_url = "C:/Users/IT/Documents/kiosk/k.html"
    base_dir = (
        os.path.dirname(sys.executable)
        if getattr(sys, 'frozen', False)
        else os.path.dirname(os.path.abspath(__file__))
    )
    file_path = os.path.join(base_dir, "urls.txt")

    try:
        if os.path.exists(file_path):
            with open(file_path, "r", encoding="utf-8") as f:
                lines = [line.strip() for line in f if line.strip()]
                if lines:
                    url = _path_to_url(lines[0])
                    logging.info(f"Φορτώθηκε URL από urls.txt: {url}")
                    return url
    except Exception as e:
        logging.error(f"Σφάλμα ανάγνωσης urls.txt: {e}")

    url = _path_to_url(default_url)
    logging.info(f"Χρήση default URL: {url}")
    return url


def load_config():
    """
    Διαβάζει το config.txt και επιστρέφει τις παραμέτρους.
    """
    base_dir = (
        os.path.dirname(sys.executable)
        if getattr(sys, 'frozen', False)
        else os.path.dirname(os.path.abspath(__file__))
    )
    file_path = os.path.join(base_dir, "config.txt")
    exit_password     = "854712"
    keyboard_timeout  = 30
    enable_log        = True
    default_lang      = "en"
    url               = None
    cm_offset         = 0
    watchdog_interval = 120
    freeze_timeout    = 5
    freeze_retries    = 2

    try:
        if os.path.exists(file_path):
            with open(file_path, "r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if not line or line.startswith("#"):
                        continue
                    if line.lower().startswith("pass:"):
                        exit_password = line.split(":", 1)[1].strip()
                    elif line.lower().startswith("key:"):
                        try:
                            keyboard_timeout = int(line.split(":", 1)[1].strip())
                        except ValueError:
                            pass
                    elif line.lower().startswith("log:"):
                        try:
                            enable_log = int(line.split(":", 1)[1].strip()) != 0
                        except ValueError:
                            pass
                    elif line.lower().startswith("el:"):
                        try:
                            default_lang = "el" if int(line.split(":", 1)[1].strip()) != 0 else "en"
                        except ValueError:
                            pass
                    elif line.lower().startswith("url:"):
                        url = line.split(":", 1)[1].strip()
                    elif line.lower().startswith("cm:"):
                        try:
                            cm_offset = float(line.split(":", 1)[1].strip())
                        except ValueError:
                            pass
                    elif line.lower().startswith("watchdog:"):
                        try:
                            watchdog_interval = int(line.split(":", 1)[1].strip())
                        except ValueError:
                            pass
                    elif line.lower().startswith("freeze_timeout:"):
                        try:
                            freeze_timeout = int(line.split(":", 1)[1].strip())
                        except ValueError:
                            pass
                    elif line.lower().startswith("freeze_retries:"):
                        try:
                            freeze_retries = int(line.split(":", 1)[1].strip())
                        except ValueError:
                            pass
    except Exception as e:
        print(f"[CONFIG] Σφάλμα ανάγνωσης config.txt: {e}")

    return exit_password, keyboard_timeout, enable_log, default_lang, url, cm_offset, watchdog_interval, freeze_timeout, freeze_retries


# ---------------- Virtual Keyboard (In-Page Overlay) ----------------
KEYBOARD_JS = """
(function() {
    if (document.getElementById('__vkb_overlay')) return;

    var LAYOUTS = {
        en_lower: [
            ['1','2','3','4','5','6','7','8','9','0','⌫'],
            ['q','w','e','r','t','y','u','i','o','p'],
            ['a','s','d','f','g','h','j','k','l','↵'],
            ['⇧','z','x','c','v','b','n','m',',','.','⇧'],
            ['EN/EL', '@','_','-','SPACE','!','?','✕']
        ],
        en_upper: [
            ['1','2','3','4','5','6','7','8','9','0','⌫'],
            ['Q','W','E','R','T','Y','U','I','O','P'],
            ['A','S','D','F','G','H','J','K','L','↵'],
            ['⇧','Z','X','C','V','B','N','M',',','.','⇧'],
            ['EN/EL', '@','_','-','SPACE','!','?','✕']
        ],
        el_lower: [
            ['1','2','3','4','5','6','7','8','9','0','⌫'],
            ['ς','ε','ρ','τ','υ','θ','ι','ο','π'],
            ['α','σ','δ','φ','γ','η','ξ','κ','λ','↵'],
            ['⇧','ζ','χ','ψ','ω','β','ν','μ',',','.','⇧'],
            ['EN/EL', '@','_','-','SPACE','!','?','✕']
        ],
        el_upper: [
            ['1','2','3','4','5','6','7','8','9','0','⌫'],
            ['Σ','Ε','Ρ','Τ','Υ','Θ','Ι','Ο','Π'],
            ['Α','Σ','Δ','Φ','Γ','Η','Ξ','Κ','Λ','↵'],
            ['⇧','Ζ','Χ','Ψ','Ω','Β','Ν','Μ',',','.','⇧'],
            ['EN/EL', '@','_','-','SPACE','!','?','✕']
        ]
    };

    var lang    = 'en';
    var shifted = false;
    var autoCloseTimer = null;
    var VKB_TIMEOUT_MS = 30000;

    var style = document.createElement('style');
    style.textContent = [
        '#__vkb_overlay{',
        '  position:fixed;bottom:var(--vkb-bottom,0cm);left:0;right:0;',
        '  background:#1a1a2e;border-top:2px solid #4a4a8a;',
        '  padding:8px 6px 12px;z-index:2147483647;display:none;',
        '  box-shadow:0 -4px 24px rgba(0,0,0,.5);',
        '  touch-action:manipulation;user-select:none;',
        '}',
        '#__vkb_overlay .vkb-row{display:flex;justify-content:center;gap:4px;margin-bottom:4px;}',
        '#__vkb_overlay button{',
        '  background:#2d2d5e;color:#fff;border:1px solid #4a4a8a;',
        '  border-radius:7px;font-size:17px;font-family:sans-serif;',
        '  height:48px;min-width:40px;padding:0 8px;cursor:pointer;',
        '  flex:1;max-width:68px;touch-action:manipulation;',
        '  transition:background .08s;-webkit-tap-highlight-color:transparent;',
        '}',
        '#__vkb_overlay button:active,#__vkb_overlay button.vkb-pressed{background:#5555aa;}',
        '#__vkb_overlay button[data-k="SPACE"]{flex:5;max-width:280px;font-size:13px;}',
        '#__vkb_overlay button[data-k="⌫"],',
        '#__vkb_overlay button[data-k="↵"],',
        '#__vkb_overlay button[data-k="⇧"]{background:#3a3a7a;flex:1.5;}',
        '#__vkb_overlay button[data-k="EN/EL"]{background:#2a5a2a;font-size:13px;flex:1.5;}',
        '#__vkb_overlay button[data-k="✕"]{background:#6a1a1a;font-size:20px;flex:1.2;}',
        '#__vkb_overlay button.vkb-shifted{background:#5a3a9a!important;}',
        '#__vkb_overlay button.vkb-lang-active{background:#1a6a1a!important;}',
        '#__vkb_timer_bar{height:3px;background:#4a4a8a;transition:width linear;}',
        '#__vkb_timer_wrap{background:#111130;height:3px;width:100%;margin-bottom:6px;border-radius:2px;overflow:hidden;}'
    ].join('');
    document.head.appendChild(style);

    var overlay = document.createElement('div');
    overlay.id  = '__vkb_overlay';

    var timerWrap = document.createElement('div');
    timerWrap.id  = '__vkb_timer_wrap';
    var timerBar  = document.createElement('div');
    timerBar.id   = '__vkb_timer_bar';
    timerBar.style.width = '100%';
    timerWrap.appendChild(timerBar);
    overlay.appendChild(timerWrap);

    document.body.appendChild(overlay);

    function currentLayout() {
        return LAYOUTS[lang + (shifted ? '_upper' : '_lower')];
    }

    function buildRows() {
        var old = overlay.querySelectorAll('.vkb-row');
        old.forEach(function(r){ overlay.removeChild(r); });

        currentLayout().forEach(function(keys) {
            var row = document.createElement('div');
            row.className = 'vkb-row';
            keys.forEach(function(k) {
                var btn = document.createElement('button');
                btn.textContent = (k === 'SPACE') ? '     ' : k;
                btn.setAttribute('data-k', k);
                btn.setAttribute('tabindex', '-1');

                if (k === '⇧' && shifted)   btn.classList.add('vkb-shifted');
                if (k === 'EN/EL' && lang === 'el') btn.classList.add('vkb-lang-active');

                btn.addEventListener('pointerdown', function(e){ e.preventDefault(); }, {passive:false});
                btn.addEventListener('pointerup',   function(e){ e.preventDefault(); handleKey(k, this); }, {passive:false});
                row.appendChild(btn);
            });
            overlay.appendChild(row);
        });
    }

    function startAutoClose() {
        clearAutoClose();
        if (!VKB_TIMEOUT_MS || VKB_TIMEOUT_MS <= 0) return;

        timerBar.style.transition = 'none';
        timerBar.style.width = '100%';
        timerBar.getBoundingClientRect();
        timerBar.style.transition = 'width ' + (VKB_TIMEOUT_MS/1000) + 's linear';
        timerBar.style.width = '0%';

        autoCloseTimer = setTimeout(function() {
            window.__vkbHide();
        }, VKB_TIMEOUT_MS);
    }

    function resetAutoClose() {
        startAutoClose();
    }

    function clearAutoClose() {
        if (autoCloseTimer) { clearTimeout(autoCloseTimer); autoCloseTimer = null; }
        timerBar.style.transition = 'none';
        timerBar.style.width = '100%';
    }

    function handleKey(k, btnEl) {
        btnEl.classList.add('vkb-pressed');
        setTimeout(function(){ btnEl.classList.remove('vkb-pressed'); }, 110);

        resetAutoClose();

        if (k === '✕') { window.__vkbHide(); return; }

        if (k === 'EN/EL') {
            lang = (lang === 'en') ? 'el' : 'en';
            shifted = false;
            buildRows();
            return;
        }

        if (k === '⇧') {
            shifted = !shifted;
            buildRows();
            return;
        }

        var el = (window.__vkbTargetOverride && window.__vkbTargetOverride.isConnected)
                 ? window.__vkbTargetOverride
                 : document.activeElement;
        if (!el) return;

        if (k === '⌫') {
            var s = el.selectionStart, e2 = el.selectionEnd;
            if (s !== e2) { insertAt(el, ''); }
            else if (s > 0) { el.selectionStart = s - 1; insertAt(el, ''); }
            triggerEvents(el);
            return;
        }

        if (k === '↵') {
            var form = el.closest ? el.closest('form') : null;
            if (form) {
                var sub = form.querySelectorAll('[type=submit],button:not([type=button])');
                if (sub.length) { sub[0].click(); window.__vkbHide(); return; }
            }
            if (el.tagName.toLowerCase() === 'textarea') { insertAt(el, '\\n'); }
            triggerEvents(el);
            if (el.tagName.toLowerCase() !== 'textarea') { el.blur(); window.__vkbHide(); }
            return;
        }

        var ch = (k === 'SPACE') ? ' ' : k;
        insertAt(el, ch);
        triggerEvents(el);

        if (shifted) { shifted = false; buildRows(); }
    }

    function insertAt(el, text) {
        var s = el.selectionStart != null ? el.selectionStart : (el.value||'').length;
        var e = el.selectionEnd   != null ? el.selectionEnd   : (el.value||'').length;
        el.value = (el.value||'').substring(0,s) + text + (el.value||'').substring(e);
        el.selectionStart = el.selectionEnd = s + text.length;
    }

    function triggerEvents(el) {
        el.dispatchEvent(new Event('input',  {bubbles:true}));
        el.dispatchEvent(new Event('change', {bubbles:true}));
    }

    window.__vkbSetConfig = function(timeoutMs, defLang, cmOffset) {
        if (timeoutMs !== undefined) VKB_TIMEOUT_MS = timeoutMs;
        if (defLang !== undefined) { lang = defLang; }
        if (cmOffset !== undefined) {
            overlay.style.setProperty('--vkb-bottom', cmOffset + 'cm');
        }
    };

    window.__vkbShow = function(timeoutMs) {
        if (timeoutMs !== undefined) VKB_TIMEOUT_MS = timeoutMs;
        overlay.style.display = 'block';
        shifted = false;
        buildRows();
        startAutoClose();
    };

    window.__vkbHide = function() {
        clearAutoClose();
        overlay.style.display = 'none';
        if (!window.__vkbTargetOverride) {
            if (document.activeElement && document.activeElement !== document.body) {
                document.activeElement.blur();
            }
        }
    };

    window.__vkbIsVisible = function() {
        return overlay.style.display !== 'none';
    };

    var INPUT_SEL = 'input:not([type=hidden]):not([type=submit]):not([type=button])' +
                    ':not([type=checkbox]):not([type=radio]), textarea';

    function attachToInput(el) {
        if (el.__vkbAttached) return;
        el.__vkbAttached = true;
        el.addEventListener('focus', function() {
            window.__vkbShow();
        });
        el.addEventListener('blur', function() {
            setTimeout(function() {
                var active = document.activeElement;
                var inOverlay = overlay.contains(active);
                var isInput = active && (
                    active.tagName === 'INPUT' || active.tagName === 'TEXTAREA' ||
                    active.getAttribute('contenteditable') === 'true'
                );
                if (!inOverlay && !isInput) {
                    window.__vkbHide();
                }
            }, 200);
        });
    }

    document.querySelectorAll(INPUT_SEL).forEach(attachToInput);

    new MutationObserver(function(muts) {
        muts.forEach(function(m) {
            m.addedNodes.forEach(function(n) {
                if (n.nodeType !== 1) return;
                if (n.matches && n.matches(INPUT_SEL)) attachToInput(n);
                n.querySelectorAll && n.querySelectorAll(INPUT_SEL).forEach(attachToInput);
            });
        });
    }).observe(document.body, {childList:true, subtree:true});

    document.addEventListener('pointerdown', function(e) {
        if (!window.__vkbIsVisible()) return;
        var active = document.activeElement;
        var clickedOverlay = overlay.contains(e.target);
        var clickedInput   = e.target.tagName === 'INPUT' || e.target.tagName === 'TEXTAREA';
        if (!clickedOverlay && !clickedInput) {
            window.__vkbHide();
        }
    }, true);

    console.log('[VKB] Virtual keyboard initialized (EN+EL, auto-close, close btn)');
})();
"""


def inject_virtual_keyboard(driver, timeout_ms=30000, default_lang="en", cm_offset=0):
    """Εισάγει το in-page virtual keyboard overlay στη σελίδα."""
    try:
        driver.execute_script(KEYBOARD_JS)
        driver.execute_script(f"""
            if(window.__vkbSetConfig) {{
                window.__vkbSetConfig({timeout_ms}, '{default_lang}', {cm_offset});
            }}
        """)
        logging.info(f"[VKB] Virtual keyboard overlay εισήχθη (timeout={timeout_ms}ms lang={default_lang} cm_offset={cm_offset})")
    except Exception as e:
        logging.error(f"[VKB] Σφάλμα inject_virtual_keyboard: {e}")


def _set_taskbar_visibility(visible: bool):
    try:
        import ctypes
        SW_HIDE, SW_SHOW = 0, 5
        hwnd = ctypes.windll.user32.FindWindowW("Shell_TrayWnd", None)
        hwnd2 = ctypes.windll.user32.FindWindowW("Windows.UI.Core.CoreWindow", None)
        cmd = SW_SHOW if visible else SW_HIDE
        if hwnd:  ctypes.windll.user32.ShowWindow(hwnd,  cmd)
        if hwnd2: ctypes.windll.user32.ShowWindow(hwnd2, cmd)
        logging.info(f"[TASKBAR] {'ΕΜΦΑΝΙΣΗ' if visible else 'ΑΠΟΚΡΥΨΗ'} taskbar")
    except Exception as e:
        logging.error(f"[TASKBAR] Σφάλμα: {e}")

def hide_taskbar(): _set_taskbar_visibility(False)
def show_taskbar(): _set_taskbar_visibility(True)


def hide_system_cursor():
    try:
        import ctypes
        SM_CXCURSOR = 13
        SM_CYCURSOR = 14
        w = ctypes.windll.user32.GetSystemMetrics(SM_CXCURSOR)
        h = ctypes.windll.user32.GetSystemMetrics(SM_CYCURSOR)

        blank = ctypes.windll.user32.CreateCursor(
            None, 0, 0, w, h,
            (ctypes.c_byte * (w * h // 8))(*([0xFF] * (w * h // 8))),
            (ctypes.c_byte * (w * h // 8))(*([0x00] * (w * h // 8)))
        )

        OCR_NORMAL      = 32512
        OCR_IBEAM       = 32513
        OCR_WAIT        = 32514
        OCR_CROSS       = 32515
        OCR_HAND        = 32649
        for cursor_id in [OCR_NORMAL, OCR_IBEAM, OCR_WAIT, OCR_CROSS, OCR_HAND]:
            ctypes.windll.user32.SetSystemCursor(
                ctypes.windll.user32.CopyCursor(blank), cursor_id
            )

        logging.info("[CURSOR] System cursor κρύφτηκε")
    except Exception as e:
        logging.error(f"[CURSOR] Σφάλμα hide_system_cursor: {e}")


def restore_system_cursor():
    try:
        import ctypes
        ctypes.windll.user32.SystemParametersInfoW(0x0057, 0, None, 0)
        logging.info("[CURSOR] System cursor επαναφέρθηκε")
    except Exception as e:
        logging.error(f"[CURSOR] Σφάλμα restore_system_cursor: {e}")


# ---------------- Chrome Always On Top ----------------
def get_chrome_hwnd(driver):
    try:
        import ctypes
        import ctypes.wintypes
        import subprocess

        cd_pid = driver.service.process.pid

        chrome_pids = set()
        try:
            out = subprocess.check_output(
                f'wmic process where (ParentProcessId={cd_pid}) get ProcessId',
                shell=True, stderr=subprocess.DEVNULL
            ).decode(errors='ignore')
            for line in out.splitlines():
                line = line.strip()
                if line.isdigit():
                    chrome_pids.add(int(line))
        except Exception as we:
            logging.debug(f"[TOPMOST] WMIC αποτυχία: {we}")

        use_pid_filter = len(chrome_pids) > 0
        logging.debug(f"[TOPMOST] Chrome PIDs: {chrome_pids}")

        results = []

        EnumWindowsProc_type = ctypes.WINFUNCTYPE(
            ctypes.c_bool, ctypes.wintypes.HWND, ctypes.wintypes.LPARAM
        )

        def enum_callback(hwnd, lParam):
            try:
                if not ctypes.windll.user32.IsWindowVisible(hwnd):
                    return True

                class_buf = ctypes.create_unicode_buffer(256)
                ctypes.windll.user32.GetClassNameW(hwnd, class_buf, 256)
                if class_buf.value != "Chrome_WidgetWin_1":
                    return True

                if use_pid_filter:
                    win_pid = ctypes.wintypes.DWORD()
                    ctypes.windll.user32.GetWindowThreadProcessId(hwnd, ctypes.byref(win_pid))
                    if win_pid.value not in chrome_pids:
                        return True

                length = ctypes.windll.user32.GetWindowTextLengthW(hwnd)
                results.append((hwnd, length))
            except Exception:
                pass
            return True

        cb = EnumWindowsProc_type(enum_callback)
        ctypes.windll.user32.EnumWindows(cb, 0)

        if not results:
            logging.debug("[TOPMOST] Δεν βρέθηκε Chrome_WidgetWin_1 παράθυρο")
            return None

        results.sort(key=lambda x: x[1], reverse=True)
        hwnd = results[0][0]
        logging.debug(f"[TOPMOST] Επιλέχθηκε HWND={hwnd} (από {len(results)} παράθυρα)")
        return hwnd

    except Exception as e:
        logging.error(f"[TOPMOST] Σφάλμα get_chrome_hwnd: {e}")
        return None


def bring_chrome_to_front(driver):
    try:
        import ctypes
        import ctypes.wintypes

        hwnd = get_chrome_hwnd(driver)
        if not hwnd:
            logging.debug("[TOPMOST] HWND δεν βρέθηκε")
            return

        cur_hwnd = ctypes.windll.user32.GetForegroundWindow()
        cur_tid  = ctypes.windll.user32.GetWindowThreadProcessId(cur_hwnd, None)
        my_tid   = ctypes.windll.kernel32.GetCurrentThreadId()
        attached = False
        if cur_tid and cur_tid != my_tid:
            ctypes.windll.user32.AttachThreadInput(my_tid, cur_tid, True)
            attached = True

        ctypes.windll.user32.AllowSetForegroundWindow(ctypes.c_uint(-1))
        ctypes.windll.user32.ShowWindow(hwnd, 9)  # SW_RESTORE
        ctypes.windll.user32.BringWindowToTop(hwnd)
        ctypes.windll.user32.SetForegroundWindow(hwnd)

        if attached:
            ctypes.windll.user32.AttachThreadInput(my_tid, cur_tid, False)

        try:
            window_info = driver.execute_cdp_cmd("Browser.getWindowForTarget", {})
            state = window_info.get("bounds", {}).get("windowState", "")
            if state != "fullscreen":
                driver.execute_cdp_cmd("Browser.setWindowBounds", {
                    "windowId": window_info["windowId"],
                    "bounds": {"windowState": "fullscreen"}
                })
                logging.debug("[TOPMOST] Fullscreen επαναφέρθηκε μέσω CDP")
        except Exception as ce:
            logging.debug(f"[TOPMOST] CDP fullscreen check: {ce}")

        logging.debug("[TOPMOST] Chrome brought to front")
    except Exception as e:
        logging.error(f"[TOPMOST] Σφάλμα bring_chrome_to_front: {e}")


# Stubs
def open_virtual_keyboard():  pass
def close_virtual_keyboard(): pass
def ensure_tabtip_registry(): pass
def _is_osk_running(): return False

# ---------------- URL Health Check ----------------
def check_url_reachable(url, timeout=5):
    try:
        import urllib.request
        req = urllib.request.Request(url, method="HEAD")
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            logging.info(f"[URL-CHECK] {url} → HTTP {resp.status}")
            return resp.status == 200
    except Exception as e:
        logging.warning(f"[URL-CHECK] {url} → Αποτυχία: {e}")
        return False


# ---------------- Chrome ----------------
def disable_right_click_and_selection(driver):
    try:
        driver.execute_script("""
            document.addEventListener('contextmenu', e => e.preventDefault());
            const css = `
                * {
                    -webkit-user-select: none !important;
                    -moz-user-select: none !important;
                    -ms-user-select: none !important;
                    user-select: none !important;
                    cursor: none !important;
                }
                input, textarea, [contenteditable] {
                    cursor: none !important;
                }
            `;
            const style = document.createElement('style');
            style.innerHTML = css;
            document.head.appendChild(style);
        """)
    except Exception as e:
        logging.error(f"Σφάλμα στο disable_right_click_and_selection: {e}")


def setup_persistent_scripts(driver, timeout_ms=30000, default_lang="en", exit_password="", cm_offset=0):
    try:
        cursor_css = """
            (function() {
                var s = document.createElement('style');
                s.textContent = '*, *::before, *::after { cursor: none !important; }';
                var inject = function() {
                    if (document.head) { document.head.appendChild(s); }
                    else if (document.documentElement) { document.documentElement.appendChild(s); }
                };
                inject();
                document.addEventListener('DOMContentLoaded', inject);
            })();
        """
        driver.execute_cdp_cmd("Page.addScriptToEvaluateOnNewDocument", {"source": cursor_css})

        vkb_init = f"""
            {KEYBOARD_JS}
            if(window.__vkbSetConfig) {{ window.__vkbSetConfig({timeout_ms}, '{default_lang}', {cm_offset}); }}
        """
        driver.execute_cdp_cmd("Page.addScriptToEvaluateOnNewDocument", {"source": vkb_init})

        exit_js = EXIT_OVERLAY_JS.replace("'__EXIT_PASS__'", repr(exit_password))
        driver.execute_cdp_cmd("Page.addScriptToEvaluateOnNewDocument", {"source": exit_js})

        logging.info("[CDP] Persistent scripts καταχωρήθηκαν (VKB + exit overlay)")
    except Exception as e:
        logging.error(f"[CDP] Σφάλμα setup_persistent_scripts: {e}")


def safe_get(driver, url):
    try:
        driver.get(url)
        disable_right_click_and_selection(driver)
        inject_virtual_keyboard(driver, timeout_ms=getattr(safe_get, "_kb_timeout_ms", 30000), default_lang=getattr(safe_get, "_kb_default_lang", "en"), cm_offset=getattr(safe_get, "_kb_cm_offset", 0))
        inject_exit_overlay(driver, getattr(safe_get, "_exit_password", ""))
    except WebDriverException as e:
        logging.error(f"Σφάλμα φόρτωσης URL {url}: {e}")
    except Exception as e:
        logging.error(f"Άγνωστο σφάλμα φόρτωσης σελίδας: {e}")


# ---------------- Exit Overlay JS ----------------
EXIT_OVERLAY_JS = """
(function() {
    if (document.getElementById('__exit_overlay')) return;

    var CLICKS_REQUIRED = 8;
    var CLICK_WINDOW_MS = 3000;
    var clickTimes = [];
    var EXIT_PASSWORD = '__EXIT_PASS__';

    var style = document.createElement('style');
    style.textContent = [
        '#__exit_overlay {',
        '  display:none;position:fixed;top:0;left:0;right:0;bottom:0;',
        '  background:rgba(0,0,0,0.75);z-index:2147483646;',
        '  justify-content:center;align-items:center;',
        '}',
        '#__exit_box {',
        '  background:#1a1a2e;border:2px solid #4a4a8a;border-radius:12px;',
        '  padding:32px 40px;text-align:center;min-width:320px;',
        '  box-shadow:0 8px 32px rgba(0,0,0,0.6);',
        '}',
        '#__exit_box h2 {color:#fff;margin:0 0 20px;font-family:sans-serif;font-size:20px;}',
        '#__exit_pass_input {',
        '  width:100%;padding:12px;font-size:18px;border-radius:6px;',
        '  border:2px solid #4a4a8a;background:#0d0d1a;color:#fff;',
        '  text-align:center;letter-spacing:4px;box-sizing:border-box;outline:none;',
        '}',
        '#__exit_pass_input:focus {border-color:#7070cc;}',
        '#__exit_err {color:#ff6666;font-family:sans-serif;font-size:14px;margin-top:12px;min-height:18px;}',
        '#__exit_btn_row {display:flex;gap:12px;margin-top:20px;justify-content:center;}',
        '#__exit_ok_btn, #__exit_cancel_btn {',
        '  padding:10px 28px;font-size:16px;border-radius:6px;border:none;',
        '  cursor:pointer;font-family:sans-serif;font-weight:bold;',
        '}',
        '#__exit_ok_btn {background:#5555aa;color:#fff;}',
        '#__exit_ok_btn:active {background:#7777cc;}',
        '#__exit_cancel_btn {background:#3a3a3a;color:#ccc;}',
        '#__exit_cancel_btn:active {background:#555;}',
    ].join('');
    document.head.appendChild(style);

    var overlay = document.createElement('div');
    overlay.id = '__exit_overlay';
    overlay.innerHTML = [
        '<div id=\"__exit_box\">',
        '  <h2>&#128274; Κωδικός Εξόδου</h2>',
        '  <input type=\"password\" id=\"__exit_pass_input\" placeholder=\"••••••\" autocomplete=\"off\" />',
        '  <div id=\"__exit_err\"></div>',
        '  <div id=\"__exit_btn_row\">',
        '    <button id=\"__exit_ok_btn\">OK</button>',
        '    <button id=\"__exit_cancel_btn\">Άκυρο</button>',
        '  </div>',
        '</div>'
    ].join('');
    overlay.style.display = 'none';
    document.body.appendChild(overlay);

    var overlayVisible = false;
    var exitAutoCloseTimer = null;
    var EXIT_OVERLAY_TIMEOUT_MS = 30000;

    function getInp() { return document.getElementById('__exit_pass_input'); }

    function startExitAutoClose() {
        clearExitAutoClose();
        exitAutoCloseTimer = setTimeout(function() {
            if (overlayVisible) { hideExitOverlay(); }
        }, EXIT_OVERLAY_TIMEOUT_MS);
    }

    function resetExitAutoClose() {
        startExitAutoClose();
    }

    function clearExitAutoClose() {
        if (exitAutoCloseTimer) { clearTimeout(exitAutoCloseTimer); exitAutoCloseTimer = null; }
    }

    function showExitOverlay() {
        overlayVisible = true;
        overlay.style.display = 'flex';
        var inp = getInp();
        inp.value = '';
        document.getElementById('__exit_err').textContent = '';
        window.__vkbTargetOverride = inp;
        startExitAutoClose();
        var attempts = 0;
        function tryFocus() {
            inp.focus();
            attempts++;
            if (document.activeElement !== inp && attempts < 15) {
                setTimeout(tryFocus, 60);
            } else {
                if (window.__vkbShow) window.__vkbShow();
            }
        }
        setTimeout(tryFocus, 60);
    }

    function hideExitOverlay() {
        clearExitAutoClose();
        overlayVisible = false;
        overlay.style.display = 'none';
        window.__vkbTargetOverride = null;
        if (window.__vkbHide) window.__vkbHide();
    }

    function tryExit() {
        var val = getInp().value;
        if (val === EXIT_PASSWORD) {
            clearExitAutoClose();
            window.__kiosk_exit_triggered = true;
        } else {
            document.getElementById('__exit_err').textContent = 'Λάθος κωδικός!';
            getInp().value = '';
            window.__vkbTargetOverride = getInp();
            getInp().focus();
            resetExitAutoClose();
        }
    }

    document.getElementById('__exit_ok_btn').addEventListener('pointerup', function(e){
        e.preventDefault(); resetExitAutoClose(); tryExit();
    });
    document.getElementById('__exit_cancel_btn').addEventListener('pointerup', function(e){
        e.preventDefault(); hideExitOverlay();
    });
    getInp().addEventListener('keydown', function(e){
        resetExitAutoClose();
        if (e.key === 'Enter') tryExit();
    });
    getInp().addEventListener('input', function(e){
        resetExitAutoClose();
    });

    document.addEventListener('click', function(e) {
        if (overlayVisible) return;
        var now = Date.now();
        clickTimes.push(now);
        clickTimes = clickTimes.filter(function(t){ return now - t <= CLICK_WINDOW_MS; });
        if (clickTimes.length >= CLICKS_REQUIRED) {
            clickTimes = [];
            showExitOverlay();
        }
    }, true);

    window.__exitOverlayShow = showExitOverlay;
    window.__exitOverlayHide = hideExitOverlay;
    window.__vkbTargetOverride = null;
    console.log('[EXIT] Exit overlay initialized (8-click trigger)');
})();
"""


def inject_exit_overlay(driver, exit_password):
    try:
        js = EXIT_OVERLAY_JS.replace("'__EXIT_PASS__'", repr(exit_password))
        driver.execute_script(js)
        logging.info("[EXIT] Exit overlay εισήχθη επιτυχώς")
    except Exception as e:
        logging.error(f"[EXIT] Σφάλμα inject_exit_overlay: {e}")


# ---------------- Watchdog Log ----------------
def watchdog_log(event_type, message):
    try:
        base_dir = (
            os.path.dirname(sys.executable)
            if getattr(sys, 'frozen', False)
            else os.path.dirname(os.path.abspath(__file__))
        )
        log_path = os.path.join(base_dir, "watchdog-log.txt")
        from datetime import datetime
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        line = f"{timestamp} | {event_type:<8} | {message}\n"
        with open(log_path, "a", encoding="utf-8") as f:
            f.write(line)
        logging.info(f"[WATCHDOG-LOG] {line.strip()}")
    except Exception as e:
        logging.error(f"[WATCHDOG-LOG] Σφάλμα εγγραφής: {e}")


# ---------------- Keyboard polling thread ----------------
def keyboard_polling_thread(driver_ref, stop_event, exit_password, keyboard_timeout=30,
                            target_url=None, fallback_url=None, watchdog_interval=120,
                            freeze_timeout=5, freeze_retries=2, navigating_lock=None):
    poll_count        = 0
    last_url          = None
    last_watchdog_check = time.time()
    WATCHDOG_INTERVAL = max(30, watchdog_interval)
    if navigating_lock is None:
        navigating_lock = threading.Lock()
    FREEZE_TIMEOUT    = max(3, freeze_timeout)
    FREEZE_RETRIES    = max(1, freeze_retries)

    from urllib.parse import urlparse
    def _domain(u):
        if not u:
            return ""
        p = urlparse(u)
        if p.scheme in ("http", "https"):
            return f"{p.scheme}://{p.netloc}".rstrip("/")
        return u.split("?")[0].rstrip("/")

    target_domain   = _domain(target_url)   if target_url   else None
    fallback_domain = _domain(fallback_url) if fallback_url else None
    fallback_base   = fallback_url.split("?")[0].rstrip("/") if fallback_url else None

    accepted_domains = set()
    if target_domain:   accepted_domains.add(target_domain)
    if fallback_domain: accepted_domains.add(fallback_domain)

    logging.info("[KB-THREAD] Εκκίνηση keyboard polling thread")
    logging.info(f"[KB-THREAD] Exit password μήκος: {len(exit_password)}")
    logging.info(f"[KB-THREAD] Watchdog: interval={WATCHDOG_INTERVAL}s | freeze_timeout={FREEZE_TIMEOUT}s | freeze_retries={FREEZE_RETRIES} | domains: {accepted_domains}")
    logging.info(f"[KB-THREAD] target_url={target_url} | fallback_url={fallback_url}")

    def do_reinject(driver):
        try:
            inject_virtual_keyboard(
                driver,
                timeout_ms=getattr(safe_get, "_kb_timeout_ms", 30000),
                default_lang=getattr(safe_get, "_kb_default_lang", "en"),
                cm_offset=getattr(safe_get, "_kb_cm_offset", 0)
            )
            inject_exit_overlay(driver, exit_password)
            disable_right_click_and_selection(driver)
            logging.info("[KB-THREAD] Re-inject scripts μετά από navigation")
        except Exception as e:
            logging.warning(f"[KB-THREAD] Re-inject αποτυχία: {e}")

    def do_shutdown():
        time.sleep(0.5)
        show_taskbar()
        time.sleep(0.3)
        try:
            driver_ref[0].quit()
            logging.info("[KB-THREAD] Chrome έκλεισε.")
        except Exception as eq:
            logging.warning(f"[KB-THREAD] Chrome quit: {eq}")
        time.sleep(2)
        logging.info("[KB-THREAD] Τερματισμός Python.")
        os._exit(0)

    while not stop_event.is_set():
        try:
            driver = driver_ref[0]
            if driver is None:
                time.sleep(0.5)
                continue

            poll_count += 1
            if poll_count % 30 == 0:
                logging.debug(f"[KB-THREAD] poll #{poll_count} alive")
            if poll_count % 3 == 0:
                bring_chrome_to_front(driver)

            # Έλεγχος αλλαγής σελίδας
            try:
                current_url = driver.current_url
                if current_url != last_url and current_url not in ("", "about:blank", None):
                    time.sleep(0.8)
                    ready = driver.execute_script("return document.readyState;")
                    if ready == "complete":
                        last_url = current_url
                        do_reinject(driver)
            except Exception:
                pass

            # ---- Watchdog ----
            now = time.time()
            if accepted_domains and (now - last_watchdog_check) >= WATCHDOG_INTERVAL:
                last_watchdog_check = now
                try:
                    cur = driver.current_url or ""
                    cur_domain = _domain(cur)

                    # Περίπτωση 1: Domain εκτός λίστας → redirect στο fallback
                    if cur_domain and cur_domain not in accepted_domains:
                        watchdog_log("REDIRECT",
                            f"Μη αποδεκτό domain: {cur_domain} | url: {cur} | → fallback k.html")
                        with navigating_lock:
                            driver.get(fallback_url or target_url)
                            time.sleep(1.0)
                            do_reinject(driver)
                            last_url = driver.current_url

                    # Περίπτωση 2: Τρέχει fallback (k.html) → έλεγχε αν το κύριο URL επέστρεψε
                    elif (target_url and fallback_base
                          and target_url != fallback_url
                          and cur.split("?")[0].rstrip("/").startswith(fallback_base)):
                        logging.debug("[WATCHDOG] Τρέχει fallback — έλεγχος αν επέστρεψε το κύριο URL")
                        if check_url_reachable(target_url, timeout=5):
                            watchdog_log("RECOVERY",
                                f"Κύριο URL διαθέσιμο ξανά | → redirect: {target_url}")
                            with navigating_lock:
                                driver.get(target_url)
                                time.sleep(1.0)
                                do_reinject(driver)
                                last_url = driver.current_url
                        else:
                            logging.debug("[WATCHDOG] Κύριο URL ακόμα μη διαθέσιμο — παραμένουμε στο fallback")

                    # Περίπτωση 3: Domain OK — έλεγχος freeze
                    else:
                        freeze_count = 0
                        for attempt in range(FREEZE_RETRIES):
                            try:
                                driver.set_script_timeout(FREEZE_TIMEOUT)
                                result = driver.execute_script("return 1;")
                                if result == 1:
                                    freeze_count = 0
                                    break
                            except Exception:
                                freeze_count += 1
                                logging.warning(f"[WATCHDOG] Δεν απάντησε ο Chrome (attempt {attempt+1}/{FREEZE_RETRIES})")
                                time.sleep(1)

                        if freeze_count >= FREEZE_RETRIES:
                            watchdog_log("FREEZE",
                                f"Chrome δεν απάντησε σε {FREEZE_TIMEOUT}s × {FREEZE_RETRIES} φορές | "
                                f"url: {cur} | → Restart Chrome")
                            try:
                                driver_ref[0].quit()
                            except Exception:
                                pass
                            time.sleep(2)
                        else:
                            logging.debug(f"[WATCHDOG] OK — domain: {cur_domain} | url: {cur}")

                except Exception as we:
                    logging.warning(f"[WATCHDOG] Σφάλμα ελέγχου: {we}")

            # Έλεγχος exit
            triggered = driver.execute_script("return !!window.__kiosk_exit_triggered;")
            if triggered:
                logging.info("[KB-THREAD] EXIT επιβεβαιώθηκε! Τερματισμός...")
                stop_event.set()
                threading.Thread(target=do_shutdown, daemon=True).start()
                return

        except Exception as e:
            logging.error(f"[KB-THREAD] Σφάλμα: {type(e).__name__}: {e}")
            time.sleep(1)

        time.sleep(4)


# ---------------- Main ----------------
def main():
    exit_password, keyboard_timeout, enable_log, default_lang, config_url, cm_offset, watchdog_interval, freeze_timeout, freeze_retries = load_config()

    log_path = setup_logger(enable_log=enable_log)
    logging.info("Έναρξη κύριας διαδικασίας")
    hide_system_cursor()
    logging.info(f"[MAIN] Config: timeout={keyboard_timeout}s log={'ON' if enable_log else 'OFF'} lang={default_lang} cm_offset={cm_offset} watchdog={watchdog_interval}s freeze_timeout={freeze_timeout}s freeze_retries={freeze_retries}")

    ensure_tabtip_registry()

    urls_txt_url = load_url()
    config_fallback_url = _path_to_url(config_url) if config_url else None

    # ---- ΔΙΟΡΘΩΣΗ: target_url είναι ΠΑΝΤΑ το αρχικό HTTP URL από urls.txt ----
    # Έτσι ο watchdog ξέρει πάντα ποιο URL να ελέγξει για επαναφορά,
    # ακόμα και αν ξεκινήσαμε με fallback λόγω αναποκρισίας.
    target_url = urls_txt_url

    if urls_txt_url.startswith("http://") or urls_txt_url.startswith("https://"):
        logging.info(f"[MAIN] Έλεγχος προσβασιμότητας urls.txt URL: {urls_txt_url}")
        if check_url_reachable(urls_txt_url):
            url = urls_txt_url
            logging.info(f"[MAIN] urls.txt URL OK → χρήση: {url}")
        else:
            # Ξεκινάμε με fallback, αλλά target_url παραμένει το αρχικό HTTP URL
            url = config_fallback_url or _path_to_url("C:/Users/IT/Documents/kiosk/k.html")
            logging.warning(f"[MAIN] urls.txt URL ΜΗ προσβάσιμο → εκκίνηση με fallback: {url}")
            logging.info(f"[MAIN] Watchdog θα ελέγχει για επαναφορά: {target_url}")
    else:
        url = urls_txt_url
        logging.info(f"[MAIN] Τοπικό path, χωρίς HTTP check: {url}")

    safe_get._exit_password   = exit_password
    safe_get._kb_timeout_ms   = keyboard_timeout * 1000
    safe_get._kb_default_lang = default_lang
    safe_get._kb_cm_offset    = cm_offset

    logging.info(f"URL εκκίνησης: {url}")
    logging.info(f"Target URL (watchdog): {target_url}")
    print(f">>> URL εκκίνησης: {url}")
    print(f">>> Target URL (watchdog): {target_url}")

    fallback_url = config_fallback_url or _path_to_url("C:/Users/IT/Documents/kiosk/k.html")

    def start_chrome():
        chrome_options = Options()
        chrome_options.add_argument("--window-position=-10000,-10000")
        chrome_options.add_argument("--disable-infobars")
        chrome_options.add_argument("--disable-extensions")
        chrome_options.add_argument("--noerrdialogs")
        chrome_options.add_argument("--disable-session-crashed-bubble")
        chrome_options.add_argument("--disable-background-networking")
        chrome_options.add_argument("--disable-client-side-phishing-detection")
        chrome_options.add_argument("--autoplay-policy=no-user-gesture-required")
        chrome_options.add_argument("--disable-pinch")
        chrome_options.add_argument("--disable-features=TouchpadAndWheelScrollLatching")
        chrome_options.add_argument("--remote-debugging-port=0")
        chrome_options.add_argument("--user-data-dir=" + tempfile.mkdtemp())
        chrome_options.add_argument("--enable-virtual-keyboard")
        chrome_options.add_argument("--enable-features=VirtualKeyboard")
        chrome_options.add_experimental_option("excludeSwitches", ["enable-automation"])
        chrome_options.add_experimental_option("useAutomationExtension", False)
        chrome_options.add_argument(fallback_url)

        chromedriver_path = resource_path("chromedriver.exe")

        try:
            service = Service(chromedriver_path) if os.path.exists(chromedriver_path) else Service()
            driver = webdriver.Chrome(service=service, options=chrome_options)
            driver.execute_script("Object.defineProperty(navigator, 'webdriver', {get: () => undefined})")
            setup_persistent_scripts(
                driver,
                timeout_ms=safe_get._kb_timeout_ms,
                default_lang=safe_get._kb_default_lang,
                exit_password=safe_get._exit_password,
                cm_offset=safe_get._kb_cm_offset
            )
            safe_get(driver, url)
            for _ in range(30):
                try:
                    ready = driver.execute_script("return document.readyState;")
                    if ready == "complete":
                        break
                except Exception:
                    pass
                time.sleep(0.5)
            try:
                window_info = driver.execute_cdp_cmd("Browser.getWindowForTarget", {})
                driver.execute_cdp_cmd("Browser.setWindowBounds", {
                    "windowId": window_info["windowId"],
                    "bounds": {"windowState": "fullscreen"}
                })
                logging.info("[CHROME] Fullscreen μέσω CDP")
            except Exception as fe:
                logging.warning(f"[CHROME] Fullscreen απέτυχε: {fe}")
            time.sleep(0.5)
            bring_chrome_to_front(driver)
            hide_taskbar()
            logging.info("Chrome εκκινήθηκε επιτυχώς")
            return driver
        except Exception as e:
            logging.error(f"Αδυναμία εκκίνησης Chrome: {e}")
            return None

    driver = start_chrome()
    if not driver:
        logging.error("Αποτυχία εκκίνησης Chrome. Τερματισμός.")
        return

    print(f"Kiosk browser εκκινήθηκε. URL: {url}")
    print(f"Logs στο: {log_path}")

    driver_ref = [driver]
    stop_event = threading.Event()
    navigating_lock = threading.Lock()  # προστατεύει από ταυτόχρονο restart κατά navigation

    kb_thread = threading.Thread(
        target=keyboard_polling_thread,
        args=(driver_ref, stop_event, exit_password),
        kwargs={
            "target_url": target_url,
            "fallback_url": fallback_url,
            "watchdog_interval": watchdog_interval,
            "freeze_timeout": freeze_timeout,
            "freeze_retries": freeze_retries,
            "navigating_lock": navigating_lock   # ← νέο
        },
        daemon=True
    )
    kb_thread.start()
    logging.info("Keyboard polling thread εκκινήθηκε")

    # ---------------- Main loop ----------------
    while True:
        try:
            _ = driver_ref[0].current_url
            time.sleep(1)

        except KeyboardInterrupt:
            logging.info("Χειροκίνητος τερματισμός από χρήστη.")
            break

        except Exception as e:
            # Αν ο watchdog κάνει navigation αυτή τη στιγμή, το current_url
            # μπορεί να πετάξει exception στιγμιαία — δεν είναι πραγματικό crash.
            if navigating_lock.locked():
                logging.debug("[MAIN] Exception κατά navigation (αναμενόμενο) — αγνοείται")
                time.sleep(1)
                continue

            logging.error(f"Chrome crash ή απώλεια σύνδεσης: {e}. Επανεκκίνηση...")
            try:
                driver_ref[0].quit()
            except Exception:
                pass
            time.sleep(2)
            new_driver = start_chrome()
            if new_driver:
                driver_ref[0] = new_driver
                logging.info("Chrome επανεκκινήθηκε επιτυχώς")
            else:
                logging.error("Αποτυχία επανεκκίνησης Chrome. Αναμονή 10s...")
                time.sleep(10)

    # ---------------- Cleanup ----------------
    stop_event.set()
    show_taskbar()
    restore_system_cursor()
    close_virtual_keyboard()
    try:
        driver_ref[0].quit()
    except Exception:
        pass
    logging.info("Τερματισμός προγράμματος.")


if __name__ == "__main__":
    main()
