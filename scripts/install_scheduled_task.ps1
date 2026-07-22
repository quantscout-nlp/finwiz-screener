# Install / update Windows Scheduled Task for Finwiz automation (always-on background)
# Run once in elevated or normal PowerShell:
#   .\scripts\install_scheduled_task.ps1
#   .\scripts\install_scheduled_task.ps1 -Minutes 15
#   .\scripts\install_scheduled_task.ps1 -Uninstall

param(
  [int]$Minutes = 15,
  [switch]$Uninstall
)

$TaskName = "FinwizScreenerAutomation"
$Root = Split-Path -Parent $PSScriptRoot
$Runner = Join-Path $PSScriptRoot "run_automation.ps1"

if ($Uninstall) {
  Unregister-ScheduledTask -TaskName $TaskName -Confirm:$false -ErrorAction SilentlyContinue
  Write-Host "Removed scheduled task: $TaskName" -ForegroundColor Yellow
  exit 0
}

if (-not (Test-Path $Runner)) {
  Write-Error "Missing $Runner"
  exit 1
}

$action = New-ScheduledTaskAction `
  -Execute "powershell.exe" `
  -Argument "-NoProfile -ExecutionPolicy Bypass -File `"$Runner`"" `
  -WorkingDirectory $Root

# Repeat for ~10 years (Windows rejects [TimeSpan]::MaxValue)
$trigger = New-ScheduledTaskTrigger -Once -At (Get-Date).AddMinutes(1) `
  -RepetitionInterval (New-TimeSpan -Minutes $Minutes) `
  -RepetitionDuration (New-TimeSpan -Days 3650)

$settings = New-ScheduledTaskSettingsSet `
  -AllowStartIfOnBatteries `
  -DontStopIfGoingOnBatteries `
  -StartWhenAvailable `
  -MultipleInstances IgnoreNew `
  -ExecutionTimeLimit (New-TimeSpan -Hours 1)

$principal = New-ScheduledTaskPrincipal -UserId $env:USERNAME -LogonType Interactive -RunLevel Limited

Unregister-ScheduledTask -TaskName $TaskName -Confirm:$false -ErrorAction SilentlyContinue

Register-ScheduledTask `
  -TaskName $TaskName `
  -Action $action `
  -Trigger $trigger `
  -Settings $settings `
  -Principal $principal `
  -Description "Finwiz Screener: Elite sync + rebuild + paper trades + deep-dive stubs every $Minutes minutes" `
  -Force | Out-Null

$task = Get-ScheduledTask -TaskName $TaskName -ErrorAction Stop
Write-Host "Installed scheduled task: $($task.TaskName) [$($task.State)]" -ForegroundColor Green
Write-Host "  Interval: every $Minutes minutes"
Write-Host "  Runner:   $Runner"
Write-Host "  Logs:     $Root\data\automation_logs\"
Write-Host ""
Write-Host "Manual run:  powershell -File `"$Runner`""
Write-Host "Uninstall:   .\scripts\install_scheduled_task.ps1 -Uninstall"
Write-Host "Status:      Get-ScheduledTask -TaskName $TaskName | Format-List"
