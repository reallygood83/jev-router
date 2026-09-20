from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Iterable, Mapping, Optional
import json
import math
import os
from pathlib import Path


@dataclass(frozen=True)
class ModelSpec:
    id: str
    provider: str
    model: str
    approved: bool = False
    kind: str = "codex"
    argv: tuple[str, ...] = field(default_factory=tuple)
    purpose: str = ""
    when: str = ""
    context_tokens: int = 0
    input_cost_per_1k: float = 0.0
    output_cost_per_1k: float = 0.0
    latency_prior_ms: float = 0.0
    quality_prior: float = 0.5
    enabled: bool = True

    def __post_init__(self) -> None:
        if not self.id or not self.provider or not self.model:
            raise ValueError("id, provider, and model are required")
        if self.context_tokens < 0:
            raise ValueError("context_tokens must be non-negative")
        if not math.isfinite(self.input_cost_per_1k) or not math.isfinite(self.output_cost_per_1k):
            raise ValueError("costs must be finite")
        if self.input_cost_per_1k < 0 or self.output_cost_per_1k < 0:
            raise ValueError("costs must be non-negative")
        if not math.isfinite(self.latency_prior_ms):
            raise ValueError("latency_prior_ms must be finite")
        if self.latency_prior_ms < 0:
            raise ValueError("latency_prior_ms must be non-negative")
        if not 0 <= self.quality_prior <= 1:
            raise ValueError("quality_prior must be between 0 and 1")
        object.__setattr__(self, "argv", tuple(self.argv))


def eligible_models(
    models: Iterable[ModelSpec],
    health: Mapping[str, Mapping[str, Any]],
    now: Optional[datetime] = None,
    ttl_seconds: int = 3600,
) -> list[ModelSpec]:
    if ttl_seconds < 0:
        raise ValueError("ttl_seconds must be non-negative")
    current = now or datetime.now(timezone.utc)
    if current.tzinfo is None:
        current = current.replace(tzinfo=timezone.utc)
    eligible: list[ModelSpec] = []
    for model in models:
        if not model.approved or not model.enabled:
            continue
        result = health.get(model.id)
        if not result or result.get("ok") is not True:
            continue
        checked_at = result.get("checked_at")
        if checked_at is None:
            continue
        try:
            checked = datetime.fromisoformat(str(checked_at).replace("Z", "+00:00"))
        except ValueError:
            continue
        if checked.tzinfo is None:
            checked = checked.replace(tzinfo=timezone.utc)
        age_seconds = (current - checked).total_seconds()
        if age_seconds < 0 or age_seconds > ttl_seconds:
            continue
        eligible.append(model)
    return eligible


def validate_registry(models: Iterable[ModelSpec]) -> list[ModelSpec]:
    validated = list(models)
    ids = [model.id for model in validated]
    if len(ids) != len(set(ids)):
        raise ValueError("registry model IDs must be unique")
    return validated


def model_to_dict(model: ModelSpec) -> dict[str, Any]:
    return {
        "id": model.id,
        "provider": model.provider,
        "model": model.model,
        "approved": model.approved,
        "kind": model.kind,
        "argv": list(model.argv),
        "purpose": model.purpose,
        "when": model.when,
        "context_tokens": model.context_tokens,
        "input_cost_per_1k": model.input_cost_per_1k,
        "output_cost_per_1k": model.output_cost_per_1k,
        "latency_prior_ms": model.latency_prior_ms,
        "quality_prior": model.quality_prior,
        "enabled": model.enabled,
    }


def model_from_dict(data: Mapping[str, Any]) -> ModelSpec:
    return ModelSpec(
        id=str(data["id"]),
        provider=str(data["provider"]),
        model=str(data["model"]),
        approved=bool(data.get("approved", False)),
        kind=str(data.get("kind", data.get("provider", "codex"))),
        argv=tuple(str(value) for value in data.get("argv", ())),
        purpose=str(data.get("purpose", "")),
        when=str(data.get("when", "")),
        context_tokens=int(data.get("context_tokens", 0)),
        input_cost_per_1k=float(data.get("input_cost_per_1k", 0.0)),
        output_cost_per_1k=float(data.get("output_cost_per_1k", 0.0)),
        latency_prior_ms=float(data.get("latency_prior_ms", 0.0)),
        quality_prior=float(data.get("quality_prior", 0.5)),
        enabled=bool(data.get("enabled", True)),
    )


def save_registry(path: Path, models: Iterable[ModelSpec]) -> None:
    validated = validate_registry(models)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(
        json.dumps([model_to_dict(model) for model in validated], indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    os.replace(temporary, path)


def load_registry(path: Path) -> list[ModelSpec]:
    if not path.exists():
        return []
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, list):
        raise ValueError("registry must contain a JSON array")
    return validate_registry(model_from_dict(item) for item in payload)
