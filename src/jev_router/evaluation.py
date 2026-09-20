import random
import math
import json
from collections import defaultdict
from statistics import mean
from pathlib import Path


def _as_float(value, name):
    try:
        number = float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{name} must be numeric") from exc
    if not math.isfinite(number):
        raise ValueError(f"{name} must be finite")
    return number


def _utility(row, weights):
    return (
        float(row.get("quality", 0.0))
        - float(weights.get("lambda", 0.0)) * float(row.get("cost", 0.0))
        - float(weights.get("mu", 0.0)) * float(row.get("time_ms", 0.0))
        - float(weights.get("nu", 0.0)) * float(row.get("failure_cost", 0.0))
        - float(row.get("overhead", 0.0))
    )


def _validate_weights(weights, bootstrap_samples):
    for name in ("lambda", "mu", "nu", "delta"):
        value = _as_float(weights.get(name, 0.0), name)
        if value < 0:
            raise ValueError(f"{name} must be non-negative")
    min_pairs_value = weights.get("min_pairs", 2)
    min_pairs = int(min_pairs_value)
    if min_pairs != min_pairs_value:
        raise ValueError("min_pairs must be an integer")
    if min_pairs <= 0:
        raise ValueError("min_pairs must be positive")
    if int(bootstrap_samples) != bootstrap_samples or bootstrap_samples <= 0:
        raise ValueError("bootstrap_samples must be positive")
    return min_pairs


def _validate_row(row):
    if not row.get("task_id") or not row.get("arm"):
        raise ValueError("each row requires task_id and arm")
    for name in ("quality", "cost", "time_ms", "failure_cost", "overhead"):
        value = _as_float(row.get(name, 0.0), name)
        if name == "quality" and not 0 <= value <= 1:
            raise ValueError("quality must be between 0 and 1")
        if name != "quality" and value < 0:
            raise ValueError(f"{name} must be non-negative")


def _quantile(values, probability):
    ordered = sorted(values)
    if not ordered:
        return 0.0
    position = (len(ordered) - 1) * probability
    lower = int(position)
    upper = min(lower + 1, len(ordered) - 1)
    fraction = position - lower
    return ordered[lower] + (ordered[upper] - ordered[lower]) * fraction


def evaluate_rows(rows, weights, seed=0, bootstrap_samples=1000):
    min_pairs = _validate_weights(weights, bootstrap_samples)
    grouped = defaultdict(dict)
    rows = list(rows)
    if any("split" in row for row in rows):
        rows = [row for row in rows if row.get("split") == "holdout"]
    for row in rows:
        _validate_row(row)
        task_id = row["task_id"]
        arm = row["arm"]
        if arm in grouped[task_id]:
            raise ValueError(f"duplicate arm for task {task_id}")
        grouped[task_id][arm] = _utility(row, weights)

    deltas = []
    for arms in grouped.values():
        if "jev" not in arms:
            continue
        baselines = [arms[arm] for arm in ("single", "static-team") if arm in arms]
        if baselines:
            deltas.append(arms["jev"] - max(baselines))

    if len(deltas) < min_pairs:
        return {
            "verdict": "insufficient_evidence",
            "pairs": len(deltas),
            "delta_mean": mean(deltas) if deltas else 0.0,
            "delta_lcb95": 0.0,
            "delta_ucb95": 0.0,
            "seed": seed,
            "bootstrap_samples": bootstrap_samples,
        }

    rng = random.Random(seed)
    bootstrap_means = [mean(rng.choice(deltas) for _ in deltas) for _ in range(bootstrap_samples)]
    delta_mean = mean(deltas)
    delta_lcb95 = _quantile(bootstrap_means, 0.025)
    delta_ucb95 = _quantile(bootstrap_means, 0.975)
    threshold = _as_float(weights.get("delta", 0.0), "delta")
    if delta_lcb95 > threshold:
        verdict = "effective"
    elif delta_ucb95 <= threshold:
        verdict = "not_effective"
    else:
        verdict = "inconclusive"
    return {
        "verdict": verdict,
        "pairs": len(deltas),
        "delta_mean": delta_mean,
        "delta_lcb95": delta_lcb95,
        "delta_ucb95": delta_ucb95,
        "seed": seed,
        "bootstrap_samples": bootstrap_samples,
    }


def load_jsonl(path):
    rows = []
    for line_number, line in enumerate(Path(path).read_text(encoding="utf-8").splitlines(), 1):
        if not line.strip():
            continue
        try:
            row = json.loads(line)
        except ValueError as exc:
            raise ValueError(f"invalid JSONL at line {line_number}") from exc
        if not isinstance(row, dict):
            raise ValueError(f"JSONL row {line_number} must be an object")
        rows.append(row)
    return rows


def render_report(result, weights, evidence_class="unverified"):
    verdict = result["verdict"]
    return "\n".join(
        [
            "# Jev effectiveness report",
            "",
            f"- Evidence class: {evidence_class}",
            f"- Verdict: {verdict}",
            f"- Paired holdout tasks: {result['pairs']}",
            f"- Mean utility delta (Jev - best baseline): {result['delta_mean']:.6f}",
            f"- Bootstrap 95% CI: [{result['delta_lcb95']:.6f}, {result['delta_ucb95']:.6f}]",
            f"- Required delta: {float(weights.get('delta', 0.0)):.6f}",
            f"- Seed: {result['seed']}",
            f"- Bootstrap samples: {result['bootstrap_samples']}",
            "",
            "A publishable effectiveness claim requires live or explicitly labeled holdout evidence; fixture results validate the evaluator only.",
            "",
        ]
    )
