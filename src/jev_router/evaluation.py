import random
import math
import json
import os
import re
from collections import defaultdict
from statistics import mean
from pathlib import Path

from .evidence import verify_record
from .registry import ModelSpec, eligible_models, model_fingerprint

_SCORE_SOURCES = {"human", "judge"}
_SHA256 = re.compile(r"^[0-9a-f]{64}$")


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
    incomplete_tasks = []
    for task_id, arms in grouped.items():
        if not all(arm in arms for arm in ("single", "static-team", "jev")):
            incomplete_tasks.append(task_id)
            continue
        deltas.append(arms["jev"] - max(arms["single"], arms["static-team"]))

    if incomplete_tasks or len(deltas) < min_pairs:
        return {
            "verdict": "insufficient_evidence",
            "pairs": len(deltas),
            "incomplete_tasks": incomplete_tasks,
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
        "incomplete_tasks": [],
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


def merge_live_scores(rows, scores, manifest=None, evidence_key="", scorer_key="", scorer_id="", registry=None, health=None, health_ttl=3600):
    evidence_key = evidence_key or os.environ.get("JEV_EVIDENCE_KEY", "").strip()
    scorer_key = scorer_key or os.environ.get("JEV_SCORER_KEY", "").strip()
    scorer_id = scorer_id or os.environ.get("JEV_SCORER_ID", "").strip()
    if not evidence_key:
        raise ValueError("live evidence requires JEV_EVIDENCE_KEY")
    if not scorer_key:
        raise ValueError("live evidence requires JEV_SCORER_KEY")
    if not scorer_id:
        raise ValueError("live evidence requires JEV_SCORER_ID")
    if registry is None:
        raise ValueError("live evidence requires the approved model registry")
    if health is None:
        raise ValueError("live evidence requires fresh model health records")
    if not isinstance(manifest, dict) or not verify_record(manifest, evidence_key, "manifest_signature"):
        raise ValueError("live evidence requires a valid execution manifest")
    if manifest.get("execution_evidence_class") != "live":
        raise ValueError("fixture execution cannot be live evidence")
    registered = {model.id: model for model in registry if isinstance(model, ModelSpec)}
    healthy = {
        model.id: model
        for model in eligible_models(registry, health, ttl_seconds=health_ttl, require_fingerprint=True)
    }
    benchmark_rows = list(rows)
    expected = {}
    manifest_ids = set()
    manifest_records = manifest.get("row_records")
    if not isinstance(manifest_records, list):
        raise ValueError("execution manifest rows are missing")
    manifest_by_key = {}
    for item in manifest_records:
        if not isinstance(item, dict) or not isinstance(item.get("task_id"), str) or not isinstance(item.get("arm"), str):
            raise ValueError("execution manifest row key is invalid")
        key = (item["task_id"], item["arm"])
        if key in manifest_by_key:
            raise ValueError("execution manifest contains duplicate rows")
        manifest_by_key[key] = item
    for row in benchmark_rows:
        if not isinstance(row.get("task_id"), str) or not isinstance(row.get("arm"), str):
            raise ValueError("live evidence row key is invalid")
        key = (row.get("task_id"), row.get("arm"))
        output_sha256 = row.get("output_sha256")
        if row.get("evidence_class") != "runtime_unscored" or row.get("executed") is not True:
            raise ValueError("live evidence requires benchmark rows produced by execution")
        if not isinstance(output_sha256, str) or not _SHA256.fullmatch(output_sha256):
            raise ValueError("live evidence requires a valid output_sha256 for every row")
        prompt_sha256 = row.get("prompt_sha256")
        if not isinstance(prompt_sha256, str) or not _SHA256.fullmatch(prompt_sha256):
            raise ValueError("live evidence requires a valid prompt_sha256 for every row")
        if row.get("execution_evidence_class") != "live":
            raise ValueError("fixture execution cannot be live evidence")
        manifest_id = row.get("execution_manifest_id")
        if not isinstance(manifest_id, str) or not manifest_id:
            raise ValueError("live evidence requires an execution manifest ID")
        manifest_ids.add(manifest_id)
        model_count = row.get("model_count")
        if not isinstance(model_count, int) or isinstance(model_count, bool) or model_count < 1:
            raise ValueError("live evidence requires at least one executed model per arm")
        model_ids = row.get("model_ids")
        if not isinstance(model_ids, list) or len(model_ids) != model_count or not all(isinstance(model_id, str) and model_id for model_id in model_ids) or len(set(model_ids)) != len(model_ids):
            raise ValueError("live evidence requires the executed model IDs")
        if row.get("status") != "ok" or row.get("output_nonempty") is not True:
            raise ValueError("live evidence requires successful non-empty executions")
        fingerprints = row.get("model_fingerprints")
        if not isinstance(fingerprints, dict) or set(fingerprints) != set(model_ids):
            raise ValueError("live evidence requires model fingerprints for every executed model")
        for model_id in model_ids:
            model = registered.get(model_id)
            if model is None or not model.approved or not model.enabled:
                raise ValueError("live evidence contains a model outside the approved registry")
            if model_id not in healthy:
                raise ValueError("live evidence requires fresh health for every executed model")
            if fingerprints.get(model_id) != model_fingerprint(model):
                raise ValueError("live evidence model fingerprint does not match the registry")
        if row.get("route_source") == "fixture":
            raise ValueError("fixture-backed routes cannot be live evidence")
        if row.get("arm") == "jev" and row.get("route_source") != "typesafe":
            raise ValueError("live Jev evidence requires a live TypeSafe route")
        if not verify_record(row, evidence_key, "evidence_signature"):
            raise ValueError("execution manifest signature is invalid")
        manifest_row = manifest_by_key.get(key)
        if not isinstance(manifest_row, dict):
            raise ValueError("execution manifest is missing a benchmark row")
        for name in ("prompt_sha256", "output_sha256", "evidence_signature"):
            if manifest_row.get(name) != row.get(name):
                raise ValueError("benchmark row is not bound to the execution manifest")
        if key in expected:
            raise ValueError(f"duplicate benchmark row for task {key[0]} arm {key[1]}")
        expected[key] = row
    if len(manifest_ids) != 1:
        raise ValueError("live evidence rows must share one execution manifest")
    manifest_task_ids = manifest.get("task_ids")
    expected_task_ids = {key[0] for key in expected}
    if not isinstance(manifest_task_ids, list) or not all(isinstance(task_id, str) for task_id in manifest_task_ids) or set(manifest_task_ids) != expected_task_ids:
        raise ValueError("execution manifest task set does not match benchmark rows")
    if manifest.get("manifest_id") not in manifest_ids or set(manifest_by_key) != set(expected):
        raise ValueError("execution manifest task and arm set does not match benchmark rows")
    if manifest.get("row_count") != len(expected) or manifest.get("task_count") != len({key[0] for key in expected}):
        raise ValueError("execution manifest counts do not match benchmark rows")

    scored = {}
    for score in scores:
        if not isinstance(score, dict):
            raise ValueError("each live score must be an object")
        if not isinstance(score.get("task_id"), str) or not isinstance(score.get("arm"), str):
            raise ValueError("live score row key is invalid")
        key = (score.get("task_id"), score.get("arm"))
        if key not in expected:
            raise ValueError(f"score does not match a benchmark row: {key[0]} / {key[1]}")
        if key in scored:
            raise ValueError(f"duplicate live score for task {key[0]} arm {key[1]}")
        if score.get("output_sha256") != expected[key].get("output_sha256"):
            raise ValueError(f"score hash does not match output for task {key[0]} arm {key[1]}")
        for name in ("execution_manifest_id", "prompt_sha256", "model_ids", "model_fingerprints"):
            if score.get(name) != expected[key].get(name):
                raise ValueError(f"score is not bound to execution manifest for task {key[0]} arm {key[1]}")
        if score.get("scorer_id") != scorer_id:
            raise ValueError("score scorer_id does not match JEV_SCORER_ID")
        if not verify_record(score, scorer_key, "score_signature"):
            raise ValueError("score signature is invalid")
        source = score.get("source")
        if source not in _SCORE_SOURCES:
            raise ValueError("live score source must be human or judge")
        scorer_id = score.get("scorer_id")
        if not isinstance(scorer_id, str) or not scorer_id.strip():
            raise ValueError("live scores require scorer_id")
        if isinstance(score.get("quality"), bool):
            raise ValueError("quality must be numeric")
        quality = _as_float(score.get("quality"), "quality")
        if not 0 <= quality <= 1:
            raise ValueError("quality must be between 0 and 1")
        scored[key] = (quality, source)

    missing = sorted(set(expected) - set(scored))
    if missing:
        raise ValueError("live scores are missing benchmark rows")
    merged = []
    for row in benchmark_rows:
        quality, source = scored[(row["task_id"], row["arm"])]
        item = dict(row)
        item["quality"] = quality
        item["evidence_class"] = "live"
        item["quality_source"] = source
        merged.append(item)
    return merged


def render_report(result, weights, evidence_class="unverified"):
    verdict = result["verdict"]
    return "\n".join(
        [
            "# Jev effectiveness report",
            "",
            f"- Evidence class: {evidence_class}",
            f"- Verdict: {verdict}",
            f"- Publishable: {'yes' if evidence_class == 'live' and verdict == 'effective' else 'no'}",
            f"- Paired holdout tasks: {result['pairs']}",
            f"- Incomplete tasks: {len(result.get('incomplete_tasks', []))}",
            f"- Mean utility delta (Jev - best baseline): {result['delta_mean']:.6f}",
            f"- Bootstrap 95% CI: [{result['delta_lcb95']:.6f}, {result['delta_ucb95']:.6f}]",
            f"- Required delta: {float(weights.get('delta', 0.0)):.6f}",
            f"- Seed: {result['seed']}",
            f"- Bootstrap samples: {result['bootstrap_samples']}",
            "",
            "A publishable effectiveness claim requires signed live execution and scorer evidence; fixture results validate the evaluator only.",
            "",
        ]
    )
