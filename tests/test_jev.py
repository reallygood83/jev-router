import unittest
from datetime import datetime, timezone
from typing import Any

from jev_router.jev import JevClient, build_payload, parse_classification, route_task
from jev_router.registry import ModelSpec, model_fingerprint


class JevTests(unittest.TestCase):
    models: list[ModelSpec] = []
    health: dict[str, dict[str, Any]] = {}

    def setUp(self):
        self.models = [
            ModelSpec(id="cheap", provider="codex", model="luna", kind="codex", approved=True),
            ModelSpec(id="strong", provider="claude", model="opus", kind="claude", approved=True),
        ]
        checked_at = datetime.now(timezone.utc).isoformat()
        self.health = {
            model.id: {"ok": True, "checked_at": checked_at, "model_fingerprint": model_fingerprint(model)}
            for model in self.models
        }

    def test_payload_asks_intent_not_model_ids(self):
        payload = build_payload("write tests")
        questions = payload["questions"]
        self.assertEqual(set(questions), {"intent", "difficulty", "needs_korean"})
        self.assertEqual(questions["intent"]["type"], "choice")
        self.assertEqual(questions["difficulty"]["type"], "score")
        self.assertNotIn("candidates", payload["state"])
        self.assertNotIn("cheap", str(questions))

    def test_parse_classification_reads_typed_answers(self):
        classification = parse_classification(
            {
                "answers": {
                    "intent": {"choice": "review", "confidence": 0.82, "probabilities": {"review": 0.7}},
                    "difficulty": {"score": 1, "confidence": 0.7},
                    "needs_korean": {"noul": 0.12},
                }
            }
        )
        self.assertEqual(classification["intent"], "review")
        self.assertEqual(classification["difficulty"], 1)
        self.assertEqual(classification["intent_confidence"], 0.82)

    def test_unknown_intent_becomes_other(self):
        classification = parse_classification({"answers": {"intent": {"choice": "billing", "confidence": 0.9}}})
        self.assertEqual(classification["intent"], "other")

    def test_route_uses_lookup_instead_of_model_choice(self):
        response = {
            "answers": {
                "intent": {"choice": "review", "confidence": 0.82},
                "difficulty": {"score": 1, "confidence": 0.7},
                "needs_korean": {"noul": 0.1},
            }
        }
        client = JevClient(transport=lambda endpoint, body, key: response)
        result = route_task("compare two designs", self.models, client, health=self.health)
        self.assertEqual(result["status"], "ok")
        self.assertEqual(result["mode"], "single")
        self.assertEqual(result["role"], "write")
        self.assertEqual(result["worker_id"], "strong")
        self.assertEqual(result["candidate_ids"], ["cheap", "strong"])

    def test_route_requires_health_evidence(self):
        client = JevClient(transport=lambda endpoint, body, key: {"answers": {"intent": {"choice": "code", "confidence": 0.9}}})
        result = route_task("write tests", self.models, client)
        self.assertEqual(result["status"], "blocked")

    def test_custom_type_safe_endpoint_is_rejected(self):
        with self.assertRaises(ValueError):
            JevClient(endpoint="http://attacker.invalid/collect")


if __name__ == "__main__":
    unittest.main()
