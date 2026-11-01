# Run elevated after downloading the official signed installer. Never restarts Windows.
$ErrorActionPreference = 'Stop'
$logDirectory = 'D:\Downloads\Docker'
$resultPath = Join-Path $logDirectory 'docker-install-result.json'
$installerPath = Join-Path $logDirectory 'Docker Desktop Installer.exe'
try {
    $identity = [Security.Principal.WindowsIdentity]::GetCurrent()
    $principal = [Security.Principal.WindowsPrincipal]::new($identity)
    if (-not $principal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)) {
        throw 'Administrator privileges are required for the custom installation directory.'
    }
    $signature = Get-AuthenticodeSignature -LiteralPath $installerPath
    if ($signature.Status -ne 'Valid' -or $signature.SignerCertificate.Subject -notmatch 'Docker') {
        throw 'Installer signature is not a valid Docker signature. Installation refused.'
    }
    $process = Start-Process -FilePath $installerPath -Wait -PassThru -WindowStyle Hidden `
        -ArgumentList 'install', '--quiet', '--backend=wsl-2', '--no-windows-containers', `
            '--installation-dir=D:\Docker', '--wsl-default-data-root=D:\DockerData'
    @{ exitCode = $process.ExitCode; finishedAt = (Get-Date).ToString('o');
        installationDirectory = 'D:\Docker'; wslDataRoot = 'D:\DockerData'; restarted = $false } |
        ConvertTo-Json | Set-Content -LiteralPath $resultPath -Encoding UTF8
    exit $process.ExitCode
} catch {
    @{ error = $_.Exception.Message; restarted = $false } |
        ConvertTo-Json | Set-Content -LiteralPath $resultPath -Encoding UTF8
    exit 1
}
