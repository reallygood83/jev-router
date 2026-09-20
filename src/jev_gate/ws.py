import json
import os
import struct


def pop_frame(buf):
    data = bytes(buf)
    if len(data) < 2:
        return None, data
    first, second = data[0], data[1]
    fin = bool(first & 0x80)
    opcode = first & 0x0F
    masked = bool(second & 0x80)
    length = second & 0x7F
    index = 2
    if length == 126:
        if len(data) < 4:
            return None, data
        length = int.from_bytes(data[2:4], "big")
        index = 4
    elif length == 127:
        if len(data) < 10:
            return None, data
        length = int.from_bytes(data[2:10], "big")
        index = 10
    mask = None
    if masked:
        if len(data) < index + 4:
            return None, data
        mask = data[index : index + 4]
        index += 4
    if len(data) < index + length:
        return None, data
    payload = data[index : index + length]
    if mask:
        payload = bytes(payload[i] ^ mask[i % 4] for i in range(len(payload)))
    rest = data[index + length :]
    original = data[: index + length]
    return {"fin": fin, "opcode": opcode, "payload": payload, "masked": masked, "original": original}, rest


def encode_frame(opcode, payload, masked=True, fin=True):
    payload = bytes(payload)
    header = bytes([((0x80 if fin else 0) | opcode)])
    length = len(payload)
    if length < 126:
        length_bits = length
        extra = b""
    elif length < 65536:
        length_bits = 126
        extra = struct.pack("!H", length)
    else:
        length_bits = 127
        extra = struct.pack("!Q", length)
    mask = b""
    if masked:
        length_bits |= 0x80
        mask = os.urandom(4)
        payload = bytes(payload[i] ^ mask[i % 4] for i in range(len(payload)))
    return bytes([header[0], length_bits]) + extra + mask + payload


def rewrite_model_payload(payload, rewriter):
    try:
        text = payload.decode("utf-8")
        body = json.loads(text)
    except (UnicodeDecodeError, ValueError):
        return payload
    if not isinstance(body, dict) or "model" not in body:
        return payload
    updated = rewriter(body)
    if not isinstance(updated, dict):
        return payload
    return json.dumps(updated, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
