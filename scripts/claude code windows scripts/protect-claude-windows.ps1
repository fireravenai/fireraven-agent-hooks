<#
.SYNOPSIS
  Lock Claude Code hooks + settings.json so a non-admin user cannot modify or delete them.

.DESCRIPTION
  Run as Administrator. Takes ownership as Administrators and sets ACLs so the target
  user can READ/EXECUTE hooks and READ settings.json, but cannot edit or delete them
  without elevating (UAC / admin password).

  Writable exceptions (required for Claude Code + FireGuard):
  - %USERPROFILE%\.claude\hooks\state\     (FireGuard session cache)
  - Other %USERPROFILE%\.claude\* children (projects, history, plugins, caches, …)
  - New files the user creates under .claude (via CREATOR OWNER)

  The .claude directory itself is left without DELETE_CHILD for the user so they
  cannot bypass file ACLs by deleting settings.json or the hooks folder from Explorer.

.EXAMPLE
  powershell -ExecutionPolicy Bypass -File .\protect-claude-windows.ps1

.EXAMPLE
  powershell -ExecutionPolicy Bypass -File .\protect-claude-windows.ps1 -TargetUser jsmith
#>

param(
    [string]$TargetUser = ""
)

$ErrorActionPreference = "Stop"

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

function Get-EmployeeProfilePath {
    param([string]$UserName)

    $localUser = Get-LocalUser -Name $UserName -ErrorAction SilentlyContinue
    if (-not $localUser) {
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

function Invoke-Native {
    param(
        [string]$FilePath,
        [string[]]$Arguments,
        [string]$Label
    )

    # Native tools write "Access is denied" to stderr; with $ErrorActionPreference=Stop,
    # capturing 2>&1 turns that into a terminating ErrorRecord. Keep going and check exit code.
    $prevEap = $ErrorActionPreference
    $ErrorActionPreference = "Continue"
    try {
        $out = & $FilePath @Arguments 2>&1 | ForEach-Object { "$_" }
    }
    finally {
        $ErrorActionPreference = $prevEap
    }

    $code = $LASTEXITCODE
    $text = ($out -join " ").Trim()
    if ($code -ne 0) {
        Write-Warn "$FilePath $Label exited $code : $text"
    }
    return $code
}

function Invoke-Icacls {
    param(
        [string[]]$Arguments,
        [string]$Label
    )
    return Invoke-Native -FilePath "icacls.exe" -Arguments $Arguments -Label $Label
}

function Invoke-Takeown {
    param(
        [string[]]$Arguments,
        [string]$Label
    )
    return Invoke-Native -FilePath "takeown.exe" -Arguments $Arguments -Label $Label
}

function Protect-FileReadOnly {
    param(
        [string]$Path,
        [string]$AccountName
    )

    if (-not (Test-Path -LiteralPath $Path)) {
        throw "Missing path to protect: $Path"
    }

    Write-Info "Protecting file (read-only for user): $Path"
    Invoke-Takeown -Arguments @("/F", $Path, "/A") -Label $Path | Out-Null
    # Grant Admin/SYSTEM first, then strip inheritance — never leave an empty DACL mid-flight.
    Invoke-Icacls -Arguments @(
        $Path,
        "/grant:r", "Administrators:F",
        "/grant:r", "SYSTEM:F",
        "/grant:r", "${AccountName}:R"
    ) -Label "grant $Path" | Out-Null
    Invoke-Icacls -Arguments @($Path, "/inheritance:r") -Label "inheritance $Path" | Out-Null
    Invoke-Icacls -Arguments @(
        $Path,
        "/grant:r", "Administrators:F",
        "/grant:r", "SYSTEM:F",
        "/grant:r", "${AccountName}:R"
    ) -Label "re-grant $Path" | Out-Null
}

function Protect-HooksTree {
    param(
        [string]$HooksDir,
        [string]$StateDir,
        [string]$AccountName
    )

    if (-not (Test-Path -LiteralPath $HooksDir)) {
        throw "Missing hooks directory: $HooksDir"
    }

    if (-not (Test-Path -LiteralPath $StateDir)) {
        New-Item -ItemType Directory -Path $StateDir -Force | Out-Null
        Write-Info "Created state dir: $StateDir"
    }

    Write-Info "Protecting hooks tree (RX for user): $HooksDir"
    Invoke-Takeown -Arguments @("/F", $HooksDir, "/A", "/R", "/D", "Y") -Label $HooksDir | Out-Null
    Invoke-Icacls -Arguments @(
        $HooksDir,
        "/grant:r", "Administrators:(OI)(CI)F",
        "/grant:r", "SYSTEM:(OI)(CI)F",
        "/T", "/C", "/Q"
    ) -Label "pre-grant admin $HooksDir" | Out-Null
    Invoke-Icacls -Arguments @($HooksDir, "/inheritance:r", "/T", "/C", "/Q") -Label "inheritance $HooksDir" | Out-Null
    Invoke-Icacls -Arguments @(
        $HooksDir,
        "/grant:r", "Administrators:(OI)(CI)F",
        "/grant:r", "SYSTEM:(OI)(CI)F",
        "/grant:r", "${AccountName}:(OI)(CI)RX",
        "/T", "/C", "/Q"
    ) -Label "grant $HooksDir" | Out-Null

    # FireGuard must write session state; keep this subtree user-modifiable.
    Write-Info "Allowing user modify on state: $StateDir"
    Invoke-Icacls -Arguments @(
        $StateDir,
        "/grant:r", "Administrators:(OI)(CI)F",
        "/grant:r", "SYSTEM:(OI)(CI)F",
        "/grant:r", "${AccountName}:(OI)(CI)M",
        "/T", "/C", "/Q"
    ) -Label "grant $StateDir" | Out-Null
    Invoke-Icacls -Arguments @($StateDir, "/inheritance:r", "/T", "/C", "/Q") -Label "inheritance $StateDir" | Out-Null
    Invoke-Icacls -Arguments @(
        $StateDir,
        "/grant:r", "Administrators:(OI)(CI)F",
        "/grant:r", "SYSTEM:(OI)(CI)F",
        "/grant:r", "${AccountName}:(OI)(CI)M",
        "/T", "/C", "/Q"
    ) -Label "re-grant $StateDir" | Out-Null
    Invoke-Icacls -Arguments @($StateDir, "/setowner", $AccountName, "/T", "/C", "/Q") -Label "owner $StateDir" | Out-Null
}

function Protect-ClaudeParent {
    param(
        [string]$ClaudeDir,
        [string]$HooksDir,
        [string]$AccountName
    )

    Write-Info "Hardening .claude parent (no DELETE_CHILD for user): $ClaudeDir"
    Invoke-Takeown -Arguments @("/F", $ClaudeDir, "/A") -Label $ClaudeDir | Out-Null
    # Keep existing inherited ACEs, then stop further inheritance so we can shape the user ACE.
    Invoke-Icacls -Arguments @($ClaudeDir, "/inheritance:d") -Label "inheritance $ClaudeDir" | Out-Null

    # Drop prior explicit grants for this user on the directory object, then re-add tightly.
    Invoke-Icacls -Arguments @($ClaudeDir, "/remove:g", $AccountName) -Label "remove $AccountName" | Out-Null
    # RX = list/read/traverse; W = create files/folders (does not include delete-child).
    Invoke-Icacls -Arguments @(
        $ClaudeDir,
        "/grant:r", "Administrators:(OI)(CI)F",
        "/grant:r", "SYSTEM:(OI)(CI)F",
        "/grant:r", "${AccountName}:(RX,W)",
        "/grant", "CREATOR OWNER:(OI)(CI)(IO)F"
    ) -Label "grant $ClaudeDir" | Out-Null

    # Claude Code (and plugins) need full modify under their own subtrees — everything
    # except the protected hooks folder.
    Get-ChildItem -LiteralPath $ClaudeDir -Force -ErrorAction SilentlyContinue | ForEach-Object {
        if ($_.FullName -ieq $HooksDir) {
            return
        }
        if ($_.PSIsContainer) {
            Write-Info "Allowing user modify on $($_.FullName)"
            Invoke-Icacls -Arguments @(
                $_.FullName,
                "/grant:r", "${AccountName}:(OI)(CI)M",
                "/T", "/C", "/Q"
            ) -Label "grant $($_.Name)" | Out-Null
        }
        else {
            # Root-level runtime files (history.jsonl, caches, …)
            if ($_.Name -ieq "settings.json") {
                return
            }
            Invoke-Icacls -Arguments @(
                $_.FullName,
                "/grant:r", "${AccountName}:M",
                "/C", "/Q"
            ) -Label "grant $($_.Name)" | Out-Null
        }
    }
}

# --- main --------------------------------------------------------------------

if (-not (Test-IsAdministrator)) {
    throw "This script must be run as Administrator (elevated PowerShell)."
}

if (-not $TargetUser) {
    $TargetUser = $env:USERNAME
}

$accountName = Get-AccountName -UserName $TargetUser
$employeeHome = Get-EmployeeProfilePath -UserName $TargetUser
$claudeDir = Join-Path $employeeHome ".claude"
$hooksDir = Join-Path $claudeDir "hooks"
$stateDir = Join-Path $hooksDir "state"
$settingsJson = Join-Path $claudeDir "settings.json"

Write-Info "Target user: $TargetUser ($accountName)"
Write-Info "Claude dir: $claudeDir"

if (-not (Test-Path -LiteralPath $claudeDir)) {
    throw "Claude dir not found: $claudeDir. Install/deploy hooks first."
}
if (-not (Test-Path -LiteralPath $settingsJson)) {
    throw "settings.json not found: $settingsJson. Install/deploy hooks first."
}
if (-not (Test-Path -LiteralPath $hooksDir)) {
    throw "hooks dir not found: $hooksDir. Install/deploy hooks first."
}

# Lock targets first, then harden the parent (avoids locking ourselves out mid-flight).
Protect-FileReadOnly -Path $settingsJson -AccountName $accountName
Protect-HooksTree -HooksDir $hooksDir -StateDir $stateDir -AccountName $accountName
Protect-ClaudeParent -ClaudeDir $claudeDir -HooksDir $hooksDir -AccountName $accountName

Write-Host ""
Write-Info "Protection applied for $TargetUser"
Write-Info "Locked: $settingsJson"
Write-Info "Locked: $hooksDir  (except state\ which stays writable)"
Write-Info "Claude Code can still write projects\, history, plugins, caches under .claude"
Write-Info "User/Claude cannot edit settings.json or hook scripts without admin elevation."
Write-Info "To reverse: run unprotect-claude-windows.ps1 as Administrator."
Write-Host ""
