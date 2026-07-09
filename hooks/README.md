# Fireraven Agent Hook Scripts

Installed to each agent's hooks directory (e.g. `~/.codeium/windsurf/hooks/`).

## Entry scripts

| Script | Agent | Invoked by |
|--------|-------|------------|
| `windsurf_guardrail.py` | Windsurf / Devin | `hooks.json` pre/post events |
| `cursor_guardrail.py` | Cursor | `hooks.json` before* events |
| `run_cursor_guardrail.ps1` | Cursor on Windows | Optional raw-stdin PowerShell fallback |
| `claude_guardrail.py` | Claude Code | `settings.json` PreToolUse + UserPromptSubmit |
| `github_copilot_guardrail.py` | GitHub Copilot | `fireraven-fireguard.json` userPromptSubmitted / preToolUse / postToolUse |
| `run_github_copilot_guardrail.ps1` | GitHub Copilot on Windows | Optional raw-stdin PowerShell fallback |
| `fireraven_input_guardrail.py` | Windsurf | Backward-compatible alias |

## Install

```bash
curl -fsSL https://raw.githubusercontent.com/fireravenai/fireraven-agent-hooks/refs/heads/main/install.sh | sh
```

Windows PowerShell:

```powershell
irm https://raw.githubusercontent.com/fireravenai/fireraven-agent-hooks/refs/heads/main/install.ps1 | iex
& ([scriptblock]::Create((irm https://raw.githubusercontent.com/fireravenai/fireraven-agent-hooks/refs/heads/main/install.ps1))) -Agent cursor
```

## Configure

After install, edit `config.env` in the agent's hooks directory. Restart the IDE after changes.

| Agent | `config.env` path |
|-------|-------------------|
| Cursor | `~/.cursor/hooks/config.env` |
| Windsurf / Devin | `~/.codeium/windsurf/hooks/config.env` |
| Claude Code | `~/.claude/hooks/config.env` |
| GitHub Copilot | `~/.copilot/hooks/fireraven/config.env` or `.github/hooks/fireraven/config.env` (project) |

**Required:**

```env
FIRERAVEN_GUARDRAILS_API_KEY=<your-api-key>
FIRERAVEN_PROJECT_ID=<your-project-id>
```

**Optional:**

```env
FIRERAVEN_API_URL=https://api.fireraven.ai
FIRERAVEN_EXECUTION_MODE=normal
FIRERAVEN_REQUEST_TIMEOUT_SEC=15
FIRERAVEN_FAIL_MODE=open
```

### `FIRERAVEN_EXECUTION_MODE`

| Value | Default | Behavior |
|-------|---------|----------|
| `fast` | | Lower latency. FireGuard runs eligible checks in parallel and returns as soon as a blocking result is known. |
| `normal` | yes | Full sequential checks with complete policy and security details. |

### `FIRERAVEN_FAIL_MODE`

| Value | Default | Behavior |
|-------|---------|----------|
| `closed` | | Block the agent action when the hook cannot reach FireGuard (network, timeout, or HTTP error). |
| `open` | yes | Allow the action through on transient FireGuard API failures. Policy violations and missing credentials still block. |

See [config.example.env](config.example.env) for inline comments.

## Manual test (Windsurf)

```bash
echo '{"agent_action_name":"pre_user_prompt","trajectory_id":"test-001","tool_info":{"user_prompt":"hello"}}' \
  | python3 windsurf_guardrail.py
echo "exit: $?"
```

PowerShell:

```powershell
'{"agent_action_name":"pre_user_prompt","trajectory_id":"test-001","tool_info":{"user_prompt":"hello"}}' | py -3 .\windsurf_guardrail.py
$LASTEXITCODE
```

## Manual test (Cursor)

Cursor hooks must print a JSON decision to stdout. With `config.env` present, `beforeSubmitPrompt` should return `{"continue":true}` or `{"continue":false,...}`. Other Cursor events should return `{"permission":"allow"}` or `{"permission":"deny",...}`.

```bash
echo '{"hook_event_name":"beforeSubmitPrompt","conversation_id":"test-001","prompt":"hello"}' \
  | python3 cursor_guardrail.py
```

PowerShell:

```powershell
'{"hook_event_name":"beforeSubmitPrompt","conversation_id":"test-001","prompt":"hello"}' | py -3 .\cursor_guardrail.py
```

## Manual test (Claude Code)

Claude Code hooks deny via exit code 2. `PreToolUse` screens tool calls; `UserPromptSubmit` screens typed prompts before Claude processes them.

```bash
echo '{"session_id":"test-001","tool_name":"Bash","tool_input":{"command":"echo hi"}}' \
  | python3 claude_guardrail.py

echo '{"session_id":"test-001","hook_event_name":"UserPromptSubmit","prompt":"hello"}' \
  | python3 claude_guardrail.py
```

PowerShell:

```powershell
'{"session_id":"test-001","tool_name":"Bash","tool_input":{"command":"echo hi"}}' | py -3 .\claude_guardrail.py

'{"session_id":"test-001","hook_event_name":"UserPromptSubmit","prompt":"hello"}' | py -3 .\claude_guardrail.py
```

Fallback wrapper from `%USERPROFILE%\.cursor`:

```powershell
'{"hook_event_name":"beforeSubmitPrompt","conversation_id":"test-001","prompt":"hello"}' | powershell -NoProfile -ExecutionPolicy Bypass -File hooks\run_cursor_guardrail.ps1
```

## Windows runtime notes

- Cursor on Windows should launch hooks with `py -3 hooks/cursor_guardrail.py` from `%USERPROFILE%\.cursor`. Use `powershell -NoProfile -ExecutionPolicy Bypass -File hooks/run_cursor_guardrail.ps1` only as a fallback if `py` is unavailable to Cursor.
- Devin/Windsurf on Windows should use Cascade's `powershell` hook field with a direct Python invocation, not only the Unix `command` field.
- The Windows user-level hook directories are `%USERPROFILE%\.cursor\hooks\` for Cursor and `%USERPROFILE%\.codeium\windsurf\hooks\` for Devin/Windsurf.
- Restart the IDE after changing `hooks.json` or `config.env`.

## Layout after install

```
~/.codeium/windsurf/hooks/
├── core/                  # shared API client, session store
├── adapters/              # per-IDE dispatch logic
├── windsurf_guardrail.py  # entry script
├── run_cursor_guardrail.ps1 # Cursor Windows fallback wrapper
├── config.env             # credentials (chmod 600)
└── state/                 # session cache (conversation_id, input_id)
```

On Windows, the same package layout is installed under:

```text
%USERPROFILE%\.codeium\windsurf\hooks\
%USERPROFILE%\.cursor\hooks\
```
