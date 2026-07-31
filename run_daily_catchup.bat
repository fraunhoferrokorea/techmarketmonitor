@echo off
setlocal
cd /d "%~dp0"

REM If Task Scheduler still points at this .bat (visible console), detach a
REM hidden worker so closing the console cannot CTRL_CLOSE-kill the job.
if /I not "%~1"=="--hidden" (
  start "" wscript.exe //B "%~dp0run_hidden.vbs" "%~f0"
  exit /b 0
)

set TMM_SCHEDULED=1
set LOG=%~dp0output\logs\daily.log
if not exist "%~dp0output\logs" mkdir "%~dp0output\logs"
set PYTHON=C:\Users\Admin\AppData\Local\Programs\Python\Python314\python.exe
if exist "%~dp0.venv\Scripts\python.exe" set PYTHON=%~dp0.venv\Scripts\python.exe

echo [%date% %time%] daily-catchup start >> "%LOG%"
"%PYTHON%" -m src.main daily-catchup >> "%LOG%" 2>&1
if errorlevel 1 (
  echo [%date% %time%] daily-catchup failed >> "%LOG%"
  exit /b 1
)

git add output/daily/*.md data/monitor.db data/daily_scheduler_state.json 2>nul
git diff --staged --quiet
if errorlevel 1 (
  git -c user.name="yenaalisonhong" -c user.email="yenaalisonhong@users.noreply.github.com" commit -m "report: daily local sync" >> "%LOG%" 2>&1
  git pull --rebase origin main >> "%LOG%" 2>&1
  git push origin main >> "%LOG%" 2>&1
)
echo [%date% %time%] daily-catchup done >> "%LOG%"

REM On last business day, chain monthly after daily so StartWhenAvailable
REM cannot generate monthly before yesterday's daily exists.
echo [%date% %time%] monthly-after-daily start >> "%LOG%"
"%PYTHON%" "%~dp0run_monthly_if_last_bizday.py" >> "%~dp0output\logs\monthly.log" 2>&1
if errorlevel 1 (
  echo [%date% %time%] monthly-after-daily skipped_or_failed >> "%LOG%"
) else (
  git add output/monthly/*.md output/monthly/*.docx 2>nul
  git diff --staged --quiet
  if errorlevel 1 (
    git -c user.name="yenaalisonhong" -c user.email="yenaalisonhong@users.noreply.github.com" commit -m "report: monthly local sync" >> "%~dp0output\logs\monthly.log" 2>&1
    git pull --rebase origin main >> "%~dp0output\logs\monthly.log" 2>&1
    git push origin main >> "%~dp0output\logs\monthly.log" 2>&1
  )
  echo [%date% %time%] monthly-after-daily done >> "%LOG%"
)
