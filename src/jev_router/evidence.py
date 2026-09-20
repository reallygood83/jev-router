import hashlib
import hmac
import json


def sign_record(record, key, signature_field):
    payload = {name: value for name, value in record.items() if name != signature_field}
    message = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hmac.new(str(key).encode("utf-8"), message, hashlib.sha256).hexdigest()


def verify_record(record, key, signature_field):
    signature = record.get(signature_field)
    if not isinstance(signature, str):
        return False
    expected = sign_record(record, key, signature_field)
    return hmac.compare_digest(signature, expected)
