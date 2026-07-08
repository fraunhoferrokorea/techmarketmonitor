@echo off
setlocal
cd /d "%~dp0"
set LOG=%~dp0output\logs\monthly.log
if not exist "%~dp0output\logs" mkdir "%~dp0output\logs"
set PYTHON=C:\Users\Admin\AppData\Local\Programs\Python\Python314\python.exe
if exist "%~dp0.venv\Scripts\python.exe" set PYTHON=%~dp0.venv\Scripts\python.exe

echo [%date% %time%] monthly check start >> "%LOG%"
"%PYTHON%" "%~dp0run_monthly_if_last_bizday.py" >> "%LOG%" 2>&1
if errorlevel 1 (
  echo [%date% %time%] monthly failed >> "%LOG%"
  exit /b 1
)

git add output/monthly/*.md output/monthly/*.docx 2>nul
git diff --staged --quiet
if errorlevel 1 (
  git -c user.name="yenaalisonhong" -c user.email="yenaalisonhong@users.noreply.github.com" commit -m "report: monthly local sync" >> "%LOG%" 2>&1
  git pull --rebase origin main >> "%LOG%" 2>&1
  git push origin main >> "%LOG%" 2>&1
)
echo [%date% %time%] monthly done >> "%LOG%"
