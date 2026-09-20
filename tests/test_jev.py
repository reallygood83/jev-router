import unittest
from datetime import datetime, timezone
from typing import Any, cast

from jev_router.jev import JevClient, build_payload, parse_decision, route_task
from jev_router.registry import ModelSpec, model_fingerprint


class JevTests(unittest.TestCase):
    models: list[ModelSpec] = []
    health: dict[str, dict[str, Any]] = {}

    def setUp(self):
        self.models: list[ModelSpec] = [
            ModelSpec(id="cheap", provider="codex", model="luna", approved=True),
            ModelSpec(id="strong", provider="claude", model="opus", approved=True),
        ]
        checked_at = datetime.now(timezone.utc).isoformat()
        self.health = {
            model.id: {"ok": True, "checked_at": checked_at, "model_fingerprint": model_fingerprint(model)}
            for model in self.models
        }

    def test_payload_is_limited_to_approved_healthy_candidates(self):
        unapproved = ModelSpec(id="unapproved", provider="grok", model="grok", approved=False)
        payload = build_payload("write tests", self.models + [unapproved], health=self.health)
        state = cast(dict[str, Any], payload["state"])
        candidates = cast(list[dict[str, Any]], state["candidates"])
        self.assertEqual([item["id"] for item in candidates], ["cheap", "strong"])

    def test_jev_decision_selects_captain_and_workers(self):
        response = {"mode": "orchestration", "captain_id": "strong", "worker_ids": ["cheap", "strong"]}
        decision = parse_decision(response, self.models, health=self.health)
        self.assertEqual(decision["mode"], "orchestration")
        self.assertEqual(decision["captain_id"], "strong")

        client = JevClient(transport=lambda endpoint, body, key: response)
        result = route_task("write tests", self.models, client, health=self.health)
        self.assertEqual(result["status"], "ok")
        self.assertEqual(result["worker_ids"], ["cheap", "strong"])

    def test_jev_cannot_select_outside_candidate_set(self):
        with self.assertRaises(ValueError):
            parse_decision({"mode": "single", "model_id": "not-approved"}, self.models, health=self.health)

    def test_jev_orchestration_requires_two_models(self):
        with self.assertRaises(ValueError):
            parse_decision(
                {"mode": "orchestration", "captain_id": "cheap", "worker_ids": ["cheap"]},
                self.models,
                health=self.health,
            )

    def test_jev_rejects_duplicate_workers(self):
        with self.assertRaises(ValueError):
            parse_decision(
                {"mode": "orchestration", "captain_id": "strong", "worker_ids": ["cheap", "strong", "strong"]},
                self.models,
                health=self.health,
            )

    def test_route_requires_health_evidence(self):
        client = JevClient(transport=lambda endpoint, body, key: {"mode": "single", "model_id": "cheap"})
        result = route_task("write tests", self.models, client)
        self.assertEqual(result["status"], "blocked")

    def test_custom_type_safe_endpoint_is_rejected(self):
        with self.assertRaises(ValueError):
            JevClient(endpoint="http://attacker.invalid/collect")


if __name__ == "__main__":
    unittest.main()
