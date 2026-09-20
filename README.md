# jev-router

Two tools:

- **`jev-gate`**: thin role gate in front of [OpenCodex](https://github.com/bitkyc08/opencodex). A local GUI binds home / implement / research / write to catalog models. Jev classifies the prompt; the gate rewrites `model` (and optional `reasoning_effort`) only when the client is still on **home**.
- **`jev-router`**: opt-in CLI that classifies a task, then runs a local provider CLI from a routing table.

Jev does not pick model ids. It picks a role. Failures pass through.

## Install

Requires Python 3.9+ and a running OpenCodex on `http://127.0.0.1:10100`.

```bash
git clone https://github.com/reallygood83/jev-router.git
cd jev-router
python3 -m pip install -e .
```

## Jev Gate (recommended)

```bash
jev-gate
```

Then:

1. Open http://127.0.0.1:10115/
2. Save a TypeSafe API key (stored in `~/.config/jev-gate/secrets.json`, mode 600, never shown again)
3. Set home + role models from the live OpenCodex catalog
4. Point Codex / any OpenAI-compatible client at `http://127.0.0.1:10115/v1`
5. Leave the picker on **home**. Search prompts can rewrite to research; code prompts to implement.
6. Click **상시 실행 켜기** so the gate starts at login and stays up if it crashes.

Without a key, the gate is a pure proxy (`error-pass`). If OpenCodex is down, the client sees the upstream error.

```bash
jev-gate --port 10115 --upstream http://127.0.0.1:10100
```

## jev-router CLI

```bash
export TYPESAFE_API_KEY=...
jev-router setup --json
jev-router --dry-run --json "format this note"
```

`--dry-run` never launches a provider. `--execute` runs the mapped CLI. `--single` / `--orch` bypass Jev.

## Skill / MCP

From the gate GUI: **스킬 원클릭 설치** copies a portable TypeSafe skill into `~/.agents/skills`, `~/.codex/skills`, and `~/.claude/skills`. **MCP 원클릭 설치** adds `typesafe-jev` to Codex `config.toml` and Claude `mcpServers` using `python -m jev_gate.mcp`. The API key is not written into those configs.

## Evidence

Fixture numbers in `artifacts/` test the evaluator. They are not a live quality claim.

## License

MIT

## Troubleshooting

**Codex App shows "다시 연결 중" / reconnecting.** Stop the old `jev-gate` and start a new one from this repo (0.3.2+). The proxy must speak HTTP/1.1 and must not re-chunk SSE streams. In the GUI, connection should show `gate 0.3.2 HTTP/1.1`. Then fully quit Codex (Cmd+Q) and reopen. `openai_base_url` must be `http://127.0.0.1:10115/v1`.

**Pack or TypeSafe key will not save.** You are on a stale process that still proxies `/api` to OpenCodex (401) or crashes on `~/.config` permissions. Stop it and start `jev-gate` again. A second `jev-gate` on the same port replaces the previous one via a pid file.

**ChatGPT app does nothing.** Expected. Only Codex App/CLI (or another client using that base URL) hits the gate.
