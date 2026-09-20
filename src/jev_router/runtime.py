import os
from pathlib import Path


_BASE_ENV = {"HOME", "PATH", "USER", "LOGNAME", "LANG", "LC_ALL", "TERM", "TMPDIR", "PWD"}
_PROVIDER_ENV = {
    "codex": {"OPENAI_API_KEY"},
    "grok": {"XAI_API_KEY"},
    "claude": {"ANTHROPIC_API_KEY"},
    "agent": {"CURSOR_API_KEY"},
    "kimi": {"KIMI_API_KEY", "MOONSHOT_API_KEY"},
}


def provider_environment(command):
    executable = Path(str(command[0])).name.lower() if command else ""
    allowed = _BASE_ENV | _PROVIDER_ENV.get(executable, set())
    return {name: value for name, value in os.environ.items() if name in allowed}
