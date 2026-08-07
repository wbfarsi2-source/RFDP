KINTARA COME TO MOLTEN COOKIE-GATED SPECTATOR PROBE

Purpose
-------
This diagnostic checks the current official Kintara Ember entry gate while remaining
strictly inside Spectator mode.

The session cookie is used only so the official client can evaluate the account-based
Ember entry condition. It does not create a gameplay Presence session.

Safety properties
-----------------
- Presence is hard-blocked before any page script runs.
- Only WebSocket URLs containing /ws/spectate/ are allowed.
- No /ws/presence connection is allowed.
- No movement, combat, farming, chat, inventory, trade, purchase, or account-changing
  action is sent.
- No cookie value or token value is written to the report.
- terms.html is blocked.
- Kintara Club entries are excluded from the 25 normal servers.

What the probe tests
--------------------
1. Validates the session cookie with /api/auth/me.
2. Loads the official Spectator page in a temporary headless browser.
3. Uses the official trySpectatorRealmTransitionAt function for:
   world -> pond -> beach -> ember.
4. Records the exact Spectator messages and server regions.
5. Verifies that no Presence or other non-Spectator WebSocket was created.
6. If an Ember request is captured, tests anonymous, cookie, and spectate-token
   Spectator-only replay modes on representative servers.
7. If a replay mode is verified, scans the 25 normal servers and produces Top 3.

Install and run
---------------
Extract this ZIP into the GameBot project root, next to START_GAMEBOT.bat.
Close GameBot and other Kintara processes before running the diagnostic.
Run:

TEST_CTM_COOKIE_SPECTATOR.bat

Outputs
-------
diagnostics\ctm_cookie_spectator_<date>\summary.txt
diagnostics\ctm_cookie_spectator_<date>\cookie_spectator_report.json
