import os
from pathlib import Path


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
    return user_home() / ".config" / "jev-gate"
