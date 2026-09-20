import contextlib
import io
import json
import unittest

from jev_router.cli import _static_plan, main
from jev_router.registry import ModelSpec


class CliTests(unittest.TestCase):
    def test_dry_run_returns_only_approved_healthy_candidates(self):
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            code = main([
                "--dry-run",
                "--json",
                "--config",
                "tests/fixtures/config.json",
                "--task-file",
                "tests/fixtures/task.txt",
            ])
        payload = json.loads(output.getvalue())
        self.assertEqual(code, 0)
        self.assertEqual(payload["candidate_ids"], ["fixture-cheap", "fixture-strong"])
        self.assertNotIn("fixture-unapproved", payload["candidate_ids"])
        self.assertEqual(payload["source"], "fixture")

    def test_policy_baseline_fails_closed_for_empty_or_missing_models(self):
        self.assertEqual(_static_plan([], "single", ["missing"])["status"], "blocked")
        model = ModelSpec(id="live", provider="codex", model="sol")
        self.assertEqual(_static_plan([model], "single", ["missing"])["status"], "blocked")

    def test_fixture_cannot_be_labeled_live(self):
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            code = main([
                "evaluate",
                "--input",
                "artifacts/benchmark.jsonl",
                "--weights",
                "config/weights.toml",
                "--evidence-class",
                "live",
            ])
        payload = json.loads(output.getvalue())
        self.assertEqual(code, 2)
        self.assertEqual(payload["verdict"], "blocked")


if __name__ == "__main__":
    unittest.main()
