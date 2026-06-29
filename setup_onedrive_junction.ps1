# OneDrive 단일 경로 통합 — Documents 복사본을 junction으로 교체
# Cursor 등에서 python-project 폴더를 연 프로그램을 모두 닫은 뒤, PowerShell에서 실행:
#   Set-ExecutionPolicy -Scope Process Bypass
#   cd "C:\Users\Admin\OneDrive - Fraunhofer\Documents\python-project"
#   .\setup_onedrive_junction.ps1

$ErrorActionPreference = "Stop"

$OneDrive = "C:\Users\Admin\OneDrive - Fraunhofer\Documents\python-project"
$Documents = "C:\Users\Admin\Documents\python-project"
$Backup = "C:\Users\Admin\Documents\python-project.bak-$(Get-Date -Format 'yyyyMMdd-HHmmss')"

if (-not (Test-Path $OneDrive)) {
    Write-Error "OneDrive project not found: $OneDrive"
}

$item = Get-Item $Documents -Force -ErrorAction SilentlyContinue
if ($null -eq $item) {
    Write-Host "Documents path missing — creating junction only."
} elseif ($item.LinkType -eq "Junction") {
    $target = (Get-Item $Documents).Target
    if ($target -eq $OneDrive) {
        Write-Host "Already consolidated. Junction points to OneDrive."
        exit 0
    }
    Write-Error "Existing junction points elsewhere: $target"
} else {
    Write-Host "Moving old Documents copy to: $Backup"
    Rename-Item -LiteralPath $Documents -NewName (Split-Path $Backup -Leaf)
}

Write-Host "Creating junction: $Documents -> $OneDrive"
cmd /c mklink /J "$Documents" "$OneDrive" | Out-Null

Write-Host ""
Write-Host "Done. Both paths now use the same OneDrive folder." -ForegroundColor Green
Write-Host "  $Documents"
Write-Host "  $OneDrive"
if (Test-Path $Backup) {
    Write-Host ""
    Write-Host "Old copy kept at: $Backup" -ForegroundColor Yellow
    Write-Host "After confirming everything works, delete the backup folder manually."
}
