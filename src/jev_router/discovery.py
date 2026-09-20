import ast
import json
import re
import shutil
import subprocess
from pathlib import Path

from .registry import ModelSpec


def parse_grok_models(output):
    models = []
    for line in output.splitlines():
        value = line.strip()
        if not value.startswith("-"):
            continue
        model = value[1:].strip()
        if model and model not in models:
            models.append(model)
    return models


def parse_cursor_models(output):
    models = []
    for line in output.splitlines():
        value = line.strip()
        if " - " not in value:
            continue
        model = value.split(" - ", 1)[0].strip()
        if model and model.lower() != "available models" and model not in models:
            models.append(model)
    return models


def parse_codex_catalog(data):
    models = []
    for entry in data.get("models", []) if isinstance(data, dict) else []:
        if not isinstance(entry, dict):
            continue
        slug = entry.get("slug")
        if slug and slug not in models:
            models.append(str(slug))
    return models


def _value(text):
    value = text.strip()
    if " #" in value:
        value = value.split(" #", 1)[0].rstrip()
    try:
        return ast.literal_eval(value)
    except (SyntaxError, ValueError):
        return value.strip('"').strip("'")


def _sections(path):
    if not path.exists():
        return {}
    sections = {}
    current = None
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError:
        return {}
    for line in lines:
        match = re.match(r"\s*\[([^\]]+)\]", line)
        if match:
            current = match.group(1)
            sections.setdefault(current, {})
            continue
        match = re.match(r"\s*([A-Za-z0-9_.-]+)\s*=\s*(.+?)\s*$", line)
        if match and current is not None:
            sections[current][match.group(1)] = _value(match.group(2))
    return sections


def _config_value(path, key):
    if not path.exists():
        return None
    try:
        for line in path.read_text(encoding="utf-8").splitlines():
            match = re.match(rf"\s*{re.escape(key)}\s*=\s*(['\"])(.+?)\1", line)
            if match:
                return match.group(2)
    except OSError:
        return None
    return None


def _command(command, timeout, runner=None):
    if runner is not None:
        result = runner(command, timeout=timeout)
    else:
        if not shutil.which(command[0]):
            return None, "executable unavailable"
        try:
            result = subprocess.run(
                command,
                cwd=str(Path.home()),
                stdin=subprocess.DEVNULL,
                capture_output=True,
                text=True,
                timeout=timeout,
                check=False,
            )
        except subprocess.TimeoutExpired:
            return None, "timeout"
        except OSError:
            return None, "provider process unavailable"
    if isinstance(result, tuple):
        code, stdout, _stderr = result
    else:
        code = result.returncode
        stdout = result.stdout or ""
    if code != 0:
        return None, f"command failed (exit {code})"
    return str(stdout), ""


def _model_spec(provider, model, kind=None, context_tokens=0, purpose=""):
    resolved_kind = kind or provider
    flags = {
        "codex": ("-m", model),
        "grok": ("-m", model),
        "claude": ("--model", model),
        "cursor": ("--model", model),
        "kimi": ("--model", model),
    }
    return ModelSpec(
        id=f"{provider}:{model}",
        provider=provider,
        model=model,
        kind=resolved_kind,
        argv=flags.get(resolved_kind, ()),
        context_tokens=int(context_tokens or 0),
        purpose=purpose,
    )


def _grok_specs(home, runner=None):
    path = home / ".grok" / "config.toml"
    sections = _sections(path)
    specs = []
    for section, values in sections.items():
        if not section.startswith("model.") or not values.get("model"):
            continue
        model = str(values["model"])
        specs.append(_model_spec("grok", model, "grok", values.get("context_window", 0), "Configured in Grok"))
    if specs:
        return specs, "ok", "config"
    output, reason = _command(["grok", "inspect", "--json"], 20, runner)
    if output is not None:
        return [], "ok", "inspect"
    return [], "unavailable", reason


def _codex_specs(home):
    config = home / ".codex" / "config.toml"
    catalog_name = _config_value(config, "model_catalog_json")
    catalog = Path(catalog_name).expanduser() if catalog_name else home / ".codex" / "opencodex-catalog.json"
    if not catalog.exists():
        return [], "unavailable", "catalog unavailable"
    try:
        data = json.loads(catalog.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return [], "unavailable", "catalog unreadable"
    specs = []
    for entry in data.get("models", []):
        if not isinstance(entry, dict) or not entry.get("slug"):
            continue
        if entry.get("visibility") == "hide":
            continue
        specs.append(
            _model_spec(
                "codex",
                str(entry["slug"]),
                "codex",
                entry.get("context_window", 0),
                "Codex catalog model",
            )
        )
    return specs, "ok", "catalog"


def _cursor_specs(runner=None):
    output, reason = _command(["agent", "--list-models"], 20, runner)
    if output is None:
        return [], "unavailable", reason
    return [
        _model_spec("cursor", model, "cursor", purpose="Cursor Agent model")
        for model in parse_cursor_models(output)
    ], "ok", "agent --list-models"


def _claude_specs(home):
    if shutil.which("claude") is None:
        return [], "unavailable", "executable unavailable"
    aliases = ["fable", "opus", "sonnet"]
    names = list(aliases)
    settings = home / ".claude" / "settings.json"
    try:
        payload = json.loads(settings.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        payload = {}
    for item in payload.get("models", []) if isinstance(payload, dict) else []:
        if isinstance(item, dict):
            name = item.get("name") or item.get("displayName")
            if name and name not in names:
                names.append(str(name))
    return [
        _model_spec("claude", name, "claude", purpose="Claude alias or local setting")
        for name in names
    ], "ok", "aliases/settings"


def _kimi_specs(home, runner=None):
    sections = _sections(home / ".kimi-code" / "config.toml")
    specs = []
    for section, values in sections.items():
        if section.startswith("models.") and values.get("model"):
            specs.append(
                _model_spec(
                    "kimi",
                    str(values["model"]),
                    "kimi",
                    values.get("max_context_size", 0),
                    "Kimi provider configuration",
                )
            )
    output, reason = _command(
        [str(home / ".kimi-code" / "bin" / "kimi"), "provider", "list"],
        20,
        runner,
    )
    if specs:
        return specs, "ok", "config"
    if output is not None:
        return [], "ok", "provider list"
    return [], "unavailable", reason


def discover_local_models(home=None, runner=None):
    root = Path(home or Path.home())
    providers = {}
    all_specs = []
    for name, loader in (
        ("codex", lambda: _codex_specs(root)),
        ("grok", lambda: _grok_specs(root, runner)),
        ("claude", lambda: _claude_specs(root)),
        ("cursor", lambda: _cursor_specs(runner)),
        ("kimi", lambda: _kimi_specs(root, runner)),
    ):
        specs, status, source = loader()
        providers[name] = {
            "status": status,
            "source": source,
            "models": [model.model for model in specs],
        }
        all_specs.extend(specs)
    unique = {}
    for model in all_specs:
        unique[model.id] = model
    return {
        "providers": providers,
        "models": [
            {
                "id": model.id,
                "provider": model.provider,
                "model": model.model,
                "kind": model.kind,
                "argv": list(model.argv),
                "context_tokens": model.context_tokens,
                "purpose": model.purpose,
            }
            for model in unique.values()
        ],
    }
