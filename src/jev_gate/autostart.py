import os
import subprocess
import sys
from pathlib import Path

from .paths import user_home


LABEL = "local.jev-gate"


def plist_path():
    return user_home() / "Library" / "LaunchAgents" / f"{LABEL}.plist"


def log_path():
    return user_home() / "Library" / "Logs" / "jev-gate.log"


def _xml(value):
    return str(value).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def _pythonpath():
    root = Path(__file__).resolve().parent.parent
    if (root / "jev_gate").is_dir() and root.name == "src":
        return str(root)
    return ""


def render_plist(host, port, upstream):
    python = sys.executable
    env = _pythonpath()
    env_xml = ""
    if env:
        env_xml = f"""
  <key>EnvironmentVariables</key>
  <dict>
    <key>PYTHONPATH</key>
    <string>{_xml(env)}</string>
  </dict>"""
    return f"""<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key>
  <string>{LABEL}</string>
  <key>ProgramArguments</key>
  <array>
    <string>{_xml(python)}</string>
    <string>-m</string>
    <string>jev_gate</string>
    <string>--host</string>
    <string>{_xml(host)}</string>
    <string>--port</string>
    <string>{int(port)}</string>
    <string>--upstream</string>
    <string>{_xml(upstream)}</string>
  </array>
  <key>RunAtLoad</key>
  <true/>
  <key>KeepAlive</key>
  <true/>
  <key>StandardOutPath</key>
  <string>{_xml(log_path())}</string>
  <key>StandardErrorPath</key>
  <string>{_xml(log_path())}</string>{env_xml}
</dict>
</plist>
"""


def _launchctl(*args):
    return subprocess.run(["launchctl", *args], capture_output=True, text=True)


def status():
    path = plist_path()
    loaded = False
    uid = os.getuid()
    probe = _launchctl("print", f"gui/{uid}/{LABEL}")
    if probe.returncode == 0:
        loaded = True
    else:
        probe = _launchctl("list", LABEL)
        loaded = probe.returncode == 0
    return {
        "enabled": path.exists(),
        "loaded": loaded,
        "plist": str(path) if path.exists() else "",
        "log": str(log_path()),
    }


def enable(host="127.0.0.1", port=10115, upstream="http://127.0.0.1:10100"):
    path = plist_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    log_path().parent.mkdir(parents=True, exist_ok=True)
    path.write_text(render_plist(host, port, upstream), encoding="utf-8")
    uid = os.getuid()
    domain = f"gui/{uid}"
    _launchctl("bootout", f"{domain}/{LABEL}")
    loaded = _launchctl("bootstrap", domain, str(path))
    if loaded.returncode != 0:
        loaded = _launchctl("load", "-w", str(path))
    result = status()
    result["ok"] = path.exists()
    result["launchctl"] = (loaded.stderr or loaded.stdout or "").strip()[:300]
    return result


def disable():
    uid = os.getuid()
    _launchctl("bootout", f"gui/{uid}/{LABEL}")
    _launchctl("unload", "-w", str(plist_path()))
    path = plist_path()
    if path.exists():
        path.unlink()
    result = status()
    result["ok"] = True
    return result
