import contextlib
import io
import json
import unittest

from jev_router.cli import main


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


if __name__ == "__main__":
    unittest.main()
