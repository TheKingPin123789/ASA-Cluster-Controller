@echo off
cd /d "%~dp0"

:: Kill the controller CMD window using the stored cmd.exe PID
set PID_FILE=controller\controller.pid
if exist "%PID_FILE%" (
    set /p CTRL_PID=<"%PID_FILE%"
    taskkill /F /T /PID %CTRL_PID% >nul 2>&1
    del "%PID_FILE%" >nul 2>&1
)

:: Fallback: kill by window title if PID file was missing
taskkill /F /FI "WINDOWTITLE eq ASA Cluster Controller" >nul 2>&1

:: Brief pause so files are fully released
timeout /t 2 >nul

:: Re-launch controller in its own window
start "ASA Cluster Controller" cmd /k "cd /d "%~dp0controller" && python asa_cluster_controller.py"
