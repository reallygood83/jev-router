# jev-router

`jev-router` classifies a task with [TypeSafe Jev](https://docs.typesafe.ai/concepts/use-case-map.md), then runs a local model that **your routing table** selected.

Jev does not pick `codex:gpt-5.6-sol` or any other model id. It answers three System One questions:

- Choice: `code` / `write` / `search` / `review` / `other`
- Score: difficulty `0` / `1` / `2`
- Noul: is Korean quality central?

Code maps that to one of three roles: `fast`, `code`, `write`. If intent confidence is below `0.6`, the router ignores the classification and uses `fast`. Teams are opt-in (`--orch`); the default plan is always a single model.

This is not evidence that Jev chooses better models than a human. It is a small, honest classifier in front of CLIs you already have.

## Install

```bash
python3 -m pip install -e .
export TYPESAFE_API_KEY=...
jev-router setup --json
```

`setup` discovers local Codex / Grok / Claude / Cursor Agent / Kimi CLIs, registers a 3-model pool when those IDs exist (`codex:gpt-5.6-sol`, `codex:gpt-5.6-terra`, `claude:sonnet`), binds roles, and health-checks only those models.

No provider keys are stored here. Jev reads `TYPESAFE_API_KEY`. Provider subprocesses keep their own env and config, except `TYPESAFE_*` and `JEV_*` secrets which are stripped.

## Route

```bash
jev-router --dry-run --json "이 함수 테스트 짜줘"
jev-router --execute "이 함수 테스트 짜줘"
jev-router --single --dry-run --json "format this note"
jev-router --orch --dry-run --json "compare two independent designs"
```

`--dry-run` never launches a provider. `--execute` runs the mapped CLI. Without a Jev key, the default route returns `status: blocked`; `--single` and `--orch` bypass Jev.

A dry-run JSON includes `intent`, `difficulty`, `intent_confidence`, `role`, `worker_id`, and `fallback`. That classification is the product.

## Routing table

`~/.config/jev-router/config.json`:

```json
{
  "routing": {
    "confidence_floor": 0.6,
    "roles": {
      "fast": "codex:gpt-5.6-sol",
      "code": "codex:gpt-5.6-terra",
      "write": "claude:sonnet"
    }
  }
}
```

| Intent | Difficulty | Role |
| --- | --- | --- |
| `code` | 0 | `fast` |
| `code` | 1 or 2 | `code` |
| `write` / `review` | any | `write` |
| `search` | 0 or 1 | `fast` |
| `search` | 2 | `code` |
| Korean-central write/search/other | any | `fast` |
| confidence < floor | any | `fast` |

Edit the role IDs to match models you actually registered. `health` probes in parallel and reuses records inside `--health-ttl`. Pass `--refresh` to probe again.

## Evidence

Fixture evaluator numbers in `artifacts/` test the math. They are not a live quality claim. `publishable=false` until you run a signed holdout with independent scores. See `jev-router evaluate --help` and `config/weights.toml`.

## 한국어

Jev는 모델 이름을 고르지 않습니다. 작업의 의도·난이도·한국어 중요도만 분류하고, 실행할 CLI는 로컬 라우팅 테이블이 정합니다. confidence가 낮으면 `fast`로 떨어집니다. 기본은 단일 모델이고, 팀은 `--orch`일 때만 씁니다.

처음에는 `setup`으로 3개만 등록하세요. `discover`는 목록 확인용입니다.

## Evidence boundary

There is no theorem that Jev wins on every task. The honest claim is: on the registered role map and declared confidence floor, Jev either classifies with enough confidence to leave the default, or it does not.
