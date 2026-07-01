param(
    [ValidateSet("windsurf", "cursor", "claude", "copilot", "all")]
    [string]$Agent = $(if ($env:FIRERAVEN_AGENT) { $env:FIRERAVEN_AGENT } else { "windsurf" }),
    [string]$HooksRepo = $(if ($env:FIRERAVEN_HOOKS_REPO) { $env:FIRERAVEN_HOOKS_REPO } else { "fireravenai/fireraven-agent-hooks" }),
    [string]$HooksRef = $(if ($env:FIRERAVEN_HOOKS_REF) { $env:FIRERAVEN_HOOKS_REF } else { "main" })
)

$ErrorActionPreference = "Stop"

$Marker = "fireraven"
$WindsurfScript = "windsurf_guardrail.py"
$CursorScript = "cursor_guardrail.py"
$ClaudeScript = "claude_guardrail.py"
$WindsurfPreEvents = @("pre_user_prompt", "pre_run_command", "pre_mcp_tool_use", "pre_write_code", "pre_read_code")
$WindsurfPostEvents = @("post_cascade_response", "post_write_code")
$CursorEvents = @("beforeSubmitPrompt", "beforeShellExecution", "beforeMCPExecution", "beforeReadFile")
$FireravenEntryPattern = "fireraven|windsurf_guardrail\.py|cursor_guardrail\.py|run_cursor_guardrail\.ps1|claude_guardrail\.py|fireraven_input_guardrail\.py"

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

function Get-WindsurfHooksDir { Join-Path (Get-WindsurfInstallDir) "hooks" }
function Get-CursorHooksDir { Join-Path (Get-CursorInstallDir) "hooks" }
function Get-ClaudeHooksDir { Join-Path (Get-ClaudeInstallDir) "hooks" }

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

function Quote-PowerShellArgument {
    param([string]$Value)
    return "'" + ($Value -replace "'", "''") + "'"
}

function New-PythonInvocation {
    param(
        [hashtable]$PythonCommand,
        [string]$ScriptPath
    )

    $parts = @((Quote-PowerShellArgument $PythonCommand.FilePath))
    foreach ($arg in $PythonCommand.Arguments) {
        $parts += (Quote-PowerShellArgument $arg)
    }
    $parts += (Quote-PowerShellArgument $ScriptPath)
    return "`$input | & " + ($parts -join " ")
}

function New-PowerShellPythonCommand {
    param(
        [hashtable]$PythonCommand,
        [string]$ScriptPath
    )

    $parts = @((Quote-PowerShellArgument $PythonCommand.FilePath))
    foreach ($arg in $PythonCommand.Arguments) {
        $parts += (Quote-PowerShellArgument $arg)
    }
    $parts += (Quote-PowerShellArgument $ScriptPath)
    return "& " + ($parts -join " ")
}

function New-CursorHookCommand {
    param([string]$PythonInvocation)
    $escaped = $PythonInvocation -replace '"', '\"'
    return "powershell -NoProfile -ExecutionPolicy Bypass -Command `"$escaped`""
}

function New-CursorDirectHookCommand {
    return "py -3 hooks/cursor_guardrail.py"
}

function New-PortablePythonCommand {
    param([string]$ScriptPath)
    return "python3 `"$ScriptPath`""
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

function Copy-PackageTree {
    param(
        [string]$SourceRoot,
        [string]$DestinationDir
    )

    New-Item -ItemType Directory -Force -Path $DestinationDir | Out-Null
    foreach ($dir in @("core", "adapters")) {
        $dest = Join-Path $DestinationDir $dir
        if (Test-Path $dest) {
            Remove-Item -Recurse -Force $dest
        }
        Copy-Item -Recurse -Force (Join-Path $SourceRoot $dir) $DestinationDir
    }

    foreach ($file in @("_bootstrap.py", "windsurf_guardrail.py", "cursor_guardrail.py", "run_cursor_guardrail.ps1", "claude_guardrail.py", "fireraven_input_guardrail.py", "config.example.env", "README.md")) {
        $source = Join-Path (Join-Path $SourceRoot "hooks") $file
        if (Test-Path $source) {
            Copy-Item -Force $source (Join-Path $DestinationDir $file)
        }
    }
}

function Download-File {
    param(
        [string]$Url,
        [string]$Destination
    )
    New-Item -ItemType Directory -Force -Path (Split-Path -Parent $Destination) | Out-Null
    Write-Info "Downloading $Url"
    Invoke-WebRequest -UseBasicParsing -Uri $Url -OutFile $Destination
}

function Download-PackageTree {
    param(
        [string]$RawBase,
        [string]$DestinationDir
    )

    New-Item -ItemType Directory -Force -Path $DestinationDir | Out-Null

    foreach ($path in @(
        "core/__init__.py",
        "core/config.py",
        "core/session_store.py",
        "core/fireraven_client.py",
        "core/serializers.py",
        "core/guardrail.py",
        "adapters/__init__.py",
        "adapters/windsurf.py",
        "adapters/cursor.py",
        "adapters/claude.py"
    )) {
        Download-File -Url "$RawBase/$path" -Destination (Join-Path $DestinationDir ($path -replace "/", "\"))
    }

    foreach ($file in @("_bootstrap.py", "windsurf_guardrail.py", "cursor_guardrail.py", "run_cursor_guardrail.ps1", "claude_guardrail.py", "fireraven_input_guardrail.py", "config.example.env", "README.md")) {
        Download-File -Url "$RawBase/hooks/$file" -Destination (Join-Path $DestinationDir $file)
    }
}

function Install-PackageTree {
    param([string]$DestinationDir)

    $repoRoot = Get-LocalRepoRoot
    if ($repoRoot) {
        Write-Info "Installing from local repo: $repoRoot"
        Copy-PackageTree -SourceRoot $repoRoot -DestinationDir $DestinationDir
        return
    }

    $rawBase = "https://raw.githubusercontent.com/$HooksRepo/refs/heads/$HooksRef"
    Download-PackageTree -RawBase $rawBase -DestinationDir $DestinationDir
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
    param(
        [string]$Path,
        [hashtable]$DefaultValue = @{}
    )

    if ((Test-Path $Path) -and ((Get-Item $Path).Length -gt 0)) {
        return ConvertTo-Hashtable ((Get-Content -Raw -Path $Path) | ConvertFrom-Json)
    }
    return $DefaultValue.Clone()
}

function Write-JsonFile {
    param(
        [string]$Path,
        [hashtable]$Data
    )

    New-Item -ItemType Directory -Force -Path (Split-Path -Parent $Path) | Out-Null
    ($Data | ConvertTo-Json -Depth 20) + "`n" | Set-Content -Encoding UTF8 -Path $Path
}

function Ensure-ConfigEnv {
    param([string]$DestinationDir)

    $configEnv = Join-Path $DestinationDir "config.env"
    $exampleEnv = Join-Path $DestinationDir "config.example.env"
    if (Test-Path $configEnv) {
        Write-Info "Keeping existing config: $configEnv"
        return
    }
    if (-not (Test-Path $exampleEnv)) {
        throw "Missing config template: $exampleEnv"
    }
    Copy-Item -Force $exampleEnv $configEnv
    Write-Warn "Created $configEnv - add FIRERAVEN_GUARDRAILS_API_KEY and FIRERAVEN_PROJECT_ID"
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

function Add-HookEntry {
    param(
        [hashtable]$Hooks,
        [string]$Event,
        [hashtable]$Entry
    )

    $entries = @()
    if ($Hooks.ContainsKey($Event)) {
        $entries = Remove-FireravenEntries $Hooks[$Event]
    }
    $entries += $Entry
    $Hooks[$Event] = $entries
}

function Merge-WindsurfHooksJson {
    param(
        [hashtable]$PythonCommand,
        [string]$RawBase
    )

    $hooksJson = Join-Path (Get-WindsurfInstallDir) "hooks.json"
    $scriptPath = Join-Path (Get-WindsurfHooksDir) $WindsurfScript
    $events = ($WindsurfPreEvents + $WindsurfPostEvents) -join " "

    Invoke-MergeHooksConfig -PythonCommand $PythonCommand -RawBase $RawBase -Arguments @(
        "merge-windsurf",
        "--path", $hooksJson,
        "--script-path", $scriptPath,
        "--events", $events,
        "--owned-pattern", $FireravenEntryPattern,
        "--powershell-command", (New-PowerShellPythonCommand -PythonCommand $PythonCommand -ScriptPath $scriptPath)
    )
    Write-Info "Registered Devin/Windsurf hooks in $hooksJson"
}

function Merge-CursorHooksJson {
    param(
        [hashtable]$PythonCommand,
        [string]$RawBase
    )

    $hooksJson = Join-Path (Get-CursorInstallDir) "hooks.json"
    Invoke-MergeHooksConfig -PythonCommand $PythonCommand -RawBase $RawBase -Arguments @(
        "merge-cursor",
        "--path", $hooksJson,
        "--script-path", (Join-Path (Get-CursorHooksDir) $CursorScript),
        "--events", ($CursorEvents -join " "),
        "--owned-pattern", $FireravenEntryPattern,
        "--command", (New-CursorDirectHookCommand)
    )
    Write-Info "Registered Cursor hooks in $hooksJson"
}

function Merge-ClaudeSettingsJson {
    param(
        [hashtable]$PythonCommand,
        [string]$RawBase
    )

    $settingsJson = Join-Path (Get-ClaudeInstallDir) "settings.json"
    $scriptPath = Join-Path (Get-ClaudeHooksDir) $ClaudeScript
    $pythonInvocation = New-PythonInvocation -PythonCommand $PythonCommand -ScriptPath $scriptPath

    Invoke-MergeHooksConfig -PythonCommand $PythonCommand -RawBase $RawBase -Arguments @(
        "merge-claude",
        "--path", $settingsJson,
        "--script-path", $scriptPath,
        "--command", (New-CursorHookCommand -PythonInvocation $pythonInvocation)
    )
    Write-Info "Registered Claude Code hooks in $settingsJson"
}

function Install-Windsurf {
    param(
        [hashtable]$PythonCommand,
        [string]$RawBase
    )
    $destination = Get-WindsurfHooksDir
    Write-Info "Installing Devin/Windsurf hooks to $destination"
    Install-PackageTree -DestinationDir $destination
    Ensure-ConfigEnv -DestinationDir $destination
    Merge-WindsurfHooksJson -PythonCommand $PythonCommand -RawBase $RawBase
}

function Install-Cursor {
    param(
        [hashtable]$PythonCommand,
        [string]$RawBase
    )
    $destination = Get-CursorHooksDir
    Write-Info "Installing Cursor hooks to $destination"
    Install-PackageTree -DestinationDir $destination
    Ensure-ConfigEnv -DestinationDir $destination
    Merge-CursorHooksJson -PythonCommand $PythonCommand -RawBase $RawBase
}

function Install-Claude {
    param(
        [hashtable]$PythonCommand,
        [string]$RawBase
    )
    $destination = Get-ClaudeHooksDir
    Write-Info "Installing Claude Code hooks to $destination"
    Install-PackageTree -DestinationDir $destination
    Ensure-ConfigEnv -DestinationDir $destination
    Merge-ClaudeSettingsJson -PythonCommand $PythonCommand -RawBase $RawBase
}

$pythonCommand = Get-PythonCommand
$pythonText = (@($pythonCommand.FilePath) + @($pythonCommand.Arguments)) -join " "
$rawBase = "https://raw.githubusercontent.com/$HooksRepo/refs/heads/$HooksRef"
Write-Info "Using Python command: $pythonText"
Write-Info "Installing Fireraven agent hooks ($Agent)"

switch ($Agent) {
    "all" {
        Install-Windsurf -PythonCommand $pythonCommand -RawBase $rawBase
        Install-Cursor -PythonCommand $pythonCommand -RawBase $rawBase
        Install-Claude -PythonCommand $pythonCommand -RawBase $rawBase
        Write-Info "Copilot uses connector topics in adapters/copilot/ (no local hook install)"
    }
    "windsurf" { Install-Windsurf -PythonCommand $pythonCommand -RawBase $rawBase }
    "cursor" { Install-Cursor -PythonCommand $pythonCommand -RawBase $rawBase }
    "claude" { Install-Claude -PythonCommand $pythonCommand -RawBase $rawBase }
    "copilot" { Write-Info "Copilot uses connector topics in adapters/copilot/ (no local hook install)" }
}

Write-Host ""
Write-Warn "Edit config.env in each installed hooks directory with FIRERAVEN_* credentials"
Write-Info "Restart your IDE(s) to load hook configuration"
Write-Host ""
