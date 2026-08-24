# Kintara Market v2.1.0 — Android game shell and market-flow polish

## v2.1.0

- Added a Premium-only long press on Settings that opens the online Kintara game in a dedicated immersive Android Activity.
- Requested portrait rotation for the game and restored the normal orientation policy when returning to the market.
- Reused the encrypted authenticated session cookie and official Kintara API/Queue/Presence/WebSocket client path; no browser chrome is shown.
- Reworked Market Flow labels into short readable names and assigned item-aware colours. Gold, Molten Rock and Brute Horn now have distinct semantic colours and purple is removed from the charts.

# Kintara Market v2.0.0 — Premium, cache and market-flow update

## v2.0.0

- Added weekly (3.99 USDC) and monthly (9.99 USDC) Premium plans, two included encrypted wallet profiles, paid extra-account slots, and five-account admin capacity.
- Gated the final Buy Now mutation behind Premium and retained exact on-chain payment verification.
- Added wallet-scoped encrypted inventory/market/flow caches, cache-first Trends, silent refresh, and stale-response protection for quantity edits.
- Added the purple long-press Trends Market Flow view for 1h/12h/24h/30d buyer spend, sold volume, and seller profit.
- Normalized Brute Horn to 100-item pricing, removed pull-to-refresh copy, repaired market detail fallback rendering, and replaced remaining stock dialogs with branded surfaces.
- Added public-mirror item-art aliases and changed the credit line to By JavadTM.

# Kintara Market v1.9.3 — Graphic Notices

## Branded in-app feedback

- Replaced all Android system toasts with one consistent in-app notification component.
- Added animated, resolution-independent badges for success, cancellation/error, warning, and information states.
- Added semantic green, red, amber, and blue accents plus a glass panel and polished entrance/exit motion.
- Listing, cancellation, validation, wallet, purchase, copy, and navigation feedback now use the same visual system.
- Removed the generic Android robot/app icon from short action messages.
- Kept the v1.9.2 Buy and recovery behavior unchanged.

# Kintara Market v1.9.2 — Visual UX

## User-facing market redesign

- Kept the v1.9.1 Buy and recovery behavior unchanged.
- Removed raw internal error codes and connection terminology from the visible interface.
- Reduced Background Game Presence to a compact Reconnect card: green when ready and yellow otherwise.
- Reconnect now randomly selects from the quietest eligible public servers and avoids the previous route when alternatives exist.
- Restored Gold + $KINS as the default market filter.
- Removed secondary Market Board and purchase-review explanations.
- Replaced technical purchase progress text with an animated shield-and-lock treatment.
- Changed the wallet action to a compact `CONNECT` button.
- Rebuilt price charts with smooth animated curves, glow, gradient fill, moving sweep, and a pulsing live point.

# Kintara Market v1.9.1 — Paid Purchase Recovery

## Paid $KINS recovery hotfix

- Fixed the missing on-chain confirmation stage between `sendTransaction` and Kintara delivery.
- Polls `getSignatureStatuses` with `searchTransactionHistory=true` for the saved first signature before server confirmation.
- Increased the server-confirm response window and distinguishes network timeout, retryable, result-unknown, on-chain failure, and paid-undeliverable states.
- Preserves a paid or ambiguous pending record until delivery succeeds or a definitive failed-payment result is received.
- A server-side `paid_listing_gone` or unresolved signature conflict no longer erases the saved transaction ID.
- Added Copy Transaction ID to the recovery dialog for support/escalation.
- Existing v1.9.0 pending purchases remain available after installing this update.

# Kintara Market v1.9.0 — Background Bank Presence

## Automatic public-server presence

- Replaced the visible embedded game with a lightweight hidden authenticated session document; the game renderer is never loaded.
- Automatically selects an available public `Server 9+` and uses the official Queue and Presence WebSocket paths.
- Matches the regional connection-token protocol, including `purpose`, zone, global display ID, and the `kt` URL parameter.
- Publishes the exact Bank Market position requested by the marketplace workflow every two seconds.
- Added queue silence detection, the stable `ahead=0` fallback used by the supplied reference client, Presence reconnect backoff, and an explicit Reconnect control.
- Buy and Sell now stop before mutation if the real background Presence socket is not ready.

## Purchase reliability retained

## Marketplace Buy

- Enabled Buy for Gold and $KINS listings.
- Added a graphical purchase review with exact item, seller, quantity, total, checkout stages, and live-session state.
- Matched Kintara's reserve, Gold buy, token quote, token confirm, release, and recovery endpoints.
- Validates the token quote against the selected listing before opening the wallet.
- Saves the complete signed transaction and its first Solana signature before broadcast.
- Retries uncertain broadcasts and server confirmation without asking the user to pay again.
- Added a persistent recovery card and a clear safe-retry warning for pending $KINS purchases.

## Visual design and official art

- Added official server artwork for all catalog resources, fish, food, bait, potions, and fishing rods.
- Added official matching art for available tools, cosmetics, pets, mounts, furniture, and property keys.
- Updated item tiles to preserve transparent artwork without cropping.
- Redesigned the market item hero, live-session card, Buy confirmation, payment progress, pending recovery, and presence-required dialogs.
- Retained the v1.7.2 rounded-square launcher icon and graphical Premium UI; pull-to-refresh is now gesture-only with no instructional overlay.

## Access scope

- Premium remains required only for Market Trends.
- Market, Buy, Sell, Inventory, all History tabs, and Settings remain free.
- Premium screens display only real plan, wallet, entitlement, and payment-state information.
