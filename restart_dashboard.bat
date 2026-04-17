@echo off
cd /d "%~dp0"

set PID_FILE=controller\dashboard.pid

:: Kill the Python process — cmd /c (used to launch it) will close the window automatically
if exist "%PID_FILE%" (
    set /p DASH_PID=<"%PID_FILE%"
    taskkill /F /PID %DASH_PID% >nul 2>&1
    del "%PID_FILE%" >nul 2>&1
)

:: Fallback: kill by window title in case PID file was missing
taskkill /F /FI "WINDOWTITLE eq ASA Dashboard" >nul 2>&1

:: Brief pause so the port is fully released
timeout /t 2 >nul

:: Re-launch dashboard — cmd /c closes the window automatically when Python exits
:: The existing browser tab reloads itself via the JS polling overlay
start "ASA Dashboard" cmd /c "cd /d "%~dp0controller" && python dashboard.py"
