import unittest
import math
from datetime import datetime, timezone

from jev_router.registry import ModelSpec, eligible_models, model_from_dict, validate_registry


class RegistryTests(unittest.TestCase):
    def test_unapproved_models_are_excluded(self):
        models = [
            ModelSpec(id="approved", provider="codex", model="sol", approved=True),
            ModelSpec(id="discovered-only", provider="grok", model="grok-4.6", approved=False),
        ]

        eligible = eligible_models(
            models,
            health={"approved": {"ok": True, "checked_at": datetime.now(timezone.utc).isoformat()}},
            require_fingerprint=False,
        )

        self.assertEqual([model.id for model in eligible], ["approved"])

    def test_metadata_validation_rejects_negative_cost(self):
        with self.assertRaises(ValueError):
            ModelSpec(
                id="bad",
                provider="codex",
                model="sol",
                input_cost_per_1k=-1,
            )

    def test_metadata_validation_rejects_non_finite_cost(self):
        with self.assertRaises(ValueError):
            ModelSpec(
                id="bad",
                provider="codex",
                model="sol",
                output_cost_per_1k=math.inf,
            )

    def test_duplicate_ids_are_rejected(self):
        models = [
            ModelSpec(id="same", provider="codex", model="sol"),
            ModelSpec(id="same", provider="grok", model="grok-4.6"),
        ]

        with self.assertRaises(ValueError):
            validate_registry(models)

    def test_registry_rejects_string_booleans(self):
        with self.assertRaises(ValueError):
            model_from_dict({"id": "bad", "provider": "codex", "model": "sol", "approved": "false"})
        with self.assertRaises(ValueError):
            model_from_dict({"id": "bad", "provider": "codex", "model": "sol", "enabled": "false"})


if __name__ == "__main__":
    unittest.main()
