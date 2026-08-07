@echo off
setlocal EnableExtensions EnableDelayedExpansion
chcp 65001 >nul
cd /d "%~dp0"
title GameBot Platform - Python v0.7.0 Final
set "PYTHONUNBUFFERED=1"

echo ==================================================
echo              GameBot Platform Launcher
echo ==================================================
echo Project: %CD%
echo.

if not exist "app.py" (
    echo [ERROR] app.py was not found.
    echo Put this BAT file inside the Start project folder.
    pause
    exit /b 1
)

rem Detect a working route. AUTO is direct-first and uses a proxy only as fallback.
set "DETECTED_HTTP_PROXY="
set "DETECTED_HTTPS_PROXY="
set "DETECTED_ALL_PROXY="
set "DETECTED_NO_PROXY=localhost,127.0.0.1,::1"
set "PROXY_SOURCE=direct-unverified"
set "PROXY_VERIFIED=false"
set "PROXY_URL="

if exist "scripts\detect_system_proxy.ps1" (
    for /f "usebackq tokens=1,* delims=|" %%A in (`powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%CD%\scripts\detect_system_proxy.ps1"`) do (
        if /i "%%A"=="PROXY_SOURCE" set "PROXY_SOURCE=%%B"
        if /i "%%A"=="PROXY_URL" set "PROXY_URL=%%B"
        if /i "%%A"=="HTTP_PROXY" set "DETECTED_HTTP_PROXY=%%B"
        if /i "%%A"=="HTTPS_PROXY" set "DETECTED_HTTPS_PROXY=%%B"
        if /i "%%A"=="ALL_PROXY" set "DETECTED_ALL_PROXY=%%B"
        if /i "%%A"=="NO_PROXY" set "DETECTED_NO_PROXY=%%B"
        if /i "%%A"=="PROXY_VERIFIED" set "PROXY_VERIFIED=%%B"
    )
)

rem Never keep stale proxy variables inherited from an old VPN/proxy session.
set "HTTP_PROXY="
set "HTTPS_PROXY="
set "ALL_PROXY="
set "NO_PROXY="
set "http_proxy="
set "https_proxy="
set "all_proxy="
set "no_proxy="

if defined DETECTED_HTTP_PROXY set "HTTP_PROXY=!DETECTED_HTTP_PROXY!"
if defined DETECTED_HTTPS_PROXY set "HTTPS_PROXY=!DETECTED_HTTPS_PROXY!"
if defined DETECTED_ALL_PROXY set "ALL_PROXY=!DETECTED_ALL_PROXY!"
if defined DETECTED_NO_PROXY set "NO_PROXY=!DETECTED_NO_PROXY!"
if defined HTTP_PROXY set "http_proxy=!HTTP_PROXY!"
if defined HTTPS_PROXY set "https_proxy=!HTTPS_PROXY!"
if defined ALL_PROXY set "all_proxy=!ALL_PROXY!"
if defined NO_PROXY set "no_proxy=!NO_PROXY!"

set "GAMEBOT_AUTO_PROXY_URL=!PROXY_URL!"
set "GAMEBOT_AUTO_PROXY_SOURCE=!PROXY_SOURCE!"

if defined PROXY_URL (
    echo [NETWORK] Direct route unavailable; verified proxy fallback enabled.
    echo [NETWORK] Route: !PROXY_SOURCE!
) else if /i "!PROXY_VERIFIED!"=="true" (
    echo [NETWORK] Direct Telegram connection verified.
) else (
    echo [NETWORK] No route verified yet. GameBot will still start and retry automatically.
)
echo.

rem A copied .venv is not portable: pyvenv.cfg contains the original Windows Python path.
rem Validate the interpreter itself, not only the existence of python.exe.
set "VENV_PY=%CD%\.venv\Scripts\python.exe"
set "VENV_OK=0"
if exist "!VENV_PY!" (
    "!VENV_PY!" -c "import sys; raise SystemExit(0 if sys.version_info >= (3, 11) else 1)" >nul 2>&1
    if not errorlevel 1 set "VENV_OK=1"
)

if "!VENV_OK!"=="1" (
    echo [1/4] Virtual environment found and verified.
) else (
    if exist ".venv" (
        echo [1/4] Existing virtual environment is broken or belongs to another Windows user.
        echo [1/4] Rebuilding .venv automatically...
        rmdir /s /q ".venv" >nul 2>&1
        if exist ".venv" (
            echo [ERROR] Could not remove the old .venv folder.
            echo Close programs using files inside .venv and run this launcher again.
            pause
            exit /b 1
        )
    ) else (
        echo [1/4] Creating Python virtual environment...
    )

    set "BASE_PY="
    where py >nul 2>&1
    if not errorlevel 1 (
        py -3 -c "import sys; raise SystemExit(0 if sys.version_info >= (3, 11) else 1)" >nul 2>&1
        if not errorlevel 1 set "BASE_PY=py -3"
    )

    if not defined BASE_PY (
        where python >nul 2>&1
        if not errorlevel 1 (
            python -c "import sys; raise SystemExit(0 if sys.version_info >= (3, 11) else 1)" >nul 2>&1
            if not errorlevel 1 set "BASE_PY=python"
        )
    )

    if not defined BASE_PY (
        echo [ERROR] Python 3.11 or newer was not found.
        echo Install Python and enable the Python launcher or Add Python to PATH.
        pause
        exit /b 1
    )

    !BASE_PY! -m venv ".venv"
    if errorlevel 1 (
        echo [ERROR] Virtual environment creation failed.
        pause
        exit /b 1
    )

    set "VENV_PY=%CD%\.venv\Scripts\python.exe"
    "!VENV_PY!" -c "import sys; raise SystemExit(0 if sys.version_info >= (3, 11) else 1)" >nul 2>&1
    if errorlevel 1 (
        echo [ERROR] The new virtual environment is not usable.
        pause
        exit /b 1
    )
    echo [1/4] Virtual environment rebuilt successfully.
)

echo [2/4] Checking dependencies cache...
if exist "scripts\bootstrap_dependencies.py" (
    "!VENV_PY!" "scripts\bootstrap_dependencies.py"
) else (
    "!VENV_PY!" -m pip install --disable-pip-version-check --no-input -r requirements.txt
)
if errorlevel 1 (
    echo [ERROR] Dependency setup failed.
    echo [HINT] Proxy/VPN is optional. The launcher uses direct internet first and proxy only as fallback.
    echo [HINT] Check internet/DNS access and run this file again.
    pause
    exit /b 1
)

if not exist ".env" (
    echo [3/4] Creating .env from .env.example...
    if not exist ".env.example" (
        echo [ERROR] .env.example was not found.
        pause
        exit /b 1
    )
    copy /y ".env.example" ".env" >nul
    echo.
    echo The .env file has been created and will open now.
    echo Set TELEGRAM_BOT_TOKEN, ADMIN_USER_IDS and MASTER_KEY.
    start "" notepad.exe ".env"
    echo Save the file, close Notepad, then press any key here.
    pause >nul
) else (
    echo [3/4] Existing .env found.
)

echo [4/4] Validating configuration...
"!VENV_PY!" "scripts\validate_setup.py"
if errorlevel 1 (
    echo.
    echo [ERROR] Configuration validation failed.
    echo Fix the reported settings in .env and run this file again.
    pause
    exit /b 1
)

echo.
echo ==================================================
echo Starting GameBot... Press Ctrl+C to stop.
echo Network mode: !PROXY_SOURCE!
echo ==================================================
echo.
"!VENV_PY!" "app.py"
set "EXIT_CODE=!ERRORLEVEL!"

echo.
echo GameBot stopped with exit code !EXIT_CODE!.
pause
exit /b !EXIT_CODE!
