@echo off
setlocal
pushd "%~dp0" >nul
powershell -NoProfile -ExecutionPolicy Bypass -File ".\qmt_bridge_control.ps1" -Action use-big-qmt %*
set EXITCODE=%ERRORLEVEL%
popd >nul
pause
exit /b %EXITCODE%
