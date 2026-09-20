import subprocess
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from pathlib import Path

from .adapters import command_for_prompt
from .registry import eligible_models, model_fingerprint
from .runtime import provider_environment


_PROMPT = "Reply with exactly: OK"
_ERROR_MARKERS = {"ERROR", "FAILED", "FAIL"}


def command_for_model(model):
    extra = []
    if (model.kind or model.provider).lower() == "grok":
        extra = ["--max-turns", "1"]
    return command_for_prompt(model, _PROMPT, extra_flags=extra)


def partition_health_targets(models, health, now=None, ttl_seconds=3600, require_fingerprint=True, refresh=False):
    current = now or datetime.now(timezone.utc)
    if refresh:
        return {}, list(models)
    fresh = {}
    stale = []
    for model in models:
        record = health.get(model.id) if isinstance(health, dict) else None
        if record and eligible_models(
            [model],
            {model.id: record},
            now=current,
            ttl_seconds=ttl_seconds,
            require_fingerprint=require_fingerprint,
        ):
            fresh[model.id] = dict(record)
        else:
            stale.append(model)
    return fresh, stale


def _run(command, timeout):
    completed = subprocess.run(
        command,
        cwd=str(Path.home()),
        stdin=subprocess.DEVNULL,
        capture_output=True,
        text=True,
        timeout=timeout,
        check=False,
        env=provider_environment(command),
    )
    return completed.returncode, completed.stdout, completed.stderr


def _classify_output(stdout):
    text = str(stdout).strip()
    if not text:
        return False, "empty output"
    lowered = text.lower()
    if "invalid api key" in lowered or "unauthorized" in lowered or "unauthenticated" in lowered:
        return False, "probe returned an auth or permission error"
    first = text.split()[0].strip(".,!:;").upper()
    if text.upper() in _ERROR_MARKERS or first in _ERROR_MARKERS:
        return False, "probe did not return OK"
    return True, "ok"


def probe_model(model, runner=None, timeout_seconds=45):
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
    ok, reason = _classify_output(stdout)
    if not ok:
        return {
            "ok": False,
            "reason": reason,
            "checked_at": checked_at,
            "latency_ms": latency_ms,
        }
    return {
        "ok": True,
        "reason": reason,
        "checked_at": checked_at,
        "latency_ms": latency_ms,
        "model_fingerprint": model_fingerprint(model),
        "exact_ok": str(stdout).strip() == "OK",
    }


def probe_models(models, runner=None, timeout_seconds=45, max_workers=4):
    targets = list(models)
    if not targets:
        return {}
    workers = max(1, min(max_workers, len(targets)))
    results = {}
    with ThreadPoolExecutor(max_workers=workers) as pool:
        futures = {
            pool.submit(probe_model, model, runner, timeout_seconds): model
            for model in targets
        }
        for future, model in futures.items():
            results[model.id] = future.result()
    return results
