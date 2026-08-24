# Kintara Market v1.3.0 — Seller Intelligence implementation

## Product boundary
This build is seller-first. It intentionally contains **no marketplace purchase execution**:
- no Buy button
- no reserve call
- no Gold buy call
- no token quote/sign/confirm/recover flow
- no sweep execution
- no wallet transaction signing

Read-only marketplace information that can help a seller is retained, including current competing listings and Bought history.

## New marketplace read model
The app now uses the current marketplace read endpoints for:
- market board items, search, categories, currency and sort
- per-item Gold / $KINS stats
- 30-day official history
- recent completed sales
- current listing book
- Active / Sold / Bought account history
- active-listing floor/trend enrichment

## Seller Intelligence
Demand and supply are deliberately separated:
- **Demand:** completed sales, completed units in the last 24h, recent sales, 30-day traded-day history.
- **Supply / competition:** active available units, current listings, visible floor depth, cheaper listings, listings at/below a target sell price.

Derived seller signals include:
- liquidity tier
- supply pressure
- supply cover at the latest 24h completed-unit velocity
- visible floor-depth velocity cover
- last completed sale vs current floor
- current 30-day momentum
- seller signal such as positive momentum / defensive pricing / high competition

Derived cover values are explicitly analytical signals and are not promised sale times.

## 30-day chart behavior
`MarketChartView` mirrors the current web timeline semantics:
- 30 UTC calendar days
- actual traded days are marked from server history
- after the first trade, no-sale dates carry the previous price forward so spacing remains calendar-correct
- no-sale dates still report `no sales` during touch inspection
- low / high / percentage change / traded-day count
- touch or drag crosshair with date, unit price and completed sale count

## Selling
The existing FAST / BALANCE / PROFIT experience is preserved and expanded with:
- Gold and $KINS currency support
- Match Floor
- custom total price
- Club/non-Club single-listing quantity limit detection (10,000 / 5,000)
- visible cheaper-unit competition for each pricing mode
- richer sell-side market intelligence before creating the listing

## Active Sales
Active listings now include:
- total and unit price
- floor comparison
- market trend
- listing age
- checkout hold state
- live checkout countdown
- cancel lock while a server checkout hold is active

## Refresh behavior
The header refresh arrow is removed. At the top of the app, pull downward far enough and keep holding for approximately two seconds. The app then refreshes the current page plus Active Sales.

## Validation performed in this environment
- Purchase execution route grep: PASS — no reserve/buy/token-buy/sweep endpoints in app source.
- Java brace balance: PASS for all source files.
- Java parser-level syntax error patterns via `javac`: none found.
- Full Android build could not be run because this environment does not contain Android Platform 35 / build-tools.
