@echo off
cd /d "%~dp0"

set REPO_URL=https://github.com/TheKingPin123789/ASA-Cluster-Controller
set REPO_ZIP=%REPO_URL%/archive/refs/heads/main.zip
set DOWNLOAD_ZIP=%~dp0controller_download.zip
set EXTRACT_DIR=%~dp0controller_extract

:: Download controller files if missing
if not exist "controller\asa_cluster_controller.py" (
    echo.
    echo Controller files not found. Downloading from GitHub...
    echo.

    powershell -Command "Invoke-WebRequest -Uri '%REPO_ZIP%' -OutFile '%DOWNLOAD_ZIP%'"
    if not exist "%DOWNLOAD_ZIP%" (
        echo Download failed. Check your internet connection and try again.
        pause
        exit /b 1
    )

    powershell -Command "Expand-Archive -Path '%DOWNLOAD_ZIP%' -DestinationPath '%EXTRACT_DIR%' -Force"

    xcopy /E /I /Y "%EXTRACT_DIR%\ASA-Cluster-Controller-main\controller" "controller\" >nul
    xcopy /E /I /Y "%EXTRACT_DIR%\ASA-Cluster-Controller-main\scripts" "scripts\" >nul
    copy /Y "%EXTRACT_DIR%\ASA-Cluster-Controller-main\start_controller.bat" "%~dp0start_controller.bat" >nul

    :: Clean up download artifacts
    del "%DOWNLOAD_ZIP%" >nul 2>&1
    if exist "%EXTRACT_DIR%" rmdir /S /Q "%EXTRACT_DIR%"
    if exist "%~dp0ASA-Cluster-Controller-main" rmdir /S /Q "%~dp0ASA-Cluster-Controller-main"

    echo Files downloaded successfully.
    echo.
)

:: Install Python dependencies if needed
python -c "import flask" >nul 2>&1
if %ERRORLEVEL% neq 0 (
    echo Installing Python dependencies...
    pip install -r requirements.txt -q
)

cd /d "%~dp0controller"

:: Start controller -- wizard runs here on first boot if no config.ini found
start "ASA Cluster Controller" cmd /c python asa_cluster_controller.py

:: Wait for config.ini before launching the dashboard
echo Waiting for setup to complete...
:wait_config
if not exist "config.ini" (
    timeout /t 2 >nul
    goto wait_config
)

:: Start dashboard
start "ASA Dashboard" cmd /c python dashboard.py

:: Open browser
timeout /t 2 >nul
for /f "tokens=*" %%p in ('python -c "import configparser; c=configparser.RawConfigParser(); c.read('config.ini'); print(c.get('network','web_status_port') if c.has_option('network','web_status_port') else 5000)"') do set DASH_PORT=%%p
if not defined DASH_PORT set DASH_PORT=5000
start http://localhost:%DASH_PORT%
