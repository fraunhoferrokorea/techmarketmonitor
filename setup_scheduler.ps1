# Tech Market Monitor — Windows Task Scheduler Setup
# Run in Administrator PowerShell:
#   Set-ExecutionPolicy -Scope Process Bypass
#   cd "C:\Users\Admin\Documents\python-project"
#   .\setup_scheduler.ps1
#
# Design goals (avoid missed / half-killed runs):
# - Launch bats via run_hidden.vbs (no console → no CTRL_CLOSE kill)
# - Restart failed tasks up to 3 times
# - Daily + health checks use StartWhenAvailable; Monthly does NOT
#   (overnight SWA monthly raced ahead of yesterday's daily)
# - Midday/afternoon health checks refill holes; daily chains monthly on LBD

$PROJECT = "C:\Users\Admin\Documents\python-project"
$LOGDIR  = "$PROJECT\output\logs"
$VBS     = "$PROJECT\run_hidden.vbs"

$IsAdmin = ([Security.Principal.WindowsPrincipal][Security.Principal.WindowsIdentity]::GetCurrent()).IsInRole(
    [Security.Principal.WindowsBuiltInRole]::Administrator
)
if (-not $IsAdmin) {
    Write-Host ""
    Write-Host "ERROR: Administrator PowerShell required." -ForegroundColor Red
    Write-Host "  Start menu -> Windows PowerShell -> Run as administrator"
    Write-Host "  Window title must show: Administrator: Windows PowerShell"
    Write-Host ""
    exit 1
}

if (-not (Test-Path $PROJECT)) {
    Write-Error "Project folder not found: $PROJECT"
    exit 1
}
if (-not (Test-Path $VBS)) {
    Write-Error "Hidden launcher not found: $VBS"
    exit 1
}

New-Item -ItemType Directory -Force -Path $LOGDIR | Out-Null

function Register-TmmTask {
    param(
        [string]$Name,
        [string]$BatchPath,
        [string]$Time,
        [switch]$StartWhenAvailable,
        [switch]$AtLogon,
        [int]$ExecHours = 72
    )

    if (-not (Test-Path $BatchPath)) {
        Write-Host "FAILED: batch not found: $BatchPath" -ForegroundColor Red
        exit 1
    }

    Unregister-ScheduledTask -TaskName $Name -Confirm:$false -ErrorAction SilentlyContinue

    $arg = "//B `"$VBS`" `"$BatchPath`""
    $action = New-ScheduledTaskAction -Execute "wscript.exe" -Argument $arg -WorkingDirectory $PROJECT

    if ($AtLogon) {
        $trigger = New-ScheduledTaskTrigger -AtLogOn
    } else {
        $trigger = New-ScheduledTaskTrigger -Daily -At $Time
    }

    $settingsParams = @{
        AllowStartIfOnBatteries    = $true
        DontStopIfGoingOnBatteries = $true
        ExecutionTimeLimit         = (New-TimeSpan -Hours $ExecHours)
        RestartCount               = 3
        RestartInterval            = (New-TimeSpan -Minutes 20)
        MultipleInstances          = "IgnoreNew"
    }
    if ($StartWhenAvailable) {
        $settingsParams["StartWhenAvailable"] = $true
    }
    $settings = New-ScheduledTaskSettingsSet @settingsParams

    $principal = New-ScheduledTaskPrincipal `
        -UserId $env:USERNAME `
        -LogonType Interactive `
        -RunLevel Limited

    try {
        Register-ScheduledTask `
            -TaskName $Name `
            -Action $action `
            -Trigger $trigger `
            -Settings $settings `
            -Principal $principal `
            -Force | Out-Null
    } catch {
        Write-Host "FAILED: $Name — $_" -ForegroundColor Red
        exit 1
    }

    $swa = if ($StartWhenAvailable) { "SWA=on" } else { "SWA=off" }
    $when = if ($AtLogon) { "at logon" } else { $Time }
    Write-Host "OK: $Name ($when, $swa, hidden, restart×3) -> $BatchPath" -ForegroundColor Green
}

Write-Host "Registering tasks for: $PROJECT"
Write-Host ""

Register-TmmTask -Name "TechMarketMonitor-Daily" `
    -BatchPath "$PROJECT\run_daily_catchup.bat" `
    -Time "08:00" `
    -StartWhenAvailable

Register-TmmTask -Name "TechMarketMonitor-GitSync" `
    -BatchPath "$PROJECT\run_sync_from_github.bat" `
    -Time "08:20" `
    -StartWhenAvailable `
    -ExecHours 1

# Watchdogs if morning run was killed / PC was off past SWA window
Register-TmmTask -Name "TechMarketMonitor-Health-1100" `
    -BatchPath "$PROJECT\run_health_check.bat" `
    -Time "11:00" `
    -StartWhenAvailable

Register-TmmTask -Name "TechMarketMonitor-Health-1500" `
    -BatchPath "$PROJECT\run_health_check.bat" `
    -Time "15:00" `
    -StartWhenAvailable

# Monthly backups only — primary path is chained from daily-catchup on LBD.
# No StartWhenAvailable: overnight catch-up must not run monthly before daily.
Register-TmmTask -Name "TechMarketMonitor-Monthly" `
    -BatchPath "$PROJECT\run_monthly_check.bat" `
    -Time "18:30"

Register-TmmTask -Name "TechMarketMonitor-Monthly-1030" `
    -BatchPath "$PROJECT\run_monthly_check.bat" `
    -Time "10:30"

Register-TmmTask -Name "TechMarketMonitor-Daily-Logon" `
    -BatchPath "$PROJECT\run_daily_catchup.bat" `
    -Time "08:00" `
    -AtLogon `
    -StartWhenAvailable `
    -ExecHours 12

Register-TmmTask -Name "TechMarketMonitor-GitSync-Logon" `
    -BatchPath "$PROJECT\run_sync_from_github.bat" `
    -Time "08:20" `
    -AtLogon `
    -ExecHours 1

Write-Host ""
Write-Host "Verify:"
Write-Host '  Get-ScheduledTask -TaskName "TechMarketMonitor-*" | Format-Table TaskName, State'
Write-Host '  schtasks /Query /TN "TechMarketMonitor-Daily" /V /FO LIST | findstr /i "Task To Run Next"'
