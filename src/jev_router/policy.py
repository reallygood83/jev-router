from dataclasses import dataclass
import math


@dataclass(frozen=True)
class StrategyEstimate:
    strategy: str
    mean: float
    lcb95: float


@dataclass(frozen=True)
class StrategyDecision:
    strategy: str
    reason: str
    delta_lcb95: float = 0.0


def choose_strategy(estimates, delta=0.0):
    estimates = list(estimates)
    if not estimates:
        raise ValueError("at least one strategy estimate is required")
    if not math.isfinite(float(delta)) or delta < 0:
        raise ValueError("delta must be finite and non-negative")
    for estimate in estimates:
        if not estimate.strategy:
            raise ValueError("strategy names are required")
        if not math.isfinite(float(estimate.mean)) or not math.isfinite(float(estimate.lcb95)):
            raise ValueError("strategy estimates must be finite")
    jev = next((estimate for estimate in estimates if estimate.strategy == "jev"), None)
    baselines = [estimate for estimate in estimates if estimate.strategy != "jev"]
    baseline = max(baselines or estimates, key=lambda estimate: estimate.lcb95)
    if jev is None:
        return StrategyDecision(baseline.strategy, "no Jev estimate; selected the strongest baseline")
    delta_lcb95 = jev.lcb95 - baseline.lcb95
    if delta_lcb95 > delta:
        return StrategyDecision(
            "jev",
            "Jev lower confidence bound beats the best baseline by the required margin",
            delta_lcb95,
        )
    return StrategyDecision(
        baseline.strategy,
        "conservative lower confidence bound does not justify Jev overhead",
        delta_lcb95,
    )
