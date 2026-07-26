@echo off
title Рятувальничок - Disable autostart
cd /d "%~dp0"
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\autostart-disable.ps1"
echo.
pause
