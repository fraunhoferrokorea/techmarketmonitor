# ─────────────────────────────────────────────────────────────────────────────
# Tech Market Monitor — Windows Task Scheduler Setup
#
# 등록 작업 2개:
#   1. TechMarketMonitor-Daily   : 매일 08:00  →  python -m src.main daily-catchup
#   2. TechMarketMonitor-Monthly : 매일 18:30  →  run_monthly_if_last_bizday.py
#                                  (마지막 영업일에만 실제로 월간 보고서 생성)
# ─────────────────────────────────────────────────────────────────────────────

$PROJECT  = "C:\Users\Admin\Documents\python-project"
$PYTHON   = "$PROJECT\.venv\Scripts\python.exe"
$LOGDIR   = "$PROJECT\output\logs"

# Ensure log directory exists
New-Item -ItemType Directory -Force -Path $LOGDIR | Out-Null

# ── Helper: remove existing task if present ──────────────────────────────────
function Remove-TaskIfExists($Name) {
    if (Get-ScheduledTask -TaskName $Name -ErrorAction SilentlyContinue) {
        Unregister-ScheduledTask -TaskName $Name -Confirm:$false
        Write-Host "  Removed existing task: $Name"
    }
}

# ─────────────────────────────────────────────────────────────────────────────
# TASK 1 — Daily report (every day at 08:00)
# ─────────────────────────────────────────────────────────────────────────────
$DailyName    = "TechMarketMonitor-Daily"
$DailyLog     = "$LOGDIR\daily.log"
$DailyArgs    = "-m src.main daily-catchup"
$DailyAction  = New-ScheduledTaskAction `
    -Execute $PYTHON `
    -Argument $DailyArgs `
    -WorkingDirectory $PROJECT

$DailyTrigger = New-ScheduledTaskTrigger -Daily -At "08:00"

$Settings = New-ScheduledTaskSettingsSet `
    -ExecutionTimeLimit (New-TimeSpan -Hours 4) `
    -RestartCount 2 `
    -RestartInterval (New-TimeSpan -Minutes 10) `
    -StartWhenAvailable `
    -MultipleInstances IgnoreNew

Remove-TaskIfExists $DailyName
Register-ScheduledTask `
    -TaskName   $DailyName `
    -Action     $DailyAction `
    -Trigger    $DailyTrigger `
    -Settings   $Settings `
    -Description "Tech Market Monitor — daily fetch/summarize/store + Markdown report" `
    -Force | Out-Null

Write-Host "✅ Registered: $DailyName  (daily at 08:00)"

# ─────────────────────────────────────────────────────────────────────────────
# TASK 2 — Monthly Word report (daily trigger at 18:30; script decides the date)
# ─────────────────────────────────────────────────────────────────────────────
$MonthlyName    = "TechMarketMonitor-Monthly"
$MonthlyScript  = "$PROJECT\run_monthly_if_last_bizday.py"
$MonthlyArgs    = "`"$MonthlyScript`""
$MonthlyAction  = New-ScheduledTaskAction `
    -Execute $PYTHON `
    -Argument $MonthlyArgs `
    -WorkingDirectory $PROJECT

$MonthlyTrigger = New-ScheduledTaskTrigger -Daily -At "18:30"

Remove-TaskIfExists $MonthlyName
Register-ScheduledTask `
    -TaskName   $MonthlyName `
    -Action     $MonthlyAction `
    -Trigger    $MonthlyTrigger `
    -Settings   $Settings `
    -Description "Tech Market Monitor — monthly Word report on last business day" `
    -Force | Out-Null

Write-Host "✅ Registered: $MonthlyName  (checks daily at 18:30; runs on last business day only)"

Write-Host ""
Write-Host "Done. Verify in Task Scheduler (taskschd.msc) or run:"
Write-Host "  Get-ScheduledTask | Where-Object TaskName -like 'TechMarket*' | Select TaskName, State"
