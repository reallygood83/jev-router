import unittest
import math

from jev_router.policy import StrategyEstimate, choose_strategy


class PolicyTests(unittest.TestCase):
    def test_orchestration_requires_positive_conservative_delta(self):
        decision = choose_strategy(
            [
                StrategyEstimate("single", mean=0.74, lcb95=0.68),
                StrategyEstimate("static-team", mean=0.80, lcb95=0.60),
                StrategyEstimate("jev", mean=0.84, lcb95=0.67),
            ],
            delta=0.02,
        )

        self.assertEqual(decision.strategy, "single")
        self.assertIn("conservative", decision.reason)

    def test_orchestration_is_selected_when_lower_bound_beats_baseline(self):
        decision = choose_strategy(
            [
                StrategyEstimate("single", mean=0.65, lcb95=0.58),
                StrategyEstimate("static-team", mean=0.69, lcb95=0.60),
                StrategyEstimate("jev", mean=0.82, lcb95=0.75),
            ],
            delta=0.02,
        )

        self.assertEqual(decision.strategy, "jev")
        self.assertGreater(decision.delta_lcb95, 0.02)

    def test_non_finite_confidence_is_rejected(self):
        with self.assertRaises(ValueError):
            choose_strategy([StrategyEstimate("single", mean=0.5, lcb95=math.nan)])


if __name__ == "__main__":
    unittest.main()
