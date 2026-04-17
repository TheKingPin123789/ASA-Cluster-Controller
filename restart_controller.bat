@echo off
cd /d "%~dp0"

:: Kill existing controller window if still running
set PID_FILE=controller\controller.pid
if exist "%PID_FILE%" (
    set /p CTRL_PID=<"%PID_FILE%"
    taskkill /F /PID %CTRL_PID% >nul 2>&1
    del "%PID_FILE%" >nul 2>&1
)

:: Also kill by window title as a fallback
taskkill /F /FI "WINDOWTITLE eq ASA Cluster Controller" >nul 2>&1

:: Brief pause so the port / files are fully released
timeout /t 2 >nul

:: Re-launch controller in its own window
start "ASA Cluster Controller" cmd /k "cd /d "%~dp0controller" && python asa_cluster_controller.py"
