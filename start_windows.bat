@echo off
setlocal
cd /d "%~dp0"
where python >nul 2>&1
if errorlevel 1 (
  echo Python 3.11 or newer is required. Install Python and try again.
  pause
  exit /b 1
)
if not exist .venv\Scripts\python.exe (
  python -m venv .venv
  if errorlevel 1 goto fail
)
call .venv\Scripts\activate.bat
python -m pip install -e .
if errorlevel 1 goto fail
echo.
echo DataDoctor will be available at http://127.0.0.1:8000
python -m uvicorn datadoctor.api:app --host 127.0.0.1 --port 8000
goto end
:fail
echo Installation failed. Check your internet connection and Python version.
:end
pause
