GAMEBOT ROOT FIX — REPLACE FILES V1
========================================

This package contains only replacement project files. There is no installer BAT.

HOW TO APPLY
1. Stop GameBot completely.
2. Make a copy of your current Start folder.
3. Extract this ZIP directly into:
   C:\Users\JavadTM\Desktop\Start
4. Choose Replace the files in the destination.
5. IMPORTANT: manually DELETE the obsolete paths listed below.
6. Start GameBot normally with your existing START_GAMEBOT.bat.

DELETE THESE OLD SCORPIA PATCH FILES/FOLDERS IF THEY EXIST
----------------------------------------------------------
games\kintara\services\king_scorpia\
games\kintara\telegram\dunes_status.py
games\kintara\telegram\monitor_admin.py
games\kintara\services\monitor_control.py
data\kintara_monitor_flags.json
data\kintara_monitor_runtime.json

Also delete any root test files/folders whose names contain:
SCORPIA
SCORPION
DUNES_SOUTH

DO NOT DELETE
-------------
.env
.venv
data\gamebot.db (or your configured database)
games\kintara\runtime\
logs\
games\kintara\runtime\shared\ember\

WHAT THIS FIXES
---------------
- Removes The Dunes South button from the user Kintara menu.
- Removes King Scorpia routing/startup/admin integration.
- Restores clean Kintara/Molten routing from the known-good project baseline.
- Come To Molten automatically creates/synchronizes the Telegram user record
  instead of incorrectly telling the user to send /start again.
- Keeps the existing Come To Molten admin controls from the stable project.
- Fixes stale VPN/proxy route pinning in core/system_proxy.py.
- app.py rebuilds the Telegram Bot/aiohttp session after:
  * a real proxy route change, or
  * confirmed internet/VPN loss followed by recovery.
- Worker/shared Molten services remain alive while only Telegram networking is rebuilt.

Replacement files are based on the clean Start(2).rar project baseline plus the
two targeted fixes above.
