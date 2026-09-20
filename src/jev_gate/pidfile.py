import os
import signal
import time
from pathlib import Path

from .paths import config_dir


def pid_path(port):
    return config_dir() / f"jev-gate-{int(port)}.pid"


def _alive(pid):
    try:
        os.kill(pid, 0)
        return True
    except ProcessLookupError:
        return False
    except PermissionError:
        return True


def replace_previous(port):
    path = pid_path(port)
    if not path.exists():
        return
    try:
        old = int(path.read_text(encoding="utf-8").strip())
    except (OSError, ValueError):
        return
    if old == os.getpid():
        return
    if not _alive(old):
        try:
            path.unlink()
        except OSError:
            pass
        return
    for sig in (signal.SIGTERM, signal.SIGKILL):
        try:
            os.kill(old, sig)
        except ProcessLookupError:
            break
        except PermissionError:
            break
        time.sleep(0.25)
    try:
        path.unlink()
    except OSError:
        pass


def write_pid(port):
    path = pid_path(port)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(str(os.getpid()) + "\n", encoding="utf-8")
    return path
