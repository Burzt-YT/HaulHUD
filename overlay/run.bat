@echo off
setlocal enabledelayedexpansion

set "ROOT=%~dp0"
set "VENV=%ROOT%.venv"
set "VENV_PY=%VENV%\Scripts\python.exe"

set "GLOBAL_PY="
where py >nul 2>&1
if !errorlevel! equ 0 (
    set "GLOBAL_PY=py -3"
) else (
    where python >nul 2>&1
    if !errorlevel! equ 0 (
        set "GLOBAL_PY=python"
    )
)

set "USE_GLOBAL=0"
if defined GLOBAL_PY (
    !GLOBAL_PY! "%ROOT%check_requirements.py" "%ROOT%requirements.txt" >nul 2>&1
    if !errorlevel! equ 0 (
        set "USE_GLOBAL=1"
    )
)

if "!USE_GLOBAL!"=="1" (
    !GLOBAL_PY! "%ROOT%main.py"
    if !errorlevel! neq 0 (
        echo.
        echo HaulHUD exited with an error ^(code !errorlevel!^).
        pause
    )
    endlocal
    exit /b 0
)

if not exist "%VENV_PY%" (
    echo Existing Python install doesn't have everything HaulHUD needs.
    echo Setting up an isolated virtual environment instead...
    if defined GLOBAL_PY (
        !GLOBAL_PY! -m venv "%VENV%"
    ) else (
        echo No Python 3 installation found on PATH.
        echo Install Python 3 from https://www.python.org/downloads/ and try again.
        pause
        exit /b 1
    )
    if not exist "%VENV_PY%" (
        echo Failed to create virtual environment.
        pause
        exit /b 1
    )

    echo Installing dependencies into the virtual environment...
    "%VENV_PY%" -m pip install --upgrade pip >nul
    "%VENV_PY%" -m pip install -r "%ROOT%requirements.txt"
    if !errorlevel! neq 0 (
        echo Failed to install dependencies.
        pause
        exit /b 1
    )
)

"%VENV_PY%" "%ROOT%main.py"
if !errorlevel! neq 0 (
    echo.
    echo HaulHUD exited with an error ^(code !errorlevel!^).
    pause
)

endlocal
