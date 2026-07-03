param(
    [ValidateSet("windsurf", "cursor", "claude", "github-copilot", "copilot", "all")]
    [string]$Agent = $(if ($env:FIRERAVEN_AGENT) { $env:FIRERAVEN_AGENT } else { "all" }),
    [switch]$Project,
    [string]$HooksRepo = $(if ($env:FIRERAVEN_HOOKS_REPO) { $env:FIRERAVEN_HOOKS_REPO } else { "fireravenai/fireraven-agent-hooks" }),
    [string]$HooksRef = $(if ($env:FIRERAVEN_HOOKS_REF) { $env:FIRERAVEN_HOOKS_REF } else { "main" })
)

$ErrorActionPreference = "Stop"

$FireravenEntryPattern = "fireraven|windsurf_guardrail\.py|cursor_guardrail\.py|run_cursor_guardrail\.ps1|claude_guardrail\.py|fireraven_input_guardrail\.py|github_copilot_guardrail\.py|run_github_copilot_guardrail\.ps1"
$WindsurfEvents = @("pre_user_prompt", "pre_run_command", "pre_mcp_tool_use", "pre_write_code", "pre_read_code", "post_cascade_response", "post_write_code")
$CursorEvents = @("beforeSubmitPrompt", "beforeShellExecution", "beforeMCPExecution", "beforeReadFile")
$GitHubCopilotEvents = @("userPromptSubmitted", "preToolUse", "postToolUse")

function Write-Info {
    param([string]$Message)
    Write-Host "[INFO] $Message" -ForegroundColor Green
}

function Write-Warn {
    param([string]$Message)
    Write-Host "[WARN] $Message" -ForegroundColor Yellow
}

function Get-UserHome {
    if ($env:USERPROFILE) {
        return $env:USERPROFILE
    }
    return [Environment]::GetFolderPath("UserProfile")
}

function Get-WindsurfInstallDir {
    if ($env:FIRERAVEN_INSTALL_DIR) {
        return $env:FIRERAVEN_INSTALL_DIR
    }
    return (Join-Path (Get-UserHome) ".codeium\windsurf")
}

function Get-CursorInstallDir {
    if ($env:FIRERAVEN_CURSOR_INSTALL_DIR) {
        return $env:FIRERAVEN_CURSOR_INSTALL_DIR
    }
    return (Join-Path (Get-UserHome) ".cursor")
}

function Get-ClaudeInstallDir {
    if ($env:FIRERAVEN_CLAUDE_INSTALL_DIR) {
        return $env:FIRERAVEN_CLAUDE_INSTALL_DIR
    }
    return (Join-Path (Get-UserHome) ".claude")
}

function Get-GitHubCopilotInstallDir {
    if ($env:FIRERAVEN_GITHUB_COPILOT_INSTALL_DIR) {
        return $env:FIRERAVEN_GITHUB_COPILOT_INSTALL_DIR
    }
    return (Join-Path (Get-UserHome) ".copilot")
}

function Get-GitHubCopilotHooksJson { Join-Path (Get-GitHubCopilotInstallDir) "hooks\fireraven-fireguard.json" }
function Get-GitHubCopilotProjectHooksJson { Join-Path (Get-Location) ".github\hooks\fireraven-fireguard.json" }

function Scrub-GitHubCopilotHooks {
    param(
        [hashtable]$PythonCommand,
        [string]$RawBase,
        [string]$HooksJson
    )

    if (-not (Test-Path $HooksJson)) {
        return
    }

    Invoke-MergeHooksConfig -PythonCommand $pythonCommand -RawBase $rawBase -Arguments @(
        "scrub-github-copilot",
        "--path", $HooksJson,
        "--events", ($GitHubCopilotEvents -join " "),
        "--owned-pattern", $FireravenEntryPattern
    )
}

function Test-CommandWorks {
    param(
        [string]$FilePath,
        [string[]]$ArgumentList
    )
    try {
        $process = Start-Process -FilePath $FilePath -ArgumentList ($ArgumentList + @("--version")) -NoNewWindow -PassThru -Wait -RedirectStandardOutput ([IO.Path]::GetTempFileName()) -RedirectStandardError ([IO.Path]::GetTempFileName())
        return ($process.ExitCode -eq 0)
    }
    catch {
        return $false
    }
}

function Get-PythonCommand {
    $candidates = @(
        @{ FilePath = "py"; Arguments = @("-3") },
        @{ FilePath = "python"; Arguments = @() },
        @{ FilePath = "python3"; Arguments = @() }
    )

    foreach ($candidate in $candidates) {
        if (Get-Command $candidate.FilePath -ErrorAction SilentlyContinue) {
            if (Test-CommandWorks -FilePath $candidate.FilePath -ArgumentList $candidate.Arguments) {
                return $candidate
            }
        }
    }

    throw "Python 3 is required. Install Python from https://www.python.org/downloads/windows/ and make sure it is on PATH."
}

function Get-LocalRepoRoot {
    if (-not $PSScriptRoot) {
        return $null
    }
    if ((Test-Path (Join-Path $PSScriptRoot "core")) -and (Test-Path (Join-Path $PSScriptRoot "hooks"))) {
        return $PSScriptRoot
    }
    return $null
}

function Download-File {
    param(
        [string]$Url,
        [string]$Destination
    )
    New-Item -ItemType Directory -Force -Path (Split-Path -Parent $Destination) | Out-Null
    Invoke-WebRequest -UseBasicParsing -Uri $Url -OutFile $Destination
}

function Get-MergeHooksScriptsDir {
    param([string]$RawBase)

    $repoRoot = Get-LocalRepoRoot
    if ($repoRoot) {
        $scriptsDir = Join-Path $repoRoot "scripts"
        if (Test-Path (Join-Path $scriptsDir "merge_hooks_config.py")) {
            return $scriptsDir
        }
    }

    $dir = Join-Path $env:TEMP "fireraven-agent-hooks-scripts"
    New-Item -ItemType Directory -Force -Path $dir | Out-Null
    foreach ($file in @("jsonc_modify.py", "merge_hooks_config.py")) {
        Download-File -Url "$RawBase/scripts/$file" -Destination (Join-Path $dir $file)
    }
    return $dir
}

function Invoke-MergeHooksConfig {
    param(
        [hashtable]$PythonCommand,
        [string]$RawBase,
        [string[]]$Arguments
    )

    $scriptsDir = Get-MergeHooksScriptsDir -RawBase $RawBase
    $scriptPath = Join-Path $scriptsDir "merge_hooks_config.py"
    $command = @($PythonCommand.FilePath) + @($PythonCommand.Arguments) + @($scriptPath) + $Arguments
    & $command[0] $command[1..($command.Length - 1)]
    if ($LASTEXITCODE -ne 0) {
        throw "merge_hooks_config.py failed"
    }
}

$pythonCommand = Get-PythonCommand
$rawBase = "https://raw.githubusercontent.com/$HooksRepo/refs/heads/$HooksRef"

Write-Info "Uninstalling Fireraven hooks (agent=$Agent)"

switch ($Agent) {
    "all" {
        Invoke-MergeHooksConfig -PythonCommand $pythonCommand -RawBase $rawBase -Arguments @(
            "scrub-windsurf",
            "--path", (Join-Path (Get-WindsurfInstallDir) "hooks.json"),
            "--events", ($WindsurfEvents -join " "),
            "--owned-pattern", $FireravenEntryPattern
        )
        Invoke-MergeHooksConfig -PythonCommand $pythonCommand -RawBase $rawBase -Arguments @(
            "scrub-cursor",
            "--path", (Join-Path (Get-CursorInstallDir) "hooks.json"),
            "--events", ($CursorEvents -join " "),
            "--owned-pattern", $FireravenEntryPattern
        )
        Invoke-MergeHooksConfig -PythonCommand $pythonCommand -RawBase $rawBase -Arguments @(
            "scrub-claude",
            "--path", (Join-Path (Get-ClaudeInstallDir) "settings.json"),
            "--owned-pattern", $FireravenEntryPattern
        )
        Scrub-GitHubCopilotHooks -PythonCommand $pythonCommand -RawBase $rawBase -HooksJson (Get-GitHubCopilotHooksJson)
        if ($Project) {
            Scrub-GitHubCopilotHooks -PythonCommand $pythonCommand -RawBase $rawBase -HooksJson (Get-GitHubCopilotProjectHooksJson)
        }
        Write-Info "Copilot Studio uses connector topics in adapters/copilot/ (see README)"
    }
    "windsurf" {
        Invoke-MergeHooksConfig -PythonCommand $pythonCommand -RawBase $rawBase -Arguments @(
            "scrub-windsurf",
            "--path", (Join-Path (Get-WindsurfInstallDir) "hooks.json"),
            "--events", ($WindsurfEvents -join " "),
            "--owned-pattern", $FireravenEntryPattern
        )
    }
    "cursor" {
        Invoke-MergeHooksConfig -PythonCommand $pythonCommand -RawBase $rawBase -Arguments @(
            "scrub-cursor",
            "--path", (Join-Path (Get-CursorInstallDir) "hooks.json"),
            "--events", ($CursorEvents -join " "),
            "--owned-pattern", $FireravenEntryPattern
        )
    }
    "claude" {
        Invoke-MergeHooksConfig -PythonCommand $pythonCommand -RawBase $rawBase -Arguments @(
            "scrub-claude",
            "--path", (Join-Path (Get-ClaudeInstallDir) "settings.json"),
            "--owned-pattern", $FireravenEntryPattern
        )
    }
    "github-copilot" {
        Scrub-GitHubCopilotHooks -PythonCommand $pythonCommand -RawBase $rawBase -HooksJson (Get-GitHubCopilotHooksJson)
        if ($Project) {
            Scrub-GitHubCopilotHooks -PythonCommand $pythonCommand -RawBase $rawBase -HooksJson (Get-GitHubCopilotProjectHooksJson)
        }
    }
    "copilot" {
        Write-Info "Copilot Studio uses connector topics in adapters/copilot/ (see README)"
    }
}

Write-Warn "config.env files were not removed (may contain secrets)"
Write-Info "Restart your IDE(s) to apply changes"
