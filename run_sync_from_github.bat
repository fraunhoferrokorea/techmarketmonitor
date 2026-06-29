@echo off
setlocal
cd /d "%~dp0"
set LOG=%~dp0output\logs\sync.log
if not exist "%~dp0output\logs" mkdir "%~dp0output\logs"
echo [%date% %time%] git pull >> "%LOG%"
git fetch origin main >> "%LOG%" 2>&1
git pull --rebase origin main >> "%LOG%" 2>&1
if errorlevel 1 (
  echo [%date% %time%] pull failed >> "%LOG%"
  exit /b 1
)
echo [%date% %time%] sync ok >> "%LOG%"
