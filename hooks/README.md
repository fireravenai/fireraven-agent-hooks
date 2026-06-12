# Fireraven FireGuard Input Guardrail Hook

[Cascade Hooks](https://docs.devin.ai/desktop/cascade/hooks) script that runs **Fireraven FireGuard input guardrails** on every user prompt before Cascade processes it.

Registered from `~/.codeium/windsurf/hooks.json` via the `pre_user_prompt` event.

## Install (recommended)

From any machine with `curl` and `python3`:

```bash
curl -fsSL https://raw.githubusercontent.com/fireravenai/windsurf-fireguard-hooks/refs/heads/main/install.sh | sh
```

Optional environment variables:

| Variable | Default | Description |
|----------|---------|-------------|
| `FIRERAVEN_INSTALL_DIR` | `$HOME/.codeium/windsurf` | Windsurf config root |
| `FIRERAVEN_HOOKS_REPO` | `fireravenai/windsurf-fireguard-hooks` | GitHub `owner/repo` |
| `FIRERAVEN_HOOKS_REF` | `main` | Branch or tag |

The installer copies hook files into `~/.codeium/windsurf/hooks/`, creates `config.env` from the template if missing, and merges the hook into `hooks.json`.

## How it works

```
User prompt → pre_user_prompt hook → FireGuard API → allow or block
```

1. Cascade invokes `pre_user_prompt` and passes hook context as JSON on stdin.
2. The hook maps the Cascade `trajectory_id` to a FireGuard conversation via `conversation_copilot`.
3. The hook calls `input_guardrails` with the current user message.
4. If `is_safe` is `true`, the prompt proceeds. Otherwise the hook exits with code `2` and Cascade shows the block message from stderr.

On API errors, missing config, or timeouts, the hook **fails closed** (prompt is blocked).

## Files

```
~/.codeium/windsurf/
├── hooks.json
└── hooks/
    ├── README.md
    ├── fireraven_input_guardrail.py    # Hook script (Python 3, stdlib only)
    ├── config.example.env              # Config template
    └── config.env                      # Your credentials (chmod 600; do not commit)
```

## Prerequisites

1. A [FireGuard](https://doc.fireraven.ai/) project with input policies and/or security guardrails configured.
2. A FireGuard API key (Project Settings → API).
3. Your FireGuard project ID (Project Settings → General).
4. Python 3 on your PATH (used as `python3`).

## Post-install configuration

1. Edit `~/.codeium/windsurf/hooks/config.env` (created on first install):

   ```env
   FIRERAVEN_GUARDRAILS_API_KEY=<your-api-key>
   FIRERAVEN_PROJECT_ID=<your-project-id>
   ```

2. Restart Windsurf so Cascade reloads `hooks.json`.

If you installed manually, ensure `hooks.json` includes:

```json
{
  "hooks": {
    "pre_user_prompt": [
      {
        "command": "python3 ~/.codeium/windsurf/hooks/fireraven_input_guardrail.py"
      }
    ]
  }
}
```

Use the full path to your home directory (tilde expansion depends on how Windsurf invokes the command; the installer writes an absolute path).

## Configuration

| Variable | Required | Default | Description |
|----------|----------|---------|-------------|
| `FIRERAVEN_GUARDRAILS_API_KEY` | Yes | — | FireGuard API key |
| `FIRERAVEN_PROJECT_ID` | Yes | — | FireGuard project ID |
| `FIRERAVEN_API_URL` | No | `https://api.fireraven.ai` | API base URL |
| `FIRERAVEN_EXECUTION_MODE` | No | `fast` | `fast` or `normal` |
| `FIRERAVEN_REQUEST_TIMEOUT_SEC` | No | `15` | HTTP timeout in seconds |

Values can also be set as environment variables (config file takes precedence for keys present in both).

## Testing

Run the hook manually with mock Cascade input (from the installed hooks directory):

```bash
cd ~/.codeium/windsurf/hooks
echo '{"agent_action_name":"pre_user_prompt","trajectory_id":"test-001","tool_info":{"user_prompt":"What is the weather today?"}}' \
  | python3 fireraven_input_guardrail.py
echo "exit code: $?"
```

| Scenario | Expected exit code |
|----------|-------------------|
| Safe prompt | `0` |
| Policy/security violation | `2` (violation message on stderr) |
| Missing or invalid API key | `2` (fail closed) |
| Empty / whitespace prompt | `0` (skipped) |

In Cascade, submit a benign prompt (should proceed) and a prompt that violates a configured policy (should block with a FireGuard message). Conversations appear in the FireGuard monitoring dashboard, keyed by Cascade `trajectory_id`.

## API reference

- [Cascade Hooks](https://docs.devin.ai/desktop/cascade/hooks)
- [FireGuard Guardrails API](https://doc.fireraven.ai/)
- [fireguard-demo-python](https://github.com/fireravenai/fireguard-demo-python)

## Notes

- v1 sends only the current user message in `messages_history` (no multi-turn cache). Security guardrails and most input policies work with this; multi-turn policy context can be added later via a `post_cascade_response` history cache.
- Output guardrails are not included; `post_cascade_response` hooks cannot block agent output, only audit it.
