import os
from pathlib import Path


def _writable(directory):
    try:
        directory.mkdir(parents=True, exist_ok=True)
        probe = directory / ".write-test"
        probe.write_text("ok", encoding="utf-8")
        probe.unlink()
        return True
    except OSError:
        return False


def user_home():
    override = os.environ.get("JEV_GATE_HOME")
    if override:
        return Path(override).expanduser()
    home = Path.home()
    if "aside/runtime/home" in str(home).replace("\\", "/"):
        real = Path("/Users") / (os.environ.get("USER") or "moon")
        if real.is_dir():
            return real
    return home


def config_dir():
    candidates = [
        user_home() / ".config" / "jev-gate",
        Path.home() / ".config" / "jev-gate",
        Path("/tmp/jev-gate"),
    ]
    for directory in candidates:
        if _writable(directory):
            return directory
    return candidates[-1]
