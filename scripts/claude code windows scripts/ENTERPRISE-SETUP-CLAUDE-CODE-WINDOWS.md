# Fireraven Guardrails for Claude Code on Windows — Enterprise Setup

This guide walks an IT / security admin through connecting **Fireraven FireGuard** guardrails to employee **Claude Code** instances on Windows.

These steps and requirements can be adapted to the client’s environment. For full product and integration details, see [doc.fireraven.ai](https://doc.fireraven.ai).

| Resource | URL |
|----------|-----|
| Fireraven platform | [app.fireraven.ai](https://app.fireraven.ai) |
| Documentation | [doc.fireraven.ai](https://doc.fireraven.ai) |
| Agent hooks repository | [github.com/fireravenai/fireraven-agent-hooks](https://github.com/fireravenai/fireraven-agent-hooks) |

> **Scope of this guide:** Windows 11+ employee PCs, Claude Code (CLI or VS Code chat). Linux and macOS are supported by the same hooks project, but use different installers — not covered here.

---

## Requirements

### Client / IT admin

- Access to create and manage a Fireraven account, organization, projects, API keys, and policies at [app.fireraven.ai](https://app.fireraven.ai)
- Ability to run PowerShell on each employee computer (**Administrator** and/or standard user sessions, as needed)
- A record of each employee’s Fireraven **project ID** and the organization **API key** (store securely)

### Employee computers

| Requirement | Notes |
|-------------|--------|
| **Windows 11+** | Target environment for these scripts |
| **Python 3+** | Must be available in the session that runs the deploy script (`py -3 --version` or `python --version`). Machine-wide install is recommended for admin deploys |
| **Claude Code** | Accessible via CLI and/or the VS Code Claude Code chat interface |
| **Network** | Outbound HTTPS to the Fireraven API (default `https://api.fireraven.ai`) |
| **User profile** | Employee has logged in at least once so `C:\Users\<username>` exists |
| **Non-admin employee (recommended)** | Employees should not be local administrators. Combined with `protect-claude-windows.ps1`, this prevents them from removing or editing guardrail hooks without an admin |

### Scripts in this folder

| Script | Purpose | Elevation |
|--------|---------|-----------|
| `deploy-claude-windows.ps1` | Install hooks, write credentials, smoke-test FireGuard | Admin **or** non-admin (if installing into the current user’s own profile and Python is available) |
| `protect-claude-windows.ps1` | Lock hooks / settings so a non-admin cannot modify or delete them | **Administrator required** |
| `unprotect-claude-windows.ps1` | Undo the lock (for updates or uninstall) | **Administrator required** |

---

## Concepts (organization vs project)

On the Fireraven platform:

- An **organization** is a workspace for the company (or for an organizational unit). It contains multiple projects and shares org-level settings such as API keys and policies.
- A **project** represents one AI agent, or one **instance** of an agent for a given employee.
  - Example: a multi-agent workflow → one project per agent.
  - Example: employees using Claude Code → **one project per employee Claude Code instance**, so usage and guardrail decisions can be monitored per person.

---

## Step-by-step setup

### 1. Create a Fireraven account

1. Go to [app.fireraven.ai](https://app.fireraven.ai)
2. Sign up / sign in

### 2. Create an organization

1. Create an **organization** for the company (or one per business unit)
2. This organization will hold all employee projects and shared policies

### 3. Create a project per employee

1. For each employee who will use Claude Code, create a **project** in that organization
2. Name projects clearly (for example `ClaudeCode john@company.com`) so they map to people later
3. **Save each project ID** — you will pass it to the deploy script on that employee’s PC

> Projects can also be created programmatically. This guide assumes **manual** creation in the UI.

### 4. Create and save an organization API key

1. In the organization settings, create an **API key**
2. Store it securely (password manager / secrets vault)
3. You may reuse the **same org API key** for every employee, or issue different keys if your security model requires it
4. Each deploy still uses that employee’s unique **project ID**

### 5. Deploy guardrails on each employee computer

On the employee PC:

1. Confirm **Python 3+** works in the PowerShell session you will use
2. Confirm Claude Code is installed for that employee
3. Get the scripts from this repository (`scripts/claude code windows scripts/`), or from your internal distribution package
4. Run `deploy-claude-windows.ps1` with:
   - `-TargetUser` = the Windows profile folder name under `C:\Users\<HERE>`
   - `-ApiKey` = organization API key
   - `-ProjectId` = that employee’s Fireraven project ID

**Example:**

```powershell
powershell -ExecutionPolicy Bypass -File .\deploy-claude-windows.ps1 `
  -TargetUser "EMPLOYEE USER" `
  -ApiKey "YOUR_ORG_API_KEY" `
  -ProjectId "EMPLOYEE_PROJECT_ID"
```

You can also edit the **CONFIG** block at the top of the script and run it without parameters.

What the deploy script does:

1. Installs Fireraven Claude Code hooks under `C:\Users\<TargetUser>\.claude\`
2. Writes `hooks\config.env` with the API key and project ID
3. Registers hooks in `settings.json` (merges with existing Claude Code settings; does not wipe the whole Claude setup)
4. Smoke-tests FireGuard with a `hello world` prompt
5. On success, ask the employee to **restart Claude Code** (or start a new session)

### 6. (Recommended) Lock hooks so employees cannot remove them

If employees are **non-admin**, run this **as Administrator** after a successful deploy:

```powershell
powershell -ExecutionPolicy Bypass -File .\protect-claude-windows.ps1 `
  -TargetUser "EMPLOYEE USER"
```

This locks the guardrail hooks and related settings so only a computer **administrator** can unlock or change them. Non-admin employees can still use Claude Code normally; they cannot delete or edit the Fireraven hooks to bypass guardrails.

To unlock later (updates, uninstall, or troubleshooting):

```powershell
powershell -ExecutionPolicy Bypass -File .\unprotect-claude-windows.ps1 `
  -TargetUser "EMPLOYEE USER"
```

> Run **unprotect** before re-deploying or upgrading hooks if files are locked; then deploy again; then **protect** again.

### 7. Confirm the connection

After deploy (and restart of Claude Code):

- Claude Code for that employee is linked to Fireraven via the org API key + employee project ID
- A successful smoke test / first guarded prompt should appear as activity on that project in [app.fireraven.ai](https://app.fireraven.ai)

### 8. Configure policies on the Fireraven platform

1. Open the **Policies** page in [app.fireraven.ai](https://app.fireraven.ai)
2. Review **default policies** already provided by Fireraven in the environment
3. Create or adjust any additional policies required by the company
4. Policies are enforced through the installed guardrails on each employee’s Claude Code — no need to reinstall hooks when only policy content changes

---

## Recommended rollout checklist (per employee)

- [ ] Fireraven org exists; API key saved
- [ ] Project created for this employee; project ID saved
- [ ] Employee profile exists (`C:\Users\<username>`)
- [ ] Python 3+ available on the PC
- [ ] Claude Code available (CLI and/or VS Code)
- [ ] `deploy-claude-windows.ps1` succeeded (including smoke test)
- [ ] Employee restarted Claude Code
- [ ] (Optional) `protect-claude-windows.ps1` run as Administrator
- [ ] Policies configured / verified in the Fireraven Policies page

---

## Notes and adaptations

- Instructions and scripts can be adjusted for domain join, Intune/MDM packaging, different API URLs, or automated project provisioning
- Keep API keys out of shared tickets and chat; prefer a secrets vault
- For other coding agents (Cursor, Windsurf/Devin, GitHub Copilot, Copilot Studio), see the main [repository README](https://github.com/fireravenai/fireraven-agent-hooks) and [doc.fireraven.ai](https://doc.fireraven.ai)
- Linux / macOS installs use `install.sh` / `./fg` rather than these Windows enterprise scripts

---

## Quick reference — script examples

```powershell
# Deploy (org API key + employee project ID)
powershell -ExecutionPolicy Bypass -File .\deploy-claude-windows.ps1 `
  -TargetUser "EMPLOYEE USER" `
  -ApiKey "YOUR_ORG_API_KEY" `
  -ProjectId "EMPLOYEE_PROJECT_ID"

# Lock hooks (Administrator)
powershell -ExecutionPolicy Bypass -File .\protect-claude-windows.ps1 `
  -TargetUser "EMPLOYEE USER"

# Unlock hooks (Administrator)
powershell -ExecutionPolicy Bypass -File .\unprotect-claude-windows.ps1 `
  -TargetUser "EMPLOYEE USER"
```
