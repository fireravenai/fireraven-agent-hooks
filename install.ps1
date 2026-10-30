param(
    [ValidateSet("windsurf", "cursor", "claude", "devin", "github-copilot", "copilot", "all")]
    [string]$Agent = $(if ($env:FIRERAVEN_AGENT) { $env:FIRERAVEN_AGENT } else { "windsurf" }),
    [switch]$Project,
    [string]$HooksRepo = $(if ($env:FIRERAVEN_HOOKS_REPO) { $env:FIRERAVEN_HOOKS_REPO } else { "fireravenai/fireraven-agent-hooks" }),
    [string]$HooksRef = $(if ($env:FIRERAVEN_HOOKS_REF) { $env:FIRERAVEN_HOOKS_REF } else { "" }),
    [string]$HooksRawBase = $(if ($env:FIRERAVEN_HOOKS_RAW_BASE) { $env:FIRERAVEN_HOOKS_RAW_BASE } else { "" }),
    [string]$HooksGitlabProject = $(if ($env:FIRERAVEN_HOOKS_GITLAB_PROJECT) { $env:FIRERAVEN_HOOKS_GITLAB_PROJECT } else { "" }),
    [string]$HooksGitlabHost = $(if ($env:FIRERAVEN_HOOKS_GITLAB_HOST) { $env:FIRERAVEN_HOOKS_GITLAB_HOST } else { "https://gitlab.com" }),
    [string]$HooksToken = $(if ($env:FIRERAVEN_HOOKS_TOKEN) { $env:FIRERAVEN_HOOKS_TOKEN } else { "" })
)

$ErrorActionPreference = "Stop"

$Marker = "fireraven"
$WindsurfScript = "windsurf_guardrail.py"
$CursorScript = "cursor_guardrail.py"
$ClaudeScript = "claude_guardrail.py"
$DevinScript = "devin_guardrail.py"
$GitHubCopilotScript = "github_copilot_guardrail.py"
$WindsurfPreEvents = @("pre_user_prompt", "pre_run_command", "pre_mcp_tool_use", "pre_write_code", "pre_read_code")
$WindsurfPostEvents = @("post_cascade_response", "post_write_code")
$CursorEvents = @("beforeSubmitPrompt", "beforeShellExecution", "beforeMCPExecution", "beforeReadFile", "preToolUse", "subagentStart", "afterFileEdit")
$GitHubCopilotEvents = @("userPromptSubmitted", "preToolUse", "postToolUse")
# Markers are literal substrings (not regex) matched against serialized hook entries.
$FireravenEntryPattern = "fireraven|windsurf_guardrail.py|cursor_guardrail.py|run_cursor_guardrail.ps1|claude_guardrail.py|fireraven_input_guardrail.py|github_copilot_guardrail.py|run_github_copilot_guardrail.ps1|devin_guardrail.py"

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

function Get-DevinInstallDir {
    if ($env:FIRERAVEN_DEVIN_INSTALL_DIR) {
        return $env:FIRERAVEN_DEVIN_INSTALL_DIR
    }
    if ($env:APPDATA) {
        return (Join-Path $env:APPDATA "devin")
    }
    return (Join-Path (Get-UserHome) "AppData\Roaming\devin")
}

function Get-GitHubCopilotInstallDir {
    if ($env:FIRERAVEN_GITHUB_COPILOT_INSTALL_DIR) {
        return $env:FIRERAVEN_GITHUB_COPILOT_INSTALL_DIR
    }
    return (Join-Path (Get-UserHome) ".copilot")
}

function Get-WindsurfHooksDir { Join-Path (Get-WindsurfInstallDir) "hooks\fireraven" }
function Get-CursorHooksDir { Join-Path (Get-CursorInstallDir) "hooks\fireraven" }
function Get-ClaudeHooksDir { Join-Path (Get-ClaudeInstallDir) "hooks\fireraven" }
function Get-DevinHooksDir { Join-Path (Get-DevinInstallDir) "hooks\fireraven" }
function Get-GitHubCopilotHooksDir { Join-Path (Get-GitHubCopilotInstallDir) "hooks\fireraven" }
function Get-GitHubCopilotHooksJson { Join-Path (Get-GitHubCopilotInstallDir) "hooks\fireraven-fireguard.json" }
function Get-GitHubCopilotProjectHooksDir { Join-Path (Get-Location) ".github\hooks\fireraven" }
function Get-GitHubCopilotProjectHooksJson { Join-Path (Get-Location) ".github\hooks\fireraven-fireguard.json" }

# Channel state filled by Resolve-Channel
$script:Channel = "github"
$script:RawBase = ""
$script:GitlabHost = ""
$script:GitlabProject = ""
$script:GitlabRef = ""

function Resolve-Channel {
    $script:Channel = "github"
    $script:RawBase = ""
    $script:GitlabHost = ""
    $script:GitlabProject = ""
    $script:GitlabRef = ""

    if ($HooksGitlabProject -and $HooksGitlabProject.Trim()) {
        $script:Channel = "gitlab_api"
        $script:GitlabHost = $HooksGitlabHost.TrimEnd("/")
        $script:GitlabProject = $HooksGitlabProject.Trim()
        $script:GitlabRef = if ($HooksRef) { $HooksRef } else { "dev" }
        if (-not $HooksToken) {
            throw "FIRERAVEN_HOOKS_TOKEN is required for private GitLab installs (PRIVATE-TOKEN)"
        }
        return
    }

    if ($HooksRawBase -and $HooksRawBase.Trim()) {
        $raw = $HooksRawBase.Trim().TrimEnd("/")
        if ($raw -match '^(https?://[^/]+)/(.+)/-/raw/([^/]+)$') {
            $script:Channel = "gitlab_api"
            $script:GitlabHost = $Matches[1]
            $script:GitlabProject = $Matches[2]
            $script:GitlabRef = $Matches[3]
            if (-not $HooksToken) {
                throw "FIRERAVEN_HOOKS_TOKEN is required for private GitLab installs (PRIVATE-TOKEN)"
            }
            return
        }
        $script:Channel = "github"
        $script:RawBase = $raw
        if (-not $HooksRef) { $script:HooksRefLocal = "main" } else { $script:HooksRefLocal = $HooksRef }
        return
    }

    $ref = if ($HooksRef) { $HooksRef } else { "main" }
    $script:Channel = "github"
    $script:RawBase = "https://raw.githubusercontent.com/$HooksRepo/refs/heads/$ref"
    $script:HooksRefLocal = $ref
}

function Get-FileUrl {
    param([string]$Path)
    if ($script:Channel -eq "gitlab_api") {
        $encProject = [uri]::EscapeDataString($script:GitlabProject)
        $encPath = [uri]::EscapeDataString($Path)
        return "$($script:GitlabHost)/api/v4/projects/$encProject/repository/files/$encPath/raw?ref=$($script:GitlabRef)"
    }
    return "$($script:RawBase.TrimEnd('/'))/$Path"
}

function Write-Utf8NoBom {
    param(
        [string]$Path,
        [string]$Content
    )
    $parent = Split-Path -Parent $Path
    if ($parent -and -not (Test-Path -LiteralPath $parent)) {
        New-Item -ItemType Directory -Force -Path $parent | Out-Null
    }
    $utf8NoBom = New-Object System.Text.UTF8Encoding $false
    [System.IO.File]::WriteAllText($Path, $Content, $utf8NoBom)
}

function Write-InstallMeta {
    param(
        [string]$DestinationDir,
        [string]$Agents
    )
    New-Item -ItemType Directory -Force -Path $DestinationDir | Out-Null
    if ($script:Channel -eq "gitlab_api") {
        $meta = @{
            agents      = $Agents
            channel     = "gitlab_api"
            gitlab_host = $script:GitlabHost
            project     = $script:GitlabProject
            ref         = $script:GitlabRef
            raw_base    = ""
        }
    }
    else {
        $ref = if ($script:HooksRefLocal) { $script:HooksRefLocal } elseif ($HooksRef) { $HooksRef } else { "main" }
        $meta = @{
            agents   = $Agents
            channel  = "github"
            raw_base = $script:RawBase
            repo     = $HooksRepo
            ref      = $ref
        }
    }
    $path = Join-Path $DestinationDir "install_meta.json"
    Write-Utf8NoBom -Path $path -Content (($meta | ConvertTo-Json -Depth 5) + "`n")
}

function Ensure-HooksTokenInConfig {
    param([string]$DestinationDir)
    if (-not $HooksToken) { return }
    $configEnv = Join-Path $DestinationDir "config.env"
    if (-not (Test-Path $configEnv)) { return }
    $text = [System.IO.File]::ReadAllText($configEnv)
    if ($text -match '(?m)^FIRERAVEN_HOOKS_TOKEN=') { return }
    if ($text.Length -gt 0 -and -not $text.EndsWith("`n")) {
        $text += "`n"
    }
    $text += "FIRERAVEN_HOOKS_TOKEN=$HooksToken`n"
    Write-Utf8NoBom -Path $configEnv -Content $text
    Write-Info "Wrote FIRERAVEN_HOOKS_TOKEN into $configEnv for update checks"
}

# Toast branding: Start Menu shortcut + AppUserModelID (must match core/unavailable_notice.py).
$script:FireravenToastAumid = "Fireraven.FireGuard"
$script:FireravenToastShortcutName = "Fireraven.lnk"

function Get-FireravenToastShortcutDir {
    $appData = if ($env:APPDATA) { $env:APPDATA } else { Join-Path (Get-UserHome) "AppData\Roaming" }
    return (Join-Path $appData "Microsoft\Windows\Start Menu\Programs\Fireraven")
}

function Find-FireravenToastIcon {
    foreach ($hooksDir in @(
        (Get-CursorHooksDir),
        (Get-WindsurfHooksDir),
        (Get-ClaudeHooksDir),
        (Get-DevinHooksDir),
        (Get-GitHubCopilotHooksDir),
        (Get-GitHubCopilotProjectHooksDir)
    )) {
        $icon = Join-Path $hooksDir "assets\fireraven.ico"
        if (Test-Path -LiteralPath $icon) {
            return $icon
        }
    }
    return $null
}

function Ensure-FireravenShortcutAumidType {
    if ("FireravenShortcutAumid.Creator" -as [type]) {
        return
    }
    Add-Type -TypeDefinition @"
using System;
using System.Runtime.InteropServices;
using System.Text;

namespace FireravenShortcutAumid {
    [ComImport]
    [Guid("00021401-0000-0000-C000-000000000046")]
    public class CShellLink { }

    [ComImport]
    [InterfaceType(ComInterfaceType.InterfaceIsIUnknown)]
    [Guid("000214F9-0000-0000-C000-000000000046")]
    public interface IShellLinkW {
        void GetPath([Out, MarshalAs(UnmanagedType.LPWStr)] StringBuilder pszFile, int cchMaxPath, IntPtr pfd, int fFlags);
        void GetIDList(out IntPtr ppidl);
        void SetIDList(IntPtr pidl);
        void GetDescription([Out, MarshalAs(UnmanagedType.LPWStr)] StringBuilder pszName, int cchMaxName);
        void SetDescription([MarshalAs(UnmanagedType.LPWStr)] string pszName);
        void GetWorkingDirectory([Out, MarshalAs(UnmanagedType.LPWStr)] StringBuilder pszDir, int cchMaxPath);
        void SetWorkingDirectory([MarshalAs(UnmanagedType.LPWStr)] string pszDir);
        void GetArguments([Out, MarshalAs(UnmanagedType.LPWStr)] StringBuilder pszArgs, int cchMaxPath);
        void SetArguments([MarshalAs(UnmanagedType.LPWStr)] string pszArgs);
        void GetHotkey(out short pwHotkey);
        void SetHotkey(short wHotkey);
        void GetShowCmd(out int piShowCmd);
        void SetShowCmd(int iShowCmd);
        void GetIconLocation([Out, MarshalAs(UnmanagedType.LPWStr)] StringBuilder pszIconPath, int cchIconPath, out int piIcon);
        void SetIconLocation([MarshalAs(UnmanagedType.LPWStr)] string pszIconPath, int iIcon);
        void SetRelativePath([MarshalAs(UnmanagedType.LPWStr)] string pszPathRel, int dwReserved);
        void Resolve(IntPtr hwnd, int fFlags);
        void SetPath([MarshalAs(UnmanagedType.LPWStr)] string pszFile);
    }

    [ComImport]
    [InterfaceType(ComInterfaceType.InterfaceIsIUnknown)]
    [Guid("0000010b-0000-0000-C000-000000000046")]
    public interface IPersistFile {
        void GetClassID(out Guid pClassID);
        [PreserveSig] int IsDirty();
        void Load([MarshalAs(UnmanagedType.LPWStr)] string pszFileName, uint dwMode);
        void Save([MarshalAs(UnmanagedType.LPWStr)] string pszFileName, [MarshalAs(UnmanagedType.Bool)] bool fRemember);
        void SaveCompleted([MarshalAs(UnmanagedType.LPWStr)] string pszFileName);
        void GetCurFile([MarshalAs(UnmanagedType.LPWStr)] out string ppszFileName);
    }

    [StructLayout(LayoutKind.Sequential, Pack = 4)]
    public struct PropertyKey {
        public Guid fmtid;
        public uint pid;
    }

    [StructLayout(LayoutKind.Sequential)]
    public struct PropVariant {
        public short vt;
        public short wReserved1;
        public short wReserved2;
        public short wReserved3;
        public IntPtr pointerValue;
    }

    [ComImport]
    [InterfaceType(ComInterfaceType.InterfaceIsIUnknown)]
    [Guid("886D8EEB-8CF2-4446-8D02-CDBA1DBDCF99")]
    public interface IPropertyStore {
        uint GetCount();
        void GetAt(uint iProp, out PropertyKey pkey);
        void GetValue(ref PropertyKey key, out PropVariant pv);
        void SetValue(ref PropertyKey key, ref PropVariant pv);
        void Commit();
    }

    public static class Creator {
        // Create .lnk and set AUMID in one COM session (avoids STG_E_ACCESSDENIED).
        public static void CreateBrandedShortcut(
            string shortcutPath,
            string targetPath,
            string arguments,
            string workingDirectory,
            string description,
            string iconPath,
            string appId
        ) {
            var link = (IShellLinkW)new CShellLink();
            link.SetPath(targetPath);
            link.SetArguments(arguments ?? "");
            link.SetWorkingDirectory(workingDirectory ?? "");
            link.SetDescription(description ?? "");
            if (!string.IsNullOrEmpty(iconPath)) {
                link.SetIconLocation(iconPath, 0);
            }

            var store = (IPropertyStore)link;
            var pk = new PropertyKey {
                fmtid = new Guid("9F4C2855-9F79-4B39-A8D0-E1D42DE1D5F3"),
                pid = 5
            };
            var pv = new PropVariant {
                vt = 31,
                pointerValue = Marshal.StringToCoTaskMemUni(appId)
            };
            try {
                store.SetValue(ref pk, ref pv);
                store.Commit();
            } finally {
                Marshal.FreeCoTaskMem(pv.pointerValue);
            }

            var file = (IPersistFile)link;
            file.Save(shortcutPath, true);
        }
    }
}
"@
}

function Install-FireravenToastApp {
    # Silent user-scope Start Menu shortcut so Action Center toasts can brand as Fireraven.
    try {
        Ensure-FireravenShortcutAumidType
        $dir = Get-FireravenToastShortcutDir
        New-Item -ItemType Directory -Force -Path $dir | Out-Null
        $lnkPath = Join-Path $dir $script:FireravenToastShortcutName

        $psExe = Join-Path $env:SystemRoot "System32\WindowsPowerShell\v1.0\powershell.exe"
        $icon = Find-FireravenToastIcon
        [FireravenShortcutAumid.Creator]::CreateBrandedShortcut(
            $lnkPath,
            $psExe,
            "-NoProfile -WindowStyle Hidden -Command exit",
            (Get-UserHome),
            "Fireraven FireGuard notifications",
            $(if ($icon) { $icon } else { $null }),
            $script:FireravenToastAumid
        )
        Write-Info "Registered toast app identity ($($script:FireravenToastAumid)) at $lnkPath"
    } catch {
        Write-Warn "Could not register Fireraven toast Start Menu shortcut: $_"
    }
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
    return "py -3 hooks/fireraven/cursor_guardrail.py"
}

function New-DirectPyHookCommand {
    param([string]$ScriptPath)
    # Forward slashes: Devin Local / Claude Code run hooks via a POSIX shell that
    # treats backslashes as escapes (C:\Users\... becomes C:Users...).
    $normalized = $ScriptPath -replace '\\', '/'
    return "py -3 $normalized"
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
        Download-RepoFile -Path "scripts/$file" -Destination (Join-Path $dir $file)
    }
    return $dir
}

function Invoke-MergeHooksConfig {
    param(
        [hashtable]$PythonCommand,
        [string[]]$Arguments
    )

    $scriptsDir = Get-MergeHooksScriptsDir
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
    foreach ($dir in @("core", "adapters", "assets")) {
        $source = Join-Path $SourceRoot $dir
        if (-not (Test-Path $source)) {
            continue
        }
        $dest = Join-Path $DestinationDir $dir
        if (Test-Path $dest) {
            Remove-Item -Recurse -Force $dest
        }
        Copy-Item -Recurse -Force $source $DestinationDir
    }

    foreach ($file in @("_bootstrap.py", "windsurf_guardrail.py", "cursor_guardrail.py", "run_cursor_guardrail.ps1", "claude_guardrail.py", "devin_guardrail.py", "github_copilot_guardrail.py", "run_github_copilot_guardrail.ps1", "fireraven_input_guardrail.py", "config.example.env", "README.md")) {
        $source = Join-Path (Join-Path $SourceRoot "hooks") $file
        if (Test-Path $source) {
            Copy-Item -Force $source (Join-Path $DestinationDir $file)
        }
    }

    $versionSource = Join-Path $SourceRoot "VERSION"
    if (Test-Path $versionSource) {
        Copy-Item -Force $versionSource (Join-Path $DestinationDir "VERSION")
    }
}

function Download-RepoFile {
    param(
        [string]$Path,
        [string]$Destination
    )
    $url = Get-FileUrl -Path $Path
    New-Item -ItemType Directory -Force -Path (Split-Path -Parent $Destination) | Out-Null
    Write-Info "Downloading $Path"
    $headers = @{}
    if ($script:Channel -eq "gitlab_api") {
        $headers["PRIVATE-TOKEN"] = $HooksToken
    }
    Invoke-WebRequest -UseBasicParsing -Uri $url -Headers $headers -OutFile $Destination
}

function Download-PackageTree {
    param([string]$DestinationDir)

    New-Item -ItemType Directory -Force -Path $DestinationDir | Out-Null

    foreach ($path in @(
        "VERSION",
        "core/__init__.py",
        "core/config.py",
        "core/session_store.py",
        "core/fireraven_client.py",
        "core/serializers.py",
        "core/guardrail.py",
        "core/human_override.py",
        "core/hook_io.py",
        "core/unavailable_notice.py",
        "core/secured_notice.py",
        "core/update_check.py",
        "adapters/__init__.py",
        "adapters/windsurf.py",
        "adapters/cursor.py",
        "adapters/claude.py",
        "adapters/devin.py",
        "adapters/github_copilot.py",
        "assets/fireraven.ico"
    )) {
        Download-RepoFile -Path $path -Destination (Join-Path $DestinationDir ($path -replace "/", "\"))
    }

    foreach ($file in @("_bootstrap.py", "windsurf_guardrail.py", "cursor_guardrail.py", "run_cursor_guardrail.ps1", "claude_guardrail.py", "devin_guardrail.py", "github_copilot_guardrail.py", "run_github_copilot_guardrail.ps1", "fireraven_input_guardrail.py", "config.example.env", "README.md")) {
        Download-RepoFile -Path "hooks/$file" -Destination (Join-Path $DestinationDir $file)
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

    Download-PackageTree -DestinationDir $DestinationDir
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

    Write-Utf8NoBom -Path $Path -Content (($Data | ConvertTo-Json -Depth 20) + "`n")
}

function Ensure-ConfigEnv {
    param([string]$DestinationDir)

    $configEnv = Join-Path $DestinationDir "config.env"
    $exampleEnv = Join-Path $DestinationDir "config.example.env"
    if (Test-Path $configEnv) {
        Write-Info "Keeping existing config: $configEnv"
        Ensure-HooksTokenInConfig -DestinationDir $DestinationDir
        return
    }
    if (-not (Test-Path $exampleEnv)) {
        throw "Missing config template: $exampleEnv"
    }
    Copy-Item -Force $exampleEnv $configEnv
    Write-Warn "Created $configEnv - add FIRERAVEN_GUARDRAILS_API_KEY and FIRERAVEN_PROJECT_ID"
    Ensure-HooksTokenInConfig -DestinationDir $DestinationDir
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
    param([hashtable]$PythonCommand)

    $hooksJson = Join-Path (Get-WindsurfInstallDir) "hooks.json"
    $scriptPath = Join-Path (Get-WindsurfHooksDir) $WindsurfScript
    $events = ($WindsurfPreEvents + $WindsurfPostEvents) -join " "

    Invoke-MergeHooksConfig -PythonCommand $PythonCommand -Arguments @(
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
    param([hashtable]$PythonCommand)

    $hooksJson = Join-Path (Get-CursorInstallDir) "hooks.json"
    Invoke-MergeHooksConfig -PythonCommand $PythonCommand -Arguments @(
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
    param([hashtable]$PythonCommand)

    $settingsJson = Join-Path (Get-ClaudeInstallDir) "settings.json"
    $scriptPath = Join-Path (Get-ClaudeHooksDir) $ClaudeScript

    Invoke-MergeHooksConfig -PythonCommand $PythonCommand -Arguments @(
        "merge-claude",
        "--path", $settingsJson,
        "--script-path", $scriptPath,
        "--command", (New-DirectPyHookCommand -ScriptPath $scriptPath)
    )
    Write-Info "Registered Claude Code hooks in $settingsJson"
}

function Merge-DevinConfigJson {
    param([hashtable]$PythonCommand)

    $configJson = Join-Path (Get-DevinInstallDir) "config.json"
    $scriptPath = Join-Path (Get-DevinHooksDir) $DevinScript

    Invoke-MergeHooksConfig -PythonCommand $PythonCommand -Arguments @(
        "merge-devin",
        "--path", $configJson,
        "--script-path", $scriptPath,
        "--command", (New-DirectPyHookCommand -ScriptPath $scriptPath)
    )
    Write-Info "Registered Devin Local hooks in $configJson"
}

function Merge-GitHubCopilotHooksJson {
    param(
        [hashtable]$PythonCommand,
        [ValidateSet("user", "project")]
        [string]$Target = "user"
    )

    if ($Target -eq "project") {
        $hooksJson = Get-GitHubCopilotProjectHooksJson
        $scriptPath = ".github/hooks/fireraven/$GitHubCopilotScript"
    }
    else {
        $hooksJson = Get-GitHubCopilotHooksJson
        $scriptPath = Join-Path (Get-GitHubCopilotHooksDir) $GitHubCopilotScript
    }

    $bashCommand = "python3 $scriptPath"
    $powershellCommand = New-PowerShellPythonCommand -PythonCommand $PythonCommand -ScriptPath $scriptPath

    Invoke-MergeHooksConfig -PythonCommand $PythonCommand -Arguments @(
        "merge-github-copilot",
        "--path", $hooksJson,
        "--script-path", $scriptPath,
        "--events", ($GitHubCopilotEvents -join " "),
        "--owned-pattern", $FireravenEntryPattern,
        "--bash-command", $bashCommand,
        "--powershell-command", $powershellCommand,
        "--cwd", "."
    )
    Write-Info "Registered GitHub Copilot hooks in $hooksJson"
}

function Install-Windsurf {
    param(
        [hashtable]$PythonCommand,
        [string]$MetaAgents
    )
    $destination = Get-WindsurfHooksDir
    Write-Info "Installing Devin/Windsurf hooks to $destination"
    Install-PackageTree -DestinationDir $destination
    Write-InstallMeta -DestinationDir $destination -Agents $MetaAgents
    Ensure-ConfigEnv -DestinationDir $destination
    Merge-WindsurfHooksJson -PythonCommand $PythonCommand
}

function Install-Cursor {
    param(
        [hashtable]$PythonCommand,
        [string]$MetaAgents
    )
    $destination = Get-CursorHooksDir
    Write-Info "Installing Cursor hooks to $destination"
    Install-PackageTree -DestinationDir $destination
    Write-InstallMeta -DestinationDir $destination -Agents $MetaAgents
    Ensure-ConfigEnv -DestinationDir $destination
    Merge-CursorHooksJson -PythonCommand $PythonCommand
}

function Install-Claude {
    param(
        [hashtable]$PythonCommand,
        [string]$MetaAgents
    )
    $destination = Get-ClaudeHooksDir
    Write-Info "Installing Claude Code hooks to $destination"
    Install-PackageTree -DestinationDir $destination
    Write-InstallMeta -DestinationDir $destination -Agents $MetaAgents
    Ensure-ConfigEnv -DestinationDir $destination
    Merge-ClaudeSettingsJson -PythonCommand $PythonCommand
}

function Install-Devin {
    param(
        [hashtable]$PythonCommand,
        [string]$MetaAgents
    )
    $destination = Get-DevinHooksDir
    Write-Info "Installing Devin Local hooks to $destination"
    Install-PackageTree -DestinationDir $destination
    Write-InstallMeta -DestinationDir $destination -Agents $MetaAgents
    Ensure-ConfigEnv -DestinationDir $destination
    Merge-DevinConfigJson -PythonCommand $PythonCommand
}

function Install-GitHubCopilot {
    param(
        [hashtable]$PythonCommand,
        [string]$MetaAgents,
        [ValidateSet("user", "project")]
        [string]$Target = "user"
    )

    if ($Target -eq "project") {
        $destination = Get-GitHubCopilotProjectHooksDir
        Write-Info "Installing GitHub Copilot project hooks to $destination"
    }
    else {
        $destination = Get-GitHubCopilotHooksDir
        Write-Info "Installing GitHub Copilot hooks to $destination"
    }

    Install-PackageTree -DestinationDir $destination
    Write-InstallMeta -DestinationDir $destination -Agents $MetaAgents
    Ensure-ConfigEnv -DestinationDir $destination
    Merge-GitHubCopilotHooksJson -PythonCommand $PythonCommand -Target $Target

    if ($Target -eq "project") {
        Write-Warn "Commit .github/hooks/fireraven-fireguard.json and .github/hooks/fireraven/ to your default branch for Copilot cloud agent"
    }
}

Resolve-Channel
$pythonCommand = Get-PythonCommand
$pythonText = (@($pythonCommand.FilePath) + @($pythonCommand.Arguments)) -join " "
Write-Info "Using Python command: $pythonText"
Write-Info "Installing Fireraven agent hooks ($Agent)"
if ($script:Channel -eq "gitlab_api") {
    Write-Info "Channel: gitlab_api project=$($script:GitlabProject) ref=$($script:GitlabRef)"
}
else {
    Write-Info "Channel: github raw_base=$($script:RawBase)"
}

function Test-FireravenGuardrail {
    param(
        [string]$InstallDir,
        [string]$ScriptName
    )
    $flat = Join-Path (Join-Path $InstallDir "hooks") $ScriptName
    $nested = Join-Path (Join-Path $InstallDir "hooks\fireraven") $ScriptName
    return (Test-Path -LiteralPath $flat) -or (Test-Path -LiteralPath $nested)
}

function Get-InstallAgents {
    param([string]$Requested)
    if ($Requested -ne "windsurf") {
        return @($Requested)
    }
    if (Test-FireravenGuardrail -InstallDir (Get-WindsurfInstallDir) -ScriptName $WindsurfScript) {
        return @("windsurf")
    }
    $found = @()
    if (Test-FireravenGuardrail -InstallDir (Get-CursorInstallDir) -ScriptName $CursorScript) {
        $found += "cursor"
    }
    if (Test-FireravenGuardrail -InstallDir (Get-ClaudeInstallDir) -ScriptName $ClaudeScript) {
        $found += "claude"
    }
    if (Test-FireravenGuardrail -InstallDir (Get-DevinInstallDir) -ScriptName $DevinScript) {
        $found += "devin"
    }
    if (Test-FireravenGuardrail -InstallDir (Get-GitHubCopilotInstallDir) -ScriptName $GitHubCopilotScript) {
        $found += "github-copilot"
    }
    if ($found.Count -eq 0) {
        return @("windsurf")
    }
    Write-Info "No Windsurf install found; installing existing agent(s): $($found -join ', ')"
    return @($found)
}

$installAgents = @(Get-InstallAgents -Requested $Agent)
foreach ($installAgent in $installAgents) {
    switch ($installAgent) {
        "all" {
            Install-Windsurf -PythonCommand $pythonCommand -MetaAgents "all"
            Install-Cursor -PythonCommand $pythonCommand -MetaAgents "all"
            Install-Claude -PythonCommand $pythonCommand -MetaAgents "all"
            Install-Devin -PythonCommand $pythonCommand -MetaAgents "all"
            Install-GitHubCopilot -PythonCommand $pythonCommand -MetaAgents "all" -Target user
            Write-Info "Copilot Studio uses connector topics in adapters/copilot/ (see README)"
        }
        "windsurf" { Install-Windsurf -PythonCommand $pythonCommand -MetaAgents "windsurf" }
        "cursor" { Install-Cursor -PythonCommand $pythonCommand -MetaAgents "cursor" }
        "claude" { Install-Claude -PythonCommand $pythonCommand -MetaAgents "claude" }
        "devin" { Install-Devin -PythonCommand $pythonCommand -MetaAgents "devin" }
        "github-copilot" {
            $target = if ($Project -and $Agent -eq "github-copilot") { "project" } else { "user" }
            Install-GitHubCopilot -PythonCommand $pythonCommand -MetaAgents "github-copilot" -Target $target
        }
        "copilot" { Write-Info "Copilot Studio uses connector topics in adapters/copilot/ (see README)" }
    }
}

Install-FireravenToastApp

Write-Host ""
Write-Warn "Edit config.env in each installed hooks directory with FIRERAVEN_* credentials"
Write-Info "Restart your IDE(s) to load hook configuration"
Write-Host ""
