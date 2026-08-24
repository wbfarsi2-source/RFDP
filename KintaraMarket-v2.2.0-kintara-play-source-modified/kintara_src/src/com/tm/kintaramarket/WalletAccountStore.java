package com.tm.kintaramarket;

import android.content.Context;

import org.json.JSONArray;
import org.json.JSONObject;

import java.util.ArrayList;
import java.util.Collections;
import java.util.Comparator;
import java.util.List;

/**
 * Encrypted, device-local wallet profile vault.
 *
 * A profile contains only the wallet session material needed to reconnect the
 * account. Private keys and recovery phrases are never present here; every
 * value is encrypted as one vault payload by SecurePrefs/Android Keystore.
 */
public final class WalletAccountStore {
    private static final String VAULT_KEY = "wallet_account_vault_v2";
    private static final String[] SESSION_KEYS = new String[]{
            "wallet_provider", "wallet_dapp_public", "wallet_dapp_secret", "wallet_shared",
            "wallet_public", "wallet_session"
    };

    public static final class AccountSummary {
        public String publicKey = "";
        public String provider = "";
        public String playerName = "";
        public long playerId;
        public long updatedAt;
    }

    private WalletAccountStore() {}

    private static JSONArray load(Context c) {
        try {
            String raw = SecurePrefs.getSecureString(c, VAULT_KEY);
            if (raw == null || raw.trim().isEmpty()) return new JSONArray();
            return new JSONArray(raw);
        } catch (Exception ignored) {
            return new JSONArray();
        }
    }

    private static void save(Context c, JSONArray rows) {
        try { SecurePrefs.saveSecureString(c, VAULT_KEY, rows == null ? "[]" : rows.toString()); }
        catch (Exception ignored) {}
    }

    /** Persist the currently active account before a logout or another wallet connect. */
    public static synchronized void saveActive(Context c) {
        if (c == null) return;
        String publicKey = SecurePrefs.getWalletPublicKey(c);
        String cookie = SecurePrefs.getCookie(c);
        if (publicKey == null || publicKey.trim().isEmpty() || cookie == null || cookie.trim().isEmpty()) return;
        try {
            JSONObject account = new JSONObject();
            account.put("publicKey", publicKey);
            account.put("provider", SecurePrefs.getWalletProvider(c));
            account.put("cookie", cookie);
            account.put("playerName", SecurePrefs.getWalletPlayerName(c));
            account.put("playerId", SecurePrefs.getWalletPlayerId(c));
            account.put("updatedAt", System.currentTimeMillis());
            JSONObject session = new JSONObject();
            for (String key : SESSION_KEYS) session.put(key, SecurePrefs.getSecureString(c, key));
            account.put("session", session);

            JSONArray old = load(c), out = new JSONArray();
            boolean replaced = false;
            for (int i = 0; i < old.length(); i++) {
                JSONObject row = old.optJSONObject(i);
                if (row == null) continue;
                if (publicKey.equals(row.optString("publicKey", ""))) {
                    if (!replaced) { out.put(account); replaced = true; }
                } else out.put(row);
            }
            if (!replaced) out.put(account);
            save(c, out);
        } catch (Exception ignored) {}
    }

    public static synchronized List<AccountSummary> summaries(Context c) {
        List<AccountSummary> out = new ArrayList<AccountSummary>();
        JSONArray rows = load(c);
        for (int i = 0; i < rows.length(); i++) {
            JSONObject row = rows.optJSONObject(i);
            if (row == null || row.optString("publicKey", "").isEmpty()) continue;
            AccountSummary a = new AccountSummary();
            a.publicKey = row.optString("publicKey", "");
            a.provider = row.optString("provider", "");
            a.playerName = row.optString("playerName", "");
            a.playerId = row.optLong("playerId", 0L);
            a.updatedAt = row.optLong("updatedAt", 0L);
            out.add(a);
        }
        Collections.sort(out, new Comparator<AccountSummary>() {
            @Override public int compare(AccountSummary a, AccountSummary b) {
                return Long.compare(b.updatedAt, a.updatedAt);
            }
        });
        return out;
    }

    public static synchronized int count(Context c) { return summaries(c).size(); }

    public static synchronized boolean contains(Context c, String publicKey) {
        if (publicKey == null || publicKey.trim().isEmpty()) return false;
        for (AccountSummary a : summaries(c)) if (publicKey.equals(a.publicKey)) return true;
        return false;
    }

    /** Switch to a saved profile without opening the wallet app again. */
    public static synchronized boolean activate(Context c, String publicKey) {
        if (c == null || publicKey == null || publicKey.trim().isEmpty()) return false;
        saveActive(c);
        JSONArray rows = load(c);
        for (int i = 0; i < rows.length(); i++) {
            JSONObject row = rows.optJSONObject(i);
            if (row == null || !publicKey.equals(row.optString("publicKey", ""))) continue;
            try {
                SecurePrefs.clearActiveWalletAuth(c);
                SecurePrefs.saveCookie(c, row.optString("cookie", ""));
                SecurePrefs.saveWalletIdentity(c, row.optString("provider", ""), publicKey);
                SecurePrefs.saveWalletPlayer(c, row.optString("playerName", ""), row.optLong("playerId", 0L));
                JSONObject session = row.optJSONObject("session");
                if (session != null) {
                    for (String key : SESSION_KEYS) SecurePrefs.saveSecureString(c, key, session.optString(key, ""));
                }
                return !SecurePrefs.getCookie(c).isEmpty();
            } catch (Exception ignored) { return false; }
        }
        return false;
    }

    /** Remove a stored profile; the active profile is cleared separately by the caller. */
    public static synchronized void remove(Context c, String publicKey) {
        if (publicKey == null || publicKey.trim().isEmpty()) return;
        JSONArray rows = load(c), out = new JSONArray();
        for (int i = 0; i < rows.length(); i++) {
            JSONObject row = rows.optJSONObject(i);
            if (row != null && !publicKey.equals(row.optString("publicKey", ""))) out.put(row);
        }
        save(c, out);
    }
}
