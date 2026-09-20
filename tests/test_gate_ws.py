import json
import unittest

from jev_gate.ws import encode_frame, pop_frame, rewrite_model_payload


class WsTests(unittest.TestCase):
    def test_masked_roundtrip(self):
        raw = encode_frame(1, b"hello", masked=True)
        frame, rest = pop_frame(raw)
        self.assertEqual(rest, b"")
        self.assertEqual(frame["payload"], b"hello")
        self.assertEqual(frame["opcode"], 1)

    def test_rewrite_changes_model(self):
        payload = json.dumps({"model": "gpt-5.6-luna", "input": "hi"}).encode()
        out = rewrite_model_payload(payload, lambda body: {**body, "model": "xai/grok-4.6"})
        self.assertEqual(json.loads(out)["model"], "xai/grok-4.6")
