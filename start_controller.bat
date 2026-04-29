@echo off
setlocal EnableDelayedExpansion
cd /d "%~dp0"

set REPO_URL=https://github.com/TheKingPin123789/ASA-Cluster-Controller
set REPO_ZIP=%REPO_URL%/archive/refs/heads/main.zip
set REPO_API=https://api.github.com/repos/TheKingPin123789/ASA-Cluster-Controller/commits/main
set DOWNLOAD_ZIP=%~dp0controller_download.zip
set EXTRACT_DIR=%~dp0controller_extract
set SHA_FILE=%~dp0.installed_sha

:: ── Fresh install ──────────────────────────────────────────────────────────────
:: Download all controller files if they are missing entirely
if not exist "controller\asa_cluster_controller.py" (
    echo.
    echo Controller files not found. Downloading from GitHub...
    echo.

    powershell -NoProfile -Command "Invoke-WebRequest -Uri '%REPO_ZIP%' -OutFile '%DOWNLOAD_ZIP%'"
    if not exist "%DOWNLOAD_ZIP%" (
        echo Download failed. Check your internet connection and try again.
        pause
        exit /b 1
    )

    powershell -NoProfile -Command "Expand-Archive -Path '%DOWNLOAD_ZIP%' -DestinationPath '%EXTRACT_DIR%' -Force"

    xcopy /E /I /Y "%EXTRACT_DIR%\ASA-Cluster-Controller-main\controller"  "controller\"  >nul
    xcopy /E /I /Y "%EXTRACT_DIR%\ASA-Cluster-Controller-main\scripts"     "scripts\"     >nul
    copy  /Y       "%EXTRACT_DIR%\ASA-Cluster-Controller-main\start_controller.bat" "%~dp0start_controller.bat" >nul
    copy  /Y       "%EXTRACT_DIR%\ASA-Cluster-Controller-main\requirements.txt"     "%~dp0requirements.txt"     >nul 2>&1
    copy  /Y       "%EXTRACT_DIR%\ASA-Cluster-Controller-main\README.md"            "%~dp0README.md"            >nul 2>&1

    :: Record the SHA we just installed so the update check has a baseline
    powershell -NoProfile -Command ^
        "try { (Invoke-WebRequest -Uri '%REPO_API%' -UseBasicParsing | ConvertFrom-Json).sha } catch { '' }" ^
        > "%SHA_FILE%" 2>nul

    :: Clean up download artifacts
    del "%DOWNLOAD_ZIP%" >nul 2>&1
    if exist "%EXTRACT_DIR%" rmdir /S /Q "%EXTRACT_DIR%"

    echo Files downloaded successfully.
    echo.
)

:: ── Update check ───────────────────────────────────────────────────────────────
echo Checking for updates...

:: Fetch latest commit SHA from GitHub API
set LATEST_SHA=
for /f "delims=" %%s in ('powershell -NoProfile -Command ^
    "try { (Invoke-WebRequest -Uri ''%REPO_API%'' -UseBasicParsing | ConvertFrom-Json).sha } catch { '' }" ^
    2^>nul') do set LATEST_SHA=%%s

if "!LATEST_SHA!"=="" (
    echo  Could not reach GitHub -- skipping update check.
    echo.
    goto :launch
)

:: Read the locally stored SHA
set INSTALLED_SHA=
if exist "%SHA_FILE%" (
    set /p INSTALLED_SHA=<"%SHA_FILE%"
)

:: No SHA on record yet (e.g. first run after adding this feature)
:: Record the current remote SHA and continue without forcing an update.
if "!INSTALLED_SHA!"=="" (
    echo !LATEST_SHA!>"%SHA_FILE%"
    echo Up to date.
    echo.
    goto :launch
)

:: Already on the latest commit
if "!LATEST_SHA!"=="!INSTALLED_SHA!" (
    echo Up to date.
    echo.
    goto :launch
)

:: ── Offer update ───────────────────────────────────────────────────────────────
echo.
echo  *** UPDATE AVAILABLE ***
echo  A newer version is available on GitHub.
echo.
set DO_UPDATE=Y
set /p DO_UPDATE="  Update now? [Y/n]: "
if /i "!DO_UPDATE!"=="n" (
    echo  Skipping update.
    echo.
    goto :launch
)

echo.
echo Downloading update...
powershell -NoProfile -Command "Invoke-WebRequest -Uri '%REPO_ZIP%' -OutFile '%DOWNLOAD_ZIP%'"
if not exist "%DOWNLOAD_ZIP%" (
    echo  Download failed -- skipping update.
    echo.
    goto :launch
)

powershell -NoProfile -Command "Expand-Archive -Path '%DOWNLOAD_ZIP%' -DestinationPath '%EXTRACT_DIR%' -Force"

xcopy /E /I /Y "%EXTRACT_DIR%\ASA-Cluster-Controller-main\controller"  "controller\"  >nul
xcopy /E /I /Y "%EXTRACT_DIR%\ASA-Cluster-Controller-main\scripts"     "scripts\"     >nul
copy  /Y       "%EXTRACT_DIR%\ASA-Cluster-Controller-main\start_controller.bat" "%~dp0start_controller.bat" >nul
copy  /Y       "%EXTRACT_DIR%\ASA-Cluster-Controller-main\requirements.txt"     "%~dp0requirements.txt"     >nul 2>&1
copy  /Y       "%EXTRACT_DIR%\ASA-Cluster-Controller-main\README.md"            "%~dp0README.md"            >nul 2>&1

del "%DOWNLOAD_ZIP%" >nul 2>&1
if exist "%EXTRACT_DIR%" rmdir /S /Q "%EXTRACT_DIR%"

:: Save the new SHA
echo !LATEST_SHA!>"%SHA_FILE%"

echo.
echo  Update applied -- restarting...
echo.
start "" "%~f0"
exit /b 0

:: ── Launch ─────────────────────────────────────────────────────────────────────
:launch

:: Check Python is available
python --version >nul 2>&1
if %ERRORLEVEL% neq 0 (
    echo.
    echo  ERROR: Python is not installed or not on PATH.
    echo  Download it from https://www.python.org/downloads/
    echo.
    pause
    exit /b 1
)

:: Install / update Python dependencies from requirements.txt
echo Checking Python dependencies...
pip install --upgrade -r requirements.txt -q
if %ERRORLEVEL% neq 0 (
    echo.
    echo  WARNING: Could not install/update dependencies. Check your internet connection.
    echo  Continuing anyway in case they are already installed...
    echo.
)
echo Dependencies ready.
echo.

cd /d "%~dp0controller"

:: ── Controller ─────────────────────────────────────────────────────────────────
:: Only start if not already running (check PID file, then verify PID is alive)
set CTRL_RUNNING=0
if exist "controller.pid" (
    set /p CTRL_PID=<"controller.pid"
    tasklist /FI "PID eq !CTRL_PID!" 2>nul | find /I "python" >nul 2>&1
    if not errorlevel 1 set CTRL_RUNNING=1
)

if "!CTRL_RUNNING!"=="1" (
    echo Controller is already running ^(PID !CTRL_PID!^) -- skipping launch.
) else (
    del "controller.pid"     >nul 2>&1
    del "controller.restart" >nul 2>&1
    echo Starting controller...
    start "ASA Cluster Controller" cmd /c python asa_cluster_controller.py
)

:: Wait for config.ini before launching the dashboard
echo Waiting for setup to complete...
:wait_config
if not exist "config.ini" (
    timeout /t 2 >nul
    goto wait_config
)

:: ── Dashboard ──────────────────────────────────────────────────────────────────
:: Only start if not already running
set DASH_RUNNING=0
if exist "dashboard.pid" (
    set /p DASH_PID=<"dashboard.pid"
    tasklist /FI "PID eq !DASH_PID!" 2>nul | find /I "python" >nul 2>&1
    if not errorlevel 1 set DASH_RUNNING=1
)

if "!DASH_RUNNING!"=="1" (
    echo Dashboard is already running ^(PID !DASH_PID!^) -- skipping launch.
) else (
    del "dashboard.pid" >nul 2>&1
    echo Starting dashboard...
    start "ASA Dashboard" cmd /c python dashboard.py
)

:: Open browser
timeout /t 2 >nul
for /f "tokens=*" %%p in ('python -c "import configparser; c=configparser.RawConfigParser(); c.read('config.ini'); print(c.get('network','web_status_port') if c.has_option('network','web_status_port') else 5000)"') do set DASH_PORT=%%p
if not defined DASH_PORT set DASH_PORT=5000
start http://localhost:%DASH_PORT%
