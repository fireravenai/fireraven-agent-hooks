$ErrorActionPreference = 'Stop'

function Read-StdinBytes {
    $inputStream = [Console]::OpenStandardInput()
    $buffer = New-Object byte[] 8192
    $ms = New-Object System.IO.MemoryStream

    try {
        while (($read = $inputStream.Read($buffer, 0, $buffer.Length)) -gt 0) {
            $ms.Write($buffer, 0, $read)
        }
    }
    finally {
        $inputStream.Close()
    }

    return $ms.ToArray()
}

$stdinBytes = Read-StdinBytes
if ($stdinBytes.Length -eq 0) {
    Write-Error 'Fireraven hook: no stdin received from GitHub Copilot.'
    exit 1
}

$pyScript = Join-Path $PSScriptRoot 'github_copilot_guardrail.py'

$psi = New-Object System.Diagnostics.ProcessStartInfo
$psi.FileName = 'py'
$psi.Arguments = "-3 `"$pyScript`""
$psi.UseShellExecute = $false
$psi.RedirectStandardInput = $true
$psi.RedirectStandardOutput = $true
$psi.RedirectStandardError = $true

$proc = New-Object System.Diagnostics.Process
$proc.StartInfo = $psi
[void]$proc.Start()

$stdinStream = $proc.StandardInput.BaseStream
$stdinStream.Write($stdinBytes, 0, $stdinBytes.Length)
$stdinStream.Flush()
$proc.StandardInput.Close()

$stdout = $proc.StandardOutput.ReadToEnd()
$stderr = $proc.StandardError.ReadToEnd()
$proc.WaitForExit()

if ($stdout) {
    Write-Output $stdout.TrimEnd()
}
if ($stderr) {
    [Console]::Error.WriteLine($stderr.TrimEnd())
}

exit $proc.ExitCode
