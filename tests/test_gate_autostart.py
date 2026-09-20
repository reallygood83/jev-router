import unittest

from jev_gate.autostart import render_plist


class AutostartTests(unittest.TestCase):
    def test_plist_keeps_gate_alive(self):
        xml = render_plist("127.0.0.1", 10115, "http://127.0.0.1:10100")
        self.assertIn("local.jev-gate", xml)
        self.assertIn("KeepAlive", xml)
        self.assertIn("jev_gate", xml)
        self.assertIn("10115", xml)
        self.assertIn("127.0.0.1:10100", xml)
