param(
    [int]$WaitPid = 0
)

$ErrorActionPreference = "Continue"
Set-Location "c:\Users\Admin\Documents\python-project"

if ($WaitPid -gt 0) {
    $proc = Get-Process -Id $WaitPid -ErrorAction SilentlyContinue
    if ($proc) {
        Wait-Process -Id $WaitPid -ErrorAction SilentlyContinue
    }
}

Start-Sleep -Seconds 3
python -m src.main monthly --year 2026 --month 6 --no-cleanup 2>&1 |
    Tee-Object -FilePath "output/regen_monthly_2026-06_after_catchup.log"

python scripts/post_reprocess_status.py 2>&1 |
    Tee-Object -FilePath "output/regen_post_status.log" -Append
