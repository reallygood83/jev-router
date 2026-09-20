import unittest

from jev_router.jev import JevClient, build_payload, parse_decision, route_task
from jev_router.registry import ModelSpec


class JevTests(unittest.TestCase):
    models: list[ModelSpec] = []

    def setUp(self):
        self.models: list[ModelSpec] = [
            ModelSpec(id="cheap", provider="codex", model="luna", approved=True),
            ModelSpec(id="strong", provider="claude", model="opus", approved=True),
        ]

    def test_payload_is_limited_to_approved_healthy_candidates(self):
        payload = build_payload("write tests", self.models)
        self.assertEqual([item["id"] for item in payload["state"]["candidates"]], ["cheap", "strong"])

    def test_jev_decision_selects_captain_and_workers(self):
        response = {"mode": "orchestration", "captain_id": "strong", "worker_ids": ["cheap", "strong"]}
        decision = parse_decision(response, self.models)
        self.assertEqual(decision["mode"], "orchestration")
        self.assertEqual(decision["captain_id"], "strong")

        client = JevClient(transport=lambda endpoint, body, key: response)
        result = route_task("write tests", self.models, client)
        self.assertEqual(result["status"], "ok")
        self.assertEqual(result["worker_ids"], ["cheap", "strong"])

    def test_jev_cannot_select_outside_candidate_set(self):
        with self.assertRaises(ValueError):
            parse_decision({"mode": "single", "model_id": "not-approved"}, self.models)

    def test_custom_type_safe_endpoint_is_rejected(self):
        with self.assertRaises(ValueError):
            JevClient(endpoint="http://attacker.invalid/collect")


if __name__ == "__main__":
    unittest.main()
