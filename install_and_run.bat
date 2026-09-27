@echo off
cd /d "%~dp0"

rem "py" is the launcher python.org installs even without "Add python.exe to PATH";
rem "python" can be the Microsoft Store alias, which only prints a message, so each
rem candidate is tried before it is used
set PY=
py -3 -c "import sys" >nul 2>&1 && set PY=py -3
if not defined PY python -c "import sys" >nul 2>&1 && set PY=python
if not defined PY (
    echo Python was not found.
    echo.
    echo Install Python 3.10 or newer from https://www.python.org/downloads/
    echo and check "Add python.exe to PATH" in the installer, then run this again.
    echo.
    echo No Python needed: download HaloBattery-^<version^>.zip from the Releases page instead.
    pause
    exit /b 1
)

%PY% -m pip install -r requirements.txt
if errorlevel 1 (echo Failed to install dependencies & pause & exit /b 1)
if "%PY%"=="python" (start "" pythonw halo_battery.pyw) else (start "" pyw -3 halo_battery.pyw)
