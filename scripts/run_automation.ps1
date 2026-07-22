# Finwiz always-on automation entrypoint for Task Scheduler
$ErrorActionPreference = "Continue"
Set-Location $PSScriptRoot\..

# Refresh User env (Finviz / OpenAI keys)
$userEnv = [Environment]::GetEnvironmentVariables("User")
foreach ($key in $userEnv.Keys) {
  Set-Item -Path "Env:$key" -Value $userEnv[$key] -ErrorAction SilentlyContinue
}

$logDir = Join-Path $PSScriptRoot "..\data\automation_logs"
New-Item -ItemType Directory -Force -Path $logDir | Out-Null
$stamp = Get-Date -Format "yyyy-MM-dd HH:mm:ss"
Add-Content -Path (Join-Path $logDir "scheduler.log") -Value "$stamp | automation start"

py -3 scripts\automation_cycle.py --deep-dives
$code = $LASTEXITCODE
Add-Content -Path (Join-Path $logDir "scheduler.log") -Value "$(Get-Date -Format 'yyyy-MM-dd HH:mm:ss') | exit $code"
exit $code
