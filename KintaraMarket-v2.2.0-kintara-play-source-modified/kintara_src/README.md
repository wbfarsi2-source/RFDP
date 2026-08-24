# Kintara Market Android v2.1.0

Live marketplace, Buy and Sell, inventory, history, seller intelligence, secure wallet authentication, and Premium Market Trends.

Market Trends, the long-press Market Flow dashboard, and the final Buy Now step require Premium. Inventory, browsing, history, and settings remain available without Premium.

## v2.1.0 changes

- Pull-to-refresh remains gesture-only; no refresh label or first-run overlay is shown.
- Market and inventory paint from wallet-scoped caches, then refresh silently; sensitive profiles, history, inventory and trend rankings use encrypted storage. Inventory edits clear stale price results immediately and discard late responses.
- Brute Horn and Molten Rock are normalized as 100-item stacks everywhere (quotes, charts, sales references, and default quantities).
- Holding the Trends tab opens a Premium Market Flow dashboard with compact readable item labels and item-aware colours (Gold is gold, Molten is orange, Brute is bronze; no chart uses purple).
- Holding the Settings tab while Premium is active opens Kintara Game in a dedicated immersive Android Activity. The device is requested to rotate to portrait, the game has no browser controls, and the official authenticated client keeps its live API/WebSocket connection to the Kintara game server.
- Premium plans are 3.99 USDC weekly or 9.99 USDC monthly. Two encrypted wallet profiles are included; additional profiles cost 5.00 USDC each, with admin access capped at five.
- Wallet profiles, entitlements, local history, inventory, and market caches are namespaced per wallet. Logging out clears only the active session.
- Missing item art falls back through aliases from the supplied public mirror; branded dialogs replace platform payment/listing dialogs. Credit is shown as `By JavadTM`.

## Marketplace Buy

Kintara's marketplace mutation APIs require the authenticated player to have a real live presence in a game server. The app now establishes that presence automatically without opening the game screen. A tiny attached WebView uses the encrypted Kintara session cookie, loads only the authenticated session endpoint, selects an available public `Server 9+`, follows the deployed Queue protocol, opens the matching Presence socket, and keeps the character online at the Bank Market position.

The background position payload is `region=bank_shop`, `x=2.5`, `y=0.41000000000000003`, `z=-0.5`, `ry=-1.5707963267948966`, `mov=false`, `le=1`, and `outfit=null`. The controller sends `q_ping` every five seconds while queued, adopts the `queue_ready` Presence token, refreshes cross-origin lobby tokens with the selected zone and global display ID, and reconnects with bounded backoff after transport loss. Buy and Sell stop before their API mutation when this live Bank Market connection is not ready.

## Online game architecture

The game entry uses a hybrid mobile-client architecture rather than duplicating the Three.js world inside native Java:

`Android App (KintaraGameActivity) → Kintara API Server → Database / account services → Game Server + Queue/Presence WebSockets`

The Activity is a native Android shell (orientation, immersive system UI, session-cookie handoff, retry and exit controls). The official Kintara game renderer remains the authoritative client, so movement, world state, matchmaking, inventory mutations and multiplayer messages continue to use the same production API and game servers as the website. This avoids a second incompatible game engine and lets server updates reach the app without repackaging a massive stale world bundle.

Gold purchases use the official reserve-then-buy endpoints. $KINS purchases mirror the current public Kintara flow: reserve the listing, request and validate the exact quote, build the Token-2022 seller/treasury/burn transaction, ask Phantom or Solflare to approve it, save the signed transaction and signature before broadcast, and retry server confirmation or recovery. A pending payment is retained so the user is warned not to pay twice.

Version 1.9.1 fixes paid-purchase recovery. After broadcast, the app now polls the saved transaction ID with Solana `getSignatureStatuses` (including transaction history) until confirmed or finalized before asking Kintara to deliver the item. Server timeouts and retryable/unknown responses keep the encrypted transaction evidence instead of collapsing into `token_confirm_failed`. Updating from 1.9.0 preserves an existing pending purchase; Recover Purchase reuses only that saved transaction and never creates a second payment.

Version 1.9.2 keeps that Buy/recovery implementation unchanged while simplifying the visible interface. Internal error codes and connection terminology are converted to user-facing messages. Background Game Presence is a compact green/yellow connection card, reconnect chooses randomly from the quietest eligible public servers and avoids the previous route when alternatives exist, the market defaults to Gold + $KINS, purchase progress uses an animated shield-and-lock graphic, and the price charts use animated curves, glow, sweep, fill, and live point motion.

Version 1.9.3 replaces every Android system toast with a branded in-app notice. Success, cancellation/error, warning, and information messages now receive their own animated vector badge, semantic accent color, glass panel, and smooth entrance/exit motion. This removes the generic Android robot icon from actions such as listing or cancelling an item while keeping the Buy and recovery implementation unchanged.

All item art packaged with this release is copied from the supplied Kintara public server mirror. Catalog resources, tools, potions, cosmetics, pets, mounts, furniture, and property keys use official artwork when the matching asset exists.

## Premium

Premium is 3.99 USDC for 7 days or 9.99 USDC for 30 days. It unlocks Market Trends, the long-press flow view, and the final Buy Now action. The Premium interface displays plan, wallet, entitlement, account-slot, and payment state. Payment uses native Solana USDC and verifies the exact mint, sender, destination token account, amount, and confirmed treasury balance change.

Administrative access uses a hidden Settings gesture and a slow one-way code verifier. Successful access is bound to the currently connected wallet and stored with Android Keystore. No wallet whitelist, plaintext admin code, admin private key, or grant-link signing key is included.

The interface and project documentation are English-only.
