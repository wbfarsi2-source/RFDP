package com.tm.kintaramarket;

import android.content.Context;

import org.json.JSONArray;
import org.json.JSONObject;

import java.nio.charset.StandardCharsets;
import java.security.MessageDigest;

/** Encrypted, wallet-scoped cache for the computed Trends ranking. */
public final class TrendRankCacheStore {
    private static final String PREFIX = "trend_rank_cache_v1_";
    private TrendRankCacheStore() {}

    private static String key(Context c) {
        String wallet = SecurePrefs.getWalletPublicKey(c);
        if (wallet == null || wallet.trim().isEmpty()) wallet = "anonymous";
        try {
            byte[] b = MessageDigest.getInstance("SHA-256").digest(wallet.getBytes(StandardCharsets.UTF_8));
            StringBuilder out = new StringBuilder();
            for (int i = 0; i < 8; i++) out.append(String.format(java.util.Locale.US, "%02x", b[i] & 0xff));
            return PREFIX + out;
        } catch (Exception ignored) { return PREFIX + "anonymous"; }
    }

    public static synchronized void save(Context c, JSONArray rows) {
        try {
            JSONObject root = new JSONObject();
            root.put("updatedAt", System.currentTimeMillis());
            root.put("rows", rows == null ? new JSONArray() : rows);
            SecurePrefs.saveSecureString(c, key(c), root.toString());
        } catch (Exception ignored) {}
    }

    public static synchronized JSONObject load(Context c) {
        try {
            String raw = SecurePrefs.getSecureString(c, key(c));
            if (raw == null || raw.trim().isEmpty()) return null;
            return new JSONObject(raw);
        } catch (Exception ignored) { return null; }
    }

    public static synchronized long age(Context c) {
        JSONObject root=load(c); if(root==null)return Long.MAX_VALUE;
        long at=root.optLong("updatedAt",0L); return at<=0?Long.MAX_VALUE:Math.max(0,System.currentTimeMillis()-at);
    }
}
