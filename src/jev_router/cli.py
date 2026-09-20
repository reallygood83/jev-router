import argparse
import hashlib
import json
import sys
from dataclasses import replace
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional, cast

from .adapters import execute_plan
from .benchmark import run_benchmark, save_jsonl
from .config import load_config, load_weights, models_from_config, put_models, save_config
from .discovery import discover_local_models
from .evaluation import evaluate_rows, load_jsonl, merge_live_scores, render_report
from .health import probe_model
from .jev import JevClient, JevUnavailable, route_task
from .policy import StrategyEstimate, choose_strategy
from .registry import ModelSpec, eligible_models, validate_registry


def _digest(text):
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:16]


def _task(parts, task_file):
    if task_file:
        return Path(task_file).read_text(encoding="utf-8").strip()
    return " ".join(parts).strip()


def _optional_path(value, config_path):
    if not value:
        return None
    target = Path(value).expanduser()
    if target.is_absolute() or target.exists():
        return str(target)
    return str(Path(config_path).expanduser().parent / target)


def _health(config):
    result = config.get("health", {})
    normalized = {}
    now = datetime.now(timezone.utc).isoformat()
    fixture = config.get("evidence_class") == "fixture"
    for model_id, value in result.items():
        item = dict(value)
        if fixture and item.get("checked_at") == "now":
            item["checked_at"] = now
        normalized[model_id] = item
    return normalized


def _base_output(task, plan: dict[str, Any]) -> dict[str, Any]:
    return {
        "task_digest": _digest(task),
        **plan,
    }


def _static_plan(models, mode, model_ids=None) -> dict[str, Any]:
    by_id = {model.id: model for model in models}
    if model_ids is not None:
        if isinstance(model_ids, str):
            model_ids = [model_ids]
        requested = list(model_ids)
        if not requested or (mode == "single" and len(requested) != 1) or (mode == "orchestration" and len(requested) < 2):
            return {"status": "blocked", "reason": "fixed baseline requires the configured model IDs"}
        missing = [model_id for model_id in requested if model_id not in by_id]
        if missing:
            return {"status": "blocked", "reason": "fixed baseline is not eligible: " + ", ".join(missing)}
        ordered = [by_id[model_id] for model_id in requested]
    else:
        ordered = sorted(models, key=lambda model: (model.quality_prior, -model.input_cost_per_1k), reverse=True)
    if not ordered:
        return {"status": "blocked", "reason": "no approved healthy models"}
    if mode == "orchestration" and len(ordered) < 2:
        return {"status": "blocked", "reason": "orchestration requires at least two models"}
    captain = ordered[0]
    if mode == "single":
        return {
            "status": "ok",
            "mode": "single",
            "worker_id": captain.id,
            "captain_id": captain.id,
            "worker_ids": [captain.id],
            "confidence": 1.0,
            "reason": "explicit single mode",
            "source": "explicit",
        }
    workers = [model.id for model in ordered] if model_ids is not None else [model.id for model in ordered[:3]]
    return {
        "status": "ok",
        "mode": "orchestration",
        "worker_id": captain.id,
        "captain_id": captain.id,
        "worker_ids": workers,
        "confidence": 1.0,
        "reason": "explicit orchestration mode",
        "source": "explicit",
    }


def _strategy_gate(config: dict[str, Any]) -> Optional[dict[str, Any]]:
    policy = config.get("policy", {})
    raw_estimates = policy.get("strategy_estimates")
    if not raw_estimates:
        return None
    estimates = [
        StrategyEstimate(
            strategy=str(item["strategy"]),
            mean=float(item["mean"]),
            lcb95=float(item["lcb95"]),
        )
        for item in raw_estimates
    ]
    decision = choose_strategy(estimates, delta=float(policy.get("delta", 0.0)))
    return {
        "strategy": decision.strategy,
        "reason": decision.reason,
        "delta_lcb95": decision.delta_lcb95,
    }


def cmd_discover(args):
    result = discover_local_models()
    print(json.dumps(result, ensure_ascii=False, indent=2) if args.json else _discover_text(result))
    return 0


def _discover_text(result):
    lines = []
    for provider, value in result["providers"].items():
        lines.append(f"{provider}: {value['status']} ({value['source']})")
        for model in value["models"][:12]:
            lines.append(f"  {model}")
    return "\n".join(lines)


def cmd_register(args):
    config = load_config(args.config)
    discovered = discover_local_models()
    by_id = {}
    for item in discovered["models"]:
        if not isinstance(item, dict):
            continue
        item_id = item.get("id")
        provider = item.get("provider")
        model_name = item.get("model")
        kind = item.get("kind")
        if not isinstance(item_id, str) or not isinstance(provider, str) or not isinstance(model_name, str) or not isinstance(kind, str):
            continue
        argv_value = item.get("argv", ())
        argv = tuple(str(value) for value in argv_value) if isinstance(argv_value, (list, tuple)) else ()
        raw_context = item.get("context_tokens", 0)
        context_tokens = int(raw_context) if isinstance(raw_context, (int, float, str)) else 0
        by_id[item_id] = ModelSpec(
            id=cast(str, item_id),
            provider=cast(str, provider),
            model=cast(str, model_name),
            kind=cast(str, kind),
            argv=argv,
            context_tokens=context_tokens,
            purpose=str(item.get("purpose", "")),
            approved=False,
        )
    wanted = set(filter(None, (args.ids or "").split(",")))
    if args.approve_all:
        wanted = set(by_id)
    if not wanted:
        payload = {"status": "needs_selection", "models": sorted(by_id)}
        print(json.dumps(payload, ensure_ascii=False, indent=2))
        return 2
    unknown = sorted(wanted - set(by_id))
    if unknown:
        print(json.dumps({"status": "error", "unknown_ids": unknown}, ensure_ascii=False), file=sys.stderr)
        return 2
    existing = {model.id: model for model in models_from_config(config)}
    for model_id in wanted:
        model = by_id[model_id]
        existing[model_id] = replace(model, approved=True)
    put_models(config, validate_registry(existing.values()))
    save_config(args.config, config)
    output = {"status": "registered", "approved_ids": sorted(wanted), "config": str(Path(args.config).expanduser())}
    print(json.dumps(output, ensure_ascii=False, indent=2))
    return 0


def cmd_health(args):
    config = load_config(args.config)
    models = models_from_config(config)
    results = {model.id: probe_model(model, timeout_seconds=args.timeout) for model in models if model.enabled}
    config["health"] = results
    save_config(args.config, config)
    payload = {"status": "completed", "models": results, "config": str(Path(args.config).expanduser())}
    print(json.dumps(payload, ensure_ascii=False, indent=2) if args.json else _health_text(results))
    return 0 if results and all(result.get("ok") for result in results.values()) else 1


def _health_text(results):
    return "\n".join(
        f"[{('ok' if value.get('ok') else 'failed')}] {model_id}: {value.get('reason', '')}"
        for model_id, value in results.items()
    )


def cmd_route(args, parts):
    task = _task(parts, args.task_file)
    if not task:
        print("task text or --task-file is required", file=sys.stderr)
        return 2
    config = load_config(args.config)
    models = validate_registry(models_from_config(config))
    candidates = eligible_models(models, _health(config), ttl_seconds=args.health_ttl)
    gate = _strategy_gate(config)
    plan: dict[str, Any]
    if not candidates:
        plan = {"status": "blocked", "reason": "no approved healthy models", "source": "health"}
    elif args.single:
        plan = _static_plan(candidates, "single") if candidates else {"status": "blocked", "reason": "no approved healthy models"}
    elif args.orch:
        plan = _static_plan(candidates, "orchestration") if candidates else {"status": "blocked", "reason": "no approved healthy models"}
    elif gate and gate["strategy"] in {"single", "static-team"}:
        policy = config.get("policy", {})
        ids = [policy.get("single_model_id")] if gate["strategy"] == "single" and policy.get("single_model_id") else policy.get("static_team_ids")
        if ids is None:
            plan = {"status": "blocked", "reason": "policy baseline model IDs are not configured", "source": "policy", "strategy_gate": gate}
        else:
            plan = _static_plan(candidates, "single" if gate["strategy"] == "single" else "orchestration", ids)
            plan["source"] = "policy"
            plan["strategy_gate"] = gate
    else:
        jev = config.get("jev", {})
        response_file = _optional_path(args.response_file or jev.get("response_file"), args.config)
        try:
            client = JevClient(
                endpoint=jev.get("endpoint", "https://api.typesafe.ai/v1/systemone"),
                model=jev.get("model", "jev-latest"),
                response_file=response_file,
            )
            plan = route_task(task, candidates, client, cwd=str(Path.cwd()), threshold=float(jev.get("orchestrator_threshold", 0.6)))
        except (JevUnavailable, ValueError) as exc:
            plan = {"status": "blocked", "reason": str(exc), "source": "jev"}
        if gate:
            plan["strategy_gate"] = gate
    output = _base_output(task, plan)
    if args.execute and plan.get("status") == "ok":
        output["execution"] = execute_plan(plan, models, task, timeout_seconds=args.timeout)
    if args.json or args.dry_run or not args.execute:
        print(json.dumps(output, ensure_ascii=False, indent=2))
    else:
        execution = output.get("execution")
        print(execution.get("output", "") if isinstance(execution, dict) else "")
    return 0 if plan.get("status") == "ok" else 1


def cmd_evaluate(args):
    try:
        rows = load_jsonl(args.input)
        if args.evidence_class == "live":
            if not args.scores:
                raise ValueError("live evidence requires --scores with external output-bound scores")
            rows = merge_live_scores(rows, load_jsonl(args.scores))
        weights = load_weights(args.weights)
        result = evaluate_rows(rows, weights, seed=args.seed, bootstrap_samples=args.bootstrap_samples)
    except (OSError, ValueError) as exc:
        print(json.dumps({"verdict": "blocked", "reason": str(exc)}, ensure_ascii=False))
        return 2
    report = render_report(result, weights, args.evidence_class)
    if args.output:
        Path(args.output).parent.mkdir(parents=True, exist_ok=True)
        Path(args.output).write_text(report, encoding="utf-8")
    print(json.dumps(result, ensure_ascii=False, indent=2))
    if args.output:
        print(f"report: {args.output}")
    return 0 if result["verdict"] == "effective" else 1


def cmd_benchmark(args):
    config = load_config(args.config)
    models = validate_registry(models_from_config(config))
    candidates = eligible_models(models, _health(config), ttl_seconds=args.health_ttl)
    if not candidates:
        print(json.dumps({"status": "blocked", "reason": "no approved healthy models"}, ensure_ascii=False))
        return 1
    single_id = args.single_id or candidates[0].id
    team_ids = [item for item in (args.team_ids or "").split(",") if item] or [model.id for model in candidates[:2]]
    jev = config.get("jev", {})
    try:
        client = JevClient(
            endpoint=jev.get("endpoint", "https://api.typesafe.ai/v1/systemone"),
            model=jev.get("model", "jev-latest"),
            response_file=_optional_path(args.response_file or jev.get("response_file"), args.config),
        )
        tasks = load_jsonl(args.tasks)
        rows = run_benchmark(tasks, candidates, single_id, team_ids, client, seed=args.seed, execute=args.execute)
    except (OSError, ValueError, JevUnavailable) as exc:
        print(json.dumps({"status": "blocked", "reason": str(exc)}, ensure_ascii=False))
        return 2
    save_jsonl(args.benchmark_output, rows)
    print(json.dumps({"status": "completed", "rows": len(rows), "output": args.benchmark_output, "executed": args.execute}, ensure_ascii=False, indent=2))
    return 0


def build_parser():
    parser = argparse.ArgumentParser(prog="jev-router")
    parser.add_argument("parts", nargs="*")
    parser.add_argument("--config", default=str(Path.home() / ".config" / "jev-router" / "config.json"))
    parser.add_argument("--task-file")
    parser.add_argument("--response-file")
    parser.add_argument("--input")
    parser.add_argument("--weights")
    parser.add_argument("--output")
    parser.add_argument("--tasks")
    parser.add_argument("--benchmark-output", default="artifacts/benchmark.jsonl")
    parser.add_argument("--single-id")
    parser.add_argument("--team-ids")
    parser.add_argument("--scores")
    parser.add_argument("--evidence-class", default="unverified")
    parser.add_argument("--ids")
    parser.add_argument("--approve-all", action="store_true")
    parser.add_argument("--single", action="store_true")
    parser.add_argument("--orch", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--execute", action="store_true")
    parser.add_argument("--json", action="store_true")
    parser.add_argument("--health", action="store_true")
    parser.add_argument("--discover", action="store_true")
    parser.add_argument("--timeout", type=int, default=120)
    parser.add_argument("--health-ttl", type=int, default=3600)
    parser.add_argument("--seed", type=int, default=0)
    parser.add_argument("--bootstrap-samples", type=int, default=1000)
    return parser


def main(argv=None):
    args = build_parser().parse_args(argv)
    command = args.parts[0] if args.parts and args.parts[0] in {"discover", "register", "health", "evaluate", "benchmark"} else "route"
    parts = args.parts[1:] if command != "route" else args.parts
    if args.discover or command == "discover":
        return cmd_discover(args)
    if command == "register":
        return cmd_register(args)
    if args.health or command == "health":
        return cmd_health(args)
    if command == "evaluate":
        if not args.input or not args.weights:
            print("evaluate requires --input and --weights", file=sys.stderr)
            return 2
        return cmd_evaluate(args)
    if command == "benchmark":
        if not args.tasks:
            print("benchmark requires --tasks", file=sys.stderr)
            return 2
        return cmd_benchmark(args)
    return cmd_route(args, parts)


if __name__ == "__main__":
    raise SystemExit(main())
