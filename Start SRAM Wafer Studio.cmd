@echo off
setlocal
cd /d "%~dp0"
where python >nul 2>nul
if errorlevel 1 (
  echo Python 3.11 or newer is required. Install it and enable Add Python to PATH.
  pause
  exit /b 1
)
set "SRAM_PY=python"
if exist ".venv\Scripts\python.exe" set "SRAM_PY=.venv\Scripts\python.exe"
"%SRAM_PY%" -c "import openpyxl, xlsxwriter, PIL, pptx, webview, matplotlib; from webview import FileDialog" >nul 2>nul
if errorlevel 1 (
  if not exist ".venv\Scripts\python.exe" python -m venv .venv
  if errorlevel 1 goto failed
  set "SRAM_PY=.venv\Scripts\python.exe"
  ".venv\Scripts\python.exe" -m pip install -r requirements.txt
  if errorlevel 1 goto failed
)
"%SRAM_PY%" -c "from pathlib import Path; import subprocess, sys; subprocess.Popen([str(Path(sys.executable).with_name('pythonw.exe')), 'app.py'])"
if errorlevel 1 goto failed
exit /b 0
:failed
echo Could not start SRAM Wafer Studio. See the message above.
pause
exit /b 1
