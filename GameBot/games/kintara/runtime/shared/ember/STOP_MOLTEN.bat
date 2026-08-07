@echo off
setlocal EnableExtensions
chcp 65001 >nul
echo stop>"%~dp0stop.request"
echo Stop request created. The platform supervisor restarts Ember while auto-start is enabled.
timeout /t 2 /nobreak >nul
