import unittest

from jev_router.registry import ModelSpec
from jev_router.routing import apply_lookup, bind_roles, role_for


class RoutingTests(unittest.TestCase):
    def setUp(self):
        self.models = [
            ModelSpec(id="fixture-cheap", provider="codex", model="luna", kind="codex", approved=True),
            ModelSpec(id="fixture-strong", provider="claude", model="opus", kind="claude", approved=True),
        ]

    def test_bind_roles_maps_codex_and_claude(self):
        roles = bind_roles(self.models)
        self.assertEqual(roles["fast"], "fixture-cheap")
        self.assertEqual(roles["code"], "fixture-cheap")
        self.assertEqual(roles["write"], "fixture-strong")

    def test_preferred_ids_win_when_present(self):
        models = [
            ModelSpec(id="codex:gpt-5.6-sol", provider="codex", model="gpt-5.6-sol", kind="codex", approved=True),
            ModelSpec(id="codex:gpt-5.6-terra", provider="codex", model="gpt-5.6-terra", kind="codex", approved=True),
            ModelSpec(id="claude:sonnet", provider="claude", model="sonnet", kind="claude", approved=True),
        ]
        self.assertEqual(
            bind_roles(models),
            {
                "fast": "codex:gpt-5.6-sol",
                "code": "codex:gpt-5.6-terra",
                "write": "claude:sonnet",
            },
        )

    def test_simple_code_uses_fast_role(self):
        self.assertEqual(role_for("code", 0), "fast")
        self.assertEqual(role_for("code", 2), "code")
        self.assertEqual(role_for("review", 1), "write")

    def test_korean_write_prefers_fast(self):
        self.assertEqual(role_for("write", 1, needs_korean=0.8), "fast")

    def test_low_confidence_defaults_to_fast(self):
        plan = apply_lookup(
            {"intent": "review", "intent_confidence": 0.2, "difficulty": 2, "needs_korean": 0.0},
            self.models,
        )
        self.assertEqual(plan["worker_id"], "fixture-cheap")
        self.assertTrue(plan["fallback"])
        self.assertEqual(plan["role"], "fast")

    def test_review_maps_to_write_role(self):
        plan = apply_lookup(
            {"intent": "review", "intent_confidence": 0.82, "difficulty": 1, "needs_korean": 0.1},
            self.models,
        )
        self.assertEqual(plan["worker_id"], "fixture-strong")
        self.assertEqual(plan["role"], "write")
        self.assertFalse(plan["fallback"])
        self.assertEqual(plan["mode"], "single")

    def test_lookup_cannot_select_ineligible_model(self):
        plan = apply_lookup(
            {"intent": "review", "intent_confidence": 0.9, "difficulty": 1, "needs_korean": 0.0},
            self.models,
            routing={"roles": {"write": "missing", "fast": "fixture-cheap"}},
        )
        self.assertEqual(plan["worker_id"], "fixture-cheap")
        self.assertTrue(plan["fallback"])
