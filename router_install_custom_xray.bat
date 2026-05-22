@echo off
setlocal
cd /d "%~dp0"
echo Installing custom Xray build to router...
echo This will NOT start VPN.
python router_install_custom_xray.py
echo.
pause
