import hashlib
import unittest
from datetime import datetime, timedelta, timezone
from typing import cast

from jev_router.benchmark import build_manifest
from jev_router.evaluation import evaluate_rows, merge_live_scores
from jev_router.evidence import sign_record
from jev_router.registry import ModelSpec, model_fingerprint


class EvaluationTests(unittest.TestCase):
    def test_paired_report_is_deterministic_and_correct(self):
        rows = [
            {"task_id": "a", "arm": "single", "quality": 0.6, "cost": 1, "time_ms": 100, "failure_cost": 0, "overhead": 0},
            {"task_id": "a", "arm": "static-team", "quality": 0.65, "cost": 1.2, "time_ms": 130, "failure_cost": 0, "overhead": 0.05},
            {"task_id": "a", "arm": "jev", "quality": 0.9, "cost": 1, "time_ms": 120, "failure_cost": 0, "overhead": 0.05},
            {"task_id": "b", "arm": "single", "quality": 0.6, "cost": 1, "time_ms": 100, "failure_cost": 0, "overhead": 0},
            {"task_id": "b", "arm": "static-team", "quality": 0.65, "cost": 1.2, "time_ms": 130, "failure_cost": 0, "overhead": 0.05},
            {"task_id": "b", "arm": "jev", "quality": 0.9, "cost": 1, "time_ms": 120, "failure_cost": 0, "overhead": 0.05},
        ]

        first = evaluate_rows(rows, weights={"lambda": 0.01, "mu": 0.0001, "nu": 1.0}, seed=7, bootstrap_samples=200)
        second = evaluate_rows(rows, weights={"lambda": 0.01, "mu": 0.0001, "nu": 1.0}, seed=7, bootstrap_samples=200)

        self.assertEqual(first, second)
        self.assertEqual(first["verdict"], "effective")
        self.assertGreater(cast(float, first["delta_mean"]), 0)
        self.assertGreater(cast(float, first["delta_lcb95"]), 0)

    def test_invalid_weights_and_bootstrap_count_are_rejected(self):
        with self.assertRaises(ValueError):
            evaluate_rows([], weights={"lambda": -1.0})
        with self.assertRaises(ValueError):
            evaluate_rows([], weights={}, bootstrap_samples=0)

    def test_missing_static_team_is_insufficient_evidence(self):
        result = evaluate_rows(
            [
                {"task_id": "a", "arm": "single", "quality": 0.6},
                {"task_id": "a", "arm": "jev", "quality": 0.9},
            ],
            weights={"min_pairs": 1},
            bootstrap_samples=20,
        )
        self.assertEqual(result["verdict"], "insufficient_evidence")
        self.assertEqual(result["incomplete_tasks"], ["a"])

    def test_live_score_is_bound_to_executed_output_hash(self):
        output_sha256 = hashlib.sha256(b"answer").hexdigest()
        model = ModelSpec(id="model-1", provider="codex", model="sol", approved=True)
        health = {
            "model-1": {
                "ok": True,
                "checked_at": datetime.now(timezone.utc).isoformat(),
                "model_fingerprint": model_fingerprint(model),
            }
        }
        rows = [{
            "task_id": "a",
            "arm": "single",
            "evidence_class": "runtime_unscored",
            "executed": True,
            "output_sha256": output_sha256,
            "prompt_sha256": hashlib.sha256(b"prompt").hexdigest(),
            "execution_manifest_id": "manifest-1",
            "execution_evidence_class": "live",
            "model_count": 1,
            "model_ids": ["model-1"],
            "model_fingerprints": {"model-1": model_fingerprint(model)},
            "status": "ok",
            "route_source": "single",
            "output_nonempty": True,
            "quality": 0.0,
        }]
        rows[0]["evidence_signature"] = sign_record(rows[0], "evidence-key", "evidence_signature")
        manifest = build_manifest(rows, evidence_key="evidence-key", evidence_class="live")
        scores = [{
            "task_id": "a",
            "arm": "single",
            "output_sha256": output_sha256,
            "quality": 0.8,
            "source": "human",
            "scorer_id": "reviewer-01",
            "execution_manifest_id": "manifest-1",
            "prompt_sha256": rows[0]["prompt_sha256"],
            "model_ids": rows[0]["model_ids"],
            "model_fingerprints": rows[0]["model_fingerprints"],
        }]
        scores[0]["score_signature"] = sign_record(scores[0], "score-key", "score_signature")

        merged = merge_live_scores(
            rows,
            scores,
            manifest=manifest,
            evidence_key="evidence-key",
            scorer_key="score-key",
            scorer_id="reviewer-01",
            registry=[model],
            health=health,
        )

        self.assertEqual(merged[0]["quality"], 0.8)
        self.assertEqual(merged[0]["evidence_class"], "live")
        with self.assertRaises(ValueError):
            merge_live_scores(
                rows[:0],
                [],
                manifest=manifest,
                evidence_key="evidence-key",
                scorer_key="score-key",
                scorer_id="reviewer-01",
                registry=[model],
                health=health,
            )
        with self.assertRaises(ValueError):
            merge_live_scores(
                rows,
                scores,
                manifest=manifest,
                evidence_key="evidence-key",
                scorer_key="score-key",
                scorer_id="reviewer-01",
                registry=[model],
                health={
                    "model-1": {
                        "ok": True,
                        "checked_at": (datetime.now(timezone.utc) - timedelta(hours=2)).isoformat(),
                        "model_fingerprint": model_fingerprint(model),
                    }
                },
            )
        with self.assertRaises(ValueError):
            merge_live_scores(
                rows,
                [dict(scores[0], output_sha256="0" * 64)],
                manifest=manifest,
                evidence_key="evidence-key",
                scorer_key="score-key",
                scorer_id="reviewer-01",
                registry=[model],
                health=health,
            )


if __name__ == "__main__":
    unittest.main()
