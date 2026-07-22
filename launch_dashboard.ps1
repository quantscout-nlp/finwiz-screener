# Finwiz Screener — Hedge Fund Manager Dashboard
Set-Location $PSScriptRoot
Write-Host ""
Write-Host "=== Finwiz Screener Dashboard ===" -ForegroundColor Cyan

# Pull latest User-level env vars into THIS process (Streamlit only sees what the parent has)
$userEnv = [Environment]::GetEnvironmentVariables("User")
foreach ($key in $userEnv.Keys) {
  Set-Item -Path "Env:$key" -Value $userEnv[$key] -ErrorAction SilentlyContinue
}
$machineEnv = [Environment]::GetEnvironmentVariables("Machine")
foreach ($key in $machineEnv.Keys) {
  if (-not (Test-Path "Env:$key")) {
    Set-Item -Path "Env:$key" -Value $machineEnv[$key] -ErrorAction SilentlyContinue
  }
}

$finviz = [bool]$env:FINVIZ_API_KEY
$openai = [bool]($env:OPENAI_API_KEY -or $env:FINWIZ_LLM_API_KEY)
Write-Host ("  Finviz Elite key: {0}" -f ($(if ($finviz) { "FOUND" } else { "MISSING (set FINVIZ_API_KEY)" }))) -ForegroundColor $(if ($finviz) { "Green" } else { "Yellow" })
Write-Host ("  OpenAI LLM key:   {0}" -f ($(if ($openai) { "FOUND" } else { "MISSING (set OPENAI_API_KEY)" }))) -ForegroundColor $(if ($openai) { "Green" } else { "Yellow" })
Write-Host "Starting Streamlit at http://localhost:8501" -ForegroundColor Green
Write-Host ""

py -3 -m pip install -q -r requirements.txt
py -3 -m streamlit run dashboard\app.py --server.headless true
