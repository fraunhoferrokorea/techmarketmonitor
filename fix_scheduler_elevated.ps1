# One-shot: re-register TechMarketMonitor tasks (requires admin).
Set-ExecutionPolicy -Scope Process Bypass -Force
& "$PSScriptRoot\setup_scheduler.ps1"
