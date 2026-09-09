@echo off
setlocal
cd /d "%~dp0"
title FireGuard AI Demo

echo ========================================
echo FireGuard AI - Windows Demo Launcher
echo ========================================
echo.

set "PYTHON_CMD="
where py >nul 2>&1
if not errorlevel 1 set "PYTHON_CMD=py"

if not defined PYTHON_CMD (
    where python >nul 2>&1
    if not errorlevel 1 set "PYTHON_CMD=python"
)

if not defined PYTHON_CMD (
    echo [ERROR] Python was not found.
    echo Please install Python 3.10 or newer and enable Add Python to PATH.
    echo https://www.python.org/downloads/
    pause
    exit /b 1
)

echo [1/3] Checking Python...
%PYTHON_CMD% --version
if errorlevel 1 goto :python_error

echo.
echo [2/3] Checking dependencies...
%PYTHON_CMD% -c "import fastapi, uvicorn, pydantic" >nul 2>&1
if errorlevel 1 (
    echo Required packages are missing. Installing now...
    %PYTHON_CMD% -m pip --version >nul 2>&1
    if errorlevel 1 (
        echo pip was not found. Trying to install pip...
        %PYTHON_CMD% -m ensurepip --upgrade
    )
    %PYTHON_CMD% -m pip install -r requirements.txt
    if errorlevel 1 goto :pip_error
) else (
    echo Dependencies are ready.
)

echo.
echo [3/3] Starting server...
echo Browser URL: http://127.0.0.1:8000
echo Close this window or press Ctrl+C to stop the server.
echo.
%PYTHON_CMD% run.py
if errorlevel 1 goto :run_error

goto :end

:python_error
echo.
echo [ERROR] Python could not start correctly.
pause
exit /b 1

:pip_error
echo.
echo [ERROR] Dependency installation failed.
echo Try this command manually:
echo %PYTHON_CMD% -m pip install -r requirements.txt
pause
exit /b 1

:run_error
echo.
echo [ERROR] FireGuard AI stopped because of an error.
echo Copy the error text above if you need help.
pause
exit /b 1

:end
pause
endlocal
