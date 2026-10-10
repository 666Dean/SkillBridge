@echo off
setlocal
cd /d "%~dp0"
python -c "import sys,tkinter; assert sys.version_info >= (3,12)" >nul 2>&1
if errorlevel 1 (
  echo Python 3.12+ with Tkinter is required. Install Python from python.org.
  pause
  exit /b 1
)
start "" /b pythonw "%~dp0app.py"
