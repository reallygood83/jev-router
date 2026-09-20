INTENTS = ("code", "write", "search", "review", "other")
ROLES = ("fast", "code", "write")
DEFAULT_CONFIDENCE_FLOOR = 0.6
PREFERRED_ROLE_IDS = {
    "fast": ("codex:gpt-5.6-sol",),
    "code": ("codex:gpt-5.6-terra",),
    "write": ("claude:sonnet",),
}


def bind_roles(models):
    approved = [model for model in models if getattr(model, "approved", False) and getattr(model, "enabled", True)]
    if not approved:
        return {}
    by_id = {model.id: model for model in approved}
    roles = {}
    for role, preferred in PREFERRED_ROLE_IDS.items():
        for model_id in preferred:
            if model_id in by_id:
                roles[role] = model_id
                break

    def assign(role, matches):
        if roles.get(role):
            return
        unused = [model for model in approved if model.id not in roles.values()]
        for model in unused:
            if matches(model):
                roles[role] = model.id
                return
        for model in approved:
            if matches(model):
                roles[role] = model.id
                return

    assign("fast", lambda model: model.kind == "codex" or model.provider == "codex")
    assign("code", lambda model: model.kind == "codex" or model.provider == "codex")
    assign("write", lambda model: model.kind in {"claude", "cursor"} or model.provider == "claude")
    default_id = approved[0].id
    for role in ROLES:
        roles.setdefault(role, roles.get("fast") or default_id)
    return roles


def role_for(intent, difficulty, needs_korean=0.0):
    intent = intent if intent in INTENTS else "other"
    difficulty = 0 if difficulty < 0 else 2 if difficulty > 2 else int(difficulty)
    if float(needs_korean or 0.0) >= DEFAULT_CONFIDENCE_FLOOR and intent in {"write", "search", "other"}:
        return "fast"
    if intent == "code":
        return "fast" if difficulty == 0 else "code"
    if intent in {"write", "review"}:
        return "write"
    if intent == "search":
        return "fast" if difficulty <= 1 else "code"
    return "fast"


def apply_lookup(classification, eligible, routing=None):
    eligible = list(eligible)
    if not eligible:
        return {"status": "blocked", "reason": "no approved healthy models"}
    routing = routing or {}
    by_id = {model.id: model for model in eligible}
    roles = {role: model_id for role, model_id in dict(routing.get("roles") or {}).items() if model_id in by_id}
    if not roles:
        roles = {role: model_id for role, model_id in bind_roles(eligible).items() if model_id in by_id}
    default_id = roles.get("fast") or eligible[0].id
    try:
        floor = float(routing.get("confidence_floor", DEFAULT_CONFIDENCE_FLOOR))
    except (TypeError, ValueError):
        floor = DEFAULT_CONFIDENCE_FLOOR
    if not 0 <= floor <= 1:
        floor = DEFAULT_CONFIDENCE_FLOOR
    intent = classification.get("intent") if classification.get("intent") in INTENTS else "other"
    try:
        difficulty = int(classification.get("difficulty") or 0)
    except (TypeError, ValueError):
        difficulty = 0
    try:
        korean = float(classification.get("needs_korean") or 0.0)
    except (TypeError, ValueError):
        korean = 0.0
    try:
        confidence = float(classification.get("intent_confidence") or 0.0)
    except (TypeError, ValueError):
        confidence = 0.0
    fallback = False
    if confidence < floor:
        role = "fast"
        fallback = True
        reason = "intent confidence below floor; defaulting to fast"
    else:
        role = role_for(intent, difficulty, korean)
        reason = f"mapped {intent}/{difficulty} to role {role}"
        if korean >= DEFAULT_CONFIDENCE_FLOOR and role == "fast":
            reason += "; korean prefers fast"
    mapped_id = roles.get(role)
    if mapped_id in by_id:
        model_id = mapped_id
    else:
        model_id = default_id
        fallback = True
        reason = "mapped role was not eligible; defaulting to fast"
    return {
        "status": "ok",
        "mode": "single",
        "worker_id": model_id,
        "captain_id": model_id,
        "worker_ids": [model_id],
        "role": role,
        "fallback": fallback,
        "confidence": confidence,
        "reason": reason,
        "classification": {
            "intent": intent,
            "intent_confidence": confidence,
            "difficulty": difficulty,
            "needs_korean": korean,
        },
        "roles": roles,
    }
