package com.tm.kintaramarket;

import android.content.Context;

import org.json.JSONArray;
import org.json.JSONObject;

import java.nio.charset.StandardCharsets;
import java.security.MessageDigest;
import java.util.ArrayList;
import java.util.List;

/** Encrypted per-wallet inventory cache used for instant screen paints. */
public final class InventoryCacheStore {
    private static final String PREFIX = "inventory_cache_v2_";
    private InventoryCacheStore() {}

    private static String suffix(Context c) {
        String wallet = SecurePrefs.getWalletPublicKey(c);
        if (wallet == null || wallet.trim().isEmpty()) wallet = "anonymous";
        try {
            byte[] b = MessageDigest.getInstance("SHA-256").digest(wallet.getBytes(StandardCharsets.UTF_8));
            StringBuilder out = new StringBuilder();
            for (int i = 0; i < 8 && i < b.length; i++) out.append(String.format(java.util.Locale.US, "%02x", b[i] & 0xff));
            return out.toString();
        } catch (Exception ignored) { return "anonymous"; }
    }

    public static synchronized void save(Context c, List<KintaraApi.InventoryEntry> rows) {
        try {
            JSONArray a = new JSONArray();
            if (rows != null) for (KintaraApi.InventoryEntry e : rows) {
                if (e == null || e.item == null || e.stock == null) continue;
                JSONObject j = new JSONObject();
                j.put("type", e.item.type); j.put("carry", e.stock.carry); j.put("bank", e.stock.bank);
                a.put(j);
            }
            SecurePrefs.saveSecureString(c, PREFIX + suffix(c), a.toString());
        } catch (Exception ignored) {}
    }

    public static synchronized List<KintaraApi.InventoryEntry> load(Context c) {
        List<KintaraApi.InventoryEntry> out = new ArrayList<KintaraApi.InventoryEntry>();
        try {
            String raw = SecurePrefs.getSecureString(c, PREFIX + suffix(c));
            if (raw == null || raw.trim().isEmpty()) return out;
            JSONArray a = new JSONArray(raw);
            for (int i = 0; i < a.length(); i++) {
                JSONObject j = a.optJSONObject(i); if (j == null) continue;
                String type = j.optString("type", ""); if (type.isEmpty()) continue;
                int carry = Math.max(0, j.optInt("carry", 0)), bank = Math.max(0, j.optInt("bank", 0));
                if (carry + bank <= 0) continue;
                out.add(new KintaraApi.InventoryEntry(KintaraApi.findItem(type), new KintaraApi.Stock(carry, bank)));
            }
        } catch (Exception ignored) {}
        return out;
    }
}
