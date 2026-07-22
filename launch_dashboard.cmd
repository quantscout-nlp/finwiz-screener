@echo off
cd /d "%~dp0"
echo.
echo === Finwiz Screener Dashboard ===
echo Refreshing User environment variables into this session...
powershell -NoProfile -Command ^
  "$u=[Environment]::GetEnvironmentVariables('User'); foreach($k in $u.Keys){ Set-Item -Path Env:$k -Value $u[$k] -ErrorAction SilentlyContinue }; ^
   if ($env:FINVIZ_API_KEY) { Write-Host '  Finviz Elite key: FOUND' -ForegroundColor Green } else { Write-Host '  Finviz Elite key: MISSING' -ForegroundColor Yellow }; ^
   if ($env:OPENAI_API_KEY -or $env:FINWIZ_LLM_API_KEY) { Write-Host '  OpenAI LLM key: FOUND' -ForegroundColor Green } else { Write-Host '  OpenAI LLM key: MISSING' -ForegroundColor Yellow }; ^
   py -3 -m pip install -q -r requirements.txt; ^
   py -3 -m streamlit run dashboard\app.py --server.headless true"
