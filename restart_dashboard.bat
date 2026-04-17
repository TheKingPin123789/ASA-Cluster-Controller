@echo off
cd /d "%~dp0"

:: Kill existing dashboard window if still running
set PID_FILE=controller\dashboard.pid
if exist "%PID_FILE%" (
    set /p DASH_PID=<"%PID_FILE%"
    taskkill /F /PID %DASH_PID% >nul 2>&1
    del "%PID_FILE%" >nul 2>&1
)

:: Also kill by window title as a fallback
taskkill /F /FI "WINDOWTITLE eq ASA Dashboard" >nul 2>&1

:: Brief pause so the port is fully released
timeout /t 2 >nul

:: Re-launch dashboard in its own window
start "ASA Dashboard" cmd /k "cd /d "%~dp0controller" && python dashboard.py"

:: Re-open the browser to the dashboard
for /f "tokens=*" %%p in ('python -c "import configparser; c=configparser.RawConfigParser(); c.read('controller\config.ini'); print(c.get('network','web_status_port') if c.has_option('network','web_status_port') else 5000)"') do set DASH_PORT=%%p
if not defined DASH_PORT set DASH_PORT=5000
timeout /t 3 >nul
start http://localhost:%DASH_PORT%
