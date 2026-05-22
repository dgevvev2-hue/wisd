@echo off
setlocal
cd /d "%~dp0"
echo Starting router panel restore...
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0router_restore_panel.ps1"
echo.
pause
