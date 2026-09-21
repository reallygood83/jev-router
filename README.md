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

### First run: get to 4/4

1. Open the Jev dashboard at http://127.0.0.1:10115/ — not `/v1/responses`.
2. Save a TypeSafe API key. It is stored in `~/.config/jev-gate/secrets.json` with mode 600 and is never shown again.
3. Select home, implement, research, and write models, then click **팩 저장**.
4. Click **역할 3개 실제 테스트**. The dashboard makes one small generation call per role and shows the selected model and any upstream error.
5. Click **Codex Base URL 복사** and set Codex / any OpenAI-compatible client to `http://127.0.0.1:10115/v1`.
6. Leave the client picker on **home**, turn on **상시 실행**, and restart the client once.

The progress indicator reaches **4/4** only after OpenCodex, the TypeSafe key, the role pack, and all three live generation probes succeed. Model probes use a small number of tokens.

Expected live routing:

```text
implement: home -> configured implement model
research:  home -> configured research model
write:     home -> configured write model
```

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

**Opening `/v1/responses` in a browser says it cannot connect.** That URL is an API/WebSocket endpoint, not a page. A normal browser GET receives `426 Upgrade Required` by design. Open http://127.0.0.1:10115/ for Jev setup, and use `/v1` only as the client Base URL.

**The dashboard route test shows `Unsupported parameter: reasoning_effort`.** Upgrade to 0.3.4+ and restart Jev Gate. Responses API requests must send effort as `reasoning.effort`; chat-completions requests use top-level `reasoning_effort`.

**Codex App shows `Unknown endpoint: GET /v1/responses` or reconnecting.** Codex talks to OpenCodex over **websocket** (`ws://127.0.0.1:10115/v1/responses`). An old gate treated that as a plain HTTP GET and OpenCodex returned 404. Use 0.3.3+ so the gate tunnels the websocket. Then `git pull`, restart `jev-gate --port 10115`, and Cmd+Q Codex.

**Pack or TypeSafe key will not save.** You are on a stale process that still proxies `/api` to OpenCodex (401) or crashes on `~/.config` permissions. Stop it and start `jev-gate` again. A second `jev-gate` on the same port replaces the previous one via a pid file.

**ChatGPT app does nothing.** Expected. Only Codex App/CLI (or another client using that base URL) hits the gate.
