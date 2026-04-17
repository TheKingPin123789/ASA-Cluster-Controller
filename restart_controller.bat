@echo off
cd /d "%~dp0"

set PID_FILE=controller\controller.pid

:: Use PowerShell to find Python's parent (cmd.exe) and kill the whole window
if exist "%PID_FILE%" (
    powershell -NoProfile -Command ^
        "try {" ^
        "  $py = Get-Process -Id (Get-Content '%PID_FILE%') -ErrorAction Stop;" ^
        "  $parent = $py.Parent.Id;" ^
        "  Stop-Process -Id $py.Id -Force -ErrorAction SilentlyContinue;" ^
        "  if ($parent) { Stop-Process -Id $parent -Force -ErrorAction SilentlyContinue }" ^
        "} catch {}"
    del "%PID_FILE%" >nul 2>&1
)

:: Fallback: kill by window title in case PID file was missing
taskkill /F /FI "WINDOWTITLE eq ASA Cluster Controller" >nul 2>&1

:: Brief pause so files and ports are fully released
timeout /t 2 >nul

:: Re-launch controller in its own window
start "ASA Cluster Controller" cmd /k "cd /d "%~dp0controller" && python asa_cluster_controller.py"
