from .pack import filled_roles


def decide(pack, incoming_model, classification=None, sticky_model="", sticky_effort="", error=""):
    incoming = str(incoming_model or "").strip()
    home = str((pack or {}).get("home_model") or "").strip()
    try:
        floor = float((pack or {}).get("confidence_floor", 0.6))
    except (TypeError, ValueError):
        floor = 0.6
    roles = filled_roles(pack)

    def result(status, model, role="-", confidence=0.0, reason="", effort=""):
        out = model or incoming
        return {
            "status": status,
            "role": role or "-",
            "confidence": confidence,
            "model_in": incoming,
            "model_out": out,
            "reasoning_effort": effort or "",
            "reason": reason,
        }

    if not pack or pack.get("enabled") is not True:
        return result("pass", incoming, reason="gate disabled")
    if error:
        return result("error-pass", incoming, reason=error)
    if not incoming:
        return result("pass", incoming, reason="no model field")
    if incoming != home:
        return result("pass", incoming, reason="incoming model is not home")
    if sticky_model:
        return result("sticky", sticky_model, role="sticky", reason="thread sticky model", effort=sticky_effort)
    if not classification:
        return result("pass", incoming, reason="no classification")

    role = str(classification.get("role") or "other")
    try:
        confidence = float(classification.get("confidence") or 0.0)
    except (TypeError, ValueError):
        confidence = 0.0
    try:
        korean = float(classification.get("needs_korean") or 0.0)
    except (TypeError, ValueError):
        korean = 0.0
    if korean >= floor and "write" in roles and role == "implement":
        role = "write"
    if role == "other":
        return result("pass", incoming, role=role, confidence=confidence, reason="role other")
    if confidence < floor:
        return result("pass", incoming, role=role, confidence=confidence, reason="confidence below floor")
    entry = roles.get(role)
    if not entry:
        return result("pass", incoming, role=role, confidence=confidence, reason="role not in pack")
    target = str(entry.get("model") or "").strip()
    if not target:
        return result("pass", incoming, role=role, confidence=confidence, reason="role has no model")
    effort = str(entry.get("reasoning_effort") or "").strip()
    if target == incoming and not effort:
        return result("pass", incoming, role=role, confidence=confidence, reason="already on role model")
    return result(
        "rewrite",
        target,
        role=role,
        confidence=confidence,
        reason="rewrote home to role model",
        effort=effort,
    )
