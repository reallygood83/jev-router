import json
import os
from pathlib import Path


EFFORTS = ("", "low", "medium", "high", "xhigh", "max", "ultra")
DEFAULT_ROLES = {
    "implement": {
        "when": "Write or edit code in the repo.",
        "model": "gpt-5.6-terra",
        "reasoning_effort": "high",
    },
    "research": {
        "when": "Look up current facts, prices, or docs.",
        "model": "xai/grok-4.5",
        "reasoning_effort": "medium",
    },
    "write": {
        "when": "Draft or edit prose. Korean quality may matter.",
        "model": "gpt-5.6-sol",
        "reasoning_effort": "low",
    },
}


def default_pack_path():
    return Path.home() / ".config" / "jev-gate" / "pack.json"


def empty_pack():
    return {
        "home_model": "gpt-5.6-sol",
        "home_reasoning_effort": "",
        "confidence_floor": 0.6,
        "enabled": True,
        "max_task_chars": 2000,
        "roles": {key: dict(value) for key, value in DEFAULT_ROLES.items()},
    }


def _effort(value):
    effort = str(value or "").strip().lower()
    return effort if effort in EFFORTS else ""


def _role_entry(value):
    if not isinstance(value, dict):
        return None
    model = str(value.get("model") or "").strip()
    when = str(value.get("when") or "").strip()
    if not model:
        return None
    return {"model": model, "when": when or model, "reasoning_effort": _effort(value.get("reasoning_effort"))}


def normalize_pack(raw):
    pack = empty_pack()
    if not isinstance(raw, dict):
        pack["enabled"] = False
        pack["_error"] = "pack must be a JSON object"
        return pack
    home = str(raw.get("home_model") or pack["home_model"]).strip()
    if home:
        pack["home_model"] = home
    try:
        floor = float(raw.get("confidence_floor", pack["confidence_floor"]))
    except (TypeError, ValueError):
        floor = 0.6
    pack["confidence_floor"] = min(1.0, max(0.0, floor))
    pack["enabled"] = bool(raw.get("enabled", True))
    pack["home_reasoning_effort"] = _effort(raw.get("home_reasoning_effort"))
    try:
        pack["max_task_chars"] = max(32, int(raw.get("max_task_chars", 2000)))
    except (TypeError, ValueError):
        pack["max_task_chars"] = 2000
    roles = {}
    incoming = raw.get("roles")
    if isinstance(incoming, dict):
        for key, value in incoming.items():
            slug = str(key).strip()
            if not slug or slug in {"home", "other"}:
                continue
            entry = _role_entry(value)
            if entry:
                roles[slug] = entry
            if len(roles) >= 4:
                break
    pack["roles"] = roles
    return pack


def load_pack(path=None):
    target = Path(path or default_pack_path())
    if not target.exists():
        return empty_pack()
    try:
        raw = json.loads(target.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        pack = empty_pack()
        pack["enabled"] = False
        pack["_error"] = str(exc)
        return pack
    return normalize_pack(raw)


def save_pack(pack, path=None):
    target = Path(path or default_pack_path())
    target.parent.mkdir(parents=True, exist_ok=True)
    payload = normalize_pack(pack)
    payload.pop("_error", None)
    temporary = target.with_suffix(target.suffix + ".tmp")
    temporary.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    os.replace(temporary, target)
    return payload


def filled_roles(pack):
    roles = pack.get("roles") if isinstance(pack, dict) else {}
    if not isinstance(roles, dict):
        return {}
    return {key: value for key, value in roles.items() if isinstance(value, dict) and value.get("model")}
