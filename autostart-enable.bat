@echo off
title Рятувальничок - Enable autostart
cd /d "%~dp0"
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\autostart-enable.ps1"
echo.
echo Dashboard will now start silently in the background on Windows login.
pause
