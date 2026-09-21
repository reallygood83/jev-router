import io
import json
import tempfile
import unittest
from http.client import HTTPMessage
from pathlib import Path
from unittest.mock import patch

from jev_gate.pack import save_pack
from jev_gate.server import STATIC_DIR, GateHandler, GateState


class GateHttpTests(unittest.TestCase):
    def test_handler_speaks_http_11(self):
        self.assertEqual(GateHandler.protocol_version, "HTTP/1.1")

    def test_plain_get_responses_is_not_websocket(self):
        handler = GateHandler.__new__(GateHandler)
        handler.command = "GET"
        handler.path = "/v1/responses"
        handler.headers = HTTPMessage()
        self.assertFalse(handler._wants_websocket("/v1/responses"))

    def test_sec_websocket_key_is_websocket(self):
        handler = GateHandler.__new__(GateHandler)
        handler.command = "GET"
        handler.path = "/v1/responses"
        handler.headers = HTTPMessage()
        handler.headers["Sec-WebSocket-Key"] = "abc"
        self.assertTrue(handler._wants_websocket("/v1/responses"))

    def test_chunked_request_body_is_decoded(self):
        handler = GateHandler.__new__(GateHandler)
        payload = b"5\r\nhello\r\n6\r\n world\r\n0\r\n\r\n"
        handler.headers = HTTPMessage()
        handler.headers["Transfer-Encoding"] = "chunked"
        handler.rfile = io.BytesIO(payload)
        self.assertEqual(handler._read_body(), b"hello world")

    def test_responses_effort_uses_nested_reasoning_parameter(self):
        handler = GateHandler.__new__(GateHandler)
        handler.path = "/v1/responses"
        raw = handler._apply_decision(
            {"model": "home", "reasoning": {"summary": "auto"}},
            {"model_out": "implement", "reasoning_effort": "max"},
        )
        body = json.loads(raw)
        self.assertEqual(body["model"], "implement")
        self.assertEqual(body["reasoning"], {"summary": "auto", "effort": "max"})
        self.assertNotIn("reasoning_effort", body)

    def test_chat_completions_effort_stays_top_level(self):
        handler = GateHandler.__new__(GateHandler)
        handler.path = "/v1/chat/completions"
        raw = handler._apply_decision(
            {"model": "home"},
            {"model_out": "implement", "reasoning_effort": "high"},
        )
        body = json.loads(raw)
        self.assertEqual(body["reasoning_effort"], "high")
        self.assertNotIn("reasoning", body)

    def test_dashboard_includes_first_run_route_check(self):
        html = (STATIC_DIR / "index.html").read_text(encoding="utf-8")
        self.assertIn("역할 3개 실제 테스트", html)
        self.assertIn('stream: true', html)
        self.assertIn('location.origin + "/v1"', html)

    def test_rewrite_omits_effort_for_model_without_reasoning_support(self):
        with tempfile.TemporaryDirectory() as directory:
            pack_path = Path(directory) / "pack.json"
            save_pack(
                {
                    "home_model": "home",
                    "enabled": True,
                    "roles": {
                        "write": {
                            "model": "writer",
                            "when": "Draft prose.",
                            "reasoning_effort": "medium",
                        }
                    },
                },
                pack_path,
            )
            state = GateState(pack_path=pack_path)
            state.catalog = {"home", "writer"}
            state.reasoning_support = {"home": True, "writer": False}

            class Handler(GateHandler):
                pass

            Handler.state = state
            handler = Handler.__new__(Handler)
            handler.path = "/v1/responses"
            handler.headers = HTTPMessage()
            with patch(
                "jev_gate.server.classify_task",
                return_value={"role": "write", "confidence": 0.99, "needs_korean": 0.0},
            ):
                raw, decision = handler._classify_and_patch(
                    json.dumps({"model": "home", "input": "Draft Korean prose."}).encode("utf-8")
                )

        body = json.loads(raw)
        self.assertEqual(body["model"], "writer")
        self.assertNotIn("reasoning", body)
        self.assertNotIn("reasoning_effort", body)
        self.assertEqual(decision["reasoning_effort"], "")
        self.assertIn("does not advertise reasoning support", str(decision["reason"]))
