# Finwiz Screener — AI searchable / queryable launcher
Set-Location $PSScriptRoot
Write-Host ""
Write-Host "=== Finwiz Screener for Promising Growth Stocks ===" -ForegroundColor Cyan
Write-Host ""
Write-Host "CONTROL PANEL (CLI toggles — NOT on finviz.com)" -ForegroundColor Yellow
Write-Host "  View/change:  py -3 scripts\toggle.py"
Write-Host "  SMA ON/OFF:   py -3 scripts\toggle.py --sma on --period 200"
Write-Host "                periods: 9 | 20 | 50 | 100 | 200"
Write-Host "  Tight BUY:    py -3 scripts\toggle.py --tight on"
Write-Host "  Capitulation: py -3 scripts\toggle.py --capitulation on"
Write-Host "  Master ON/OFF: py -3 scripts\toggle.py --on   /  --off"
Write-Host "  Config file:  config\toggles.json"
Write-Host "  Finviz HITS:  py -3 scripts\export_finviz_hits.py   (YOUR tickers, not whole market)"
Write-Host ""
Write-Host "--- Current toggle state ---" -ForegroundColor Cyan
py -3 scripts\toggle.py
Write-Host ""
Write-Host "--- Action ranks (BUY/HOLD) ---" -ForegroundColor Cyan
py -3 scripts\rank_actions.py --gate-only
Write-Host ""
Write-Host "--- Capitulation second screener ---" -ForegroundColor Cyan
py -3 scripts\screen_capitulation.py
Write-Host ""
Write-Host "--- Finviz URLs for YOUR Finwiz hits ---" -ForegroundColor Cyan
py -3 scripts\export_finviz_hits.py
Write-Host ""
py -3 scripts\rebuild_index.py
Write-Host ""
if ($args.Count -eq 0) {
  py -3 scripts\query.py "growth stocks with strong news and workable technicals" --rebuild
} else {
  py -3 scripts\query.py @args
}
Write-Host ""
Write-Host "Tips:" -ForegroundColor Yellow
Write-Host '  .\launch.ps1 "action=BUY"'
Write-Host '  .\launch.ps1 "capitulation"'
Write-Host "  py -3 scripts\toggle.py --sma on --period 50"
Write-Host "  py -3 scripts\rank_actions.py --gate-only"
Write-Host "  .\launch_dashboard.ps1   # Streamlit HF trading dashboard (http://localhost:8501)"
Write-Host "  py -3 scripts\screen_capitulation.py"
Write-Host "  py -3 scripts\export_finviz_hits.py"
Write-Host "  py -3 scripts\build_watchlist_url.py --action BUY"
