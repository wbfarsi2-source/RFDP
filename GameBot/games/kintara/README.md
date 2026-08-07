# Kintara module

This directory owns all Kintara-specific code and runtime data.

- `api/`: authenticated Kintara HTTP client.
- `telegram/`: Kintara user flows and callbacks.
- `purchases/`: purchase, admin-approval, and post-payment credential activation.
- `molten/`: Molten access policy, private-channel membership, and compact views.
- `engine/`: managed fishing and cooking engine based on the supplied Kintara runtime.
- `services/paid/`: one supervised account service per paid or trial account.
- `services/ember/`: one shared Molten monitoring process.
- `runtime/users/`: one workspace and one managed CMD per user account.
- `runtime/shared/ember/`: shared Molten state, snapshot, log, and control files.
- `manifest.json`: game-owned runtime and shared-service registration.
- `features.json`: local feature availability and visibility.

Shared services use `KINTARA_EMBER_COOKIE` or `KINTARA_COOKIE` from the project `.env` file. Paid account runtimes never use the shared project cookie. Each user credential is validated, encrypted, and stored separately.

Merchant is disabled and hidden. The spinner boundary is present but remains disabled until a verified Kintara endpoint is implemented.
