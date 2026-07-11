@echo off
setlocal enabledelayedexpansion

set "ROOT=%~dp0"
set "VENV=%ROOT%.venv"
set "PY=%VENV%\Scripts\python.exe"

if not exist "%PY%" (
    echo Creating virtual environment...
    where py >nul 2>&1
    if !errorlevel! equ 0 (
        py -3 -m venv "%VENV%"
    ) else (
        python -m venv "%VENV%"
    )
    if not exist "%PY%" (
        echo Failed to create virtual environment. Is Python 3 installed and on PATH?
        pause
        exit /b 1
    )

    echo Installing dependencies...
    "%PY%" -m pip install --upgrade pip >nul
    "%PY%" -m pip install -r "%ROOT%requirements.txt"
    if !errorlevel! neq 0 (
        echo Failed to install dependencies.
        pause
        exit /b 1
    )
)

"%PY%" "%ROOT%main.py"
if !errorlevel! neq 0 (
    echo.
    echo BeamOverlay exited with an error ^(code !errorlevel!^).
    pause
)

endlocal
