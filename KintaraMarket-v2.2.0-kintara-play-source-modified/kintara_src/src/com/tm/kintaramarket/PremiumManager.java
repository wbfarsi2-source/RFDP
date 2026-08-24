package com.tm.kintaramarket;

import android.content.Context;
import android.content.SharedPreferences;
import android.util.Base64;

import org.json.JSONArray;
import org.json.JSONObject;

import java.io.BufferedReader;
import java.io.InputStream;
import java.io.InputStreamReader;
import java.io.OutputStream;
import java.math.BigInteger;
import java.net.HttpURLConnection;
import java.net.URL;
import java.nio.charset.StandardCharsets;
import java.security.MessageDigest;

import javax.crypto.SecretKeyFactory;
import javax.crypto.spec.PBEKeySpec;

/** Wallet-bound Premium entitlement and Solana USDC payment verification. */
public final class PremiumManager {
    public static final double PRICE_WEEKLY_USDC = 3.99d;
    public static final long AMOUNT_WEEKLY_RAW = 3_990_000L;
    public static final double PRICE_MONTHLY_USDC = 9.99d;
    public static final long AMOUNT_MONTHLY_RAW = 9_990_000L;
    /** Backwards-compatible aliases used by the transaction builder. */
    public static final double PRICE_USDC = PRICE_MONTHLY_USDC;
    public static final long AMOUNT_RAW = AMOUNT_MONTHLY_RAW;
    public static final double PRICE_EXTRA_ACCOUNT_USDC = 5.00d;
    public static final long AMOUNT_EXTRA_ACCOUNT_RAW = 5_000_000L;
    public static final int INCLUDED_ACCOUNT_LIMIT = 2;
    public static final int MAX_ACCOUNT_LIMIT = 5;
    public static final int USDC_DECIMALS = 6;
    public static final long WEEKLY_DURATION_MS = 7L * 24L * 60L * 60L * 1000L;
    public static final long MONTHLY_DURATION_MS = 30L * 24L * 60L * 60L * 1000L;
    public static final long DURATION_MS = MONTHLY_DURATION_MS;
    public static final String TREASURY = "5qyTE5sykDNnpwT8uncHqtetHHFp1qLMtnNUQZqRU5gk";
    public static final String USDC_MINT = "EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v";

    private static final String DIRECT_RPC = "https://api.mainnet-beta.solana.com";
    private static final String PREFS = "kintara_premium";
    private static final String PAID_WALLET = "paid_wallet";
    private static final String PAID_UNTIL = "paid_until";
    private static final String PAID_SIG = "paid_sig";
    private static final String PAID_OWNER = "paid_owner";
    private static final String ACCOUNT_LIMIT = "account_limit";
    private static final String LINKED_WALLETS = "linked_wallets";
    private static final String PENDING_WALLET = "pending_wallet";
    private static final String PENDING_AMOUNT = "pending_usdc_amount";
    private static final String PENDING_TS = "pending_ts";
    private static final String PENDING_SIG = "pending_sig";
    private static final String PENDING_BLOCKHASH = "pending_blockhash";
    private static final String PENDING_USER_ATA = "pending_user_ata";
    private static final String PENDING_TREASURY_ATA = "pending_treasury_ata";
    private static final String PENDING_PLAN = "pending_plan";
    private static final String PENDING_PURPOSE = "pending_purpose";
    private static final String PENDING_SLOT = "pending_slot";
    private static final String ADMIN_WALLET_SECURE = "premium_admin_wallet_v2";
    private static final String PREMIUM_OWNER_SECURE = "premium_owner_wallet_v2";
    private static final String PREMIUM_PAID_SECURE = "premium_paid_wallet_v2";
    private static final String PREMIUM_LINKED_SECURE = "premium_linked_wallets_v2";
    private static final String PREMIUM_UNTIL_SECURE = "premium_until_v2";
    private static final String PREMIUM_SIG_SECURE = "premium_signature_v2";
    private static final String PREMIUM_LIMIT_SECURE = "premium_account_limit_v2";
    private static final String ADMIN_FAILURES = "admin_failures";
    private static final String ADMIN_LOCK_UNTIL = "admin_lock_until";

    /* Only a deliberately slow one-way verifier is embedded; the admin code is not. */
    private static final int ADMIN_KDF_ROUNDS = 310_000;
    private static final String ADMIN_SALT_HEX = "ac165d038e14b96835472733d20d5eac85b98efed99bfbb5";
    private static final String ADMIN_HASH_SHA256_HEX = "6d5e3e68d8256196614198db91cc910f9e78fea0f963544823bbe6e1f7483964";
    private static final String ADMIN_HASH_SHA1_HEX = "8974cbd4c180eaf56cdd0f5952229afc3941b4da593cb1342d4b3ec4029be4da";

    public static final class Quote {
        public String wallet = "", blockhash = "", userAta = "", treasuryAta = "";
        public long amountRaw = AMOUNT_RAW, createdAtMs, durationMs = MONTHLY_DURATION_MS;
        public String planId = "monthly", purpose = "subscription";
        public int accountSlot = 0;
    }

    public static final class PaymentVerification {
        public boolean ok, safeToRetry;
        public long blockTimeMs;
        public String error = "";
    }

    public static final class AdminUnlockResult {
        public boolean ok;
        public String error = "";
    }

    private PremiumManager() {}

    private static SharedPreferences prefs(Context c) {
        return c.getSharedPreferences(PREFS, Context.MODE_PRIVATE);
    }
    private static String owner(Context c){String s=SecurePrefs.getSecureString(c,PREMIUM_OWNER_SECURE);return s.isEmpty()?prefs(c).getString(PAID_OWNER,prefs(c).getString(PAID_WALLET,"")):s;}
    private static String paidWallet(Context c){String s=SecurePrefs.getSecureString(c,PREMIUM_PAID_SECURE);return s.isEmpty()?prefs(c).getString(PAID_WALLET,""):s;}
    private static JSONArray linked(Context c){try{String s=SecurePrefs.getSecureString(c,PREMIUM_LINKED_SECURE);if(!s.isEmpty())return new JSONArray(s);}catch(Exception ignored){}try{return new JSONArray(prefs(c).getString(LINKED_WALLETS,"[]"));}catch(Exception e){return new JSONArray();}}
    private static long paidUntil(Context c,SharedPreferences p){String s=SecurePrefs.getSecureString(c,PREMIUM_UNTIL_SECURE);if(!s.isEmpty())try{return Long.parseLong(s);}catch(Exception ignored){}return p.getLong(PAID_UNTIL,0L);}
    private static String paidSignature(Context c,SharedPreferences p){String s=SecurePrefs.getSecureString(c,PREMIUM_SIG_SECURE);return s.isEmpty()?p.getString(PAID_SIG,""):s;}
    private static int storedAccountLimit(Context c,SharedPreferences p){String s=SecurePrefs.getSecureString(c,PREMIUM_LIMIT_SECURE);if(!s.isEmpty())try{return Math.max(INCLUDED_ACCOUNT_LIMIT,Integer.parseInt(s));}catch(Exception ignored){}return Math.max(INCLUDED_ACCOUNT_LIMIT,p.getInt(ACCOUNT_LIMIT,INCLUDED_ACCOUNT_LIMIT));}
    private static void saveSecureEntitlement(Context c,String ownerWallet,JSONArray a){try{SecurePrefs.saveSecureString(c,PREMIUM_OWNER_SECURE,ownerWallet==null?"":ownerWallet);SecurePrefs.saveSecureString(c,PREMIUM_PAID_SECURE,ownerWallet==null?"":ownerWallet);SecurePrefs.saveSecureString(c,PREMIUM_LINKED_SECURE,a==null?"[]":a.toString());}catch(Exception ignored){}}
    private static void saveSecureMetadata(Context c,long until,String signature,int limit){try{SecurePrefs.saveSecureString(c,PREMIUM_UNTIL_SECURE,String.valueOf(Math.max(0L,until)));SecurePrefs.saveSecureString(c,PREMIUM_SIG_SECURE,signature==null?"":signature);SecurePrefs.saveSecureString(c,PREMIUM_LIMIT_SECURE,String.valueOf(Math.max(INCLUDED_ACCOUNT_LIMIT,limit)));}catch(Exception ignored){}}

    public static boolean hasPremium(Context c) {
        String wallet = WalletAuthManager.walletPublicKey(c);
        if (wallet == null || wallet.isEmpty()) return false;
        if (wallet.equals(SecurePrefs.getSecureString(c, ADMIN_WALLET_SECURE))) return true;
        SharedPreferences p = prefs(c);
        migrateLegacyEntitlement(c,p);
        return paidUntil(c,p) > System.currentTimeMillis()
                && !paidSignature(c,p).isEmpty()
                && (wallet.equals(paidWallet(c)) || isLinkedWallet(c, wallet));
    }

    public static long premiumUntil(Context c) {
        String wallet = WalletAuthManager.walletPublicKey(c);
        if (wallet == null || wallet.isEmpty()) return 0L;
        if (wallet.equals(SecurePrefs.getSecureString(c, ADMIN_WALLET_SECURE))) return Long.MAX_VALUE;
        SharedPreferences p = prefs(c);
        migrateLegacyEntitlement(c,p);
        return (wallet.equals(paidWallet(c)) || isLinkedWallet(c, wallet)) ? paidUntil(c,p) : 0L;
    }
    private static void migrateLegacyEntitlement(Context c,SharedPreferences p){if(!SecurePrefs.getSecureString(c,PREMIUM_OWNER_SECURE).isEmpty())return;String w=p.getString(PAID_WALLET,"");if(w.isEmpty())return;try{JSONArray a=new JSONArray(p.getString(LINKED_WALLETS,"[]"));if(a.length()==0)a.put(w);saveSecureEntitlement(c,p.getString(PAID_OWNER,w),a);saveSecureMetadata(c,p.getLong(PAID_UNTIL,0L),p.getString(PAID_SIG,""),p.getInt(ACCOUNT_LIMIT,INCLUDED_ACCOUNT_LIMIT));}catch(Exception ignored){}}

    public static String statusLabel(Context c) {
        long until = premiumUntil(c);
        if (until == Long.MAX_VALUE) return "Premium • admin access";
        if (until <= System.currentTimeMillis()) return "Free";
        long d = Math.max(1L, (until - System.currentTimeMillis() + 86_399_999L) / 86_400_000L);
        return "Premium • " + d + " day" + (d == 1 ? "" : "s") + " left";
    }

    public static int accountLimit(Context c) {
        String admin = SecurePrefs.getSecureString(c, ADMIN_WALLET_SECURE);
        String wallet = WalletAuthManager.walletPublicKey(c);
        if (wallet != null && wallet.equals(admin)) return MAX_ACCOUNT_LIMIT;
        // Do not expose the previous wallet's group limit while a different,
        // unlinked wallet is active.  This keeps the paywall truthful after a
        // logout/reconnect and prevents a stale group from granting a slot.
        if (!isActiveEntitlementMember(c, wallet)) return INCLUDED_ACCOUNT_LIMIT;
        return storedAccountLimit(c,prefs(c));
    }

    public static int linkedAccountCount(Context c) {
        String wallet = WalletAuthManager.walletPublicKey(c);
        String admin = SecurePrefs.getSecureString(c, ADMIN_WALLET_SECURE);
        if (wallet == null || wallet.isEmpty()) return 0;
        if (wallet.equals(admin) || isActiveEntitlementMember(c, wallet)) {
            JSONArray a=linked(c);String ownerWallet=owner(c);return a.length()+(ownerWallet.isEmpty()||containsAccount(a,ownerWallet)?0:1);
        }
        return 0;
    }

    public static boolean canUseAccount(Context c, String wallet) {
        if (wallet == null || wallet.trim().isEmpty()) return false;
        if (wallet.equals(SecurePrefs.getSecureString(c, ADMIN_WALLET_SECURE))) return true;
        return hasPremium(c) && (wallet.equals(owner(c)) || isLinkedWallet(c, wallet));
    }

    public static synchronized boolean linkAccount(Context c, String wallet) {
        if (wallet == null || wallet.trim().isEmpty()) return false;
        SharedPreferences p = prefs(c); String ownerWallet = owner(c);
        if (ownerWallet.isEmpty() || paidUntil(c,p) <= System.currentTimeMillis()) return false;
        if (wallet.equals(ownerWallet)) return true;
        String admin = SecurePrefs.getSecureString(c, ADMIN_WALLET_SECURE);
        int limit = ownerWallet.equals(admin) ? MAX_ACCOUNT_LIMIT : storedAccountLimit(c,p);
        JSONArray a=linked(c); ensureAccount(a,ownerWallet);
        for (int i=0;i<a.length();i++) if (wallet.equals(a.optString(i, ""))) return true;
        if (a.length() >= limit) return false;
        a.put(wallet); p.edit().putString(LINKED_WALLETS, a.toString()).apply(); saveSecureEntitlement(c,ownerWallet,a); return true;
    }

    /** Called after a wallet sign-in so an included slot is assigned automatically. */
    public static synchronized boolean autoLinkCurrentAccount(Context c) {
        String wallet=WalletAuthManager.walletPublicKey(c); if(wallet==null||wallet.isEmpty())return false;
        String ownerWallet=owner(c);
        if(ownerWallet.isEmpty()||paidUntil(c,prefs(c))<=System.currentTimeMillis())return false;
        if(wallet.equals(ownerWallet)||isLinkedWallet(c,wallet))return true;
        return linkAccount(c,wallet);
    }

    private static boolean isLinkedWallet(Context c, String wallet) {
        try { JSONArray a = linked(c); for (int i=0;i<a.length();i++) if (wallet.equals(a.optString(i, ""))) return true; }
        catch (Exception ignored) {}
        return false;
    }

    /** True only when the active wallet belongs to the currently live group. */
    private static boolean isActiveEntitlementMember(Context c, String wallet) {
        if (wallet == null || wallet.trim().isEmpty()) return false;
        String admin = SecurePrefs.getSecureString(c, ADMIN_WALLET_SECURE);
        if (wallet.equals(admin)) return true;
        SharedPreferences p = prefs(c);
        migrateLegacyEntitlement(c,p);
        return paidUntil(c,p) > System.currentTimeMillis()
                && (wallet.equals(owner(c)) || isLinkedWallet(c,wallet));
    }

    public static AdminUnlockResult unlockWithAdminCode(Context c, String code) {
        AdminUnlockResult out = new AdminUnlockResult();
        String wallet = WalletAuthManager.walletPublicKey(c);
        if (wallet == null || wallet.isEmpty()) { out.error = "wallet_required"; return out; }
        SharedPreferences p = prefs(c);
        long now = System.currentTimeMillis(), locked = p.getLong(ADMIN_LOCK_UNTIL, 0L);
        if (locked > now) { out.error = "locked"; return out; }
        boolean valid = false;
        try {
            byte[] salt = hex(ADMIN_SALT_HEX);
            String algorithm = android.os.Build.VERSION.SDK_INT >= 26 ? "PBKDF2WithHmacSHA256" : "PBKDF2WithHmacSHA1";
            byte[] expected = hex(android.os.Build.VERSION.SDK_INT >= 26 ? ADMIN_HASH_SHA256_HEX : ADMIN_HASH_SHA1_HEX);
            PBEKeySpec spec = new PBEKeySpec((code == null ? "" : code).toCharArray(), salt, ADMIN_KDF_ROUNDS, 256);
            byte[] actual = SecretKeyFactory.getInstance(algorithm).generateSecret(spec).getEncoded();
            spec.clearPassword();
            valid = MessageDigest.isEqual(expected, actual);
        } catch (Exception ignored) {}
        if (!valid) {
            int failures = p.getInt(ADMIN_FAILURES, 0) + 1;
            SharedPreferences.Editor e = p.edit().putInt(ADMIN_FAILURES, failures);
            if (failures >= 5) e.putLong(ADMIN_LOCK_UNTIL, now + 30_000L).putInt(ADMIN_FAILURES, 0);
            e.apply();
            out.error = "invalid";
            return out;
        }
        try {
            SecurePrefs.saveSecureString(c, ADMIN_WALLET_SECURE, wallet);
            // Start the admin group with the admin wallet itself counted as the
            // first account.  This keeps the displayed 1/5 limit truthful and
            // leaves room for four additional connected profiles.
            JSONArray adminAccounts = new JSONArray(); adminAccounts.put(wallet);
            p.edit().remove(ADMIN_FAILURES).remove(ADMIN_LOCK_UNTIL)
                    .putInt(ACCOUNT_LIMIT, MAX_ACCOUNT_LIMIT)
                    .putString(PAID_OWNER, wallet).putString(PAID_WALLET, wallet)
                    .putString(LINKED_WALLETS, adminAccounts.toString()).apply();
            saveSecureEntitlement(c, wallet, adminAccounts);
            saveSecureMetadata(c,Long.MAX_VALUE,"admin",MAX_ACCOUNT_LIMIT);
            out.ok = true;
        } catch (Exception e) { out.error = "secure_storage_failed"; }
        return out;
    }

    public static Quote createQuote(Context c) throws Exception {
        return createQuote(c, "monthly", "subscription", 0);
    }

    public static Quote createQuote(Context c, String planId, String purpose, int accountSlot) throws Exception {
        String wallet = WalletAuthManager.walletPublicKey(c);
        if (wallet == null || wallet.isEmpty()) throw new Exception("Connect a wallet first.");
        Quote q = new Quote();
        q.wallet = wallet; q.planId = "weekly".equals(planId) ? "weekly" : ("account".equals(purpose) ? "account" : "monthly");
        q.purpose = purpose == null || purpose.trim().isEmpty() ? "subscription" : purpose;
        q.accountSlot = Math.max(0, accountSlot);
        if ("account".equals(q.purpose)) { q.amountRaw = AMOUNT_EXTRA_ACCOUNT_RAW; q.durationMs = 0L; }
        else if ("weekly".equals(q.planId)) { q.amountRaw = AMOUNT_WEEKLY_RAW; q.durationMs = WEEKLY_DURATION_MS; }
        else { q.amountRaw = AMOUNT_MONTHLY_RAW; q.durationMs = MONTHLY_DURATION_MS; }
        q.createdAtMs = System.currentTimeMillis(); q.blockhash = latestBlockhash(c);
        return q;
    }

    public static void savePending(Context c, Quote q) {
        prefs(c).edit().putString(PENDING_WALLET, q.wallet).putLong(PENDING_AMOUNT, q.amountRaw)
                .putLong(PENDING_TS, q.createdAtMs).putString(PENDING_BLOCKHASH, q.blockhash)
                .putString(PENDING_USER_ATA, q.userAta).putString(PENDING_TREASURY_ATA, q.treasuryAta)
                .putString(PENDING_PLAN, q.planId).putString(PENDING_PURPOSE, q.purpose).putInt(PENDING_SLOT, q.accountSlot).apply();
    }

    public static void savePendingAccounts(Context c, Quote q, String userAta, String treasuryAta) {
        q.userAta = userAta == null ? "" : userAta; q.treasuryAta = treasuryAta == null ? "" : treasuryAta; savePending(c, q);
    }

    public static Quote pending(Context c) {
        SharedPreferences p = prefs(c); Quote q = new Quote();
        q.wallet = p.getString(PENDING_WALLET, ""); q.amountRaw = p.getLong(PENDING_AMOUNT, AMOUNT_RAW);
        q.createdAtMs = p.getLong(PENDING_TS, 0L); q.blockhash = p.getString(PENDING_BLOCKHASH, "");
        q.userAta = p.getString(PENDING_USER_ATA, ""); q.treasuryAta = p.getString(PENDING_TREASURY_ATA, "");
        q.planId = p.getString(PENDING_PLAN, "monthly"); q.purpose = p.getString(PENDING_PURPOSE, "subscription"); q.accountSlot = p.getInt(PENDING_SLOT, 0);
        q.durationMs = "account".equals(q.purpose) ? 0L : ("weekly".equals(q.planId) ? WEEKLY_DURATION_MS : MONTHLY_DURATION_MS);
        return q;
    }

    public static void savePendingSignature(Context c, String sig) { prefs(c).edit().putString(PENDING_SIG, sig == null ? "" : sig).apply(); }
    public static String pendingSignature(Context c) { return prefs(c).getString(PENDING_SIG, ""); }

    public static void clearPending(Context c) {
        prefs(c).edit().remove(PENDING_WALLET).remove(PENDING_AMOUNT).remove(PENDING_TS).remove(PENDING_SIG)
                .remove(PENDING_BLOCKHASH).remove(PENDING_USER_ATA).remove(PENDING_TREASURY_ATA)
                .remove(PENDING_PLAN).remove(PENDING_PURPOSE).remove(PENDING_SLOT).apply();
    }

    /** Extract the first wire signature before broadcast so uncertain RPC responses are recoverable. */
    public static String extractSignature(String signedBase58) throws Exception {
        byte[] raw = Base58.decode(signedBase58); if (raw.length < 65) throw new Exception("Signed transaction is incomplete.");
        int[] shortVec = readShortVec(raw, 0); if (shortVec[0] < 1 || shortVec[1] + 64 > raw.length) throw new Exception("Signed transaction has no signature.");
        byte[] sig = new byte[64]; System.arraycopy(raw, shortVec[1], sig, 0, 64);
        boolean empty = true; for (byte b : sig) if (b != 0) { empty = false; break; }
        if (empty) throw new Exception("Wallet returned an unsigned transaction."); return Base58.encode(sig);
    }

    private static int[] readShortVec(byte[] raw, int offset) throws Exception {
        int value = 0, shift = 0, i = offset;
        while (i < raw.length && shift <= 21) { int b = raw[i++] & 0xff; value |= (b & 0x7f) << shift; if ((b & 0x80) == 0) return new int[]{value, i}; shift += 7; }
        throw new Exception("Invalid transaction signature header.");
    }

    public static String sendSignedTransaction(Context c, String signedBase58) throws Exception {
        byte[] raw = Base58.decode(signedBase58); String b64 = Base64.encodeToString(raw, Base64.NO_WRAP);
        JSONArray params = new JSONArray(); params.put(b64); JSONObject opts = new JSONObject(); opts.put("encoding", "base64");
        opts.put("skipPreflight", false); opts.put("preflightCommitment", "confirmed"); opts.put("maxRetries", 8); params.put(opts);
        JSONObject out = rpc(c, "sendTransaction", params); String sig = out.optString("result", "");
        if (sig.isEmpty()) throw new Exception(rpcError(out, "Could not broadcast USDC payment.")); return sig;
    }

    public static boolean hasUsdcBalance(Context c, String userAta, long amountRaw) throws Exception {
        JSONArray params = new JSONArray(); params.put(userAta); JSONObject opts = new JSONObject(); opts.put("commitment", "confirmed"); params.put(opts);
        try { JSONObject out = rpc(c, "getTokenAccountBalance", params); JSONObject result = out.optJSONObject("result"), value = result == null ? null : result.optJSONObject("value");
            return value != null && new BigInteger(value.optString("amount", "0")).compareTo(BigInteger.valueOf(amountRaw)) >= 0;
        } catch (Exception e) { return false; }
    }

    public static PaymentVerification verifyPayment(Context c, String signature, Quote q) throws Exception {
        PaymentVerification v = new PaymentVerification();
        if (q == null || q.wallet.isEmpty() || q.treasuryAta.isEmpty()) { v.error = "Payment state is incomplete."; v.safeToRetry = true; return v; }
        JSONArray statusParams = new JSONArray(); JSONArray sigs = new JSONArray(); sigs.put(signature); statusParams.put(sigs);
        JSONObject statusOpts = new JSONObject(); statusOpts.put("searchTransactionHistory", true); statusParams.put(statusOpts);
        JSONObject statusOut = rpc(c, "getSignatureStatuses", statusParams); JSONObject statusResult = statusOut.optJSONObject("result");
        JSONArray values = statusResult == null ? null : statusResult.optJSONArray("value"); JSONObject status = values == null ? null : values.optJSONObject(0);
        if (status == null) {
            if (!q.blockhash.isEmpty() && !isBlockhashValid(c, q.blockhash)) { v.error = "The payment quote expired without an on-chain transaction. You were not charged."; v.safeToRetry = true; }
            else v.error = "USDC payment is waiting for Solana confirmation."; return v;
        }
        Object statusErr = status.opt("err");
        if (statusErr != null && statusErr != JSONObject.NULL) { v.error = "The USDC transaction failed on Solana. You were not charged."; v.safeToRetry = true; return v; }

        JSONArray params = new JSONArray(); params.put(signature); JSONObject opts = new JSONObject(); opts.put("encoding", "jsonParsed");
        opts.put("commitment", "confirmed"); opts.put("maxSupportedTransactionVersion", 0); params.put(opts);
        JSONObject out = rpc(c, "getTransaction", params); Object rObj = out.opt("result");
        if (rObj == null || rObj == JSONObject.NULL) { v.error = "USDC payment is waiting for transaction details."; return v; }
        JSONObject tx = (JSONObject) rObj; JSONObject meta = tx.optJSONObject("meta"); Object chainErr = meta == null ? null : meta.opt("err");
        if (meta == null || (chainErr != null && chainErr != JSONObject.NULL)) { v.error = "The USDC transaction failed on Solana. You were not charged."; v.safeToRetry = true; return v; }
        long blockTime = tx.optLong("blockTime", 0L) * 1000L; v.blockTimeMs = blockTime;
        if (blockTime > 0 && q.createdAtMs > 0 && blockTime < q.createdAtMs - 10L * 60L * 1000L) { v.error = "This transaction predates the current Premium payment."; v.safeToRetry = true; return v; }

        JSONObject transaction = tx.optJSONObject("transaction"), msg = transaction == null ? null : transaction.optJSONObject("message");
        JSONArray instructions = msg == null ? null : msg.optJSONArray("instructions"); boolean transfer = containsExpectedTransfer(instructions, q);
        JSONArray innerGroups = meta.optJSONArray("innerInstructions");
        if (!transfer && innerGroups != null) for (int i = 0; i < innerGroups.length(); i++) { JSONObject group = innerGroups.optJSONObject(i); if (group != null && containsExpectedTransfer(group.optJSONArray("instructions"), q)) { transfer = true; break; } }
        if (!transfer) transfer = treasuryBalanceIncrease(meta, msg, q);
        if (!transfer) { v.error = "The confirmed transaction did not contain the expected " + String.format(java.util.Locale.US, "%.2f", q.amountRaw / 1_000_000.0d) + " USDC payment."; v.safeToRetry = true; return v; }
        v.ok = true; return v;
    }

    private static boolean containsExpectedTransfer(JSONArray instructions, Quote q) {
        if (instructions == null) return false;
        for (int i = 0; i < instructions.length(); i++) {
            JSONObject ix = instructions.optJSONObject(i); if (ix == null) continue; JSONObject parsed = ix.optJSONObject("parsed"); if (parsed == null) continue;
            String type = parsed.optString("type", ""); if (!"transferChecked".equals(type) && !"transfer".equals(type)) continue;
            JSONObject info = parsed.optJSONObject("info"); if (info == null) continue; String mint = info.optString("mint", USDC_MINT);
            String destination = info.optString("destination", ""), authority = info.optString("authority", info.optString("owner", ""));
            JSONObject tokenAmount = info.optJSONObject("tokenAmount"); String amount = tokenAmount == null ? info.optString("amount", "0") : tokenAmount.optString("amount", "0");
            try { if (USDC_MINT.equals(mint) && q.treasuryAta.equals(destination) && q.wallet.equals(authority) && new BigInteger(amount).compareTo(BigInteger.valueOf(q.amountRaw)) >= 0) return true; }
            catch (Exception ignored) {}
        }
        return false;
    }

    private static boolean treasuryBalanceIncrease(JSONObject meta, JSONObject msg, Quote q) {
        try { BigInteger before = sumTreasuryBalance(meta.optJSONArray("preTokenBalances"), msg, q), after = sumTreasuryBalance(meta.optJSONArray("postTokenBalances"), msg, q); return after.subtract(before).compareTo(BigInteger.valueOf(q.amountRaw)) >= 0; }
        catch (Exception e) { return false; }
    }

    private static BigInteger sumTreasuryBalance(JSONArray balances, JSONObject msg, Quote q) {
        BigInteger total = BigInteger.ZERO; if (balances == null) return total;
        for (int i = 0; i < balances.length(); i++) {
            JSONObject row = balances.optJSONObject(i); if (row == null || !USDC_MINT.equals(row.optString("mint", ""))) continue;
            String owner = row.optString("owner", ""), account = accountKey(msg, row.optInt("accountIndex", -1));
            if (!TREASURY.equals(owner) && !q.treasuryAta.equals(account)) continue; JSONObject ui = row.optJSONObject("uiTokenAmount");
            try { total = total.add(new BigInteger(ui == null ? "0" : ui.optString("amount", "0"))); } catch (Exception ignored) {}
        }
        return total;
    }

    private static String accountKey(JSONObject msg, int index) {
        JSONArray keys = msg == null ? null : msg.optJSONArray("accountKeys"); if (keys == null || index < 0 || index >= keys.length()) return "";
        Object key = keys.opt(index); if (key instanceof JSONObject) return ((JSONObject) key).optString("pubkey", ""); return key == null ? "" : String.valueOf(key);
    }

    private static boolean isBlockhashValid(Context c, String blockhash) {
        try { JSONArray params = new JSONArray(); params.put(blockhash); JSONObject opts = new JSONObject(); opts.put("commitment", "confirmed"); params.put(opts);
            JSONObject out = rpc(c, "isBlockhashValid", params), result = out.optJSONObject("result"); return result == null || result.optBoolean("value", true);
        } catch (Exception e) { return true; }
    }

    public static void activatePaid(Context c, String wallet, String signature, long blockTimeMs) {
        Quote q = pending(c); long duration = q.durationMs > 0 ? q.durationMs : MONTHLY_DURATION_MS;
        activatePaid(c, wallet, signature, blockTimeMs, duration, q.purpose, q.accountSlot);
    }

    public static synchronized void activatePaid(Context c, String wallet, String signature, long blockTimeMs, long durationMs, String purpose, int accountSlot) {
        if (wallet == null || wallet.trim().isEmpty()) return;
        SharedPreferences p = prefs(c); long now=System.currentTimeMillis();
        migrateLegacyEntitlement(c,p);
        long current = paidUntil(c,p);
        String oldOwner=owner(c);
        boolean existingActive=current>now && (wallet.equals(oldOwner)||isLinkedWallet(c,wallet));
        String effectiveOwner=existingActive&&!oldOwner.isEmpty()?oldOwner:wallet;
        JSONArray accounts = copyAccounts(linked(c));
        int nextLimit = existingActive ? storedAccountLimit(c,p) : INCLUDED_ACCOUNT_LIMIT;
        nextLimit = Math.min(MAX_ACCOUNT_LIMIT, Math.max(INCLUDED_ACCOUNT_LIMIT, nextLimit));

        if ("account".equals(purpose)) {
            // An account-slot payment never replaces the subscription owner or
            // the linked-wallet set.  Add the paid slot atomically after the
            // payment is verified; the old implementation tried linkAccount()
            // before increasing the limit, so the first extra slot could be
            // silently rejected.
            if (!existingActive) { clearPending(c); return; }
            nextLimit = Math.min(MAX_ACCOUNT_LIMIT, nextLimit + 1);
            ensureAccount(accounts, effectiveOwner);
            p.edit().putString(PAID_WALLET,effectiveOwner)
                    .putString(PAID_OWNER,effectiveOwner)
                    .putString(PAID_SIG,signature==null?"":signature)
                    .putLong(PAID_UNTIL,current)
                    .putInt(ACCOUNT_LIMIT,nextLimit)
                    .putString(LINKED_WALLETS,accounts.toString()).apply();
            try { saveSecureEntitlement(c,effectiveOwner,accounts); saveSecureMetadata(c,current,signature,nextLimit); }
            catch(Exception ignored) {}
            clearPending(c); return;
        }

        // A subscription paid by an unlinked/expired wallet starts a fresh
        // entitlement group.  A renewal by the owner or one of its linked
        // wallets keeps the existing group and extends from its current end.
        if (!existingActive) {
            accounts = new JSONArray(); ensureAccount(accounts,wallet); effectiveOwner=wallet; nextLimit=INCLUDED_ACCOUNT_LIMIT;
        } else {
            ensureAccount(accounts,effectiveOwner);
            if (!containsAccount(accounts,wallet) && accounts.length()<nextLimit) ensureAccount(accounts,wallet);
        }
        long base = Math.max(now, Math.max(0L, blockTimeMs));
        if (existingActive && current != Long.MAX_VALUE) base=Math.max(base,current);
        long d = durationMs > 0 ? durationMs : MONTHLY_DURATION_MS;
        long until = current == Long.MAX_VALUE ? Long.MAX_VALUE : base + d;
        p.edit().putString(PAID_WALLET,effectiveOwner)
                .putString(PAID_OWNER,effectiveOwner)
                .putString(PAID_SIG,signature==null?"":signature)
                .putLong(PAID_UNTIL,until)
                .putInt(ACCOUNT_LIMIT,nextLimit)
                .putString(LINKED_WALLETS,accounts.toString()).apply();
        try { saveSecureEntitlement(c,effectiveOwner,accounts); saveSecureMetadata(c,until,signature,nextLimit); }
        catch(Exception ignored) {}
        clearPending(c);
    }

    private static JSONArray copyAccounts(JSONArray source) {
        JSONArray out = new JSONArray();
        if (source == null) return out;
        for (int i=0;i<source.length();i++) {
            String w=source.optString(i,"");
            if (!w.isEmpty() && !containsAccount(out,w)) out.put(w);
        }
        return out;
    }
    private static boolean containsAccount(JSONArray a,String wallet) {
        if (a==null||wallet==null||wallet.isEmpty()) return false;
        for(int i=0;i<a.length();i++) if(wallet.equals(a.optString(i,""))) return true;
        return false;
    }
    private static void ensureAccount(JSONArray a,String wallet) { if(a!=null&&wallet!=null&&!wallet.isEmpty()&&!containsAccount(a,wallet)) a.put(wallet); }

    private static String latestBlockhash(Context c) throws Exception {
        JSONArray params = new JSONArray(); JSONObject opts = new JSONObject(); opts.put("commitment", "finalized"); params.put(opts);
        JSONObject out = rpc(c, "getLatestBlockhash", params); JSONObject result = out.optJSONObject("result"), value = result == null ? null : result.optJSONObject("value");
        String blockhash = value == null ? "" : value.optString("blockhash", ""); if (blockhash.isEmpty()) throw new Exception(rpcError(out, "Could not get a Solana blockhash.")); return blockhash;
    }

    private static JSONObject rpc(Context c, String method, JSONArray params) throws Exception {
        Exception relayError = null; try { return KintaraApi.solanaRpc(c, method, params); } catch (Exception e) { relayError = e; }
        try { return directRpc(method, params); } catch (Exception directError) { String m = directError.getMessage(); if ((m == null || m.isEmpty()) && relayError != null) m = relayError.getMessage(); throw new Exception(m == null || m.isEmpty() ? "Solana RPC is temporarily unavailable." : m); }
    }

    private static JSONObject directRpc(String method, JSONArray params) throws Exception {
        JSONObject req = new JSONObject(); req.put("jsonrpc", "2.0"); req.put("id", 1); req.put("method", method); req.put("params", params == null ? new JSONArray() : params);
        HttpURLConnection con = null;
        try { con = (HttpURLConnection) new URL(DIRECT_RPC).openConnection(); con.setConnectTimeout(10_000); con.setReadTimeout(14_000); con.setRequestMethod("POST");
            con.setRequestProperty("Content-Type", "application/json"); con.setRequestProperty("Accept", "application/json"); con.setDoOutput(true);
            byte[] b = req.toString().getBytes(StandardCharsets.UTF_8); try (OutputStream os = con.getOutputStream()) { os.write(b); }
            int st = con.getResponseCode(); String raw = read(st >= 400 ? con.getErrorStream() : con.getInputStream()); if (raw.trim().isEmpty()) throw new Exception("Empty Solana RPC response.");
            JSONObject out = new JSONObject(raw); if (st != 200 || (out.has("error") && !out.isNull("error"))) throw new Exception(rpcError(out, "Solana RPC is unavailable.")); return out;
        } finally { if (con != null) con.disconnect(); }
    }

    private static String rpcError(JSONObject j, String fallback) { JSONObject e = j == null ? null : j.optJSONObject("error"); String m = e == null ? "" : e.optString("message", ""); return m.isEmpty() ? fallback : m; }
    private static String read(InputStream in) throws Exception { if (in == null) return ""; StringBuilder b = new StringBuilder(); try (BufferedReader r = new BufferedReader(new InputStreamReader(in, StandardCharsets.UTF_8))) { String line; while ((line = r.readLine()) != null) b.append(line); } return b.toString(); }
    private static byte[] hex(String s) { byte[] out = new byte[s.length() / 2]; for (int i = 0; i < out.length; i++) out[i] = (byte) Integer.parseInt(s.substring(i * 2, i * 2 + 2), 16); return out; }
}
