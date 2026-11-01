# Run elevated. Installs WSL without an Ubuntu distribution; never restarts Windows.
$ErrorActionPreference = 'Stop'
$logDirectory = 'D:\Downloads\Docker'
$resultPath = Join-Path $logDirectory 'wsl-install-result.json'
try {
    $identity = [Security.Principal.WindowsIdentity]::GetCurrent()
    $principal = [Security.Principal.WindowsPrincipal]::new($identity)
    if (-not $principal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)) {
        throw 'Administrator privileges are required to enable WSL.'
    }
    New-Item -ItemType Directory -Path $logDirectory -Force | Out-Null
    $process = Start-Process -FilePath "$env:WINDIR\System32\wsl.exe" `
        -ArgumentList '--install', '--no-distribution', '--web-download' `
        -Wait -PassThru -WindowStyle Hidden `
        -RedirectStandardOutput (Join-Path $logDirectory 'wsl-install.stdout.log') `
        -RedirectStandardError (Join-Path $logDirectory 'wsl-install.stderr.log')
    @{ exitCode = $process.ExitCode; finishedAt = (Get-Date).ToString('o'); restarted = $false } |
        ConvertTo-Json | Set-Content -LiteralPath $resultPath -Encoding UTF8
    exit $process.ExitCode
} catch {
    @{ error = $_.Exception.Message; restarted = $false } |
        ConvertTo-Json | Set-Content -LiteralPath $resultPath -Encoding UTF8
    exit 1
}
