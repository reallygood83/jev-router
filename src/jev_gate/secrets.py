import json
import os
from pathlib import Path

from .paths import config_dir


def default_secrets_path():
    return config_dir() / "secrets.json"


def _read(path):
    target = Path(path or default_secrets_path())
    if not target.exists():
        return {}
    try:
        payload = json.loads(target.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return payload if isinstance(payload, dict) else {}


def key_is_set(path=None):
    if os.environ.get("TYPESAFE_API_KEY", "").strip():
        return True
    return bool(str(_read(path).get("typesafe_api_key") or "").strip())


def load_key(path=None):
    env = os.environ.get("TYPESAFE_API_KEY", "").strip()
    if env:
        return env
    return str(_read(path).get("typesafe_api_key") or "").strip()


def save_key(key, path=None, clear=False):
    target = Path(path or default_secrets_path())
    target.parent.mkdir(parents=True, exist_ok=True)
    payload = _read(target)
    if clear:
        payload.pop("typesafe_api_key", None)
    elif key is not None and str(key).strip():
        payload["typesafe_api_key"] = str(key).strip()
    temporary = target.with_suffix(target.suffix + ".tmp")
    temporary.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    os.replace(temporary, target)
    os.chmod(target, 0o600)
    return key_is_set(target)
