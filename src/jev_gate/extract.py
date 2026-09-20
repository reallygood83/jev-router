def _text_from_content(content):
    if isinstance(content, str):
        return content.strip()
    if isinstance(content, dict):
        if content.get("type") in {"text", "input_text", "output_text"} or "text" in content:
            return str(content.get("text") or "").strip()
        return _text_from_content(content.get("content"))
    if isinstance(content, list):
        parts = [_text_from_content(item) for item in content]
        return "\n".join(part for part in parts if part).strip()
    return ""


def extract_task(body):
    if not isinstance(body, dict):
        return ""
    messages = body.get("messages")
    if isinstance(messages, list):
        for item in reversed(messages):
            if not isinstance(item, dict):
                continue
            if str(item.get("role") or "").lower() != "user":
                continue
            text = _text_from_content(item.get("content"))
            if text:
                return text
    for key in ("input", "instructions"):
        text = _text_from_content(body.get(key))
        if text:
            return text
    return ""


def thread_key(headers):
    if not headers:
        return ""
    mapping = {str(key).lower(): value for key, value in headers.items()}
    for name in ("x-session-id", "session-id", "thread-id"):
        value = mapping.get(name)
        if value:
            return str(value).strip()
    return ""
