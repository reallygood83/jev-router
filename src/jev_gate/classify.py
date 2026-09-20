import json
import math
import os
import urllib.error
import urllib.request

from jev_router.jev import DEFAULT_ENDPOINT, JevUnavailable, _NoRedirect, _answer_value, _validate_endpoint

from .pack import filled_roles
from .secrets import load_key


def build_payload(task, pack):
    roles = filled_roles(pack)
    criteria = {key: str(value.get("when") or key) for key, value in roles.items()}
    criteria["other"] = "None of the other options fit, mixed, or unclear."
    return {
        "model": "jev-latest",
        "state": {"task": task},
        "questions": {
            "role": {
                "type": "choice",
                "instructions": "What is the primary job of `state.task`?",
                "criteria": criteria,
            },
            "needs_korean": {
                "type": "noul",
                "instructions": "Is Korean language quality central to completing `state.task` well?",
                "criteria": {
                    "true": "The output must be good Korean, or the source is Korean.",
                    "false": "Korean is incidental or unused.",
                },
            },
        },
    }


def parse_classification(response, allowed_roles):
    if not isinstance(response, dict):
        raise ValueError("Jev response must be an object")
    body = response.get("decision", response)
    if not isinstance(body, dict):
        raise ValueError("Jev response must be an object")
    answers = body.get("answers", body)
    if not isinstance(answers, dict):
        answers = {}
    role = str(_answer_value(answers, "role", "choice") or "other")
    if role not in set(allowed_roles) | {"other"}:
        role = "other"
    confidence = float(_answer_value(answers, "role", "confidence") or 0.0)
    if not math.isfinite(confidence) or not 0 <= confidence <= 1:
        raise ValueError("Jev role confidence must be between 0 and 1")
    korean = float(_answer_value(answers, "needs_korean", "noul") or 0.0)
    if not math.isfinite(korean) or not 0 <= korean <= 1:
        raise ValueError("Jev Korean score must be between 0 and 1")
    return {"role": role, "confidence": confidence, "needs_korean": korean}


def classify_task(task, pack, key="", timeout=3, transport=None):
    payload = build_payload(task, pack)
    if transport is not None:
        response = transport(payload)
        return parse_classification(response, filled_roles(pack))
    secret = key or load_key()
    if not secret:
        raise JevUnavailable("TypeSafe API key unavailable")
    _validate_endpoint(DEFAULT_ENDPOINT)
    body = json.dumps(payload).encode("utf-8")
    request = urllib.request.Request(
        DEFAULT_ENDPOINT,
        data=body,
        method="POST",
        headers={"Authorization": f"Bearer {secret}", "Content-Type": "application/json"},
    )
    try:
        opener = urllib.request.build_opener(_NoRedirect())
        with opener.open(request, timeout=timeout) as result:
            response = json.loads(result.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        raise JevUnavailable(f"TypeSafe HTTP {exc.code}") from exc
    except (urllib.error.URLError, TimeoutError, ValueError) as exc:
        raise JevUnavailable("TypeSafe request failed") from exc
    return parse_classification(response, filled_roles(pack))
