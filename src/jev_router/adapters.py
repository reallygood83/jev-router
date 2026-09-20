import subprocess
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path


def _model_flag(model):
    if "--model" in model.argv or "-m" in model.argv:
        return []
    return ["--model", model.model]


def command_for_prompt(model, prompt):
    kind = (model.kind or model.provider).lower()
    if kind == "codex":
        return ["codex", "exec", "--skip-git-repo-check", prompt, *model.argv]
    if kind == "grok":
        return ["grok", "-p", prompt, *model.argv]
    if kind == "claude":
        return ["claude", "--print", "--output-format", "text", prompt, *_model_flag(model), *model.argv]
    if kind in {"cursor", "agent"}:
        return ["agent", "-p", prompt, *_model_flag(model), *model.argv]
    if kind == "kimi":
        return ["kimi", "--print", prompt, *_model_flag(model), *model.argv]
    raise ValueError(f"unsupported provider kind: {kind}")


def run_model(model, prompt, timeout_seconds=120, runner=None):
    command = command_for_prompt(model, prompt)
    execute = runner or _run
    started = time.perf_counter()
    try:
        result = execute(command, timeout=timeout_seconds)
    except subprocess.TimeoutExpired:
        return {"ok": False, "reason": "timeout", "output": "", "latency_ms": _latency(started)}
    except FileNotFoundError:
        return {"ok": False, "reason": "executable unavailable", "output": "", "latency_ms": _latency(started)}
    except OSError:
        return {"ok": False, "reason": "provider process unavailable", "output": "", "latency_ms": _latency(started)}
    if isinstance(result, tuple):
        returncode, stdout, stderr = result
    else:
        returncode = result.returncode
        stdout = result.stdout or ""
        stderr = result.stderr or ""
    output = str(stdout)
    if returncode != 0:
        return {"ok": False, "reason": f"command failed (exit {returncode})", "output": output, "latency_ms": _latency(started)}
    if not output.strip():
        return {"ok": False, "reason": "empty output", "output": "", "latency_ms": _latency(started)}
    return {"ok": True, "reason": "ok", "output": output, "latency_ms": _latency(started)}


def _latency(started):
    return round((time.perf_counter() - started) * 1000, 2)


def _run(command, timeout):
    return subprocess.run(
        command,
        cwd=str(Path.home()),
        stdin=subprocess.DEVNULL,
        capture_output=True,
        text=True,
        timeout=timeout,
        check=False,
    )


def execute_plan(plan, registry, prompt, timeout_seconds=120, runner=None):
    by_id = {model.id: model for model in registry}
    if plan.get("status") != "ok":
        return {"ok": False, "reason": plan.get("reason", "route blocked"), "model_count": 0, "results": []}
    if plan["mode"] == "single":
        model = by_id[plan["worker_id"]]
        result = run_model(model, prompt, timeout_seconds, runner)
        return {"ok": result["ok"], "mode": "single", "model_count": 1, "results": [{"model_id": model.id, **result}], "output": result["output"]}

    captain_id = plan["captain_id"]
    worker_ids = [model_id for model_id in plan["worker_ids"] if model_id != captain_id]
    with ThreadPoolExecutor(max_workers=max(1, min(6, len(worker_ids)))) as pool:
        futures = {
            model_id: pool.submit(run_model, by_id[model_id], prompt, timeout_seconds, runner)
            for model_id in worker_ids
        }
        worker_results = [{"model_id": model_id, **future.result()} for model_id, future in futures.items()]
    captain_prompt = prompt
    if worker_results:
        captain_prompt += "\n\nWorker outputs follow. Synthesize a final answer:\n" + "\n\n".join(
            f"[{item['model_id']}]\n{item['output']}" for item in worker_results if item["ok"]
        )
    captain = by_id[captain_id]
    captain_result = run_model(captain, captain_prompt, timeout_seconds, runner)
    results = worker_results + [{"model_id": captain.id, **captain_result}]
    return {
        "ok": captain_result["ok"] and all(item["ok"] for item in worker_results),
        "mode": "orchestration",
        "model_count": len(results),
        "results": results,
        "output": captain_result["output"],
    }
