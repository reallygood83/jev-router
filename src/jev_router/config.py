import ast
import json
import os
from pathlib import Path
from typing import Any

from .registry import model_from_dict, model_to_dict


def default_config_path():
    return Path.home() / ".config" / "jev-router" / "config.json"


def load_config(path=None) -> dict[str, Any]:
    target = Path(path or default_config_path())
    if not target.exists():
        return {"registry": [], "health": {}, "jev": {}, "policy": {}}
    payload = json.loads(target.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("config must be a JSON object")
    payload.setdefault("registry", [])
    payload.setdefault("health", {})
    payload.setdefault("jev", {})
    payload.setdefault("policy", {})
    return payload


def save_config(path, config: dict[str, Any]) -> None:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = target.with_suffix(target.suffix + ".tmp")
    temporary.write_text(json.dumps(config, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    os.replace(temporary, target)


def models_from_config(config: dict[str, Any]):
    return [model_from_dict(item) for item in config.get("registry", [])]


def put_models(config: dict[str, Any], models):
    config["registry"] = [model_to_dict(model) for model in models]
    return config


def load_weights(path) -> dict[str, Any]:
    target = Path(path)
    values = {}
    for line in target.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, raw = line.split("=", 1)
        try:
            value = ast.literal_eval(raw.strip())
        except (SyntaxError, ValueError):
            value = raw.strip().strip('"').strip("'")
        values[key.strip()] = value
    return values
