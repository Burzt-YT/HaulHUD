@echo off
set "TARGET=%APPDATA%\BeamOverlay\settings.json"
if exist "%TARGET%" (
    del "%TARGET%"
    echo Deleted %TARGET%
) else (
    echo No settings.json found at %TARGET%
)
pause
