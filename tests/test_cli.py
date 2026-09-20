import contextlib
import io
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from jev_router.cli import _health, _static_plan, main
from jev_router.evaluation import merge_live_scores
from jev_router.evidence import sign_record
from jev_router.registry import eligible_models
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

    def test_explicit_static_team_keeps_all_configured_models(self):
        models = [ModelSpec(id=f"m{i}", provider="codex", model=f"m{i}", approved=True) for i in range(4)]
        plan = _static_plan(models, "orchestration", [model.id for model in models])
        self.assertEqual(plan["worker_ids"], ["m0", "m1", "m2", "m3"])

    def test_orchestration_with_one_model_is_blocked(self):
        model = ModelSpec(id="only", provider="codex", model="only", approved=True)
        self.assertEqual(_static_plan([model], "orchestration")["status"], "blocked")

    def test_orchestration_with_duplicate_models_is_blocked(self):
        model = ModelSpec(id="same", provider="codex", model="same", approved=True)
        self.assertEqual(_static_plan([model], "orchestration", ["same", "same"])["status"], "blocked")

    def test_failed_live_benchmark_keeps_runtime_rows_for_diagnosis(self):
        with tempfile.TemporaryDirectory() as directory:
            output_path = Path(directory) / "benchmark.jsonl"
            output = io.StringIO()
            with patch("jev_router.cli.run_benchmark", return_value=[{"task_id": "a", "arm": "single"}]), patch(
                "jev_router.cli.build_manifest", side_effect=ValueError("incomplete live manifest")
            ), contextlib.redirect_stdout(output):
                code = main([
                    "benchmark",
                    "--config",
                    "tests/fixtures/config.json",
                    "--tasks",
                    "tests/fixtures/tasks.jsonl",
                    "--execute",
                    "--benchmark-output",
                    str(output_path),
                ])
            self.assertEqual(code, 2)
            self.assertEqual(json.loads(output.getvalue())["status"], "blocked")
            self.assertEqual(json.loads(output_path.read_text(encoding="utf-8"))["task_id"], "a")

    def test_live_evaluation_does_not_promote_fixture_now_health(self):
        captured = {}

        def capture_health(rows, scores, **kwargs):
            captured.update(kwargs)
            return []

        with tempfile.TemporaryDirectory() as directory:
            input_path = Path(directory) / "benchmark.jsonl"
            scores_path = Path(directory) / "scores.jsonl"
            manifest_path = Path(directory) / "manifest.json"
            input_path.write_text("", encoding="utf-8")
            scores_path.write_text("", encoding="utf-8")
            manifest_path.write_text("{}", encoding="utf-8")
            output = io.StringIO()
            with patch("jev_router.cli.merge_live_scores", side_effect=capture_health), contextlib.redirect_stdout(output):
                code = main([
                    "evaluate",
                    "--config",
                    "tests/fixtures/config.json",
                    "--input",
                    str(input_path),
                    "--scores",
                    str(scores_path),
                    "--manifest",
                    str(manifest_path),
                    "--weights",
                    "config/weights.toml",
                    "--evidence-class",
                    "live",
                ])
            self.assertEqual(code, 1)
            self.assertEqual(captured["health"]["fixture-cheap"]["checked_at"], "now")

    def test_fake_now_health_is_not_fresh_without_fixture_label(self):
        model = ModelSpec(id="live", provider="codex", model="sol", approved=True)
        config = {"health": {"live": {"ok": True, "checked_at": "now"}}}
        self.assertEqual(eligible_models([model], _health(config)), [])

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

    def test_fixture_effectiveness_is_not_publishable(self):
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            code = main([
                "evaluate",
                "--input",
                "artifacts/benchmark.jsonl",
                "--weights",
                "config/weights.toml",
                "--evidence-class",
                "fixture",
            ])
        payload = json.loads(output.getvalue())
        self.assertEqual(code, 2)
        self.assertEqual(payload["verdict"], "effective")
        self.assertFalse(payload["publishable"])

    def test_live_evidence_requires_external_hash_bound_scores(self):
        rows = [{"task_id": "a", "arm": "single", "evidence_class": "live", "executed": True, "quality_source": "human", "quality": 1.0}]
        with self.assertRaises(ValueError):
            merge_live_scores(rows, [])

    def test_forged_runtime_rows_cannot_be_published(self):
        row = {
            "task_id": "a",
            "arm": "single",
            "evidence_class": "runtime_unscored",
            "executed": True,
            "output_sha256": "0" * 64,
            "prompt_sha256": "1" * 64,
            "execution_manifest_id": "forged",
            "model_count": 0,
            "status": "failed",
            "route_source": "single",
            "quality": 0.0,
        }
        score = {
            "task_id": "a",
            "arm": "single",
            "output_sha256": row["output_sha256"],
            "quality": 1.0,
            "source": "human",
            "scorer_id": "forger",
        }
        score["score_signature"] = sign_record(score, "scorer", "score_signature")
        with tempfile.TemporaryDirectory() as directory:
            input_path = Path(directory) / "benchmark.jsonl"
            score_path = Path(directory) / "scores.jsonl"
            input_path.write_text(json.dumps(row) + "\n", encoding="utf-8")
            score_path.write_text(json.dumps(score) + "\n", encoding="utf-8")
            output = io.StringIO()
            with patch.dict(os.environ, {"JEV_EVIDENCE_KEY": "evidence", "JEV_SCORER_KEY": "scorer"}, clear=False):
                with contextlib.redirect_stdout(output):
                    code = main([
                        "evaluate",
                        "--input",
                        str(input_path),
                        "--weights",
                        "config/weights.toml",
                        "--scores",
                        str(score_path),
                        "--evidence-class",
                        "live",
                    ])
        payload = json.loads(output.getvalue())
        self.assertEqual(code, 2)
        self.assertEqual(payload["verdict"], "blocked")

    def test_malformed_evaluation_input_returns_json_error(self):
        with tempfile.TemporaryDirectory() as directory:
            input_path = Path(directory) / "broken.jsonl"
            input_path.write_text("not json\n", encoding="utf-8")
            output = io.StringIO()
            with contextlib.redirect_stdout(output):
                code = main([
                    "evaluate",
                    "--input",
                    str(input_path),
                    "--weights",
                    "config/weights.toml",
                ])
        payload = json.loads(output.getvalue())
        self.assertEqual(code, 2)
        self.assertEqual(payload["verdict"], "blocked")


if __name__ == "__main__":
    unittest.main()
