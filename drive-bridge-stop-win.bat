@echo off
setlocal
cd /d "%~dp0"

set "PYTHON_CMD="
where py >nul 2>nul
if not errorlevel 1 set "PYTHON_CMD=py -3"
if not defined PYTHON_CMD (
  where python >nul 2>nul
  if not errorlevel 1 set "PYTHON_CMD=python"
)
if not defined PYTHON_CMD (
  where python3 >nul 2>nul
  if not errorlevel 1 set "PYTHON_CMD=python3"
)

if not defined PYTHON_CMD (
  echo Cannot find Python 3. Please install Python 3 first.
  pause
  exit /b 1
)

%PYTHON_CMD% drive_bridge_gui.py --stop
pause
