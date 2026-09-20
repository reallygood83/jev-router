import json
import math
import os
import time
import urllib.error
import urllib.request
from pathlib import Path

from .registry import eligible_models
from .routing import INTENTS, apply_lookup


DEFAULT_ENDPOINT = "https://api.typesafe.ai/v1/systemone"


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise urllib.error.HTTPError(req.full_url, code, "redirect rejected", headers, None)


def _validate_endpoint(endpoint):
    if endpoint != DEFAULT_ENDPOINT:
        raise ValueError("Jev endpoint must be the official TypeSafe System One HTTPS endpoint")


class JevUnavailable(RuntimeError):
    pass


def _approved_candidates(candidates):
    return [model for model in candidates if model.approved and model.enabled]


def build_payload(task, cwd=""):
    return {
        "model": "jev-latest",
        "state": {
            "task": task,
            "cwd": cwd,
        },
        "questions": {
            "intent": {
                "type": "choice",
                "instructions": "What is the primary intent of `state.task`?",
                "criteria": {
                    "code": "Implement, debug, refactor, or test software.",
                    "write": "Draft or edit prose, docs, or explanations.",
                    "review": "Critique, check, or compare existing work.",
                    "search": "Look up, browse, or gather information.",
                    "other": "None of the other options fit, or the request is mixed or unclear.",
                },
            },
            "difficulty": {
                "type": "score",
                "instructions": "How hard is `state.task` for a local coding assistant?",
                "criteria": [
                    "Simple lookup or a short local edit",
                    "Requires some judgment or a multi-step process",
                    "Unusual, high-stakes, or likely to need a stronger model",
                ],
            },
            "needs_korean": {
                "type": "noul",
                "instructions": "Is Korean language quality central to completing `state.task` well?",
                "criteria": {
                    "true": "The output must be good Korean, or the source material is Korean.",
                    "false": "Korean is incidental or unused.",
                },
            },
        },
    }


class JevClient:
    def __init__(self, endpoint=DEFAULT_ENDPOINT, model="jev-latest", key="", response_file=None, transport=None):
        _validate_endpoint(endpoint)
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
            opener = urllib.request.build_opener(_NoRedirect())
            with opener.open(request, timeout=30) as result:
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


def _difficulty_level(score):
    if score is None:
        return 0
    value = float(score)
    if not math.isfinite(value):
        raise ValueError("difficulty score must be finite")
    if value in {0, 1, 2, 0.0, 1.0, 2.0}:
        return int(value)
    if 0 <= value <= 1:
        if value < 1 / 3:
            return 0
        if value < 2 / 3:
            return 1
        return 2
    raise ValueError("difficulty score must be 0, 1, or 2")


def parse_classification(response):
    if not isinstance(response, dict):
        raise ValueError("Jev response must be an object")
    body = response.get("decision", response)
    if not isinstance(body, dict):
        raise ValueError("Jev response must be an object")
    answers = body.get("answers", body)
    if not isinstance(answers, dict):
        answers = {}
    intent = _answer_value(answers, "intent", "choice") or "other"
    if intent not in INTENTS:
        intent = "other"
    confidence = float(_answer_value(answers, "intent", "confidence") or 0.0)
    if not math.isfinite(confidence) or not 0 <= confidence <= 1:
        raise ValueError("Jev intent confidence must be between 0 and 1")
    difficulty = _difficulty_level(_answer_value(answers, "difficulty", "score"))
    difficulty_confidence = float(_answer_value(answers, "difficulty", "confidence") or 0.0)
    if not math.isfinite(difficulty_confidence) or not 0 <= difficulty_confidence <= 1:
        raise ValueError("Jev difficulty confidence must be between 0 and 1")
    korean = float(_answer_value(answers, "needs_korean", "noul") or 0.0)
    if not math.isfinite(korean) or not 0 <= korean <= 1:
        raise ValueError("Jev Korean score must be between 0 and 1")
    probabilities = _answer_value(answers, "intent", "probabilities") or {}
    if not isinstance(probabilities, dict):
        probabilities = {}
    return {
        "intent": intent,
        "intent_confidence": confidence,
        "intent_probabilities": probabilities,
        "difficulty": difficulty,
        "difficulty_confidence": difficulty_confidence,
        "needs_korean": korean,
    }


def classify_task(task, client, cwd=""):
    payload = build_payload(task, cwd)
    response, source, latency_ms = client.ask(payload)
    classification = parse_classification(response)
    classification["source"] = source
    classification["jev_latency_ms"] = latency_ms
    return classification


def route_task(task, candidates, client, cwd="", health=None, health_ttl=3600, require_fingerprint=True, routing=None):
    if health is None:
        return {"status": "blocked", "reason": "Jev routing requires fresh health evidence"}
    eligible = eligible_models(
        _approved_candidates(candidates),
        health,
        ttl_seconds=health_ttl,
        require_fingerprint=require_fingerprint,
    )
    if not eligible:
        return {"status": "blocked", "reason": "no approved healthy models"}
    classification = classify_task(task, client, cwd)
    plan = apply_lookup(classification, eligible, routing)
    plan["source"] = classification.get("source", "typesafe")
    plan["jev_latency_ms"] = classification.get("jev_latency_ms", 0.0)
    plan["candidate_ids"] = [model.id for model in eligible]
    if isinstance(plan.get("classification"), dict):
        plan["classification"] = {
            **classification,
            **plan["classification"],
        }
    return plan
