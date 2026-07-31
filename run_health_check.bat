@echo off
REM Midday / afternoon watchdog: refill missing dailies and LBD monthly if owed.
setlocal
cd /d "%~dp0"

if /I not "%~1"=="--hidden" (
  start "" wscript.exe //B "%~dp0run_hidden.vbs" "%~f0"
  exit /b 0
)

set TMM_SCHEDULED=1
set LOG=%~dp0output\logs\health.log
if not exist "%~dp0output\logs" mkdir "%~dp0output\logs"
set PYTHON=C:\Users\Admin\AppData\Local\Programs\Python\Python314\python.exe
if exist "%~dp0.venv\Scripts\python.exe" set PYTHON=%~dp0.venv\Scripts\python.exe

echo [%date% %time%] health-check start >> "%LOG%"
"%PYTHON%" -m src.main daily-catchup >> "%LOG%" 2>&1
if errorlevel 1 (
  echo [%date% %time%] health daily-catchup failed >> "%LOG%"
  exit /b 1
)

git add output/daily/*.md data/monitor.db data/daily_scheduler_state.json 2>nul
git diff --staged --quiet
if errorlevel 1 (
  git -c user.name="yenaalisonhong" -c user.email="yenaalisonhong@users.noreply.github.com" commit -m "report: daily local sync" >> "%LOG%" 2>&1
  git pull --rebase origin main >> "%LOG%" 2>&1
  git push origin main >> "%LOG%" 2>&1
)

"%PYTHON%" "%~dp0run_monthly_if_last_bizday.py" >> "%LOG%" 2>&1
git add output/monthly/*.md output/monthly/*.docx 2>nul
git diff --staged --quiet
if errorlevel 1 (
  git -c user.name="yenaalisonhong" -c user.email="yenaalisonhong@users.noreply.github.com" commit -m "report: monthly local sync" >> "%LOG%" 2>&1
  git pull --rebase origin main >> "%LOG%" 2>&1
  git push origin main >> "%LOG%" 2>&1
)

echo [%date% %time%] health-check done >> "%LOG%"
