@echo off
cd /d "%~dp0"

set PID_FILE=controller\controller.pid

:: Kill the Python process — cmd /c (used to launch it) will close the window automatically
if exist "%PID_FILE%" (
    set /p CTRL_PID=<"%PID_FILE%"
    taskkill /F /PID %CTRL_PID% >nul 2>&1
    del "%PID_FILE%" >nul 2>&1
)

:: Fallback: kill by window title in case PID file was missing
taskkill /F /FI "WINDOWTITLE eq ASA Cluster Controller" >nul 2>&1

:: Brief pause so files are fully released
timeout /t 2 >nul

:: Re-launch controller — cmd /c closes the window automatically when Python exits
start "ASA Cluster Controller" cmd /c "cd /d "%~dp0controller" && python asa_cluster_controller.py"
