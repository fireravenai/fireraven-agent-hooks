# Fireraven Agent Hooks

FireGuard guardrails for AI coding agents: **Windsurf/Devin**, **Cursor**, **Claude Code**, and **Microsoft Copilot**.

Block secret leakage, dangerous execution, and data poisoning at the hook layer — before prompts, shell commands, MCP calls, and file writes reach your agent.

## Quick install

```bash
curl -fsSL https://raw.githubusercontent.com/fireravenai/fireraven-agent-hooks/refs/heads/main/install.sh | sh
```

Install all supported local agents:

```bash
curl -fsSL https://raw.githubusercontent.com/fireravenai/fireraven-agent-hooks/refs/heads/main/install.sh | sh -s -- --agent all
```

Or use the CLI from a clone:

```bash
./fg install --agent windsurf
./fg init
./fg doctor
```

## Value proposition

| Threat | Coverage |
|--------|----------|
| Secret leakage | User prompts, file reads, MCP args, shell commands |
| Bad execution | `pre_run_command` / `beforeShellExecution` / tool gates |
| Data poisoning | `pre_write_code`, output audit on responses |

## Supported agents

| Agent | Install | Hook config | Blocking |
|-------|---------|-------------|----------|
| Windsurf / Devin | `--agent windsurf` | `~/.codeium/windsurf/hooks.json` | pre-hooks (exit 2) |
| Cursor | `--agent cursor` | `~/.cursor/hooks.json` | JSON `permission: deny` |
| Claude Code | `--agent claude` | `~/.claude/settings.json` | PreToolUse (exit 2) |
| Copilot | See [adapters/copilot/README.md](adapters/copilot/README.md) | Studio connector topics | Flow conditions |

## Hook events by platform

### Windsurf / Devin

**Input (blocking):** `pre_user_prompt`, `pre_run_command`, `pre_mcp_tool_use`, `pre_write_code`, `pre_read_code`

**Output (audit only):** `post_cascade_response`, `post_write_code`

### Cursor

**Input (blocking):** `beforeSubmitPrompt`, `beforeShellExecution`, `beforeMCPExecution`, `beforeReadFile`

Denies via JSON `{"permission": "deny"}` rather than exit codes.

### Claude Code

**Input (blocking):** `PreToolUse` (matcher `.*` — all tools)

Denies via exit code 2.

### Microsoft Copilot

No local shell hooks. FireGuard runs in **Copilot Studio** topic flows:

| Topic | Purpose |
|-------|---------|
| `topics/01_input_guardrail.yaml` | Input guardrails — block unsafe prompts |
| `topics/02_output_guardrail.yaml` | Output guardrails — audit/block assistant responses |

See [adapters/copilot/README.md](adapters/copilot/README.md) for connector setup.

## Post-install

Edit `config.env` in each agent's hooks directory:

```env
FIRERAVEN_GUARDRAILS_API_KEY=<your-api-key>
FIRERAVEN_PROJECT_ID=<your-project-id>
```

Restart your IDE(s).

## Environment variables

| Variable | Default | Description |
|----------|---------|-------------|
| `FIRERAVEN_HOOKS_REPO` | `fireravenai/fireraven-agent-hooks` | GitHub repo |
| `FIRERAVEN_HOOKS_REF` | `main` | Branch or tag |
| `FIRERAVEN_AGENT` | `windsurf` | Agent for install |
| `FIRERAVEN_FAIL_MODE` | `closed` | `closed` or `open` on API errors |

## Local development

```bash
FIRERAVEN_INSTALL_DIR=/tmp/fg-test ./scripts/install-local.sh
FIRERAVEN_AGENT=all FIRERAVEN_INSTALL_DIR=/tmp/fg-test ./scripts/install-local.sh
```

## Uninstall

```bash
./uninstall.sh --agent all
# or
./fg uninstall --agent windsurf
```

## Publishing

1. Push to `fireravenai/fireraven-agent-hooks` on `main`
2. Tag `v1.0.0` after verifying install
3. Cross-link from [Fireraven docs](https://doc.fireraven.ai/)

## Documentation

- [hooks/README.md](hooks/README.md) — hook details and manual testing
- [Cascade Hooks](https://docs.devin.ai/desktop/cascade/hooks)
- [FireGuard API](https://doc.fireraven.ai/)
