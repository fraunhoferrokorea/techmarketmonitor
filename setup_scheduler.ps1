# ─────────────────────────────────────────────────────────────────────────────
# Tech Market Monitor — Windows Task Scheduler Setup
#
# Primary project folder (OneDrive — Fraunhofer):
#   C:\Users\Admin\OneDrive - Fraunhofer\Documents\python-project
#
# Registered tasks:
#   1. TechMarketMonitor-Daily      : 08:00  daily-catchup + git push
#   2. TechMarketMonitor-GitSync     : 08:20  git pull (GitHub Actions backup)
#   3. TechMarketMonitor-Monthly    : 18:30  monthly on last business day only
# ─────────────────────────────────────────────────────────────────────────────

$PROJECT = "C:\Users\Admin\OneDrive - Fraunhofer\Documents\python-project"
$LOGDIR  = "$PROJECT\output\logs"

if (-not (Test-Path $PROJECT)) {
    Write-Error "Project folder not found: $PROJECT"
    exit 1
}

New-Item -ItemType Directory -Force -Path $LOGDIR | Out-Null

function Remove-TaskIfExists($Name) {
    if (Get-ScheduledTask -TaskName $Name -ErrorAction SilentlyContinue) {
        Unregister-ScheduledTask -TaskName $Name -Confirm:$false
        Write-Host "  Removed existing task: $Name"
    }
}

$Settings = New-ScheduledTaskSettingsSet `
    -ExecutionTimeLimit (New-TimeSpan -Hours 4) `
    -RestartCount 2 `
    -RestartInterval (New-TimeSpan -Minutes 10) `
    -StartWhenAvailable `
    -MultipleInstances IgnoreNew

# TASK 1 — Daily (08:00)
$DailyName   = "TechMarketMonitor-Daily"
$DailyBatch  = "$PROJECT\run_daily_catchup.bat"
$DailyAction = New-ScheduledTaskAction -Execute $DailyBatch -WorkingDirectory $PROJECT
$DailyTrigger = New-ScheduledTaskTrigger -Daily -At "08:00"
Remove-TaskIfExists $DailyName
Register-ScheduledTask -TaskName $DailyName -Action $DailyAction -Trigger $DailyTrigger -Settings $Settings `
    -Description "Daily catch-up -> output/daily + git push" -Force | Out-Null
Write-Host "Registered: $DailyName (08:00 -> $DailyBatch)"

# TASK 2 — GitHub sync pull (08:20)
$SyncName   = "TechMarketMonitor-GitSync"
$SyncBatch  = "$PROJECT\run_sync_from_github.bat"
$SyncAction = New-ScheduledTaskAction -Execute $SyncBatch -WorkingDirectory $PROJECT
$SyncTrigger = New-ScheduledTaskTrigger -Daily -At "08:20"
Remove-TaskIfExists $SyncName
Register-ScheduledTask -TaskName $SyncName -Action $SyncAction -Trigger $SyncTrigger -Settings $Settings `
    -Description "Pull latest daily/monthly reports from GitHub" -Force | Out-Null
Write-Host "Registered: $SyncName (08:20 -> $SyncBatch)"

# TASK 3 — Monthly (18:30)
$MonthlyName  = "TechMarketMonitor-Monthly"
$MonthlyBatch = "$PROJECT\run_monthly_check.bat"
$MonthlyAction = New-ScheduledTaskAction -Execute $MonthlyBatch -WorkingDirectory $PROJECT
$MonthlyTrigger = New-ScheduledTaskTrigger -Daily -At "18:30"
Remove-TaskIfExists $MonthlyName
Register-ScheduledTask -TaskName $MonthlyName -Action $MonthlyAction -Trigger $MonthlyTrigger -Settings $Settings `
    -Description "Monthly Word report on last business day + git push" -Force | Out-Null
Write-Host "Registered: $MonthlyName (18:30 -> $MonthlyBatch)"

Write-Host ""
Write-Host "Project root: $PROJECT"
Write-Host "Verify: Get-ScheduledTask | Where-Object TaskName -like 'TechMarket*'"
