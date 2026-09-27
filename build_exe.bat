@echo off
cd /d "%~dp0"

rem see install_and_run.bat: "python" can be the Microsoft Store alias
set PY=
py -3 -c "import sys" >nul 2>&1 && set PY=py -3
if not defined PY python -c "import sys" >nul 2>&1 && set PY=python
if not defined PY (
    echo Python was not found. Install Python 3.10 or newer from https://www.python.org/downloads/
    echo and check "Add python.exe to PATH" in the installer, then run this again.
    pause
    exit /b 1
)

%PY% -m pip install -r requirements.txt pyinstaller
%PY% tools\make_icon.py halo.ico
%PY% tools\make_version.py version_info.txt
%PY% -m PyInstaller --noconfirm --onedir --windowed --noupx --name HaloBattery --icon halo.ico --version-file version_info.txt --hidden-import hid --hidden-import pystray._win32 halo_battery.pyw
echo.
echo Done: dist\HaloBattery\HaloBattery.exe (keep the whole HaloBattery folder together)
pause
