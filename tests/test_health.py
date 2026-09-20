import unittest
from datetime import datetime, timedelta, timezone

from jev_router.registry import ModelSpec, eligible_models


class HealthTests(unittest.TestCase):
    def test_failed_or_stale_models_are_excluded(self):
        now = datetime.now(timezone.utc)
        models = [
            ModelSpec(id="live", provider="codex", model="sol", approved=True),
            ModelSpec(id="failed", provider="grok", model="grok-4.6", approved=True),
            ModelSpec(id="stale", provider="claude", model="sonnet", approved=True),
        ]
        health = {
            "live": {"ok": True, "checked_at": now.isoformat()},
            "failed": {"ok": False, "checked_at": now.isoformat()},
            "stale": {
                "ok": True,
                "checked_at": (now - timedelta(hours=2)).isoformat(),
            },
        }

        eligible = eligible_models(models, health=health, now=now, ttl_seconds=3600)

        self.assertEqual([model.id for model in eligible], ["live"])

    def test_missing_or_future_health_timestamp_is_excluded(self):
        now = datetime.now(timezone.utc)
        model = ModelSpec(id="model", provider="codex", model="sol", approved=True)

        missing = eligible_models([model], {"model": {"ok": True}}, now=now)
        future = eligible_models(
            [model],
            {"model": {"ok": True, "checked_at": (now + timedelta(minutes=5)).isoformat()}},
            now=now,
        )

        self.assertEqual(missing, [])
        self.assertEqual(future, [])

    def test_non_boolean_health_success_is_excluded(self):
        now = datetime.now(timezone.utc)
        model = ModelSpec(id="model", provider="codex", model="sol", approved=True)

        eligible = eligible_models(
            [model],
            {"model": {"ok": "true", "checked_at": now.isoformat()}},
            now=now,
        )

        self.assertEqual(eligible, [])


if __name__ == "__main__":
    unittest.main()
