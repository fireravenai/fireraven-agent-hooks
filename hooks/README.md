# Fireraven Agent Hook Scripts

Installed to each agent's hooks directory (e.g. `~/.codeium/windsurf/hooks/`).

## Entry scripts

| Script | Agent | Invoked by |
|--------|-------|------------|
| `windsurf_guardrail.py` | Windsurf / Devin | `hooks.json` pre/post events |
| `cursor_guardrail.py` | Cursor | `hooks.json` before* events |
| `claude_guardrail.py` | Claude Code | `settings.json` PreToolUse |
| `fireraven_input_guardrail.py` | Windsurf | Backward-compatible alias |

## Install

```bash
curl -fsSL https://raw.githubusercontent.com/fireravenai/fireraven-agent-hooks/refs/heads/main/install.sh | sh
```

## Manual test (Windsurf)

```bash
echo '{"agent_action_name":"pre_user_prompt","trajectory_id":"test-001","tool_info":{"user_prompt":"hello"}}' \
  | python3 windsurf_guardrail.py
echo "exit: $?"
```

## Layout after install

```
~/.codeium/windsurf/hooks/
├── core/                  # shared API client, session store
├── adapters/              # per-IDE dispatch logic
├── windsurf_guardrail.py  # entry script
├── config.env             # credentials (chmod 600)
└── state/                 # session cache (conversation_id, input_id)
```
