import subprocess
import time
from datetime import datetime, timezone
from pathlib import Path


_PROMPT = "Reply with exactly: OK"


def _model_flag(model):
    if "--model" in model.argv or "-m" in model.argv:
        return []
    return ["--model", model.model]


def command_for_model(model):
    kind = (model.kind or model.provider).lower()
    if kind == "codex":
        return ["codex", "exec", "--skip-git-repo-check", _PROMPT, *model.argv]
    if kind == "grok":
        return ["grok", "-p", _PROMPT, "--max-turns", "1", *model.argv]
    if kind == "claude":
        return ["claude", "--print", "--output-format", "text", _PROMPT, *_model_flag(model), *model.argv]
    if kind in {"cursor", "agent"}:
        return ["agent", "-p", _PROMPT, *_model_flag(model), *model.argv]
    if kind == "kimi":
        return ["kimi", "--print", _PROMPT, *_model_flag(model), *model.argv]
    raise ValueError(f"unsupported provider kind: {kind}")


def _run(command, timeout):
    completed = subprocess.run(
        command,
        cwd=str(Path.home()),
        stdin=subprocess.DEVNULL,
        capture_output=True,
        text=True,
        timeout=timeout,
        check=False,
    )
    return completed.returncode, completed.stdout, completed.stderr


def probe_model(model, runner=None, timeout_seconds=30):
    command = command_for_model(model)
    execute = runner or _run
    started = time.perf_counter()
    checked_at = datetime.now(timezone.utc).isoformat()
    try:
        result = execute(command, timeout=timeout_seconds)
    except subprocess.TimeoutExpired:
        return {
            "ok": False,
            "reason": "timeout",
            "checked_at": checked_at,
            "latency_ms": round((time.perf_counter() - started) * 1000, 2),
        }
    except FileNotFoundError:
        return {
            "ok": False,
            "reason": "executable unavailable",
            "checked_at": checked_at,
            "latency_ms": round((time.perf_counter() - started) * 1000, 2),
        }
    except OSError:
        return {
            "ok": False,
            "reason": "provider process unavailable",
            "checked_at": checked_at,
            "latency_ms": round((time.perf_counter() - started) * 1000, 2),
        }

    if isinstance(result, tuple):
        returncode, stdout, _stderr = result
    else:
        returncode = int(getattr(result, "returncode", 1))
        stdout = getattr(result, "stdout", "") or ""
    latency_ms = round((time.perf_counter() - started) * 1000, 2)
    if returncode != 0:
        return {
            "ok": False,
            "reason": f"command failed (exit {returncode})",
            "checked_at": checked_at,
            "latency_ms": latency_ms,
        }
    if not str(stdout).strip():
        return {
            "ok": False,
            "reason": "empty output",
            "checked_at": checked_at,
            "latency_ms": latency_ms,
        }
    if str(stdout).strip() != "OK":
        return {
            "ok": False,
            "reason": "probe did not return exactly OK",
            "checked_at": checked_at,
            "latency_ms": latency_ms,
        }
    return {"ok": True, "reason": "ok", "checked_at": checked_at, "latency_ms": latency_ms}
