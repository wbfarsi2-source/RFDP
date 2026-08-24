# Paid $KINS purchase recovery (v1.9.1)

If a wallet-approved purchase returns to the app but delivery is still pending:

1. Do not repeat the purchase.
2. Do not uninstall the app, clear its data, or sign out.
3. Install v1.9.1 over v1.9.0 so Android preserves the encrypted pending record.
4. Open Market and tap **RECOVER** once.
5. Recovery rebroadcasts only the already-signed transaction when needed, waits for Solana confirmation, and then asks Kintara to deliver the item. It never opens the wallet or creates a second payment.
6. If delivery remains pending, use **COPY TRANSACTION ID** and retain it for support.

The pending record is cleared only after successful delivery or a definitive failed-on-chain status showing that the token transfer did not complete.
