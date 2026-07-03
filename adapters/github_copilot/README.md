# GitHub Copilot Integration

FireGuard guardrails for **GitHub Copilot CLI** and **Copilot cloud agent** via [shell hooks](https://docs.github.com/en/copilot/how-tos/copilot-on-github/customize-copilot/customize-cloud-agent/use-hooks).

> This is **GitHub Copilot** (CLI / cloud agent). For **Microsoft Copilot Studio**, see [adapters/copilot/README.md](../copilot/README.md).

## What this covers

| Surface | Install target | Config file |
|---------|----------------|-------------|
| Copilot CLI | `./fg install --agent github-copilot` | `~/.copilot/hooks/fireraven-fireguard.json` |
| Copilot cloud agent | `./fg install --agent github-copilot --project` | `.github/hooks/fireraven-fireguard.json` |

## What this does not cover

- VS Code inline completions or Tab suggestions
- Microsoft Copilot Studio (use `--agent copilot` and [adapters/copilot/](../copilot/))
- Prompt blocking — GitHub Copilot ignores `userPromptSubmitted` hook output; enforcement is on **tool calls** via `preToolUse`

## Quick install

### User-level (Copilot CLI)

```bash
curl -fsSL https://raw.githubusercontent.com/fireravenai/fireraven-agent-hooks/refs/heads/main/install.sh | sh -s -- --agent github-copilot
```

Or from a clone:

```bash
./fg install --agent github-copilot
```

Installs to:

| Path | Purpose |
|------|---------|
| `~/.copilot/hooks/fireraven-fireguard.json` | Hook registration |
| `~/.copilot/hooks/fireraven/` | Scripts and `config.env` |

### Project-level (Copilot cloud agent)

From your repository root:

```bash
/path/to/fireraven-agent-hooks/fg install --agent github-copilot --project
```

Installs to:

| Path | Purpose |
|------|---------|
| `.github/hooks/fireraven-fireguard.json` | Hook registration (commit to default branch) |
| `.github/hooks/fireraven/` | Scripts (commit); `config.env` (gitignored) |

Cloud agent only loads `.github/hooks/*.json` from the cloned repository on the **default branch**.

## Configuration

Edit `config.env` in the installed hooks directory:

```env
FIRERAVEN_GUARDRAILS_API_KEY=your_key
FIRERAVEN_PROJECT_ID=your_project_id
```

- **User CLI:** `~/.copilot/hooks/fireraven/config.env`
- **Cloud agent:** `.github/hooks/fireraven/config.env` (add to `.gitignore`; do not commit secrets)

## Hook events

| Event | FireGuard action | Blocking? |
|-------|------------------|-----------|
| `userPromptSubmitted` | Input guardrail check | No — output is not processed by Copilot |
| `preToolUse` | Input guardrail on tool call | Yes — `permissionDecision: deny` |
| `postToolUse` | Output audit on tool result | Audit only (stderr log if unsafe) |

`preToolUse` is the primary enforcement point. Unlike Cursor, GitHub Copilot cannot block prompts via `userPromptSubmitted`.

Deny response shape:

```json
{"permissionDecision": "deny", "permissionDecisionReason": "Blocked by Fireraven FireGuard"}
```

## Getting started (recommended test order)

You do **not** need VS Code to validate the integration. Work through these steps in order:

### 1. Install and configure

```bash
./fg install --agent github-copilot
# Edit ~/.copilot/hooks/fireraven/config.env with FIRERAVEN_* credentials
```

### 2. Smoke-test the hook script (no Copilot required)

```bash
# Allow: empty stdout, exit 0
echo '{"sessionId":"test","prompt":"hello"}' \
  | python3 ~/.copilot/hooks/fireraven/github_copilot_guardrail.py
echo "exit: $?"

# Block (if policy flags it): JSON deny on stdout, exit 0
echo '{"sessionId":"test","toolName":"bash","toolArgs":"{\"command\":\"rm -rf /\"}"}' \
  | python3 ~/.copilot/hooks/fireraven/github_copilot_guardrail.py
echo "exit: $?"
```

Expected outcomes:

| Input | Allowed | Denied |
|-------|---------|--------|
| Prompt (`userPromptSubmitted`) | Empty stdout, exit 0 | Cannot block — audit only |
| Tool call (`preToolUse`) | Empty stdout, exit 0 | `{"permissionDecision":"deny",...}` on stdout, exit 0 |
| Hook crash / missing config (`preToolUse`, fail-closed) | — | Non-zero exit (Copilot treats as deny) |

### 3. End-to-end with Copilot CLI

Run a Copilot CLI agent session that triggers a tool (shell command, file edit). Unsafe tool calls should be denied by `preToolUse`.

### 4. End-to-end with Copilot cloud agent (optional)

Install with `--project`, commit hook files to the default branch, configure `config.env`, allowlist `api.fireraven.ai`, then trigger a cloud agent job on the repo.

## Cloud agent prerequisites

1. Merge hook config and scripts to your repository **default branch**
2. Configure `.github/hooks/fireraven/config.env` with Fireraven credentials (or use hook `env` entries)
3. Ensure outbound network allows `api.fireraven.ai` (org admin firewall allow rule may be required)
4. Cloud agent runs **Linux/bash only** — `powershell` hook entries are ignored

## Uninstall

```bash
./fg uninstall --agent github-copilot
./fg uninstall --agent github-copilot --project   # remove project hooks
```

## Windows

```powershell
& ([scriptblock]::Create((irm https://raw.githubusercontent.com/fireravenai/fireraven-agent-hooks/refs/heads/main/install.ps1))) -Agent github-copilot
```

Project install:

```powershell
powershell -ExecutionPolicy Bypass -File .\install.ps1 -Agent github-copilot -Project
```

If `py -3` is unavailable in the Copilot hook environment, edit `fireraven-fireguard.json` to use `run_github_copilot_guardrail.ps1` for the `powershell` field.
