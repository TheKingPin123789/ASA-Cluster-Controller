@echo off
cd /d "%~dp0"

echo.
echo  ASA Cluster Controller - Password Reset
echo  ----------------------------------------
echo  This will reset the dashboard password back to: admin
echo  Your username stays the same (check controller\config.ini if unsure).
echo.
echo  You can change it again in the dashboard Settings after logging in.
echo.
pause

:: Remove password_hash from config.ini so it falls back to default
set CONFIG=controller\config.ini

if not exist "%CONFIG%" (
    echo Config file not found: %CONFIG%
    pause
    exit /b 1
)

powershell -Command "(Get-Content \"%CONFIG%\") | Where-Object { $_ -notmatch '^\s*password_hash\s*=' } | Set-Content \"%CONFIG%\""

echo.
echo  Password reset! Restart the dashboard and log in with your username and password: admin
echo.
pause
