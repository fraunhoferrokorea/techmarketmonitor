# Cursor/Documents 쪽 코드 변경을 OneDrive(로컬 본진)로 복사
# keywords.txt, sources.txt, .env, data/, output/, .git 은 OneDrive 쪽을 유지합니다.
#
# 사용 (PowerShell):
#   Set-ExecutionPolicy -Scope Process Bypass
#   cd "C:\Users\Admin\OneDrive - Fraunhofer\Documents\python-project"
#   .\sync_code_to_onedrive.ps1
#
# Cursor 구독 종료 후에는 OneDrive 폴더에서 git pull 로 코드만 받고,
# keywords.txt / sources.txt / .env 는 OneDrive에서 직접 수정하세요.

$ErrorActionPreference = "Stop"

$OneDrive = "C:\Users\Admin\OneDrive - Fraunhofer\Documents\python-project"
$Documents = "C:\Users\Admin\Documents\python-project"

if (-not (Test-Path $OneDrive)) {
    Write-Error "OneDrive project not found: $OneDrive"
}
if (-not (Test-Path $Documents)) {
    Write-Error "Documents project not found: $Documents"
}

$docItem = Get-Item $Documents -Force
if ($docItem.LinkType -eq "Junction" -and $docItem.Target -eq $OneDrive) {
    Write-Host "Junction already active — both paths are the same folder. Nothing to sync." -ForegroundColor Green
    exit 0
}

Write-Host "Syncing code: $Documents -> $OneDrive"
Write-Host "(keeping OneDrive keywords.txt, sources.txt, .env, data/, output/, .git)" -ForegroundColor Yellow

robocopy $Documents $OneDrive /E /XD data output .git __pycache__ .cursor /XF keywords.txt sources.txt .env /NFL /NDL /NJH /NJS /NP | Out-Null

if ($LASTEXITCODE -ge 8) {
    Write-Error "robocopy failed with exit code $LASTEXITCODE"
}

Write-Host ""
Write-Host "Done. Verify with:" -ForegroundColor Green
Write-Host "  cd `"$OneDrive`""
Write-Host "  python -m src.main show-config"
