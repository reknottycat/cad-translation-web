@echo off
setlocal

cd /d "%~dp0"

if not exist "logs" mkdir "logs"

where python >nul 2>nul
if %errorlevel%==0 (
    set "PYTHON=python"
) else (
    where py >nul 2>nul
    if %errorlevel%==0 (
        set "PYTHON=py -3"
    ) else (
        echo Python was not found. Please install Python 3.10+ and try again.
        pause
        exit /b 1
    )
)

set "DELIVERY_ROOT=%CD%"
set "BACKEND_ENTRY=%DELIVERY_ROOT%\backend\run_server.py"
set "FRONTEND_DIST=%DELIVERY_ROOT%\frontend\dist"
set "APP_URL=http://127.0.0.1:8000/"

echo ============================================================
echo CAD Translation Delivery Launcher
echo ============================================================
echo Delivery root: %DELIVERY_ROOT%
echo Backend entry: %BACKEND_ENTRY%
echo Frontend dist: %FRONTEND_DIST%
echo Service URL: %APP_URL%
echo ============================================================

if not exist "%BACKEND_ENTRY%" (
    echo Backend entry was not found.
    pause
    exit /b 1
)

if not exist "%FRONTEND_DIST%\index.html" (
    echo Frontend dist was not found.
    pause
    exit /b 1
)

set "ASYNC_TASKS_MODE=local"
set "HOST=127.0.0.1"
set "PORT=8000"
set "DEBUG=false"

start "" cmd /c "timeout /t 3 /nobreak >nul && start \"\" \"%APP_URL%\""
%PYTHON% "%BACKEND_ENTRY%"

endlocal
