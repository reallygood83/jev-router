import json
import os
import shutil
import sys
from pathlib import Path


SKILL_SRC = Path(__file__).resolve().parent / "static" / "typesafe-skill" / "SKILL.md"
REPO_ROOT = Path(__file__).resolve().parents[2]
SKILL_DIRS = (
    Path.home() / ".agents" / "skills" / "typesafe-ai",
    Path.home() / ".codex" / "skills" / "typesafe-ai",
    Path.home() / ".claude" / "skills" / "typesafe-ai",
)
MCP_BLOCK = """
[mcp_servers.typesafe-jev]
command = {command!r}
args = ["-m", "jev_gate.mcp"]
cwd = {cwd!r}
startup_timeout_sec = 20.0

[mcp_servers.typesafe-jev.env]
PYTHONPATH = {pythonpath!r}
"""


def install_skill():
    if not SKILL_SRC.exists():
        raise FileNotFoundError("bundled TypeSafe skill is missing")
    installed = []
    for folder in SKILL_DIRS:
        folder.mkdir(parents=True, exist_ok=True)
        target = folder / "SKILL.md"
        shutil.copyfile(SKILL_SRC, target)
        installed.append(str(target))
    return {"ok": True, "kind": "skill", "paths": installed}


def _mcp_command():
    return {
        "command": sys.executable,
        "args": ["-m", "jev_gate.mcp"],
        "cwd": str(REPO_ROOT),
        "env": {"PYTHONPATH": str(REPO_ROOT / "src")},
    }


def _install_codex_mcp():
    path = Path.home() / ".codex" / "config.toml"
    path.parent.mkdir(parents=True, exist_ok=True)
    existing = path.read_text(encoding="utf-8") if path.exists() else ""
    if "[mcp_servers.typesafe-jev]" in existing:
        return str(path), False
    spec = _mcp_command()
    block = MCP_BLOCK.format(command=spec["command"], cwd=spec["cwd"], pythonpath=spec["env"]["PYTHONPATH"])
    if existing and not existing.endswith("\n"):
        existing += "\n"
    path.write_text(existing + block, encoding="utf-8")
    return str(path), True


def _install_claude_mcp():
    path = Path.home() / ".claude.json"
    if not path.exists():
        return None, False
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError("claude.json is not an object")
    servers = data.setdefault("mcpServers", {})
    if not isinstance(servers, dict):
        raise ValueError("mcpServers is not an object")
    created = "typesafe-jev" not in servers
    spec = _mcp_command()
    servers["typesafe-jev"] = {
        "command": spec["command"],
        "args": spec["args"],
        "env": spec["env"],
    }
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    os.replace(temporary, path)
    return str(path), created


def install_mcp():
    codex_path, codex_created = _install_codex_mcp()
    claude_path, claude_created = _install_claude_mcp()
    return {
        "ok": True,
        "kind": "mcp",
        "codex": {"path": codex_path, "created": codex_created},
        "claude": {"path": claude_path, "created": claude_created},
    }


def install_status():
    skills = [str(folder / "SKILL.md") for folder in SKILL_DIRS if (folder / "SKILL.md").exists()]
    codex = Path.home() / ".codex" / "config.toml"
    claude = Path.home() / ".claude.json"
    mcp_codex = False
    if codex.exists():
        mcp_codex = "[mcp_servers.typesafe-jev]" in codex.read_text(encoding="utf-8")
    mcp_claude = False
    if claude.exists():
        try:
            data = json.loads(claude.read_text(encoding="utf-8"))
            mcp_claude = "typesafe-jev" in (data.get("mcpServers") or {})
        except ValueError:
            mcp_claude = False
    return {"skills": skills, "mcp_codex": mcp_codex, "mcp_claude": mcp_claude}
