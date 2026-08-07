@echo off
setlocal EnableExtensions
chcp 65001 >nul
title Eldoria Account - Main
set "ELDORIA_ACCOUNT_ROOT=C:\Users\JavadTM\Desktop\Eldoria_Bot\Accounts\main"
set "ELDORIA_ACCOUNT_NAME=Main"

echo ========================================================================
echo ELDORIA ACCOUNT INSTANCE
echo ========================================================================
echo Account: Main
echo Runtime: C:\Users\JavadTM\Desktop\Eldoria_Bot\Accounts\main
echo Private: C:\Users\JavadTM\Desktop\Eldoria_Bot\Accounts\main\Private
echo State:   C:\Users\JavadTM\Desktop\Eldoria_Bot\Accounts\main\BotV3_3_Final\State
echo Logs:    C:\Users\JavadTM\Desktop\Eldoria_Bot\Accounts\main\BotV3_3_Final\Logs
echo Output:  C:\Users\JavadTM\Desktop\Eldoria_Bot\Accounts\main\Output
echo ========================================================================
echo This CMD belongs only to this account. Closing it stops only this account.
echo Press Ctrl+C to stop this account.
echo ========================================================================
echo.

if not exist "C:\Users\JavadTM\Desktop\Eldoria_Bot\Accounts\main\Private\cookie.txt" (
  echo ERROR: cookie.txt is missing for this account.
  pause
  exit /b 2
)
if not exist "C:\Users\JavadTM\Desktop\Eldoria_Bot\Accounts\main\Private\token.txt" (
  echo ERROR: token.txt is missing for this account.
  pause
  exit /b 2
)

"C:\Users\JavadTM\Desktop\Eldoria_Bot\.venv_shared\Scripts\python.exe" "C:\Users\JavadTM\Desktop\Eldoria_Bot\BotV3_3_Final\eldoria_bot_v3_8_fast_quest_combat_windows.py"
set "EXIT_CODE=%ERRORLEVEL%"
echo.
echo ========================================================================
echo Account process stopped. Exit code: %EXIT_CODE%
echo ========================================================================
pause
exit /b %EXIT_CODE%