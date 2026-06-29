# Tech Market Monitor — Windows Task Scheduler Setup
# Run in Administrator PowerShell:
#   Set-ExecutionPolicy -Scope Process Bypass
#   cd "C:\Users\Admin\OneDrive - Fraunhofer\Documents\python-project"
#   .\setup_scheduler.ps1

$PROJECT = "C:\Users\Admin\OneDrive - Fraunhofer\Documents\python-project"
$LOGDIR  = "$PROJECT\output\logs"

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

New-Item -ItemType Directory -Force -Path $LOGDIR | Out-Null

function Register-DailyTask {
    param(
        [string]$Name,
        [string]$BatchPath,
        [string]$Time
    )

    schtasks /Delete /TN $Name /F 2>$null | Out-Null
    $args = @(
        "/Create", "/TN", $Name,
        "/TR", $BatchPath,
        "/SC", "DAILY",
        "/ST", $Time,
        "/F"
    )
    & schtasks @args
    if ($LASTEXITCODE -ne 0) {
        Write-Host "FAILED: $Name" -ForegroundColor Red
        exit 1
    }
    Write-Host "OK: $Name ($Time -> $BatchPath)" -ForegroundColor Green
}

Write-Host "Registering tasks for: $PROJECT"
Write-Host ""

Register-DailyTask -Name "TechMarketMonitor-Daily" `
    -BatchPath "$PROJECT\run_daily_catchup.bat" `
    -Time "08:00"

Register-DailyTask -Name "TechMarketMonitor-GitSync" `
    -BatchPath "$PROJECT\run_sync_from_github.bat" `
    -Time "08:20"

Register-DailyTask -Name "TechMarketMonitor-Monthly" `
    -BatchPath "$PROJECT\run_monthly_check.bat" `
    -Time "18:30"

Write-Host ""
Write-Host "Verify:"
Write-Host '  schtasks /Query /TN "TechMarketMonitor-Daily" /V /FO LIST | findstr "Task To Run"'
Write-Host '  schtasks /Query /TN "TechMarketMonitor-GitSync" /V /FO LIST | findstr "Task To Run"'
Write-Host '  schtasks /Query /TN "TechMarketMonitor-Monthly" /V /FO LIST | findstr "Task To Run"'
