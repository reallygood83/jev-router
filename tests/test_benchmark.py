import unittest
from datetime import datetime, timezone

from jev_router.benchmark import run_benchmark
from jev_router.jev import JevClient
from jev_router.registry import ModelSpec


class BenchmarkTests(unittest.TestCase):
    def test_execution_never_imports_task_quality_as_live_evidence(self):
        models = [
            ModelSpec(id="cheap", provider="codex", model="cheap", approved=True),
            ModelSpec(id="strong", provider="claude", model="strong", approved=True),
        ]
        client = JevClient(transport=lambda endpoint, body, key: {"mode": "single", "model_id": "cheap"})
        rows = run_benchmark(
            [{"task_id": "a", "prompt": "answer", "quality_by_arm": {"single": 1.0, "static-team": 1.0, "jev": 1.0}}],
            models,
            "cheap",
            ["cheap", "strong"],
            client,
            runner=lambda *args, **kwargs: (0, "answer", ""),
            execute=True,
            health={model.id: {"ok": True, "checked_at": datetime.now(timezone.utc).isoformat()} for model in models},
        )

        self.assertEqual(len(rows), 3)
        self.assertTrue(all(row["evidence_class"] == "runtime_unscored" for row in rows))
        self.assertTrue(all(row["executed"] is True for row in rows))
        self.assertTrue(all(row["quality_source"] == "pending" for row in rows))
        self.assertTrue(all(row["quality"] == 0.0 for row in rows))
        self.assertTrue(all(len(row["output_sha256"]) == 64 for row in rows))


if __name__ == "__main__":
    unittest.main()
