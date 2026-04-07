#!/usr/bin/env python3
"""VRD – Virtual Remote Desktop: single-file CLI + HTTP control plane.

Usage:
    python3 vrd.py check                     Check / install dependencies
    python3 vrd.py start                     Start full stack (runs check)
    python3 vrd.py stop                      Stop and back up profile
    python3 vrd.py status                    Show status
    python3 vrd.py serve [--port 6090]       HTTP API (started by ``start``)
    python3 vrd.py switch <mode>             Switch device preset
    python3 vrd.py screenshot [label]        Screenshot
    python3 vrd.py clipboard get|set <text>  Clipboard

Config resolution order: environment → state.json → built-in defaults.
"""

from __future__ import annotations

import glob as _glob
import json
import os
import re
import secrets
import shutil
import signal
import subprocess
import sys
import threading
import time
import uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

try:
    from playwright.sync_api import sync_playwright
except ModuleNotFoundError:  # pragma: no cover
    sync_playwright = None

# ════════════════════════════════════════════════════════════════════════
#  Constants & paths
# ════════════════════════════════════════════════════════════════════════
SCRIPT_DIR = Path(__file__).resolve().parent
WORKDIR    = Path(os.environ.get("WORKDIR", Path.home() / ".openclaw/vrd-data"))
PIDFILE    = WORKDIR / "state.json"
LOGDIR     = WORKDIR / "logs"
SSHOT_DIR  = WORKDIR / "screenshots"


def _is_windows() -> bool:
    return sys.platform.startswith("win")

# ── Device presets ──
_UA = {
    "mobile":         "Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.0 Mobile/15E148 Safari/604.1",
    "iphone-safari":  "Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.0 Mobile/15E148 Safari/604.1",
    "tablet":         "Mozilla/5.0 (iPad; CPU OS 17_0 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.0 Mobile/15E148 Safari/604.1",
    "wechat-h5":      "Mozilla/5.0 (iPhone; CPU iPhone OS 16_0 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Mobile/15E148 MicroMessenger/8.0.38 NetType/WIFI Language/zh_CN",
    "android-chrome":  "Mozilla/5.0 (Linux; Android 13; Pixel 7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/116.0.0.0 Mobile Safari/537.36",
}
PRESETS: dict[str, dict] = {
    "desktop":        {"vp": "1280x720", "dpr": 1, "ua": "",                   "fw": 0,  "fh": 0,   "touch": False, "label": "Desktop 1280x720"},
    "mobile":         {"vp": "393x852",  "dpr": 3, "ua": _UA["mobile"],        "fw": 24, "fh": 112, "touch": True,  "label": "iPhone 15  393×852 @3x"},
    "iphone-safari":  {"vp": "390x844",  "dpr": 3, "ua": _UA["iphone-safari"], "fw": 24, "fh": 112, "touch": True,  "label": "iPhone 14  390×844 @3x"},
    "tablet":         {"vp": "768x1024", "dpr": 2, "ua": _UA["tablet"],        "fw": 24, "fh": 112, "touch": True,  "label": "iPad  768×1024 @2x"},
    "wechat-h5":      {"vp": "375x667",  "dpr": 2, "ua": _UA["wechat-h5"],     "fw": 24, "fh": 112, "touch": True,  "label": "WeChat H5 375x667 @2x"},
    "android-chrome": {"vp": "360x800",  "dpr": 3, "ua": _UA["android-chrome"],"fw": 24, "fh": 112, "touch": True,  "label": "Android  360×800 @3x"},
}

# ── In-process HTTP state ──
_lock   = threading.Lock()
_guide  = {"text": "", "kind": "info", "ts": 0.0}
_gate   = {"id": "", "prompt": "", "approved": None, "ts": 0.0, "timeout": 300}
_cont   = {"ts": 0.0}
_record: dict = {"active": False, "dir": "", "frames": []}
_rec_timer: threading.Timer | None = None

# ════════════════════════════════════════════════════════════════════════
#  Helpers
# ════════════════════════════════════════════════════════════════════════
def _wh(geom: str) -> tuple[int, int]:
    parts = str(geom).split("x", 1)
    if len(parts) != 2:
        return 1280, 720  # safe default
    try:
        return int(parts[0]), int(parts[1])
    except ValueError:
        return 1280, 720

def _scale(geom: str, f: int) -> str:
    w, h = _wh(geom); s = max(1, f); return f"{w*s}x{h*s}"

def _pad(geom: str, pw: int, ph: int) -> str:
    w, h = _wh(geom); return f"{w+max(0,pw)}x{h+max(0,ph)}"

def _env(name: str, default: str = "") -> str:
    return os.environ.get(name, default)

def _alive(pid) -> bool:
    try:
        p = int(pid)
        if _is_windows():
            res = subprocess.run(
                ["tasklist", "/FI", f"PID eq {p}"],
                capture_output=True,
                text=True,
            )
            out = (res.stdout or "") + (res.stderr or "")
            return str(p) in out and "No tasks are running" not in out
        os.kill(p, 0)
        status_path = f"/proc/{p}/status"
        if os.path.isfile(status_path):
            with open(status_path) as f:
                for line in f:
                    if line.startswith("State:"):
                        return "Z" not in line
        return True
    except Exception:
        return False

def _kill(pid) -> None:
    if not pid: return
    try:
        p = int(pid)
        if _is_windows():
            subprocess.run(["taskkill", "/PID", str(p), "/T", "/F"], capture_output=True, text=True)
            return
        os.kill(p, signal.SIGTERM); time.sleep(0.3)
        try: os.kill(p, signal.SIGKILL)
        except ProcessLookupError: pass
    except Exception: pass

_log_handles: list = []  # track open log file handles for cleanup

def _logfile(name: str, mode: str = "a"):
    """Open a log file, track it for cleanup."""
    fh = open(LOGDIR / name, mode)
    _log_handles.append(fh)
    return fh

def _close_log_handles() -> None:
    for fh in _log_handles:
        try:
            fh.close()
        except Exception:
            pass
    _log_handles.clear()

def _sh(cmd: str, **kw) -> subprocess.CompletedProcess:
    return subprocess.run(cmd, shell=True, capture_output=True, text=True, **kw)

def _run(cmd: list, **kw) -> subprocess.CompletedProcess:
    return subprocess.run(cmd, capture_output=True, text=True, **kw)

def _cmd_ok(name: str) -> bool:
    return shutil.which(name) is not None


def _resolve_cmd(name: str) -> str:
    if _is_windows():
        return shutil.which(name) or shutil.which(f"{name}.cmd") or shutil.which(f"{name}.exe") or name
    return shutil.which(name) or name

def _need(name: str) -> None:
    if not _cmd_ok(name):
        _die(f"Missing dependency: {name}")

def _die(msg: str) -> None:
    print(f"[ERR] {msg}", file=sys.stderr); sys.exit(1)

def _info(msg: str)  -> None: print(f"[INFO] {msg}")
def _warn(msg: str)  -> None: print(f"[WARN] {msg}")

def _pkill(pattern: str) -> None:
    if _is_windows():
        return
    try:
        subprocess.run(["pkill", "-f", pattern], capture_output=True)
    except FileNotFoundError:
        return

# ════════════════════════════════════════════════════════════════════════
#  State file
# ════════════════════════════════════════════════════════════════════════
def _load() -> dict:
    if PIDFILE.exists():
        return json.loads(PIDFILE.read_text("utf-8"))
    return {}

def _save(data: dict) -> None:
    PIDFILE.parent.mkdir(parents=True, exist_ok=True)
    tmp = PIDFILE.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2, sort_keys=True) + "\n", "utf-8")
    tmp.chmod(0o600)
    tmp.replace(PIDFILE)


def export_session(platform: str, output_path: str) -> dict:
    env = _load()
    cdp_port = str(env.get("CDP_PORT", "")).strip()
    if not cdp_port:
        raise RuntimeError("CDP port missing; start VRD first")
    if sync_playwright is None:
        raise RuntimeError("playwright is not installed; cannot export session")

    endpoint = f"http://127.0.0.1:{cdp_port}"
    with sync_playwright() as playwright:
        browser = playwright.chromium.connect_over_cdp(endpoint)
        try:
            if browser.contexts:
                context = browser.contexts[0]
            else:
                context = browser.new_context()
            storage_state = context.storage_state()
        finally:
            close_browser = getattr(browser, "close", None)
            if callable(close_browser):
                close_browser()

    payload = {
        "platform": platform,
        "source": "auto-browser",
        "storage_state": storage_state,
    }
    target = Path(output_path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    target.chmod(0o600)  # restrict access — file contains auth cookies
    return {"ok": True, "platform": platform, "path": str(target), "endpoint": endpoint}

# ════════════════════════════════════════════════════════════════════════
#  Package installs & privileged commands
# ════════════════════════════════════════════════════════════════════════
def _detect_pm() -> str:
    for pm in ("apt-get", "dnf", "yum"):
        if _cmd_ok(pm): return pm.replace("-get", "")
    return ""

def _privileged(cmd: list) -> int:
    if os.getuid() == 0:
        return subprocess.call(cmd)
    if _cmd_ok("sudo"):
        return subprocess.call(["sudo"] + cmd)
    return 1

def _install_pkg(cmd_name: str, *pkg_candidates: str) -> bool:
    if _cmd_ok(cmd_name): return True
    pm = _detect_pm()
    if not pm:
        _warn(f"Cannot install {cmd_name}: no package manager found")
        return False
    _info(f"Installing {cmd_name}...")
    for pkg in pkg_candidates:
        if pm == "apt":
            _privileged(["apt-get", "update", "-qq"])
            ret = _privileged(["apt-get", "install", "-y", pkg])
        else:
            ret = _privileged([pm, "install", "-y", pkg])
        if ret == 0 and _cmd_ok(cmd_name):
            _info(f"{cmd_name} ready"); return True
    _warn(f"Failed to install {cmd_name}; may fall back to full-display mode")
    return False

def _install_cloudflared() -> bool:
    if _cmd_ok("cloudflared"): return True
    pm = _detect_pm()
    if not pm:
        _warn("Cannot install cloudflared"); return False
    _info("Installing cloudflared...")
    if pm == "apt":
        script = (
            "set -e; apt-get update -qq; "
            "apt-get install -y ca-certificates curl gnupg >/dev/null; "
            "mkdir -p /usr/share/keyrings; "
            "curl -fsSL https://pkg.cloudflare.com/cloudflare-main.gpg "
            "| gpg --dearmor -o /usr/share/keyrings/cloudflare-main.gpg; "
            "echo 'deb [signed-by=/usr/share/keyrings/cloudflare-main.gpg] "
            "https://pkg.cloudflare.com/cloudflared any main' "
            "> /etc/apt/sources.list.d/cloudflared.list; "
            "apt-get update -qq; apt-get install -y cloudflared"
        )
        _privileged(["bash", "-lc", script])
    else:
        repo = (
            "[cloudflared-stable]\nname=cloudflared-stable\n"
            "baseurl=https://pkg.cloudflare.com/cloudflared/rpm\n"
            "enabled=1\ngpgcheck=1\n"
            "gpgkey=https://pkg.cloudflare.com/cloudflare-main.gpg\n"
        )
        repo_path = "/etc/yum.repos.d/cloudflared.repo"
        _privileged(["bash", "-c", f"cat > {repo_path} <<'R'\n{repo}R"])
        _privileged([pm, "install", "-y", "cloudflared"])
    return _cmd_ok("cloudflared")

# ════════════════════════════════════════════════════════════════════════
#  Chrome discovery & profile
# ════════════════════════════════════════════════════════════════════════
def _resolve_system_chrome() -> str:
    if _is_windows():
        candidates = [
            os.environ.get("CHROME_BIN", ""),
            shutil.which("chrome") or "",
            shutil.which("msedge") or "",
            str(Path(os.environ.get("PROGRAMFILES", "")) / "Google/Chrome/Application/chrome.exe"),
            str(Path(os.environ.get("PROGRAMFILES(X86)", "")) / "Google/Chrome/Application/chrome.exe"),
            str(Path(os.environ.get("LOCALAPPDATA", "")) / "Google/Chrome/Application/chrome.exe"),
            str(Path(os.environ.get("PROGRAMFILES", "")) / "Microsoft/Edge/Application/msedge.exe"),
            str(Path(os.environ.get("PROGRAMFILES(X86)", "")) / "Microsoft/Edge/Application/msedge.exe"),
            str(Path(os.environ.get("LOCALAPPDATA", "")) / "Microsoft/Edge/Application/msedge.exe"),
        ]
        for candidate in candidates:
            if candidate and Path(candidate).is_file():
                return str(Path(candidate))
        return ""
    for name in ("google-chrome-stable", "google-chrome", "chromium-browser", "chromium"):
        p = shutil.which(name)
        if p: return p
    return ""

def _resolve_pinned_chrome(pin_dir: str = "chromium-1208") -> str:
    root = Path(os.environ.get("PLAYWRIGHT_BROWSERS_PATH", Path.home() / ".cache/ms-playwright"))
    suffixes = ["chrome-linux64/chrome", "chrome-linux/chrome"]
    if _is_windows():
        suffixes.insert(0, "chrome-win/chrome.exe")
    for suffix in suffixes:
        c = root / pin_dir / suffix
        if c.is_file() and os.access(c, os.X_OK): return str(c)
    return ""

def _pick_chrome(strategy: str = "system-first", pin_dir: str = "chromium-1208") -> str:
    explicit = os.environ.get("CHROME_BIN", "")
    if explicit and os.access(explicit, os.X_OK): return explicit
    sys_bin = _resolve_system_chrome()
    pin_bin = _resolve_pinned_chrome(pin_dir)
    if strategy == "pinned-first":
        return pin_bin or sys_bin or ""
    return sys_bin or pin_bin or ""

def _profile_has_login(d: str) -> bool:
    dp = Path(d) / "Default"
    if not dp.is_dir(): return False
    return (
        ((dp / "Cookies").is_file() and (dp / "Cookies").stat().st_size > 0)
        or ((dp / "Login Data").is_file() and (dp / "Login Data").stat().st_size > 0)
        or (dp / "Local Storage").is_dir()
    )

def _prepare_profile(profile: str, workdir: str) -> None:
    _info("Preparing Chrome profile...")
    _pkill(f"--user-data-dir={profile}")
    time.sleep(1)
    if not _is_windows():
        subprocess.run(["pkill", "-9", "-f", f"--user-data-dir={profile}"], capture_output=True)
    time.sleep(0.5)
    pp = Path(profile)
    if pp.exists():
        for sl in pp.glob("Singleton*"):
            sl.unlink(missing_ok=True)
        if not _is_windows():
            for tmp in Path("/tmp").glob(".org.chromium.Chromium.*"):
                shutil.rmtree(tmp, ignore_errors=True)
    if _profile_has_login(profile):
        _info(f"Reusing existing profile: {profile}"); return
    _warn(f"Profile has no login data: {profile}")
    wd = Path(workdir)
    backups = sorted(wd.glob("chrome-profile-backup-*"), key=lambda p: p.name, reverse=True)
    for bk in backups:
        if _profile_has_login(str(bk)):
            _info(f"Restoring from backup: {bk}")
            if pp.exists():
                pp.rename(wd / f"chrome-profile-empty-{int(time.time())}")
            shutil.copytree(str(bk), profile)
            for sl in Path(profile).glob("Singleton*"):
                sl.unlink(missing_ok=True)
            return
    _info("No backup with login data; using a fresh profile")


def _focus_windows_window(pid: int) -> bool:
    if not _is_windows():
        return False
    try:
        import ctypes
        from ctypes import wintypes

        user32 = ctypes.windll.user32
        kernel32 = ctypes.windll.kernel32
        hwnds: list[int] = []
        WNDENUMPROC = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)

        def _enum(hwnd, _lparam):
            proc_id = wintypes.DWORD()
            user32.GetWindowThreadProcessId(hwnd, ctypes.byref(proc_id))
            if proc_id.value == pid and user32.IsWindowVisible(hwnd):
                hwnds.append(hwnd)
            return True

        for _ in range(20):
            hwnds.clear()
            user32.EnumWindows(WNDENUMPROC(_enum), 0)
            if hwnds:
                hwnd = hwnds[0]
                SW_RESTORE = 9
                user32.ShowWindow(hwnd, SW_RESTORE)
                try:
                    user32.AllowSetForegroundWindow(kernel32.GetCurrentProcessId())
                except Exception:
                    pass
                user32.SetForegroundWindow(hwnd)
                user32.BringWindowToTop(hwnd)
                return True
            time.sleep(0.25)
    except Exception:
        return False
    return False

def _backup_profile(profile: str, workdir: str, max_keep: int = 3) -> None:
    pp = Path(profile) / "Default"
    if not pp.is_dir(): return
    dst = Path(workdir) / f"chrome-profile-backup-{int(time.time())}"
    _info(f"Backing up profile → {dst}")
    try:
        shutil.copytree(profile, str(dst))
    except Exception:
        _warn("Backup failed (non-fatal)"); return
    backups = sorted(Path(workdir).glob("chrome-profile-backup-*"), key=lambda p: p.name, reverse=True)
    for old in backups[max_keep:]:
        _info(f"Removing old backup: {old}")
        shutil.rmtree(old, ignore_errors=True)

def _graceful_stop_chrome(pid: str, profile: str) -> None:
    if not pid or not _alive(pid): return
    _info(f"Stopping Chrome (PID={pid})...")
    try: os.kill(int(pid), signal.SIGTERM)
    except Exception: pass
    for _ in range(5):
        if not _alive(pid): break
        time.sleep(1)
    if _alive(pid):
        _warn("Chrome did not exit in time; forcing kill")
        try: os.kill(int(pid), signal.SIGKILL)
        except Exception: pass
        time.sleep(1)
    if profile:
        _pkill(f"--user-data-dir={profile}")
        time.sleep(0.5)

# ════════════════════════════════════════════════════════════════════════
#  Display / x11vnc / Chrome lifecycle
# ════════════════════════════════════════════════════════════════════════
def _find_novnc_web() -> str:
    for d in ("/tmp/noVNC", "/usr/share/novnc", "/usr/share/noVNC", "/opt/noVNC"):
        if os.path.isfile(f"{d}/vnc.html"): return d
    return ""

def _wait_chrome_window(dn: str, pid: int, timeout: int = 15) -> str:
    if not _cmd_ok("xdotool"): return ""
    env = dict(os.environ, DISPLAY=f":{dn}")
    deadline = time.time() + timeout
    while time.time() < deadline:
        r = _run(["xdotool", "search", "--onlyvisible", "--pid", str(pid)], env=env)
        ids = [l.strip() for l in r.stdout.splitlines() if l.strip()]
        if ids: return ids[0]
        time.sleep(0.5)
    return ""

def _start_x11vnc(dn: str, rfb: str, log: str, wid: str = "") -> tuple[str, str]:
    """Start x11vnc; returns (pid, export_mode)."""
    cmd = ["x11vnc", "-display", f":{dn}", "-forever", "-nopw", "-shared",
           "-rfbport", rfb, "-bg", "-o", log]
    mode = "display"
    if wid:
        cmd += ["-id", str(wid)]; mode = "browser-window"
    subprocess.run(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=10)
    time.sleep(0.4)
    r = _run(["pgrep", "-f", f"x11vnc.*:{dn}.*{rfb}"])
    pid = r.stdout.strip().split("\n")[0] if r.stdout.strip() else ""
    if not pid:
        import logging
        logging.getLogger("vrd").warning("x11vnc failed to start (rfbport=%s, display=:%s)", rfb, dn)
    return pid, mode

def _restart_display(env: dict, geom: str) -> None:
    """Restart Xvfb (and optional icewm); updates env."""
    dn, depth = env.get("DISPLAY_NUM", "55"), env.get("DEPTH", "16")
    for k in ("X11VNC_PID", "WM_PID", "XVFB_PID"):
        _kill(env.get(k, ""))
    for pat in (f"x11vnc.*:{dn}", f"Xvfb :{dn}", f"icewm.*:{dn}"):
        _pkill(pat)
    for p in (f"/tmp/.X{dn}-lock", f"/tmp/.X11-unix/X{dn}"):
        try: os.unlink(p)
        except FileNotFoundError: pass
    xvfb = subprocess.Popen(
        ["Xvfb", f":{dn}", "-screen", "0", f"{geom}x{depth}"],
        stdout=_logfile("xvfb.log"), stderr=subprocess.STDOUT,
    )
    time.sleep(1.5)
    if xvfb.poll() is not None:
        raise RuntimeError("Xvfb failed to start")
    env.update({"XVFB_PID": str(xvfb.pid), "WM_PID": "",
                "GEOM": geom, "CHROME_WINDOW_ID": "", "VNC_EXPORT_MODE": "display"})
    if env.get("ENABLE_WM", "0") == "1":
        fe = dict(os.environ, DISPLAY=f":{dn}")
        fx = subprocess.Popen(["icewm"], stdout=_logfile("icewm.log"),
                              stderr=subprocess.STDOUT, env=fe)
        env["WM_PID"] = str(fx.pid)

def _maximize_window(dn: str, pid: int, timeout: int = 10) -> None:
    """After Chrome window appears, maximize with xdotool (required in full-display mode)."""
    if not _cmd_ok("xdotool"): return
    env = dict(os.environ, DISPLAY=f":{dn}")
    deadline = time.time() + timeout
    while time.time() < deadline:
        r = _run(["xdotool", "search", "--onlyvisible", "--pid", str(pid)], env=env)
        ids = [l.strip() for l in r.stdout.splitlines() if l.strip()]
        if ids:
            for wid in ids:
                subprocess.run(["xdotool", "windowactivate", "--sync", wid], env=env, capture_output=True)
                subprocess.run(["xdotool", "windowsize", wid, "100%", "100%"], env=env, capture_output=True)
                subprocess.run(["xdotool", "windowmove", wid, "0", "0"], env=env, capture_output=True)
            return
        time.sleep(0.5)

def _restart_chrome(env: dict, cfg: dict) -> None:
    """Restart Chrome and x11vnc; updates env."""
    chrome = env.get("CHROME_BIN", "")
    if not chrome:
        env["CHROME_PID"] = ""
        pid, mode = _start_x11vnc(env["DISPLAY_NUM"], env.get("RFB_PORT", "5955"), str(LOGDIR / "x11vnc.log"))
        env.update({"X11VNC_PID": pid, "VNC_EXPORT_MODE": mode}); return
    _kill(env.get("CHROME_PID", ""))
    dn, cdp   = env.get("DISPLAY_NUM", "55"), env.get("CDP_PORT", "9222")
    url       = env.get("AUTO_LAUNCH_URL", "")
    profile   = env.get("CHROME_PROFILE_DIR", "")
    w, h      = cfg["window_geom"].split("x")
    only      = env.get("BROWSER_ONLY_VNC", "1") == "1"
    args = [
        chrome, "--disable-dev-shm-usage", "--disable-gpu", "--new-window",
        "--window-position=0,0", f"--window-size={w},{h}",
        "--force-device-scale-factor=1", "--hide-crash-restore-bubble", "--no-first-run",
        "--disable-extensions",
        f"--remote-debugging-port={cdp}", "--remote-debugging-address=0.0.0.0",
        "--remote-allow-origins=*", f"--user-data-dir={profile}", "--profile-directory=Default",
    ]
    if os.getuid() == 0: args.append("--no-sandbox")
    if cfg.get("mobile"):
        args += [f"--user-agent={cfg['ua']}", f"--force-device-scale-factor={cfg['dpr']}"]
    if cfg.get("touch"): args.append("--touch-events=enabled")
    args.append(f"--app={url}" if url else "about:blank")
    ce = dict(os.environ, DISPLAY=f":{dn}")
    proc = subprocess.Popen(args, stdout=_logfile("chrome.log"),
                            stderr=subprocess.STDOUT, env=ce)
    env["CHROME_PID"] = str(proc.pid)
    if only:
        wid = _wait_chrome_window(dn, proc.pid)
        pid, mode = _start_x11vnc(dn, env.get("RFB_PORT", "5955"), str(LOGDIR / "x11vnc.log"), wid)
    else:
        _maximize_window(dn, proc.pid)
        wid = ""
        pid, mode = _start_x11vnc(dn, env.get("RFB_PORT", "5955"), str(LOGDIR / "x11vnc.log"))
    env.update({"X11VNC_PID": pid, "VNC_EXPORT_MODE": mode, "CHROME_WINDOW_ID": wid or ""})

# ════════════════════════════════════════════════════════════════════════
#  Cloudflare Tunnel
# ════════════════════════════════════════════════════════════════════════
def _start_tunnel(origin: str, log_file: str) -> tuple[str, str]:
    """Start cloudflared tunnel; returns (pid, url)."""
    proc = subprocess.Popen(
        ["cloudflared", "tunnel", "--url", origin, "--no-autoupdate"],
        stdout=_logfile(Path(log_file).name, "w"), stderr=subprocess.STDOUT,
        start_new_session=True,
    )
    time.sleep(1)
    if not _alive(proc.pid): return "", ""
    for i in range(25):
        if os.path.isfile(log_file):
            text = Path(log_file).read_text(errors="replace")
            m = re.search(r"(https://[-a-zA-Z0-9.]+\.trycloudflare\.com)", text)
            if m: return str(proc.pid), m.group(1)
        if i > 0 and i % 5 == 0:
            _info(f"Waiting for Cloudflare tunnel ({origin})... {i}s")
        time.sleep(1)
    _warn(f"Cloudflare tunnel timed out ({origin})")
    return str(proc.pid), ""

# ════════════════════════════════════════════════════════════════════════
#  Device mode configuration
# ════════════════════════════════════════════════════════════════════════
def resolve_config(env: dict, mode: str) -> dict | None:
    p = PRESETS.get(mode)
    if p is None: return None
    if mode == "desktop":
        g = env.get("DESKTOP_GEOM", env.get("GEOM", "1280x720"))
        return dict(mode=mode, mobile=False, display_geom=g, window_geom=g,
                    viewer_geom=g, viewport_geom=g, dpr="1", ua="",
                    touch=False, fw="0", fh="0", label=p["label"])
    if mode == "mobile":
        vp  = env.get("MOBILE_VIEWPORT_GEOM", p["vp"])
        dpr = int(env.get("MOBILE_DPR", p["dpr"]))
        fw  = int(env.get("MOBILE_FRAME_WIDTH_PAD",  p["fw"]))
        fh  = int(env.get("MOBILE_FRAME_HEIGHT_PAD", p["fh"]))
        win = env.get("MOBILE_WINDOW_GEOM", _pad(vp, fw, fh))
        disp = env.get("MOBILE_GEOM", _scale(win, dpr))
    else:
        vp, dpr  = p["vp"], p["dpr"]
        fw, fh   = p["fw"], p["fh"]
        win      = _pad(vp, fw, fh)
        disp     = _scale(win, dpr)
    return dict(mode=mode, mobile=True, display_geom=disp, window_geom=win,
                viewer_geom=vp, viewport_geom=vp, dpr=str(dpr),
                ua=p["ua"], touch=p["touch"], fw=str(fw), fh=str(fh), label=p["label"])

def switch_mode(mode: str) -> dict:
    env = _load()
    if not env: return {"status": "error", "error": "state file not found"}
    cfg = resolve_config(env, mode)
    if cfg is None:
        return {"status": "error", "error": f"Unknown mode '{mode}'; choose one of: {list(PRESETS)}"}
    _restart_display(env, cfg["display_geom"])
    env.update({"GEOM": cfg["display_geom"], "DISPLAY_GEOM": cfg["display_geom"],
                "WINDOW_GEOM": cfg["window_geom"], "VIEWPORT_GEOM": cfg["viewport_geom"]})
    _restart_chrome(env, cfg)
    env["MODE"] = mode
    _save(env)
    return {"status": "ok", "mode": mode, "label": cfg["label"],
            "geom": cfg["display_geom"], "display_geom": cfg["display_geom"],
            "window_geom": cfg["window_geom"], "viewer_geom": cfg["viewer_geom"],
            "viewport_geom": cfg["viewport_geom"], "dpr": cfg["dpr"],
            "fw": cfg["fw"], "fh": cfg["fh"]}

# ════════════════════════════════════════════════════════════════════════
#  Screenshots / recording
# ════════════════════════════════════════════════════════════════════════
def take_screenshot(label: str = "") -> dict:
    SSHOT_DIR.mkdir(parents=True, exist_ok=True)
    env  = _load()
    dn   = env.get("DISPLAY_NUM", "55")
    ts   = int(time.time())
    safe = re.sub(r"[^a-zA-Z0-9_-]", "_", label or "shot")
    path = str(SSHOT_DIR / f"{ts}_{safe}.png")
    attempts = [
        (["scrot", "-D", f":{dn}", path], None),
        (["import", "-window", "root", path], {"DISPLAY": f":{dn}"}),
    ]
    for cmd_args, extra_env in attempts:
        run_env = dict(os.environ, **(extra_env or {}))
        try:
            r = subprocess.run(cmd_args, capture_output=True, text=True, timeout=10, env=run_env)
        except (FileNotFoundError, subprocess.TimeoutExpired):
            continue
        if r.returncode == 0 and os.path.isfile(path):
            return {"ok": True, "path": path, "filename": os.path.basename(path), "ts": ts, "label": label}
    return {"ok": False, "error": "Need scrot or ImageMagick", "ts": ts}

def _rec_tick(interval: int) -> None:
    global _rec_timer
    with _lock:
        if not _record["active"]: return
    info = take_screenshot("rec")
    if info.get("ok"):
        with _lock: _record["frames"].append(info["path"])
    _rec_timer = threading.Timer(interval, _rec_tick, args=(interval,))
    _rec_timer.daemon = True; _rec_timer.start()

def start_recording(interval: int = 3) -> dict:
    global _rec_timer
    with _lock:
        if _record["active"]: return {"ok": False, "error": "already recording"}
        d = str(SSHOT_DIR / f"rec_{int(time.time())}")
        os.makedirs(d, exist_ok=True)
        _record.update({"active": True, "dir": d, "frames": []})
    _rec_timer = threading.Timer(interval, _rec_tick, args=(interval,))
    _rec_timer.daemon = True; _rec_timer.start()
    return {"ok": True, "dir": d}

def stop_recording() -> dict:
    global _rec_timer
    with _lock:
        if not _record["active"]: return {"ok": False, "error": "not recording"}
        _record["active"] = False
        frames, d = list(_record["frames"]), _record["dir"]
    if _rec_timer: _rec_timer.cancel(); _rec_timer = None
    return {"ok": True, "frames": frames, "count": len(frames), "dir": d}

# ════════════════════════════════════════════════════════════════════════
#  Clipboard / files
# ════════════════════════════════════════════════════════════════════════
def set_clipboard(text: str) -> dict:
    env = _load(); dn = env.get("DISPLAY_NUM", "55")
    de = dict(os.environ, DISPLAY=f":{dn}")
    for tool, cmd in [
        ("xclip", ["xclip", "-selection", "clipboard"]),
        ("xsel",  ["xsel",  "--clipboard", "--input"]),
    ]:
        if not _cmd_ok(tool): continue
        r = subprocess.run(cmd, input=text, capture_output=True, text=True, env=de)
        if r.returncode == 0: return {"ok": True, "tool": tool}
    return {"ok": False, "error": "Need xclip or xsel"}

def get_clipboard() -> dict:
    env = _load(); dn = env.get("DISPLAY_NUM", "55")
    de = dict(os.environ, DISPLAY=f":{dn}")
    for tool, cmd in [
        ("xclip", ["xclip", "-selection", "clipboard", "-o"]),
        ("xsel",  ["xsel",  "--clipboard", "--output"]),
    ]:
        if not _cmd_ok(tool): continue
        r = _run(cmd, env=de)
        if r.returncode == 0: return {"ok": True, "text": r.stdout, "tool": tool}
    return {"ok": False, "text": "", "error": "Need xclip or xsel"}

def list_files(cat: str = "downloads") -> list:
    dirs = {
        "downloads":   [str(Path.home() / "Downloads"), "/tmp"],
        "screenshots": [str(SSHOT_DIR)],
        "workspace":   [str(WORKDIR)],
    }
    files: list = []
    for d in dirs.get(cat, dirs["downloads"]):
        if not os.path.isdir(d): continue
        try:
            names = sorted(os.listdir(d), key=lambda n: -os.path.getmtime(os.path.join(d, n)))[:20]
            for n in names:
                fp = os.path.join(d, n)
                if os.path.isfile(fp):
                    st = os.stat(fp)
                    files.append({"name": n, "path": fp, "size": st.st_size,
                                  "mtime": int(st.st_mtime), "dir": d})
        except PermissionError: pass
    return files[:30]

# ════════════════════════════════════════════════════════════════════════
#  Health checks
# ════════════════════════════════════════════════════════════════════════
def check_health() -> dict:
    env = _load()
    if not env: return {"ok": False, "errors": ["no state file"], "recovered": []}
    if env.get("RUNTIME_PLATFORM") == "windows-local":
        errors = []
        for k, label in [("MODE_SWITCH_PID", "serve"), ("CHROME_PID", "Chrome")]:
            pid = env.get(k, "")
            if pid and not _alive(pid):
                errors.append(f"{label} dead (pid={pid})")
        return {"ok": not errors, "errors": errors, "recovered": [], "ts": int(time.time())}
    errors, recovered = [], []
    dn = env.get("DISPLAY_NUM", "55")

    for k, label in [("XVFB_PID", "Xvfb"), ("X11VNC_PID", "x11vnc"), ("CHROME_PID", "Chrome")]:
        pid = env.get(k, "")
        if pid and not _alive(pid): errors.append(f"{label} dead (pid={pid})")

    # Auto-recover x11vnc
    x_pid = env.get("X11VNC_PID", "")
    if x_pid and not _alive(x_pid):
        _pkill(f"x11vnc.*:{dn}")
        pid, mode = _start_x11vnc(dn, env.get("RFB_PORT", "5955"),
                                  str(LOGDIR / "x11vnc.log"), env.get("CHROME_WINDOW_ID", ""))
        env.update({"X11VNC_PID": pid, "VNC_EXPORT_MODE": mode}); _save(env)
        if pid: recovered.append("x11vnc restarted")

    # Auto-recover Chrome
    chrome_pid = env.get("CHROME_PID", "")
    chrome_bin = env.get("CHROME_BIN", "")
    if chrome_pid and not _alive(chrome_pid) and chrome_bin:
        mode = env.get("MODE", "desktop")
        cfg = resolve_config(env, mode)
        if cfg:
            _restart_chrome(env, cfg)
            _save(env)
            if env.get("CHROME_PID") and _alive(env["CHROME_PID"]):
                recovered.append("chrome restarted")

    has_unrecovered = any(
        env.get(k, "") and not _alive(env.get(k, ""))
        for k in ("XVFB_PID", "X11VNC_PID", "CHROME_PID")
    )
    return {"ok": not has_unrecovered, "errors": errors, "recovered": recovered, "ts": int(time.time())}

# ════════════════════════════════════════════════════════════════════════
#  CLI: check
# ════════════════════════════════════════════════════════════════════════
def _symlink_to_path(cmd_name: str) -> bool:
    """Symlink commands visible only in login shells into /usr/local/bin to fix PATH."""
    if _cmd_ok(cmd_name): return True
    if not re.match(r"^[a-zA-Z0-9_-]+$", cmd_name): return False
    r = subprocess.run(["bash", "-lc", f"which {cmd_name} 2>/dev/null"], capture_output=True, text=True, timeout=10)
    real = r.stdout.strip()
    if not real or not os.path.isfile(real): return False
    target = f"/usr/local/bin/{cmd_name}"
    try:
        Path(target).unlink(missing_ok=True)
        os.symlink(real, target)
    except PermissionError:
        _privileged(["ln", "-sf", real, target])
    return _cmd_ok(cmd_name)

def cmd_check() -> None:
    _info("Checking VRD dependencies...")
    if _is_windows():
        for c in ("python", "curl"):
            _need(c)
        if not _cmd_ok("node") or not _cmd_ok("npm"):
            _die("Windows local browser mode requires Node.js and npm")
        npm_bin = _resolve_cmd("npm")
        agent_browser_bin = _resolve_cmd("agent-browser")
        if not _cmd_ok("agent-browser"):
            _info("Installing agent-browser...")
            subprocess.call([npm_bin, "i", "-g", "agent-browser"])
        if not _cmd_ok("agent-browser"):
            _die("agent-browser installation failed")
        pin = _env("CHROME_PIN_DIR", "chromium-1208")
        sys_c = _resolve_system_chrome()
        if sys_c:
            _info(f"System Chrome: {sys_c}")
        else:
            pin_c = _resolve_pinned_chrome(pin)
            if not pin_c:
                _info(f"Installing pinned Chrome ({pin})...")
                subprocess.call([agent_browser_bin, "install"])
                pin_c = _resolve_pinned_chrome(pin)
            if not pin_c:
                _die("No Chrome/Edge found; install a system browser or run agent-browser install")
            _info(f"pinned Chrome: {pin_c}")
        _info("All dependencies ready.")
        return
    for c in ("python3", "Xvfb", "x11vnc", "websockify", "curl"):
        _need(c)
    if _env("ENABLE_WM", "1") == "1":
        _install_pkg("icewm", "icewm")
    _install_pkg("xdotool", "xdotool")
    # node/npm may only exist on nvm login-shell PATH
    for cmd in ("node", "npm"):
        if not _cmd_ok(cmd): _symlink_to_path(cmd)
    if not _cmd_ok("agent-browser"):
        _info("Installing agent-browser...")
        subprocess.call(["bash", "-lc", "npm i -g agent-browser"])
    # Symlink into standard PATH after global install
    _symlink_to_path("agent-browser")
    if not _cmd_ok("agent-browser"):
        _die("agent-browser installation failed")
    pin = _env("CHROME_PIN_DIR", "chromium-1208")
    sys_c = _resolve_system_chrome()
    if sys_c:
        _info(f"System Chrome: {sys_c}")
    else:
        pin_c = _resolve_pinned_chrome(pin)
        if not pin_c:
            _info(f"Installing pinned Chrome ({pin})...")
            subprocess.call(["agent-browser", "install"])
            pin_c = _resolve_pinned_chrome(pin)
        if not pin_c: _die("No Chrome found; install google-chrome-stable or run agent-browser install")
        _info(f"pinned Chrome: {pin_c}")
    _info("All dependencies ready.")


def _start_windows_local_mode() -> None:
    bind = _env("KASM_BIND", "127.0.0.1")
    cdp_port = _env("CDP_PORT", "9222")
    sw_port = _env("MODE_SWITCH_PORT", "6090")
    auto_chr = _env("AUTO_LAUNCH_CHROME", "1") == "1"
    auto_url = _env("AUTO_LAUNCH_URL", "")
    profile = _env("CHROME_PROFILE_DIR", str(WORKDIR / "chrome-profile"))
    pin_dir = _env("CHROME_PIN_DIR", "chromium-1208")
    strategy = _env("CHROME_BROWSER_STRATEGY", "system-first")

    cmd_check()
    if PIDFILE.exists():
        cmd_stop(quiet=True)
        time.sleep(1)

    for d in (WORKDIR, LOGDIR, Path(profile)):
        Path(d).mkdir(parents=True, exist_ok=True)

    chrome_bin = _pick_chrome(strategy, pin_dir) if auto_chr else ""
    chrome_pid = ""
    if auto_chr:
        if not chrome_bin:
            _die("No Chrome/Edge available")
        _prepare_profile(profile, str(WORKDIR))
        args = [
            chrome_bin,
            "--new-window",
            "--no-first-run",
            "--hide-crash-restore-bubble",
            f"--remote-debugging-port={cdp_port}",
            "--remote-debugging-address=127.0.0.1",
            "--remote-allow-origins=*",
            f"--user-data-dir={profile}",
            "--profile-directory=Default",
            auto_url if auto_url else "about:blank",
        ]
        proc = subprocess.Popen(
            args,
            stdout=_logfile("chrome.log"),
            stderr=subprocess.STDOUT,
            start_new_session=True,
        )
        chrome_pid = str(proc.pid)
        _focus_windows_window(proc.pid)

    serve_proc = subprocess.Popen(
        [sys.executable, str(Path(__file__).resolve()), "serve", "--port", sw_port],
        stdout=_logfile("serve.log"),
        stderr=subprocess.STDOUT,
        env=dict(os.environ, WORKDIR=str(WORKDIR)),
        start_new_session=True,
    )
    time.sleep(1)
    if serve_proc.poll() is not None:
        _die("HTTP control plane failed to start")

    state = {
        "WORKDIR": str(WORKDIR),
        "LOGDIR": str(LOGDIR),
        "KASM_BIND": bind,
        "AUTO_LAUNCH_URL": auto_url,
        "CHROME_BIN": chrome_bin,
        "CHROME_PROFILE_DIR": profile,
        "CHROME_PID": chrome_pid,
        "CDP_PORT": cdp_port,
        "MODE_SWITCH_PID": str(serve_proc.pid),
        "MODE_SWITCH_PORT": sw_port,
        "MODE": "desktop-local",
        "RUNTIME_PLATFORM": "windows-local",
        "VNC_EXPORT_MODE": "local-browser",
        "BROWSER_ONLY_VNC": "0",
        "SWITCH_TOKEN": secrets.token_urlsafe(24),
        "PUBLIC_URL": "",
        "LOCAL_URL": f"http://127.0.0.1:{sw_port}",
    }
    _save(state)
    print("Started local browser mode.")
    print(f"Chrome: {chrome_bin}")
    print(f"CDP: {cdp_port}")
    print(f"Control: {state['LOCAL_URL']}")

# ════════════════════════════════════════════════════════════════════════
#  CLI: start
# ════════════════════════════════════════════════════════════════════════
def cmd_start() -> None:
    if _is_windows():
        _start_windows_local_mode()
        return
    # ── Configuration ──
    dn       = _env("DISPLAY_NUM",  "55")
    geom     = _env("GEOM",         "1280x720")
    depth    = _env("DEPTH",        "16")
    bind     = _env("KASM_BIND",    "127.0.0.1")
    vnc_port = _env("NOVNC_PORT",   "6080")
    rfb_port = _env("RFB_PORT",     "5955")
    cdp_port = _env("CDP_PORT",     "9222")
    sw_port  = _env("MODE_SWITCH_PORT", "6090")
    cf_on    = _env("ENABLE_CLOUDFLARE_TUNNEL", "1") == "1"
    cf_req   = _env("REQUIRE_CLOUDFLARE_LINK",  "1") == "1"
    auto_chr = _env("AUTO_LAUNCH_CHROME", "1") == "1"
    auto_url = _env("AUTO_LAUNCH_URL", "")
    profile  = _env("CHROME_PROFILE_DIR", str(WORKDIR / "chrome-profile"))
    pin_dir  = _env("CHROME_PIN_DIR", "chromium-1208")
    strategy = _env("CHROME_BROWSER_STRATEGY", "system-first")
    enable_wm     = _env("ENABLE_WM", "1")
    browser_only  = _env("BROWSER_ONLY_VNC", "0")
    mvp_geom = _env("MOBILE_VIEWPORT_GEOM", "393x852")
    m_dpr    = _env("MOBILE_DPR",    "3")
    m_fw     = _env("MOBILE_FRAME_WIDTH_PAD",  "24")
    m_fh     = _env("MOBILE_FRAME_HEIGHT_PAD", "112")
    vw, vh   = _wh(mvp_geom)
    mww      = int(_env("MOBILE_WINDOW_WIDTH",  str(vw + int(m_fw))))
    mwh      = int(_env("MOBILE_WINDOW_HEIGHT", str(vh + int(m_fh))))
    m_win    = _env("MOBILE_WINDOW_GEOM", f"{mww}x{mwh}")
    m_geom   = _env("MOBILE_GEOM", f"{mww*int(m_dpr)}x{mwh*int(m_dpr)}")

    # ── Dependencies ──
    cmd_check()
    if cf_on: _install_cloudflared()
    if cf_req and not cf_on: _die("REQUIRE_CLOUDFLARE_LINK=1 but ENABLE_CLOUDFLARE_TUNNEL=0")

    # ── noVNC ──
    novnc_web = _find_novnc_web()
    if not novnc_web: _die("noVNC static files not found")

    # ── Stop previous instance ──
    if PIDFILE.exists():
        cmd_stop(quiet=True)
        time.sleep(1)
    for pat in (f"x11vnc.*:{dn}", f"Xvfb.*:{dn}", f"websockify.*{vnc_port}", f"vrd.py.*serve"):
        _pkill(pat)
    time.sleep(1)

    # ── Directories ──
    for d in (WORKDIR, LOGDIR, Path(profile)):
        d.mkdir(parents=True, exist_ok=True) if isinstance(d, Path) else Path(d).mkdir(parents=True, exist_ok=True)
    shutil.copy2(SCRIPT_DIR / "vnc_mode.html", f"{novnc_web}/vnc_mode.html")
    for p in (f"/tmp/.X{dn}-lock", f"/tmp/.X11-unix/X{dn}"):
        try: os.unlink(p)
        except FileNotFoundError: pass

    # ── Xvfb ──
    xvfb = subprocess.Popen(
        ["Xvfb", f":{dn}", "-screen", "0", f"{geom}x{depth}"],
        stdout=_logfile("xvfb.log"), stderr=subprocess.STDOUT,
        start_new_session=True,
    )
    time.sleep(1)
    if xvfb.poll() is not None: _die("Xvfb failed to start")

    # ── WM ──
    wm_pid = ""
    if enable_wm == "1":
        wm_proc = subprocess.Popen(
            ["icewm"], stdout=_logfile("icewm.log"),
            stderr=subprocess.STDOUT, env=dict(os.environ, DISPLAY=f":{dn}"),
            start_new_session=True,
        )
        wm_pid = str(wm_proc.pid)

    # ── websockify ──
    ws = subprocess.Popen(
        ["websockify", "--web", novnc_web, f"{bind}:{vnc_port}", f"127.0.0.1:{rfb_port}"],
        stdout=_logfile("novnc.log"), stderr=subprocess.STDOUT,
        start_new_session=True,
    )
    time.sleep(1)
    if ws.poll() is not None: _die("websockify failed to start")

    # ── Chrome ──
    chrome_bin = _pick_chrome(strategy, pin_dir) if auto_chr else ""
    chrome_pid, x11vnc_pid, export_mode, win_id = "", "", "display", ""
    if auto_chr and chrome_bin:
        _prepare_profile(profile, str(WORKDIR))
        cw, ch = geom.split("x")
        c_args = [
            chrome_bin, "--disable-dev-shm-usage", "--disable-gpu", "--new-window",
            "--window-position=0,0", f"--window-size={cw},{ch}",
            "--force-device-scale-factor=1", "--hide-crash-restore-bubble", "--no-first-run",
            f"--remote-debugging-port={cdp_port}", "--remote-debugging-address=0.0.0.0",
            "--remote-allow-origins=*", f"--user-data-dir={profile}", "--profile-directory=Default",
        ]
        if os.getuid() == 0: c_args.append("--no-sandbox")
        c_args.append(f"--app={auto_url}" if auto_url else "about:blank")
        cp = subprocess.Popen(
            c_args, stdout=_logfile("chrome.log"), stderr=subprocess.STDOUT,
            env=dict(os.environ, DISPLAY=f":{dn}"), start_new_session=True,
        )
        chrome_pid = str(cp.pid)
        if browser_only == "1":
            win_id = _wait_chrome_window(dn, cp.pid)
            if win_id:
                x11vnc_pid, export_mode = _start_x11vnc(dn, rfb_port, str(LOGDIR / "x11vnc.log"), win_id)
        else:
            _maximize_window(dn, cp.pid)
    if not x11vnc_pid:
        x11vnc_pid, export_mode = _start_x11vnc(dn, rfb_port, str(LOGDIR / "x11vnc.log"))

    # ── serve (HTTP control plane; subprocess) ──
    serve_proc = subprocess.Popen(
        [sys.executable, str(Path(__file__).resolve()), "serve", "--port", sw_port],
        stdout=_logfile("serve.log"), stderr=subprocess.STDOUT,
        env=dict(os.environ, WORKDIR=str(WORKDIR)), start_new_session=True,
    )
    time.sleep(1)
    if serve_proc.poll() is not None: _die("HTTP control plane failed to start")

    # ── Cloudflare ──
    cf_vnc_pid, cf_vnc_url, cf_sw_pid, cf_sw_url = "", "", "", ""
    token = ""
    if cf_on:
        cf_vnc_pid, cf_vnc_url = _start_tunnel(f"http://127.0.0.1:{vnc_port}", str(LOGDIR / "cf-vnc.log"))
        cf_sw_pid, cf_sw_url   = _start_tunnel(f"http://127.0.0.1:{sw_port}",  str(LOGDIR / "cf-sw.log"))

    public_url = ""
    if cf_vnc_url:
        token = secrets.token_urlsafe(24)
        if cf_sw_url:
            public_url = f"{cf_vnc_url}/vnc_mode.html?switch_api={cf_sw_url}&token={token}"
        else:
            public_url = f"{cf_vnc_url}/vnc_mode.html"
    if cf_req and not public_url:
        _die("Could not obtain Cloudflare public URL; check network and retry")

    # ── Persist state ──
    state = {
        "WORKDIR": str(WORKDIR), "LOGDIR": str(LOGDIR),
        "DISPLAY": f":{dn}", "DISPLAY_NUM": dn,
        "GEOM": geom, "DISPLAY_GEOM": geom, "VIEWPORT_GEOM": geom,
        "WINDOW_GEOM": geom, "DESKTOP_GEOM": geom,
        "MOBILE_VIEWPORT_GEOM": mvp_geom, "MOBILE_DPR": m_dpr,
        "MOBILE_FRAME_WIDTH_PAD": m_fw, "MOBILE_FRAME_HEIGHT_PAD": m_fh,
        "MOBILE_WINDOW_GEOM": m_win, "MOBILE_GEOM": m_geom,
        "DEPTH": depth, "KASM_BIND": bind,
        "NOVNC_PORT": vnc_port, "RFB_PORT": rfb_port,
        "XVFB_PID": str(xvfb.pid), "WM_PID": wm_pid,
        "X11VNC_PID": x11vnc_pid, "NOVNC_PID": str(ws.pid),
        "NOVNC_WEB": novnc_web,
        "AUTO_LAUNCH_URL": auto_url,
        "CHROME_BIN": chrome_bin, "CHROME_PROFILE_DIR": profile,
        "CHROME_PID": chrome_pid, "CDP_PORT": cdp_port,
        "MODE_SWITCH_PID": str(serve_proc.pid), "MODE_SWITCH_PORT": sw_port,
        "MODE": "desktop",
        "BROWSER_ONLY_VNC": browser_only, "VNC_EXPORT_MODE": export_mode,
        "CHROME_WINDOW_ID": win_id,
        "CHROME_BROWSER_STRATEGY": strategy, "ENABLE_WM": enable_wm,
        "ENABLE_CLOUDFLARE_TUNNEL": "1" if cf_on else "0",
        "REQUIRE_CLOUDFLARE_LINK":  "1" if cf_req else "0",
        "CF_VNC_TUNNEL_PID": cf_vnc_pid, "CF_VNC_TUNNEL_URL": cf_vnc_url,
        "CF_SWITCH_TUNNEL_PID": cf_sw_pid, "CF_SWITCH_TUNNEL_URL": cf_sw_url,
        "SWITCH_TOKEN": token, "PUBLIC_URL": public_url,
    }
    _save(state)

    # ── Console output ──
    print()
    print("Virtual Remote Desktop is up.")
    print(f"URL: {public_url}")
    print(f"Display: :{dn} ({geom}x{depth})")
    print(f"Mobile: {mvp_geom} → window {m_win} → display {m_geom} @{m_dpr}x")
    print(f"Export: {export_mode}")
    if chrome_pid:
        print(f"CDP: http://127.0.0.1:{cdp_port}")
        print(f"Browser: {chrome_bin} ({strategy})")
        tag = "reuse login data" if _profile_has_login(profile) else "new"
        print(f"Profile: {tag} ({profile})")
    print(f"Cloudflare: {'ON' if cf_vnc_url else 'OFF'}")
    print(f"State: {PIDFILE}")

# ════════════════════════════════════════════════════════════════════════
#  CLI: stop
# ════════════════════════════════════════════════════════════════════════
def cmd_stop(quiet: bool = False) -> None:
    env = _load()
    if env.get("RUNTIME_PLATFORM") == "windows-local":
        if env:
            _graceful_stop_chrome(env.get("CHROME_PID", ""), env.get("CHROME_PROFILE_DIR", ""))
            _backup_profile(env.get("CHROME_PROFILE_DIR", ""), str(WORKDIR))
            for k in ("MODE_SWITCH_PID", "CHROME_PID"):
                _kill(env.get(k, ""))
            PIDFILE.unlink(missing_ok=True)
        else:
            if not quiet: _warn(f"State file missing: {PIDFILE}")
        if not quiet: print("Stopped.")
        return
    dn       = env.get("DISPLAY_NUM", "55")
    vnc_port = env.get("NOVNC_PORT",  "6080")
    sw_port  = env.get("MODE_SWITCH_PORT", "6090")
    if env:
        _graceful_stop_chrome(env.get("CHROME_PID", ""), env.get("CHROME_PROFILE_DIR", ""))
        _backup_profile(env.get("CHROME_PROFILE_DIR", ""), str(WORKDIR))
        for k in ("NOVNC_PID", "X11VNC_PID", "WM_PID",
                   "MODE_SWITCH_PID", "CF_VNC_TUNNEL_PID", "CF_SWITCH_TUNNEL_PID", "XVFB_PID"):
            _kill(env.get(k, ""))
        PIDFILE.unlink(missing_ok=True)
    else:
        if not quiet: _warn(f"State file missing: {PIDFILE}")
    for pat in (f"Xvfb :{dn}", f"x11vnc.*:{dn}", f"websockify.*:{vnc_port}",
                f"icewm.*:{dn}", f"cloudflared.*127.0.0.1:{vnc_port}",
                f"cloudflared.*127.0.0.1:{sw_port}"):
        _pkill(pat)
    for p in (f"/tmp/.X{dn}-lock", f"/tmp/.X11-unix/X{dn}"):
        try: os.unlink(p)
        except FileNotFoundError: pass
    _close_log_handles()
    if not quiet: print("Stopped.")

# ════════════════════════════════════════════════════════════════════════
#  CLI: status
# ════════════════════════════════════════════════════════════════════════
def cmd_status() -> None:
    env = _load()
    if not env: _die("State file missing (VRD not running)")
    def tag(k):
        pid = env.get(k, "")
        return f"up ({pid})" if pid and _alive(pid) else "down"
    cookie = Path(env.get("CHROME_PROFILE_DIR", "")) / "Default" / "Cookies"
    login  = "present" if cookie.is_file() else "missing"
    if env.get("RUNTIME_PLATFORM") == "windows-local":
        lines = [
            "status:",
            "  platform:   windows-local",
            f"  serve:      {tag('MODE_SWITCH_PID')}",
            f"  chrome:     {tag('CHROME_PID')}",
            f"  mode:       {env.get('MODE', 'desktop-local')}",
            f"  export:     {env.get('VNC_EXPORT_MODE', 'local-browser')}",
            f"  chrome_bin: {env.get('CHROME_BIN', '')}",
            f"  cdp:        {env.get('CDP_PORT', '')}",
            f"  cookies:    {login}",
            f"  local_url:  {env.get('LOCAL_URL', 'none')}",
        ]
        print("\n".join(lines))
        return
    lines = [
        "status:",
        f"  xvfb:       {tag('XVFB_PID')}",
        f"  wm:         {tag('WM_PID')}",
        f"  x11vnc:     {tag('X11VNC_PID')}",
        f"  novnc:      {tag('NOVNC_PID')}",
        f"  serve:      {tag('MODE_SWITCH_PID')}",
        f"  tunnel_vnc: {tag('CF_VNC_TUNNEL_PID')}",
        f"  tunnel_api: {tag('CF_SWITCH_TUNNEL_PID')}",
        f"  chrome:     {tag('CHROME_PID')}",
        f"  display:    {env.get('DISPLAY', '')}",
        f"  geom:       {env.get('GEOM', '')}",
        f"  mode:       {env.get('MODE', 'desktop')}",
        f"  export:     {env.get('VNC_EXPORT_MODE', '')}",
        f"  chrome_bin: {env.get('CHROME_BIN', '')}",
        f"  cdp:        {env.get('CDP_PORT', '')}",
        f"  cookies:    {login}",
        f"  url:        {env.get('PUBLIC_URL', 'none')}",
    ]
    print("\n".join(lines))

# ════════════════════════════════════════════════════════════════════════
#  CLI: switch / screenshot / clipboard
# ════════════════════════════════════════════════════════════════════════
def cmd_switch(mode: str) -> None:
    if not mode: _die(f"usage: vrd.py switch <mode>  modes: {list(PRESETS)}")
    res = switch_mode(mode)
    if res.get("status") == "ok":
        print(f"Switched: {res.get('label')} ({res.get('display_geom')})")
    else:
        _die(res.get("error", "switch failed"))

def cmd_screenshot(label: str = "") -> None:
    r = take_screenshot(label)
    if r.get("ok"): print(f"Screenshot: {r['path']}")
    else: _die(r.get("error", "screenshot failed"))

def cmd_clipboard(args: list) -> None:
    if not args: _die("usage: vrd.py clipboard get|set <text>")
    if args[0] == "get":
        r = get_clipboard()
        if r.get("ok"): print(r["text"])
        else: _die(r.get("error", ""))
    elif args[0] == "set":
        text = " ".join(args[1:])
        r = set_clipboard(text)
        if r.get("ok"): print("✓")
        else: _die(r.get("error", ""))
    else:
        _die("usage: vrd.py clipboard get|set <text>")


def cmd_export_session(args: list) -> None:
    if len(args) < 2:
        _die("usage: vrd.py export-session <platform> <output_path>")
    result = export_session(args[0], args[1])
    print(f"session exported: {result['path']}")

# ════════════════════════════════════════════════════════════════════════
#  HTTP control plane (serve)
# ════════════════════════════════════════════════════════════════════════
class _Handler(BaseHTTPRequestHandler):

    def _cors(self):
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET,POST,DELETE,OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")

    def do_OPTIONS(self):
        self.send_response(204); self._cors()
        self.send_header("Content-Length", "0"); self.end_headers()

    def _body(self) -> dict:
        n = int(self.headers.get("Content-Length", 0))
        if n:
            try: return json.loads(self.rfile.read(n))
            except Exception: pass
        return {}

    def _dispatch(self, method):
        parsed  = urlparse(self.path)
        qs      = parse_qs(parsed.query)
        path    = parsed.path.rstrip("/") or "/"
        env, ok = _auth(qs)
        body    = self._body() if method in ("POST", "DELETE") else {}

        if not ok:
            return self._err(403, "forbidden")
        if path == "/gate" and method == "GET":
            with _lock: return self._ok(dict(_gate))
        if path == "/guide" and method == "GET":
            with _lock: return self._ok(dict(_guide))

        # /status
        if path == "/status" and method == "GET":
            is_mob = env.get("MODE", "desktop") != "desktop"
            with _lock: rec = _record["active"]
            return self._ok({
                "mode": env.get("MODE", "desktop"),
                "geom": env.get("GEOM", ""),
                "display_geom":  env.get("DISPLAY_GEOM",  env.get("GEOM", "")),
                "window_geom":   env.get("WINDOW_GEOM",   env.get("GEOM", "")),
                "viewer_geom":   env.get("VIEWPORT_GEOM", env.get("GEOM", "")),
                "viewport_geom": env.get("VIEWPORT_GEOM", env.get("GEOM", "")),
                "dpr":  env.get("MOBILE_DPR", "3") if is_mob else "1",
                "fw":   env.get("MOBILE_FRAME_WIDTH_PAD",  "24") if is_mob else "0",
                "fh":   env.get("MOBILE_FRAME_HEIGHT_PAD", "112") if is_mob else "0",
                "export": env.get("VNC_EXPORT_MODE", "display"),
                "browser_only_vnc": env.get("BROWSER_ONLY_VNC", "1"),
                "presets": list(PRESETS), "recording": rec,
                "health": check_health().get("ok", True),
            })
        if path == "/presets" and method == "GET":
            return self._ok({k: {"label": v["label"], "viewport": v["vp"], "dpr": v["dpr"]}
                             for k, v in PRESETS.items()})
        # /switch
        if path == "/switch" and method == "POST":
            mode = qs.get("mode", [""])[0] or body.get("mode", "")
            try:
                res = switch_mode(mode)
                return self._ok(res) if res.get("status") == "ok" else self._err(400, res.get("error", ""))
            except Exception as e: return self._err(500, str(e))
        # /guide
        if path == "/guide":
            if method == "POST":
                with _lock: _guide.update({"text": body.get("text", ""), "kind": body.get("kind", "info"), "ts": time.time()})
                return self._ok({"ok": True})
            if method == "DELETE":
                with _lock: _guide.update({"text": "", "kind": "info", "ts": time.time()})
                return self._ok({"ok": True})
            if method == "GET":
                with _lock: return self._ok(dict(_guide))
        # /continue
        if path == "/continue" and method == "POST":
            with _lock: _cont["ts"] = time.time()
            return self._ok({"ok": True, "ts": _cont["ts"]})
        if path == "/continue/poll" and method == "GET":
            after   = float(qs.get("after",   ["0"])[0])
            timeout = min(float(qs.get("timeout", ["30"])[0]), 30)
            deadline = time.time() + timeout
            while time.time() < deadline:
                with _lock:
                    if _cont["ts"] > after: return self._ok({"ok": True, "signaled": True, "ts": _cont["ts"]})
                time.sleep(0.5)
            with _lock: return self._ok({"ok": True, "signaled": False, "ts": _cont["ts"]})
        # /gate
        if path == "/gate":
            if method == "POST":
                with _lock: _gate.update({"id": str(uuid.uuid4())[:8], "prompt": body.get("prompt", "Confirm?"),
                                          "approved": None, "ts": time.time(), "timeout": body.get("timeout", 300)})
                return self._ok({"ok": True, "id": _gate["id"]})
            if method == "GET":
                with _lock: return self._ok(dict(_gate))
            if method == "DELETE":
                with _lock: _gate.update({"id": "", "prompt": "", "approved": None, "ts": time.time()})
                return self._ok({"ok": True})
        if path == "/gate/respond" and method == "POST":
            with _lock: _gate["approved"] = bool(body.get("approved", False))
            return self._ok({"ok": True, "approved": _gate["approved"]})
        # /screenshot
        if path == "/screenshot" and method == "POST":
            r = take_screenshot(body.get("label", ""))
            return self._ok(r) if r.get("ok") else self._err(500, r.get("error", ""))
        if path == "/screenshots" and method == "GET":
            files = sorted(_glob.glob(str(SSHOT_DIR / "*.png")), key=lambda p: -os.path.getmtime(p))[:50]
            return self._ok({"files": [{"path": p, "filename": os.path.basename(p),
                                        "mtime": int(os.path.getmtime(p)), "size": os.path.getsize(p)} for p in files]})
        # /record
        if path == "/record/start" and method == "POST":
            return self._ok(start_recording(body.get("interval", 3)))
        if path == "/record/stop" and method == "POST":
            return self._ok(stop_recording())
        # /clipboard
        if path == "/clipboard":
            if method == "POST": return self._ok(set_clipboard(body.get("text", "")))
            if method == "GET":  return self._ok(get_clipboard())
        # /files
        if path == "/files" and method == "GET":
            cat = qs.get("dir", ["downloads"])[0]
            return self._ok({"files": list_files(cat), "category": cat})
        # /health
        if path == "/health" and method == "GET":
            return self._ok(check_health())

        self._err(404, "not found")

    def do_GET(self):    self._dispatch("GET")
    def do_POST(self):   self._dispatch("POST")
    def do_DELETE(self):  self._dispatch("DELETE")

    def _ok(self, body):  self._json(200, body)
    def _err(self, code, msg): self._json(code, {"status": "error", "error": msg})
    def _json(self, code, body):
        raw = json.dumps(body, ensure_ascii=False).encode()
        self.send_response(code); self._cors()
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(raw))); self.end_headers()
        self.wfile.write(raw)

    def log_message(self, fmt, *args):
        sys.stderr.write("[vrd] " + (fmt % args) + "\n")

def _auth(params):
    env = _load()
    return env, bool(env.get("SWITCH_TOKEN")) and params.get("token", [""])[0] == env["SWITCH_TOKEN"]

def cmd_serve() -> None:
    SSHOT_DIR.mkdir(parents=True, exist_ok=True)
    port = 6090
    if "--port" in sys.argv:
        i = sys.argv.index("--port")
        if i + 1 < len(sys.argv): port = int(sys.argv[i + 1])
    print(f"[vrd] HTTP control plane 0.0.0.0:{port}")
    ThreadingHTTPServer(("0.0.0.0", port), _Handler).serve_forever()

# ════════════════════════════════════════════════════════════════════════
#  Entry
# ════════════════════════════════════════════════════════════════════════
USAGE = """usage: python3 vrd.py <command>

  check                     Check / install dependencies
  start                     Start full stack
  stop                      Stop and back up profile
  status                    Show status
  serve [--port 6090]       HTTP control plane
  switch <mode>             Switch device preset
  screenshot [label]        Screenshot
  clipboard get|set <text>  Clipboard
  export-session <platform> <output_path>  Export browser session
"""

def main() -> None:
    if len(sys.argv) < 2:
        print(USAGE); return
    cmd = sys.argv[1]
    dispatch = {
        "check":      cmd_check,
        "start":      cmd_start,
        "stop":       lambda: cmd_stop(),
        "status":     cmd_status,
        "serve":      cmd_serve,
        "switch":     lambda: cmd_switch(sys.argv[2] if len(sys.argv) > 2 else ""),
        "screenshot": lambda: cmd_screenshot(sys.argv[2] if len(sys.argv) > 2 else ""),
        "clipboard":  lambda: cmd_clipboard(sys.argv[2:]),
        "export-session": lambda: cmd_export_session(sys.argv[2:]),
    }
    fn = dispatch.get(cmd)
    if fn: fn()
    else: print(USAGE)

if __name__ == "__main__":
    main()
