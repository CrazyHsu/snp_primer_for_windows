@echo off
setlocal

set "SCRIPT_DIR=%~dp0"
powershell -NoProfile -ExecutionPolicy Bypass -File "%SCRIPT_DIR%bootstrap_and_launch.ps1" -AppRoot "%SCRIPT_DIR%.."
if errorlevel 1 pause

endlocal
