<#
.SYNOPSIS
  Remove ACL locks from Claude Code hooks + settings.json (undo protect-claude-windows.ps1).

.DESCRIPTION
  Run as Administrator. Restores normal user ownership and Modify rights on
  %USERPROFILE%\.claude\settings.json and %USERPROFILE%\.claude\hooks\, and
  re-enables inherited ACLs on .claude so the employee can edit/delete again.

.EXAMPLE
  powershell -ExecutionPolicy Bypass -File .\unprotect-claude-windows.ps1

.EXAMPLE
  powershell -ExecutionPolicy Bypass -File .\unprotect-claude-windows.ps1 -TargetUser jsmith
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

function Restore-PathAcls {
    param(
        [string]$Path,
        [string]$AccountName,
        [switch]$Recurse
    )

    if (-not (Test-Path -LiteralPath $Path)) {
        Write-Warn "Skip missing path: $Path"
        return
    }

    Write-Info "Restoring ACLs: $Path"
    if ($Recurse) {
        Invoke-Takeown -Arguments @("/F", $Path, "/A", "/R", "/D", "Y") -Label $Path | Out-Null
        Invoke-Icacls -Arguments @($Path, "/grant:r", "Administrators:(OI)(CI)F", "/T", "/C", "/Q") -Label "pre-grant $Path" | Out-Null
        Invoke-Icacls -Arguments @($Path, "/setowner", $AccountName, "/T", "/C", "/Q") -Label "owner $Path" | Out-Null
        Invoke-Icacls -Arguments @($Path, "/reset", "/T", "/C", "/Q") -Label "reset $Path" | Out-Null
        Invoke-Icacls -Arguments @(
            $Path,
            "/grant", "${AccountName}:(OI)(CI)M",
            "/T", "/C", "/Q"
        ) -Label "grant $Path" | Out-Null
    }
    else {
        Invoke-Takeown -Arguments @("/F", $Path, "/A") -Label $Path | Out-Null
        Invoke-Icacls -Arguments @($Path, "/grant:r", "Administrators:F") -Label "pre-grant $Path" | Out-Null
        Invoke-Icacls -Arguments @($Path, "/setowner", $AccountName, "/C", "/Q") -Label "owner $Path" | Out-Null
        Invoke-Icacls -Arguments @($Path, "/reset", "/C", "/Q") -Label "reset $Path" | Out-Null
        Invoke-Icacls -Arguments @($Path, "/grant", "${AccountName}:M", "/C", "/Q") -Label "grant $Path" | Out-Null
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
$settingsJson = Join-Path $claudeDir "settings.json"

Write-Info "Target user: $TargetUser ($accountName)"
Write-Info "Claude dir: $claudeDir"

if (-not (Test-Path -LiteralPath $claudeDir)) {
    throw "Claude dir not found: $claudeDir"
}

# Parent first so children can re-inherit cleanly.
Write-Info "Re-enabling inheritance on .claude"
Invoke-Takeown -Arguments @("/F", $claudeDir, "/A") -Label $claudeDir | Out-Null
Invoke-Icacls -Arguments @($claudeDir, "/grant:r", "Administrators:(OI)(CI)F") -Label "pre-grant $claudeDir" | Out-Null
Invoke-Icacls -Arguments @($claudeDir, "/setowner", $accountName, "/C", "/Q") -Label "owner $claudeDir" | Out-Null
Invoke-Icacls -Arguments @($claudeDir, "/inheritance:e") -Label "inheritance $claudeDir" | Out-Null
Invoke-Icacls -Arguments @($claudeDir, "/grant", "${accountName}:(OI)(CI)M", "/C", "/Q") -Label "grant $claudeDir" | Out-Null

Restore-PathAcls -Path $settingsJson -AccountName $accountName
Restore-PathAcls -Path $hooksDir -AccountName $accountName -Recurse

Write-Host ""
Write-Info "Protection removed for $TargetUser"
Write-Info "Restored: $settingsJson"
Write-Info "Restored: $hooksDir"
Write-Info "User can modify/delete these paths again without elevation."
Write-Host ""
