@echo off
setlocal EnableExtensions
chcp 65001 >nul
title GameBot - Kintara Molten Location Monitor
cd /d "C:\Users\JavadTM\Desktop\Start"
if not exist ".venv\Scripts\python.exe" (
  echo [ERROR] The project virtual environment was not found.
  pause
  exit /b 1
)
".venv\Scripts\python.exe" -m games.kintara.services.ember.runner --service-key kintara_ember
exit /b %ERRORLEVEL%
