# windsurf-fireguard-hooks

Fireraven [FireGuard](https://doc.fireraven.ai/) input guardrails for [Windsurf Cascade](https://docs.devin.ai/desktop/cascade/hooks). A `pre_user_prompt` hook checks every user message against your FireGuard project before Cascade runs.

## Quick install

```bash
curl -fsSL https://raw.githubusercontent.com/fireravenai/windsurf-fireguard-hooks/refs/heads/main/install.sh | sh
```

Pin a branch or tag:

```bash
FIRERAVEN_HOOKS_REF=v1.0.0 curl -fsSL https://raw.githubusercontent.com/fireravenai/windsurf-fireguard-hooks/refs/heads/main/install.sh | sh
```

## Prerequisites

- **curl** — used by the remote installer
- **python3** — on your PATH; the hook runs as `python3 …/fireraven_input_guardrail.py`
- A FireGuard project with input policies and/or security guardrails
- FireGuard **API key** and **project ID** (Project Settings in the Fireraven app)

## Post-install

1. Open `~/.codeium/windsurf/hooks/config.env` and set:

   ```env
   FIRERAVEN_GUARDRAILS_API_KEY=<your-api-key>
   FIRERAVEN_PROJECT_ID=<your-project-id>
   ```

2. **Restart Windsurf** so `~/.codeium/windsurf/hooks.json` is reloaded.

Hook files are installed under `~/.codeium/windsurf/hooks/`. See [hooks/README.md](hooks/README.md) for behavior, testing, and configuration details.

## Environment variables (install)

| Variable | Default | Description |
|----------|---------|-------------|
| `FIRERAVEN_INSTALL_DIR` | `$HOME/.codeium/windsurf` | Windsurf config directory |
| `FIRERAVEN_HOOKS_REPO` | `fireravenai/windsurf-fireguard-hooks` | GitHub repository |
| `FIRERAVEN_HOOKS_REF` | `main` | Branch or tag for raw downloads |

## Local development

Clone this repo and install from your working tree:

```bash
./scripts/install-local.sh
```

Use a separate install root for smoke tests:

```bash
FIRERAVEN_INSTALL_DIR=/tmp/fireraven-hooks-test ./scripts/install-local.sh
```

## Uninstall

From a clone of this repository:

```bash
./uninstall.sh
```

This removes the hook entry from `hooks.json`, deletes shipped hook files under `hooks/`, and leaves `config.env` in place (it may contain secrets). Restart Windsurf after uninstalling.

Remote uninstall:

```bash
curl -fsSL https://raw.githubusercontent.com/fireravenai/windsurf-fireguard-hooks/refs/heads/main/uninstall.sh | sh
```

## Publishing checklist

Before tagging or announcing a release on `main`:

- [ ] `hooks/fireraven_input_guardrail.py` is executable and Python 3 stdlib only
- [ ] `hooks/config.example.env` documents all supported variables
- [ ] `hooks/README.md` matches install paths and testing steps
- [ ] `install.sh` downloads `scripts/lib.sh` and all files in `HOOK_FILES` from `lib.sh`
- [ ] Run `FIRERAVEN_INSTALL_DIR=/tmp/fireraven-hooks-test ./scripts/install-local.sh` and verify `hooks.json` + hook files
- [ ] Confirm curl one-liner works against the published `main` branch (after push)
- [ ] Do not commit `hooks/config.env` or real API keys

## License

See repository defaults; hook script is intended for use with Fireraven FireGuard accounts.
