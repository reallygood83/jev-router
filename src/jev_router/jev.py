import json
import math
import os
import time
import urllib.error
import urllib.request
from pathlib import Path

from .registry import ModelSpec


DEFAULT_ENDPOINT = "https://api.typesafe.ai/v1/systemone"


class JevUnavailable(RuntimeError):
    pass


def _candidate_dict(model):
    return {
        "id": model.id,
        "provider": model.provider,
        "model": model.model,
        "kind": model.kind,
        "purpose": model.purpose,
        "when": model.when,
        "context_tokens": model.context_tokens,
        "quality_prior": model.quality_prior,
        "latency_prior_ms": model.latency_prior_ms,
        "input_cost_per_1k": model.input_cost_per_1k,
        "output_cost_per_1k": model.output_cost_per_1k,
    }


def build_payload(task, candidates, cwd=""):
    rows = [_candidate_dict(model) for model in candidates]
    criteria = {model.id: model.when or model.purpose or model.model for model in candidates}
    return {
        "model": "jev-latest",
        "state": {
            "task": task,
            "cwd": cwd,
            "hint": "Choose the smallest healthy approved execution plan. Use multiple models only when independent perspectives or parallel work are useful.",
            "candidates": rows,
        },
        "questions": {
            "needs_orchestrator": {
                "type": "noul",
                "instructions": "Should this task use multiple models and a captain instead of one model?",
                "criteria": {
                    "true": "Independent deliverables, disagreement reduction, or parallel work materially improves expected utility.",
                    "false": "One model can complete the task and orchestration overhead is not justified.",
                },
            },
            "worker": {
                "type": "choice",
                "instructions": "Choose the best single model for this task.",
                "criteria": criteria,
            },
            "captain": {
                "type": "choice",
                "instructions": "Choose the strongest healthy captain if orchestration is needed.",
                "criteria": criteria,
            },
        },
    }


class JevClient:
    def __init__(self, endpoint=DEFAULT_ENDPOINT, model="jev-latest", key="", response_file=None, transport=None):
        self.endpoint = endpoint
        self.model = model
        self.key = key or os.environ.get("TYPESAFE_API_KEY", "").strip()
        self.response_file = Path(response_file).expanduser() if response_file else None
        self.transport = transport

    def ask(self, payload):
        started = time.perf_counter()
        if self.response_file is not None:
            try:
                response = json.loads(self.response_file.read_text(encoding="utf-8"))
            except (OSError, ValueError) as exc:
                raise JevUnavailable("Jev response fixture is unreadable") from exc
            return response, "fixture", round((time.perf_counter() - started) * 1000, 2)
        request_body = dict(payload)
        request_body["model"] = self.model
        body = json.dumps(request_body).encode("utf-8")
        if self.transport is not None:
            response = self.transport(self.endpoint, body, self.key)
            return response, "typesafe", round((time.perf_counter() - started) * 1000, 2)
        if not self.key:
            raise JevUnavailable("TypeSafe API key unavailable")
        request = urllib.request.Request(
            self.endpoint,
            data=body,
            method="POST",
            headers={"Authorization": f"Bearer {self.key}", "Content-Type": "application/json"},
        )
        try:
            with urllib.request.urlopen(request, timeout=30) as result:
                response = json.loads(result.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            raise JevUnavailable(f"TypeSafe HTTP {exc.code}") from exc
        except (urllib.error.URLError, TimeoutError, ValueError) as exc:
            raise JevUnavailable("TypeSafe request failed") from exc
        return response, "typesafe", round((time.perf_counter() - started) * 1000, 2)


def _answer_value(answers, name, field):
    value = answers.get(name)
    if isinstance(value, dict):
        return value.get(field)
    return value


def parse_decision(response, candidates, threshold=0.6):
    if not isinstance(response, dict):
        raise ValueError("Jev response must be an object")
    if not math.isfinite(float(threshold)) or not 0 <= float(threshold) <= 1:
        raise ValueError("orchestrator threshold must be between 0 and 1")
    allowed = {model.id: model for model in candidates}
    candidate_body = response.get("decision", response)
    body = candidate_body if isinstance(candidate_body, dict) else response
    answers = body.get("answers", {})
    if not isinstance(answers, dict):
        answers = {}
    mode = body.get("mode") if isinstance(body, dict) else None
    if not mode:
        mode_score = _answer_value(answers, "needs_orchestrator", "noul")
        if mode_score is not None and (not math.isfinite(float(mode_score)) or not 0 <= float(mode_score) <= 1):
            raise ValueError("Jev orchestration score must be between 0 and 1")
        mode = "orchestration" if float(mode_score or 0.0) >= threshold else "single"
    if mode in {"orch", "multi", "captain"}:
        mode = "orchestration"
    if mode not in {"single", "orchestration"}:
        raise ValueError("Jev returned an unknown execution mode")

    worker = body.get("worker_id") or body.get("model_id") or _answer_value(answers, "worker", "choice")
    captain = body.get("captain_id") or body.get("captain") or _answer_value(answers, "captain", "choice")
    worker = worker or (candidates[0].id if candidates else "")
    captain = captain or worker
    workers = body.get("worker_ids") or body.get("workers")
    if not workers:
        workers = [worker]
    if isinstance(workers, str):
        workers = [workers]
    workers = list(dict.fromkeys(workers))
    if mode == "orchestration" and captain not in workers:
        workers.insert(0, captain)
    selected = [model_id for model_id in workers if model_id in allowed]
    if not selected or worker not in allowed or captain not in allowed:
        raise ValueError("Jev selected a model outside the approved healthy candidate set")
    confidence = float(body.get("confidence", 0.0) or 0.0)
    if not math.isfinite(confidence) or not 0 <= confidence <= 1:
        raise ValueError("Jev confidence must be between 0 and 1")
    return {
        "mode": mode,
        "worker_id": worker,
        "captain_id": captain,
        "worker_ids": selected,
        "confidence": confidence,
        "reason": str(body.get("reason", "Jev selected the smallest eligible plan")),
    }


def route_task(task, candidates, client, cwd="", threshold=0.6):
    if not candidates:
        return {"status": "blocked", "reason": "no approved healthy models"}
    payload = build_payload(task, candidates, cwd)
    response, source, latency_ms = client.ask(payload)
    decision = parse_decision(response, candidates, threshold)
    return {
        "status": "ok",
        **decision,
        "source": source,
        "jev_latency_ms": latency_ms,
        "candidate_ids": [model.id for model in candidates],
    }
