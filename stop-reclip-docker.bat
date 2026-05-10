@echo off
setlocal

cd /d "%~dp0"

docker compose down
echo.
echo ReClip has been stopped.
pause
