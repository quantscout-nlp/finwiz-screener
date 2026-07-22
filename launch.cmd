@echo off
REM Finwiz Screener — AI searchable / queryable launcher
cd /d "%~dp0"
echo.
echo === Finwiz Screener for Promising Growth Stocks ===
echo.
echo CONTROL PANEL (CLI toggles — NOT on finviz.com)
echo   View/change:  py -3 scripts\toggle.py
echo   SMA ON/OFF:   py -3 scripts\toggle.py --sma on --period 200
echo                 periods: 9 20 50 100 200
echo   Tight BUY:    py -3 scripts\toggle.py --tight on
echo   Capitulation: py -3 scripts\toggle.py --capitulation on
echo   Master ON/OFF: py -3 scripts\toggle.py --on  /  --off
echo   Config file:  config\toggles.json
echo.
echo --- Current toggle state ---
py -3 scripts\toggle.py
echo.
echo --- Action ranks (BUY/HOLD) ---
py -3 scripts\rank_actions.py --gate-only
echo.
echo --- Capitulation second screener ---
py -3 scripts\screen_capitulation.py
echo.
py -3 scripts\rebuild_index.py
echo.
if "%~1"=="" (
  py -3 scripts\query.py "growth stocks with strong news and workable technicals" --rebuild
) else (
  py -3 scripts\query.py %*
)
echo.
echo Tips:
echo   launch.cmd "action=BUY"
echo   launch.cmd "capitulation"
echo   py -3 scripts\toggle.py --sma on --period 50
echo   py -3 scripts\rank_actions.py --gate-only
echo   py -3 scripts\screen_capitulation.py
echo.
pause
