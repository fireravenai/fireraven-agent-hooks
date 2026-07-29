<#
.SYNOPSIS
  Enterprise Windows deploy: install FireRaven Claude Code guardrails into an employee user profile.

.DESCRIPTION
  Run as Administrator on the employee PC. Edits the CONFIG block (or pass -TargetUser /
  -ApiKey / -ProjectId), then installs hooks under that user's %USERPROFILE%\.claude,
  writes credentials, fixes ACLs so the employee can use them, and smoke-tests FireGuard
  with a "hello world" UserPromptSubmit.

.EXAMPLE
  # 1) Edit the CONFIG block below, then:
  powershell -ExecutionPolicy Bypass -File .\deploy-claude-windows.ps1

.EXAMPLE
  powershell -ExecutionPolicy Bypass -File .\deploy-claude-windows.ps1 `
    -TargetUser jsmith -ApiKey "frk_..." -ProjectId "proj_..."
#>

param(
    [string]$TargetUser = "",
    [string]$ApiKey = "",
    [string]$ProjectId = "",
    [string]$ApiUrl = "",
    [ValidateSet("open", "closed")]
    [string]$FailMode = "",
    [ValidateSet("fast", "normal")]
    [string]$ExecutionMode = "",
    [string]$HooksRepo = "",
    [string]$HooksRef = "",
    [switch]$SkipSmokeTest
)

$ErrorActionPreference = "Stop"

# =============================================================================
# CONFIG - edit these before running (CLI params override these values)
# =============================================================================
$Config = @{
    # Windows local account name of the employee (non-admin is fine)
    TargetUser    = "EMPLOYEE_WINDOWS_USERNAME"

    # FireGuard org API key (same for all employees, or per-employee if you prefer)
    ApiKey        = "YOUR_ORG_API_KEY"

    # FireGuard project ID unique to this employee
    ProjectId     = "EMPLOYEE_PROJECT_ID"

    # Optional overrides
    ApiUrl        = "https://api.fireraven.ai"
    FailMode      = "open"      # open | closed
    ExecutionMode = "normal"    # fast | normal
    HooksRepo     = "fireravenai/fireraven-agent-hooks"
    HooksRef      = "main"
}
# =============================================================================

function Write-Info {
    param([string]$Message)
    Write-Host "[INFO] $Message" -ForegroundColor Green
}

function Write-Warn {
    param([string]$Message)
    Write-Host "[WARN] $Message" -ForegroundColor Yellow
}

function Write-Err {
    param([string]$Message)
    Write-Host "[ERROR] $Message" -ForegroundColor Red
}

function Test-IsAdministrator {
    $identity = [Security.Principal.WindowsIdentity]::GetCurrent()
    $principal = New-Object Security.Principal.WindowsPrincipal($identity)
    return $principal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)
}

function Resolve-ConfigValue {
    param(
        [string]$ParamValue,
        [string]$ConfigValue,
        [string]$Name,
        [string[]]$Placeholders = @()
    )

    $value = if ($ParamValue) { $ParamValue.Trim() } else { "$ConfigValue".Trim() }
    if (-not $value) {
        throw "Missing required value: $Name. Set it in the CONFIG block or pass -$Name."
    }
    foreach ($placeholder in $Placeholders) {
        if ($value -eq $placeholder) {
            throw "Replace placeholder $Name ('$placeholder') in the CONFIG block or pass -$Name."
        }
    }
    return $value
}

function Get-EmployeeProfilePath {
    param([string]$UserName)

    $localUser = Get-LocalUser -Name $UserName -ErrorAction SilentlyContinue
    if (-not $localUser) {
        # Domain / Azure AD accounts may not appear in Get-LocalUser; still require a profile folder.
        Write-Warn "Local user '$UserName' not found via Get-LocalUser; checking profile folder anyway."
    }

    $profilePath = Join-Path $env:SystemDrive "Users\$UserName"
    if (-not (Test-Path -LiteralPath $profilePath)) {
        throw "Employee profile not found: $profilePath. Log in once as $UserName so Windows creates the profile, then re-run."
    }
    return (Resolve-Path -LiteralPath $profilePath).Path
}

function Get-AccountName {
    param([string]$UserName)

    try {
        $nt = New-Object System.Security.Principal.NTAccount($UserName)
        [void]$nt.Translate([type][System.Security.Principal.SecurityIdentifier])
        return $UserName
    }
    catch {
        $qualified = "$env:COMPUTERNAME\$UserName"
        $nt = New-Object System.Security.Principal.NTAccount($qualified)
        [void]$nt.Translate([type][System.Security.Principal.SecurityIdentifier])
        return $qualified
    }
}

function Set-EmployeeAcl {
    param(
        [string]$Path,
        [string]$AccountName
    )

    if (-not (Test-Path -LiteralPath $Path)) {
        return
    }

    Write-Info "Granting $AccountName access to $Path"
    # Grant modify on the tree; keep existing inherited rights for SYSTEM/Administrators.
    & icacls.exe $Path /grant "${AccountName}:(OI)(CI)M" /T /C /Q | Out-Null
    if ($LASTEXITCODE -ne 0) {
        Write-Warn "icacls grant returned exit code $LASTEXITCODE for $Path"
    }

    & icacls.exe $Path /setowner $AccountName /T /C /Q 2>$null | Out-Null
}

function Write-ConfigEnv {
    param(
        [string]$DestinationDir,
        [string]$ApiKey,
        [string]$ProjectId,
        [string]$ApiUrl,
        [string]$FailMode,
        [string]$ExecutionMode
    )

    $configEnv = Join-Path $DestinationDir "config.env"
    $lines = @(
        "# Written by deploy-claude-windows.ps1 - do not commit secrets",
        "FIRERAVEN_GUARDRAILS_API_KEY=$ApiKey",
        "FIRERAVEN_PROJECT_ID=$ProjectId",
        "FIRERAVEN_API_URL=$ApiUrl",
        "FIRERAVEN_EXECUTION_MODE=$ExecutionMode",
        "FIRERAVEN_FAIL_MODE=$FailMode"
    )
    # UTF-8 without BOM (Python config parser / hooks expect plain text)
    $utf8NoBom = New-Object System.Text.UTF8Encoding $false
    [System.IO.File]::WriteAllText($configEnv, (($lines -join "`n") + "`n"), $utf8NoBom)
    Write-Info "Wrote credentials to $configEnv"
}

function Invoke-Installer {
    param(
        [string]$ClaudeInstallDir,
        [string]$HooksRepo,
        [string]$HooksRef
    )

    $env:FIRERAVEN_CLAUDE_INSTALL_DIR = $ClaudeInstallDir
    $env:FIRERAVEN_HOOKS_REPO = $HooksRepo
    $env:FIRERAVEN_HOOKS_REF = $HooksRef
    $env:FIRERAVEN_AGENT = "claude"

    $localInstaller = $null
    if ($PSScriptRoot) {
        $candidate = Join-Path $PSScriptRoot "install.ps1"
        if (Test-Path -LiteralPath $candidate) {
            $localInstaller = $candidate
        }
    }

    if ($localInstaller) {
        Write-Info "Running local installer: $localInstaller"
        & powershell.exe -NoProfile -ExecutionPolicy Bypass -File $localInstaller -Agent claude -HooksRepo $HooksRepo -HooksRef $HooksRef
        if ($LASTEXITCODE -ne 0) {
            throw "install.ps1 failed with exit code $LASTEXITCODE"
        }
        return
    }

    $rawUrl = "https://raw.githubusercontent.com/$HooksRepo/refs/heads/$HooksRef/install.ps1"
    $tempInstaller = Join-Path $env:TEMP "fireraven-install-$HooksRef.ps1"
    Write-Info "Downloading installer from $rawUrl"
    Invoke-WebRequest -UseBasicParsing -Uri $rawUrl -OutFile $tempInstaller
    & powershell.exe -NoProfile -ExecutionPolicy Bypass -File $tempInstaller -Agent claude -HooksRepo $HooksRepo -HooksRef $HooksRef
    if ($LASTEXITCODE -ne 0) {
        throw "Downloaded install.ps1 failed with exit code $LASTEXITCODE"
    }
}

function Test-PythonInvocation {
    param(
        [string]$FilePath,
        [string[]]$Arguments = @()
    )

    if (-not (Test-Path -LiteralPath $FilePath)) {
        return $false
    }
    try {
        $argList = @($Arguments) + @("--version")
        $out = [IO.Path]::GetTempFileName()
        $err = [IO.Path]::GetTempFileName()
        $p = Start-Process -FilePath $FilePath -ArgumentList $argList `
            -NoNewWindow -PassThru -Wait `
            -RedirectStandardOutput $out `
            -RedirectStandardError $err
        return ($p.ExitCode -eq 0)
    }
    catch {
        return $false
    }
}

function Get-PythonCommand {
    param([string]$EmployeeHome = "")

    # PATH names first (works when Python is machine-wide or on this session's PATH).
    $pathCandidates = @(
        @{ FilePath = "py"; Arguments = @("-3") },
        @{ FilePath = "python"; Arguments = @() },
        @{ FilePath = "python3"; Arguments = @() }
    )
    foreach ($candidate in $pathCandidates) {
        $cmd = Get-Command $candidate.FilePath -ErrorAction SilentlyContinue
        if (-not $cmd) {
            continue
        }
        if (Test-PythonInvocation -FilePath $cmd.Source -Arguments $candidate.Arguments) {
            return @{ FilePath = $cmd.Source; Arguments = $candidate.Arguments }
        }
    }

    # Elevated admin shells often miss per-user PATH. Probe known install locations
    # for the employee (and the current user as fallback).
    $homes = @()
    if ($EmployeeHome) { $homes += $EmployeeHome }
    if ($env:USERPROFILE -and ($homes -notcontains $env:USERPROFILE)) {
        $homes += $env:USERPROFILE
    }

    foreach ($home in $homes) {
        $launcher = Join-Path $home "AppData\Local\Programs\Python\Launcher\py.exe"
        if (Test-PythonInvocation -FilePath $launcher -Arguments @("-3")) {
            Write-Info "Using per-user Python launcher: $launcher"
            return @{ FilePath = $launcher; Arguments = @("-3") }
        }

        $pythonRoot = Join-Path $home "AppData\Local\Programs\Python"
        if (Test-Path -LiteralPath $pythonRoot) {
            $exes = Get-ChildItem -LiteralPath $pythonRoot -Filter "python.exe" -Recurse -ErrorAction SilentlyContinue |
                Where-Object { $_.FullName -notmatch '\\WindowsApps\\' } |
                Sort-Object FullName -Descending
            foreach ($exe in $exes) {
                if (Test-PythonInvocation -FilePath $exe.FullName) {
                    Write-Info "Using per-user Python: $($exe.FullName)"
                    return @{ FilePath = $exe.FullName; Arguments = @() }
                }
            }
        }
    }

    foreach ($machineDir in @(
            "${env:ProgramFiles}\Python*",
            "${env:ProgramFiles(x86)}\Python*",
            "${env:LocalAppData}\Programs\Python\Python*"
        )) {
        foreach ($dir in (Get-Item $machineDir -ErrorAction SilentlyContinue)) {
            $exe = Join-Path $dir.FullName "python.exe"
            if (Test-PythonInvocation -FilePath $exe) {
                return @{ FilePath = $exe; Arguments = @() }
            }
        }
    }

    throw @"
Python 3 was not found for this elevated/admin session.

Your Python is likely installed only for the employee user (under AppData), so an Administrator shell cannot see it on PATH.

Fix (pick one):
  1. Reinstall Python from https://www.python.org/downloads/windows/ for All Users, with 'Add python.exe to PATH'
  2. Or run this deploy script from a normal (non-admin) PowerShell when TargetUser is your own account
"@
}

function Invoke-HelloWorldSmokeTest {
    param(
        [string]$HooksDir,
        [hashtable]$PythonCommand
    )

    $scriptPath = Join-Path $HooksDir "claude_guardrail.py"
    if (-not (Test-Path -LiteralPath $scriptPath)) {
        throw "Missing hook script after install: $scriptPath"
    }

    $sessionId = "fireraven-deploy-smoke-" + (Get-Date -Format "yyyyMMddHHmmss")
    $payload = @{
        session_id      = $sessionId
        hook_event_name = "UserPromptSubmit"
        prompt          = "hello world"
    } | ConvertTo-Json -Compress

    Write-Info "Smoke-testing FireGuard with UserPromptSubmit 'hello world' (session $sessionId)"

    $psi = New-Object System.Diagnostics.ProcessStartInfo
    $psi.FileName = $PythonCommand.FilePath
    $psi.Arguments = (($PythonCommand.Arguments + @($scriptPath)) | ForEach-Object {
            if ($_ -match '\s') { '"' + ($_ -replace '"', '\"') + '"' } else { $_ }
        }) -join " "
    $psi.WorkingDirectory = $HooksDir
    $psi.UseShellExecute = $false
    $psi.RedirectStandardInput = $true
    $psi.RedirectStandardOutput = $true
    $psi.RedirectStandardError = $true
    $psi.CreateNoWindow = $true

    $proc = New-Object System.Diagnostics.Process
    $proc.StartInfo = $psi
    [void]$proc.Start()
    $proc.StandardInput.Write($payload)
    $proc.StandardInput.Close()
    $stdout = $proc.StandardOutput.ReadToEnd()
    $stderr = $proc.StandardError.ReadToEnd()
    if (-not $proc.WaitForExit(120000)) {
        try { $proc.Kill() } catch { }
        throw "Smoke test timed out after 120s waiting for FireGuard."
    }
    $exitCode = $proc.ExitCode

    if ($stdout) {
        Write-Host $stdout
    }
    if ($stderr) {
        Write-Host $stderr -ForegroundColor Yellow
    }

    $statePath = Join-Path $HooksDir "state\$sessionId.json"
    if ($exitCode -ne 0) {
        throw "Smoke test failed (exit $exitCode). Check API key, project ID, and network access to the FireGuard API."
    }
    if (-not (Test-Path -LiteralPath $statePath)) {
        throw "Smoke test exited 0 but wrote no session state at $statePath. With FIRERAVEN_FAIL_MODE=open this usually means the API call failed - verify credentials and connectivity."
    }

    $state = Get-Content -Raw -LiteralPath $statePath | ConvertFrom-Json
    if (-not $state.conversation_id) {
        throw "Smoke test state file is missing conversation_id - FireGuard did not accept the session."
    }

    Write-Info "Smoke test OK - conversation_id=$($state.conversation_id)"
    Write-Info "A 'hello world' check should appear in the FireGuard dashboard for this project."
}

# --- main --------------------------------------------------------------------

$targetUser = Resolve-ConfigValue -ParamValue $TargetUser -ConfigValue $Config.TargetUser `
    -Name "TargetUser" -Placeholders @("EMPLOYEE_WINDOWS_USERNAME")
$apiKey = Resolve-ConfigValue -ParamValue $ApiKey -ConfigValue $Config.ApiKey `
    -Name "ApiKey" -Placeholders @("YOUR_ORG_API_KEY")
$projectId = Resolve-ConfigValue -ParamValue $ProjectId -ConfigValue $Config.ProjectId `
    -Name "ProjectId" -Placeholders @("EMPLOYEE_PROJECT_ID")

$apiUrl = if ($ApiUrl) { $ApiUrl.Trim() } elseif ($Config.ApiUrl) { "$($Config.ApiUrl)".Trim() } else { "https://api.fireraven.ai" }
$failMode = if ($FailMode) { $FailMode } elseif ($Config.FailMode) { "$($Config.FailMode)" } else { "open" }
$executionMode = if ($ExecutionMode) { $ExecutionMode } elseif ($Config.ExecutionMode) { "$($Config.ExecutionMode)" } else { "normal" }
$hooksRepo = if ($HooksRepo) { $HooksRepo.Trim() } elseif ($Config.HooksRepo) { "$($Config.HooksRepo)".Trim() } else { "fireravenai/fireraven-agent-hooks" }
$hooksRef = if ($HooksRef) { $HooksRef.Trim() } elseif ($Config.HooksRef) { "$($Config.HooksRef)".Trim() } else { "main" }

if (-not (Test-IsAdministrator)) {
    Write-Warn "Not running as Administrator. Installing into another user's profile usually requires elevation."
}

$employeeHome = Get-EmployeeProfilePath -UserName $targetUser
$accountName = Get-AccountName -UserName $targetUser
$claudeDir = Join-Path $employeeHome ".claude"
$hooksDir = Join-Path $claudeDir "hooks"

Write-Info "Target user: $targetUser ($accountName)"
Write-Info "Employee profile: $employeeHome"
Write-Info "Claude install dir: $claudeDir"
Write-Info "Project ID: $projectId"

$pythonCommand = Get-PythonCommand -EmployeeHome $employeeHome
Write-Info ("Using Python: " + ((@($pythonCommand.FilePath) + @($pythonCommand.Arguments)) -join " "))

# So nested install.ps1 (and py -3 hook registration checks) see Python even in elevated shells.
$pythonDir = Split-Path -Parent $pythonCommand.FilePath
if ($env:PATH -notlike "*$pythonDir*") {
    $env:PATH = "$pythonDir;$env:PATH"
}
$launcherDir = Join-Path $employeeHome "AppData\Local\Programs\Python\Launcher"
if ((Test-Path -LiteralPath $launcherDir) -and ($env:PATH -notlike "*$launcherDir*")) {
    $env:PATH = "$launcherDir;$env:PATH"
}

Invoke-Installer -ClaudeInstallDir $claudeDir -HooksRepo $hooksRepo -HooksRef $hooksRef

if (-not (Test-Path -LiteralPath $hooksDir)) {
    throw "Install finished but hooks directory is missing: $hooksDir"
}

Write-ConfigEnv -DestinationDir $hooksDir `
    -ApiKey $apiKey `
    -ProjectId $projectId `
    -ApiUrl $apiUrl `
    -FailMode $failMode `
    -ExecutionMode $executionMode

Set-EmployeeAcl -Path $claudeDir -AccountName $accountName

$settingsJson = Join-Path $claudeDir "settings.json"
if (-not (Test-Path -LiteralPath $settingsJson)) {
    throw "Claude settings.json was not created: $settingsJson"
}
$settingsRaw = Get-Content -Raw -LiteralPath $settingsJson
if ($settingsRaw -notmatch "claude_guardrail\.py") {
    throw "Claude settings.json does not reference claude_guardrail.py - hook registration failed."
}
Write-Info "Claude Code hooks registered in $settingsJson"

if (-not $SkipSmokeTest) {
    Invoke-HelloWorldSmokeTest -HooksDir $hooksDir -PythonCommand $pythonCommand
}
else {
    Write-Warn "Skipped smoke test (-SkipSmokeTest)"
}

Write-Host ""
Write-Info "Deploy complete for $targetUser"
Write-Info "Ask the employee to restart Claude Code (or open a new session)."
Write-Info "Credentials: $hooksDir\config.env"
Write-Host ""
