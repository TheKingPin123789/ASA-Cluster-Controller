@echo off
cd /d "%~dp0"

set REPO_URL=https://github.com/TheKingPin123789/ASA-Cluster-Controller
set REPO_ZIP=%REPO_URL%/archive/refs/heads/main.zip
set DOWNLOAD_ZIP=%~dp0controller_download.zip
set EXTRACT_DIR=%~dp0controller_extract

:: ── Download controller files if missing ───────────────────────────────────
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

    del "%DOWNLOAD_ZIP%" >nul 2>&1
    rmdir /S /Q "%EXTRACT_DIR%" >nul 2>&1

    echo Files downloaded successfully.
    echo.
)

:: ── Install Python dependencies if needed ──────────────────────────────────
python -c "import flask" >nul 2>&1
if %ERRORLEVEL% neq 0 (
    echo Installing Python dependencies...
    pip install -r requirements.txt -q
)

cd /d "%~dp0controller"

:: ── Start controller ──────────────────────────────────────────────────────
start "ASA Cluster Controller" cmd /k python asa_cluster_controller.py

:: ── Start dashboard (visible window — shows the URL) ──────────────────────
start "ASA Dashboard" cmd /k python dashboard.py

:: ── Open browser ──────────────────────────────────────────────────────────
timeout /t 2 >nul
start http://localhost:5000
