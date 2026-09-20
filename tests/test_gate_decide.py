import unittest

from jev_gate.classify import build_payload, parse_classification
from jev_gate.decide import decide
from jev_gate.extract import extract_task, thread_key
from jev_gate.pack import normalize_pack


def pack():
    return normalize_pack(
        {
            "home_model": "gpt-5.6-sol",
            "confidence_floor": 0.6,
            "enabled": True,
            "roles": {
                "implement": {"when": "Write or edit code in the repo.", "model": "gpt-5.6-terra"},
                "research": {"when": "Look up current facts.", "model": "xai/grok-4.5"},
                "write": {"when": "Draft prose.", "model": "gpt-5.6-sol"},
            },
        }
    )


class GateDecideTests(unittest.TestCase):
    def test_payload_omits_empty_roles_and_model_ids(self):
        payload = build_payload("task", pack())
        criteria = payload["questions"]["role"]["criteria"]
        self.assertIn("other", criteria)
        self.assertIn("implement", criteria)
        self.assertNotIn("gpt-5.6-terra", str(payload["state"]))
        self.assertNotIn("xai/grok-4.5", str(payload["questions"]))

    def test_sticky_does_not_override_explicit_picker(self):
        decision = decide(pack(), "gpt-5.6-terra", sticky_model="xai/grok-4.5")
        self.assertEqual(decision["status"], "pass")
        self.assertEqual(decision["model_out"], "gpt-5.6-terra")

    def test_sticky_applies_when_still_on_home(self):
        decision = decide(pack(), "gpt-5.6-sol", sticky_model="xai/grok-4.5")
        self.assertEqual(decision["status"], "sticky")
        self.assertEqual(decision["model_out"], "xai/grok-4.5")

    def test_incoming_not_home_is_pass(self):
        decision = decide(pack(), "gpt-5.6-terra", {"role": "research", "confidence": 0.9, "needs_korean": 0})
        self.assertEqual(decision["status"], "pass")
        self.assertEqual(decision["model_out"], "gpt-5.6-terra")

    def test_low_confidence_is_pass(self):
        decision = decide(pack(), "gpt-5.6-sol", {"role": "research", "confidence": 0.41, "needs_korean": 0})
        self.assertEqual(decision["status"], "pass")
        self.assertEqual(decision["model_out"], "gpt-5.6-sol")

    def test_rewrite_includes_role_effort(self):
        custom = pack()
        custom["roles"]["research"]["reasoning_effort"] = "high"
        decision = decide(custom, "gpt-5.6-sol", {"role": "research", "confidence": 0.82, "needs_korean": 0.1})
        self.assertEqual(decision["status"], "rewrite")
        self.assertEqual(decision["reasoning_effort"], "high")

    def test_implement_rewrites_home_to_terra(self):
        decision = decide(pack(), "gpt-5.6-sol", {"role": "implement", "confidence": 0.9, "needs_korean": 0.1})
        self.assertEqual(decision["status"], "rewrite")
        self.assertEqual(decision["model_out"], "gpt-5.6-terra")

    def test_research_rewrites_home_to_grok(self):
        decision = decide(pack(), "gpt-5.6-sol", {"role": "research", "confidence": 0.82, "needs_korean": 0.1})
        self.assertEqual(decision["status"], "rewrite")
        self.assertEqual(decision["model_out"], "xai/grok-4.5")
        self.assertEqual(decision["role"], "research")

    def test_korean_implement_goes_to_write(self):
        decision = decide(pack(), "gpt-5.6-sol", {"role": "implement", "confidence": 0.9, "needs_korean": 0.8})
        self.assertEqual(decision["role"], "write")
        self.assertEqual(decision["status"], "pass")
        self.assertEqual(decision["model_out"], "gpt-5.6-sol")

    def test_jev_error_is_error_pass(self):
        decision = decide(pack(), "gpt-5.6-sol", error="TypeSafe request failed")
        self.assertEqual(decision["status"], "error-pass")
        self.assertEqual(decision["model_out"], "gpt-5.6-sol")

    def test_extract_last_user_message(self):
        text = extract_task(
            {
                "messages": [
                    {"role": "system", "content": "x"},
                    {"role": "user", "content": "first"},
                    {"role": "assistant", "content": "ok"},
                    {"role": "user", "content": [{"type": "text", "text": "Upstage 가격 지금 얼마야"}]},
                ]
            }
        )
        self.assertEqual(text, "Upstage 가격 지금 얼마야")

    def test_thread_key_from_headers(self):
        self.assertEqual(thread_key({"Thread-Id": "abc"}), "abc")
        self.assertEqual(thread_key({}), "")

    def test_parse_classification_unknown_role_becomes_other(self):
        parsed = parse_classification(
            {"answers": {"role": {"choice": "billing", "confidence": 0.9}, "needs_korean": {"noul": 0.1}}},
            ["implement", "research"],
        )
        self.assertEqual(parsed["role"], "other")


if __name__ == "__main__":
    unittest.main()
