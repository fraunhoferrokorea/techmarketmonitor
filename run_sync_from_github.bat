@echo off
setlocal
cd /d "%~dp0"

if /I not "%~1"=="--hidden" (
  start "" wscript.exe //B "%~dp0run_hidden.vbs" "%~f0"
  exit /b 0
)

set TMM_SCHEDULED=1
set LOG=%~dp0output\logs\sync.log
if not exist "%~dp0output\logs" mkdir "%~dp0output\logs"
set PYTHON=C:\Users\Admin\AppData\Local\Programs\Python\Python314\python.exe
if exist "%~dp0.venv\Scripts\python.exe" set PYTHON=%~dp0.venv\Scripts\python.exe

REM Skip git pull while daily/monthly holds the pipeline lock (avoids merge fights).
"%PYTHON%" -c "from src.job_guard import is_lock_held; raise SystemExit(1 if is_lock_held('pipeline') else 0)"
if errorlevel 1 (
  echo [%date% %time%] sync skipped — pipeline lock busy >> "%LOG%"
  exit /b 0
)

echo [%date% %time%] git pull >> "%LOG%"
git fetch origin main >> "%LOG%" 2>&1
git pull --rebase origin main >> "%LOG%" 2>&1
if errorlevel 1 (
  echo [%date% %time%] pull failed >> "%LOG%"
  exit /b 1
)
echo [%date% %time%] sync ok >> "%LOG%"
