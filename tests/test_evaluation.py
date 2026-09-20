import hashlib
import unittest
from typing import cast

from jev_router.evaluation import evaluate_rows, merge_live_scores


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
        rows = [{
            "task_id": "a",
            "arm": "single",
            "evidence_class": "runtime_unscored",
            "executed": True,
            "output_sha256": output_sha256,
        }]
        scores = [{
            "task_id": "a",
            "arm": "single",
            "output_sha256": output_sha256,
            "quality": 0.8,
            "source": "human",
            "scorer_id": "reviewer-01",
        }]

        merged = merge_live_scores(rows, scores)

        self.assertEqual(merged[0]["quality"], 0.8)
        self.assertEqual(merged[0]["evidence_class"], "live")
        with self.assertRaises(ValueError):
            merge_live_scores(rows, [dict(scores[0], output_sha256="0" * 64)])


if __name__ == "__main__":
    unittest.main()
