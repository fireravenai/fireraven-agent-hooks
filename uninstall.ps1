param(
    [ValidateSet("windsurf", "cursor", "claude", "copilot", "all")]
    [string]$Agent = $(if ($env:FIRERAVEN_AGENT) { $env:FIRERAVEN_AGENT } else { "all" })
)

$ErrorActionPreference = "Stop"

$FireravenEntryPattern = "fireraven|windsurf_guardrail\.py|cursor_guardrail\.py|run_cursor_guardrail\.ps1|claude_guardrail\.py|fireraven_input_guardrail\.py"
$WindsurfEvents = @("pre_user_prompt", "pre_run_command", "pre_mcp_tool_use", "pre_write_code", "pre_read_code", "post_cascade_response", "post_write_code")
$CursorEvents = @("beforeSubmitPrompt", "beforeShellExecution", "beforeMCPExecution", "beforeReadFile")

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

function ConvertTo-Hashtable {
    param($InputObject)

    if ($null -eq $InputObject) {
        return $null
    }
    if ($InputObject -is [System.Collections.IDictionary]) {
        $hash = @{}
        foreach ($key in $InputObject.Keys) {
            $hash[$key] = ConvertTo-Hashtable $InputObject[$key]
        }
        return $hash
    }
    if (($InputObject -is [System.Collections.IEnumerable]) -and -not ($InputObject -is [string])) {
        $items = @()
        foreach ($item in $InputObject) {
            $items += ConvertTo-Hashtable $item
        }
        return $items
    }
    if ($InputObject -is [pscustomobject]) {
        $hash = @{}
        foreach ($property in $InputObject.PSObject.Properties) {
            $hash[$property.Name] = ConvertTo-Hashtable $property.Value
        }
        return $hash
    }
    return $InputObject
}

function Read-JsonFile {
    param([string]$Path)

    if ((Test-Path $Path) -and ((Get-Item $Path).Length -gt 0)) {
        return ConvertTo-Hashtable ((Get-Content -Raw -Path $Path) | ConvertFrom-Json)
    }
    return $null
}

function Write-JsonFile {
    param(
        [string]$Path,
        [hashtable]$Data
    )

    ($Data | ConvertTo-Json -Depth 20) + "`n" | Set-Content -Encoding UTF8 -Path $Path
}

function Remove-FireravenEntries {
    param($Entries)

    $result = @()
    foreach ($entry in @($Entries)) {
        $serialized = $entry | ConvertTo-Json -Compress -Depth 20
        if ($serialized -notmatch $FireravenEntryPattern) {
            $result += $entry
        }
    }
    return $result
}

function Remove-HookEntries {
    param(
        [string]$Path,
        [string[]]$Events
    )

    $data = Read-JsonFile -Path $Path
    if ($null -eq $data -or -not $data.ContainsKey("hooks") -or $null -eq $data["hooks"]) {
        return
    }

    $hooks = $data["hooks"]
    foreach ($event in $Events) {
        if (-not $hooks.ContainsKey($event)) {
            continue
        }
        $remaining = Remove-FireravenEntries $hooks[$event]
        if ($remaining.Count -gt 0) {
            $hooks[$event] = $remaining
        }
        else {
            $hooks.Remove($event)
        }
    }

    Write-JsonFile -Path $Path -Data $data
}

function Remove-ClaudeHookEntries {
    param([string]$Path)

    $data = Read-JsonFile -Path $Path
    if ($null -eq $data -or -not $data.ContainsKey("hooks") -or $null -eq $data["hooks"]) {
        return
    }

    $hooks = $data["hooks"]
    if (-not $hooks.ContainsKey("PreToolUse")) {
        return
    }

    $remaining = Remove-FireravenEntries $hooks["PreToolUse"]
    if ($remaining.Count -gt 0) {
        $hooks["PreToolUse"] = $remaining
    }
    else {
        $hooks.Remove("PreToolUse")
    }

    Write-JsonFile -Path $Path -Data $data
}

Write-Info "Uninstalling Fireraven hooks (agent=$Agent)"

switch ($Agent) {
    "all" {
        Remove-HookEntries -Path (Join-Path (Get-WindsurfInstallDir) "hooks.json") -Events $WindsurfEvents
        Remove-HookEntries -Path (Join-Path (Get-CursorInstallDir) "hooks.json") -Events $CursorEvents
        Remove-ClaudeHookEntries -Path (Join-Path (Get-ClaudeInstallDir) "settings.json")
        Write-Info "Copilot uses connector topics in adapters/copilot/ (no local hook install)"
    }
    "windsurf" {
        Remove-HookEntries -Path (Join-Path (Get-WindsurfInstallDir) "hooks.json") -Events $WindsurfEvents
    }
    "cursor" {
        Remove-HookEntries -Path (Join-Path (Get-CursorInstallDir) "hooks.json") -Events $CursorEvents
    }
    "claude" {
        Remove-ClaudeHookEntries -Path (Join-Path (Get-ClaudeInstallDir) "settings.json")
    }
    "copilot" {
        Write-Info "Copilot uses connector topics in adapters/copilot/ (no local hook install)"
    }
}

Write-Warn "config.env files were not removed (may contain secrets)"
Write-Info "Restart your IDE(s) to apply changes"
