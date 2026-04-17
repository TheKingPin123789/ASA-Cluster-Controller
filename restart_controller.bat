@echo off
cd /d "%~dp0"

:: Signal the controller to exit (dashboard API already wrote the file,
:: but write it here too so this BAT works as a standalone double-click)
echo restart > controller\controller.restart

:: Wait for the controller to exit cleanly (polls every 1s, up to 15s)
:: The controller detects the restart file on its next loop tick and exits
set /a tries=0
:wait_exit
if not exist "controller\controller.pid" goto launch
if %tries% GEQ 15 goto force_kill
timeout /t 1 >nul
set /a tries=%tries%+1
goto wait_exit

:force_kill
:: Fallback if the controller didn't exit within 15s — kill it directly
if exist "controller\controller.pid" (
    set /p CTRL_PID=<"controller\controller.pid"
    taskkill /F /PID %CTRL_PID% >nul 2>&1
    del "controller\controller.pid" >nul 2>&1
)
timeout /t 2 >nul

:launch
:: Re-launch controller — cmd /c closes the window when Python exits
start "ASA Cluster Controller" cmd /c "cd /d "%~dp0controller" && python asa_cluster_controller.py"
