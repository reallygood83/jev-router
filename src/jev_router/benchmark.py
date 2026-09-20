import json
import hashlib
import random
import time
import uuid
from pathlib import Path
from typing import cast

from .adapters import execute_plan
from .evidence import sign_record
from .jev import JevClient, JevUnavailable, route_task
from .registry import model_fingerprint


def _tokens(text):
    return max(1, len(str(text).split()))


def _cost(models, result, prompt):
    by_id = {model.id: model for model in models}
    input_tokens = _tokens(prompt)
    total = 0.0
    for item in result.get("results", []):
        model = by_id[item["model_id"]]
        output_tokens = _tokens(item.get("output", "")) if item.get("ok") else 0
        total += input_tokens / 1000 * model.input_cost_per_1k
        total += output_tokens / 1000 * model.output_cost_per_1k
    return total


def _fixed_plan(mode, model_ids):
    if mode == "single":
        return {
            "status": "ok",
            "mode": "single",
            "worker_id": model_ids[0],
            "captain_id": model_ids[0],
            "worker_ids": [model_ids[0]],
        }
    return {
        "status": "ok",
        "mode": "orchestration",
        "worker_id": model_ids[0],
        "captain_id": model_ids[0],
        "worker_ids": list(dict.fromkeys(model_ids)),
    }


def run_benchmark(
    tasks,
    models,
    single_id,
    team_ids,
    jev_client,
    runner=None,
    seed=0,
    execute=False,
    health=None,
    health_ttl=3600,
    evidence_key="",
    require_fingerprint=True,
    evidence_class="live",
):
    by_id = {model.id: model for model in models}
    if single_id not in by_id or len(team_ids) < 2 or any(model_id not in by_id for model_id in team_ids):
        raise ValueError("benchmark references unknown registered model")
    rows = []
    rng = random.Random(seed)
    manifest_id = uuid.uuid4().hex if execute else ""
    for task in tasks:
        task_id = task.get("task_id")
        prompt = task.get("prompt")
        if not task_id or not prompt:
            raise ValueError("each benchmark task requires task_id and prompt")
        arms = ["single", "static-team", "jev"]
        rng.shuffle(arms)
        plans = {
            "single": _fixed_plan("single", [single_id]),
            "static-team": _fixed_plan("orchestration", team_ids),
        }
        try:
            plans["jev"] = route_task(
                prompt,
                models,
                jev_client,
                health=health,
                health_ttl=health_ttl,
                require_fingerprint=require_fingerprint,
            )
        except (JevUnavailable, ValueError) as exc:
            plans["jev"] = {"status": "blocked", "reason": str(exc)}
        for arm in arms:
            plan = plans[arm]
            started = time.perf_counter()
            result = (
                execute_plan(
                    plan,
                    models,
                    prompt,
                    runner=runner,
                    health=health,
                    health_ttl=health_ttl,
                    require_fingerprint=require_fingerprint,
                )
                if execute
                else {"ok": plan.get("status") == "ok", "results": [], "model_count": 0}
            )
            elapsed = round((time.perf_counter() - started) * 1000, 2)
            if execute:
                quality = 0.0
            else:
                quality_scores = task.get("quality_by_arm", {})
                raw_quality = quality_scores.get(arm, 1.0 if result.get("ok") else 0.0)
                quality = float(str(raw_quality)) if isinstance(raw_quality, (int, float, str)) else 0.0
            raw_overhead = plan.get("jev_latency_ms", 0.0)
            overhead = float(str(raw_overhead)) if isinstance(raw_overhead, (int, float, str)) else 0.0
            output = result.get("output", "") or ""
            output_sha256 = hashlib.sha256(str(output).encode("utf-8")).hexdigest()
            executed_model_ids = [item.get("model_id") for item in cast(list[dict[str, object]], result.get("results", []))]
            model_ids = executed_model_ids if execute else list(plan.get("worker_ids", []))
            row = {
                "task_id": task_id,
                "split": task.get("split", "holdout"),
                "arm": arm,
                "quality": quality,
                "cost": _cost(models, result, prompt) if execute else 0.0,
                "time_ms": elapsed,
                "failure_cost": 0.0 if result.get("ok") else 1.0,
                "overhead": overhead / 1000,
                "model_count": result.get("model_count", 0),
                "model_ids": model_ids,
                "model_fingerprints": {model_id: model_fingerprint(by_id[model_id]) for model_id in model_ids if model_id in by_id},
                "status": "ok" if result.get("ok") else "failed",
                "route_source": plan.get("source", arm),
                "evidence_class": "runtime_unscored" if execute else "fixture",
                "executed": bool(execute),
                "quality_source": "pending" if execute else "fixture",
                "output_sha256": output_sha256,
                "output_nonempty": bool(str(output).strip()),
                "prompt_sha256": hashlib.sha256(str(prompt).encode("utf-8")).hexdigest(),
            }
            if execute:
                row["execution_manifest_id"] = manifest_id
                row["execution_evidence_class"] = evidence_class
                if evidence_key:
                    row["evidence_signature"] = sign_record(row, evidence_key, "evidence_signature")
            rows.append(row)
    return rows


def save_jsonl(path, rows):
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text("".join(json.dumps(row, ensure_ascii=False) + "\n" for row in rows), encoding="utf-8")
