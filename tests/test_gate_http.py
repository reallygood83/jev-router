import io
import unittest

from jev_gate.server import GateHandler


class GateHttpTests(unittest.TestCase):
    def test_handler_speaks_http_11(self):
        self.assertEqual(GateHandler.protocol_version, "HTTP/1.1")

    def test_get_responses_is_treated_as_websocket(self):
        handler = GateHandler.__new__(GateHandler)
        handler.command = "GET"
        handler.path = "/v1/responses"
        handler.headers = {}
        self.assertTrue(handler._wants_websocket("/v1/responses"))

    def test_chunked_request_body_is_decoded(self):
        handler = GateHandler.__new__(GateHandler)
        payload = b"5\r\nhello\r\n6\r\n world\r\n0\r\n\r\n"
        handler.headers = {"Transfer-Encoding": "chunked"}
        handler.rfile = io.BytesIO(payload)
        self.assertEqual(handler._read_body(), b"hello world")
