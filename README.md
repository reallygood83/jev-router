# jev-router

`jev-router` is a thin, explicit router for AI models that are actually available in the local environment. It discovers local provider inventories, keeps only models the user has approved, health-checks them, and asks Jev whether the task should use one model or a small team.

The router is opt-in: it does not intercept ordinary prompts. A route is a decision surface; Codex, Grok, Claude, Cursor Agent, Kimi, Herdr, or another executor remains responsible for the actual work.

## Install

```bash
python3 -m pip install -e .
jev-router discover --json
```

No provider keys are stored by this project. Jev authentication is read from `TYPESAFE_API_KEY`; the provider CLIs keep their own credentials.

## First registration

```bash
jev-router discover --json
jev-router register --config ~/.config/jev-router/config.json --ids codex:gpt-5.6-sol,claude:sonnet
jev-router health --config ~/.config/jev-router/config.json --json
```

Discovery is informational. Only `register` with selected IDs sets `approved: true`. A model must be approved, enabled, healthy, and recently checked before it enters Jev's candidate payload.

## Route explicitly

```bash
jev-router --dry-run --json --config ~/.config/jev-router/config.json --task-file task.txt
jev-router --single --dry-run --json --config ~/.config/jev-router/config.json "format this note"
jev-router --orch --dry-run --json --config ~/.config/jev-router/config.json "compare two independent designs"
jev-router --execute --config ~/.config/jev-router/config.json --task-file task.txt
```

`--dry-run` never launches a provider process. Without an available Jev key, the normal route returns `status: blocked`; `--single` and `--orch` are explicit bypasses. A response fixture may be supplied with `--response-file` for deterministic tests.

If `policy.strategy_estimates` is present in the config, the router first applies the conservative lower-confidence-bound gate. It bypasses Jev when a baseline wins by less than the declared margin and calls Jev only when the Jev estimate clears that margin.

## Effectiveness test

The evaluator compares three arms per paired task:

1. one fixed model;
2. one fixed team;
3. Jev-selected single or team.

For each task, utility is:

`U = Q - lambda*C - mu*T - nu*F - O`

The publish gate uses the holdout difference between Jev and the best baseline. Jev passes only when the bootstrap lower 95% confidence bound is greater than `delta`. Fixture data tests the evaluator and is labeled `fixture`; it is not evidence that Jev improves real model quality.

```bash
# deterministic evaluator fixture; effective fixture results intentionally exit 2
jev-router evaluate --input artifacts/benchmark.jsonl --weights config/weights.toml --output artifacts/effectiveness.md --evidence-class fixture

# after registering and health-checking your real model pool
jev-router benchmark --config ~/.config/jev-router/config.json --tasks /path/to/holdout.jsonl --execute --benchmark-output artifacts/benchmark.jsonl
jev-router evaluate --input artifacts/benchmark.jsonl --weights config/weights.toml --scores artifacts/scores.jsonl --output artifacts/effectiveness.md --evidence-class live
```

Before a live run, provide two secrets and one signer identity outside the task and evidence files: `JEV_EVIDENCE_KEY` is used to sign the execution manifest, while `JEV_SCORER_KEY` and `JEV_SCORER_ID` are used by the independent scoring process to sign score records. The router never passes these values to provider subprocesses.

An executed benchmark records runtime metrics, prompt/output hashes, model count, route source, and an HMAC-signed execution manifest ID, but never treats task-authored quality as evidence. A separate `scores.jsonl` must contain one independently supplied and signed record per task and arm, with the matching `output_sha256`, `quality` from 0 to 1, `source` set to `human` or `judge`, and a non-empty `scorer_id`. Live publication also rejects fixture-backed routes, blocked executions, missing model runs, mismatched model fingerprints, and stale health records.

Prompts and provider output are not written to the JSONL evidence file. A score with a missing or mismatched output hash is rejected, so changing a task file or relabeling fixture quality cannot create a live result.

Example score record:

```json
{"task_id":"task-001","arm":"single","output_sha256":"...64 lowercase hex...","quality":0.82,"source":"human","scorer_id":"reviewer-01","execution_manifest_id":"...","prompt_sha256":"...64 lowercase hex...","model_ids":["provider:model"],"model_fingerprints":{"provider:model":"...64 lowercase hex..."},"score_signature":"...64 lowercase hex..."}
```

The scoring process can use `jev_router.evidence.sign_record(record, JEV_SCORER_KEY, "score_signature")`; keep that process and key outside the task runner.

## 한국어

`jev-router`는 로컬에서 실제 사용 가능한 AI 모델을 발견하고, 사용자가 승인한 모델 중 health check를 통과한 후보만 Jev에게 전달하는 얇은 라우터입니다. 일반 프롬프트를 가로채지 않고 사용자가 명시적으로 호출했을 때만 동작합니다.

처음에는 `discover`로 목록을 확인한 뒤 `register --ids ...`로 허용할 모델을 직접 승인합니다. 이후 `health`가 인증 만료·실패·빈 응답·모델 설정이 바뀐 모델을 제외하고, Jev가 단독 모델 또는 작은 팀을 선택합니다. 실제 실행은 각 provider CLI나 Herdr 같은 실행기가 담당합니다.

효과는 단일 모델, 고정 팀, Jev 선택을 같은 paired holdout 작업으로 비교합니다. 품질·비용·시간·실패·라우팅 오버헤드를 목적함수에 넣고, Jev가 최선의 baseline보다 `delta` 이상 높다는 95% bootstrap 하한을 통과해야 실제 효과라고 판정합니다. 실행 결과의 품질은 서명된 실행 manifest와 별도 output hash 결합 점수 파일에서만 주입되며, fixture 결과만으로는 GitHub publish 조건을 충족하지 않습니다.

## Evidence boundary

There is no theorem that Jev wins on every possible task. The honest claim is conditional: on the registered model pool and declared task distribution, with the declared utility weights and holdout protocol, Jev either clears the gate or it does not.
