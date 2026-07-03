@echo off
chcp 65001 >nul
setlocal
cd /d "%~dp0"

echo.
echo === OneDrive junction setup ===
echo Makes Documents\python-project point to this OneDrive folder.
echo.

tasklist /FI "IMAGENAME eq Cursor.exe" 2>nul | find /I "Cursor.exe" >nul
if %ERRORLEVEL%==0 (
  echo [BLOCKED] Cursor is still running.
  echo   1. Save your work
  echo   2. File - Exit  OR  Task Manager - end all Cursor.exe
  echo   3. Close any PowerShell window that is cd'd into Documents\python-project
  echo   4. Run this file again BEFORE reopening Cursor
  echo.
  pause
  exit /b 1
)

echo Press any key to continue...
pause >nul

powershell -ExecutionPolicy Bypass -File "%~dp0setup_onedrive_junction.ps1"
if errorlevel 1 (
  echo.
  echo [FAILED] Folder still locked. Try:
  echo   - Reboot PC, run this file first, then open Cursor
  echo   - Or skip junction: always open OneDrive folder in Cursor instead
  echo.
  pause
  exit /b 1
)

echo.
echo [OK] Verify:
cd /d "C:\Users\Admin\Documents\python-project"
python -m src.main show-config
echo.
echo Next: open Cursor with this folder:
echo   C:\Users\Admin\OneDrive - Fraunhofer\Documents\python-project
echo.
pause
