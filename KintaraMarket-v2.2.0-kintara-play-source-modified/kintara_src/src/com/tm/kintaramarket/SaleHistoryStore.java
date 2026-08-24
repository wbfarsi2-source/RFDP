package com.tm.kintaramarket;

import android.content.Context;
import android.content.SharedPreferences;

import org.json.JSONArray;
import org.json.JSONObject;

import java.util.ArrayList;
import java.util.Collections;
import java.util.Comparator;
import java.util.HashSet;
import java.util.List;
import java.util.Locale;
import java.util.Set;

/**
 * Durable cache for this account's completed marketplace sales.
 *
 * The server is still queried first. This cache fills gaps when the marketplace
 * endpoint stops returning a completed listing after it has left Active Sales.
 */
public final class SaleHistoryStore {
    private static final String PREF = "sale_history_v2";
    private static final String KEY_SALES = "sales";
    private static final String KEY_ACTIVE = "active_snapshot";
    private static final String KEY_CANCELLED = "cancelled_ids";
    private static final String KEY_UNREAD_SOLD = "unread_sold_keys";
    private static final int MAX_SALES = 750;

    private SaleHistoryStore() {}

    private static String accountKey(Context c) {
        String wallet = SecurePrefs.getWalletPublicKey(c);
        if (wallet == null || wallet.trim().isEmpty()) wallet = "anonymous";
        try {
            java.security.MessageDigest md = java.security.MessageDigest.getInstance("SHA-256");
            byte[] b = md.digest(wallet.getBytes(java.nio.charset.StandardCharsets.UTF_8));
            StringBuilder out = new StringBuilder();
            for (int i = 0; i < 8 && i < b.length; i++) out.append(String.format(Locale.US, "%02x", b[i] & 0xff));
            return out.toString();
        } catch (Exception ignored) { return "anonymous"; }
    }

    private static SharedPreferences p(Context c) {
        return c.getSharedPreferences(PREF + "_" + accountKey(c), Context.MODE_PRIVATE);
    }

    private static JSONObject toJson(KintaraApi.Listing x) {
        JSONObject j = new JSONObject();
        try {
            j.put("id", x.id == null ? "" : x.id);
            j.put("itemType", x.itemType == null ? "" : x.itemType);
            j.put("currency", x.currency == null ? "token" : x.currency);
            j.put("status", x.status == null ? "sold" : x.status);
            j.put("quantity", Math.max(1, x.quantity));
            j.put("priceUsd", x.priceUsd);
            j.put("priceGold", x.priceGold);
            j.put("createdAtMs", x.createdAtMs);
            j.put("finishedAtMs", x.finishedAtMs);
        } catch (Exception ignored) {}
        return j;
    }

    private static KintaraApi.Listing fromJson(JSONObject j) {
        if (j == null) return null;
        String type = j.optString("itemType", "");
        if (type.isEmpty()) return null;
        KintaraApi.Listing x = new KintaraApi.Listing();
        x.id = j.optString("id", "");
        x.itemType = type;
        x.currency = j.optString("currency", "token");
        x.status = j.optString("status", "sold");
        x.quantity = Math.max(1, j.optInt("quantity", 1));
        x.priceUsd = j.optDouble("priceUsd", 0);
        x.priceGold = j.optDouble("priceGold", 0);
        x.createdAtMs = j.optLong("createdAtMs", 0);
        x.finishedAtMs = j.optLong("finishedAtMs", 0);
        return x;
    }

    private static String key(KintaraApi.Listing x) {
        if (x == null) return "";
        if (x.id != null && !x.id.trim().isEmpty()) return "id:" + x.id.trim();
        long t = x.finishedAtMs > 0 ? x.finishedAtMs : x.createdAtMs;
        // Time is rounded to a minute so the same server event from two endpoints dedupes.
        long minute = t > 0 ? t / 60000L : 0;
        return String.format(Locale.US, "%s|%d|%.8f|%.8f|%d",
                x.itemType == null ? "" : x.itemType,
                Math.max(1, x.quantity), x.priceUsd, x.priceGold, minute);
    }

    public static synchronized List<KintaraApi.Listing> getAll(Context c) {
        List<KintaraApi.Listing> out = new ArrayList<>();
        try {
            JSONArray a = new JSONArray(p(c).getString(KEY_SALES, "[]"));
            for (int i=0;i<a.length();i++) {
                KintaraApi.Listing x = fromJson(a.optJSONObject(i));
                if (x != null) out.add(x);
            }
        } catch (Exception ignored) {}
        sort(out);
        return out;
    }

    public static synchronized void mergeSales(Context c, List<KintaraApi.Listing> rows) {
        List<KintaraApi.Listing> all = getAll(c);
        java.util.LinkedHashMap<String,KintaraApi.Listing> map = new java.util.LinkedHashMap<>();
        for (KintaraApi.Listing x : all) map.put(key(x), x);
        if (rows != null) {
            for (KintaraApi.Listing x : rows) {
                if (x == null || x.itemType == null || x.itemType.isEmpty()) continue;
                if (x.finishedAtMs <= 0) x.finishedAtMs = x.createdAtMs > 0 ? x.createdAtMs : System.currentTimeMillis();
                if (x.status == null || x.status.isEmpty()) x.status = "sold";
                String k = key(x);
                KintaraApi.Listing old = map.get(k);
                // Prefer the server copy when it has richer fields.
                if (old == null || x.finishedAtMs > 0 || x.priceUsd > 0 || x.priceGold > 0) map.put(k, x);
            }
        }
        List<KintaraApi.Listing> merged = new ArrayList<>(map.values());
        sort(merged);
        if (merged.size() > MAX_SALES) merged = new ArrayList<>(merged.subList(0, MAX_SALES));
        JSONArray a = new JSONArray();
        for (KintaraApi.Listing x : merged) a.put(toJson(x));
        p(c).edit().putString(KEY_SALES, a.toString()).apply();
    }

    public static synchronized void recordSold(Context c, KintaraApi.Listing active, long when) {
        if (active == null || active.itemType == null || active.itemType.isEmpty()) return;
        KintaraApi.Listing x = new KintaraApi.Listing();
        x.id = active.id;
        x.itemType = active.itemType;
        x.currency = active.currency;
        x.status = "sold";
        x.quantity = Math.max(1, active.quantity);
        x.priceUsd = active.priceUsd;
        x.priceGold = active.priceGold;
        x.createdAtMs = active.createdAtMs;
        x.finishedAtMs = when > 0 ? when : System.currentTimeMillis();
        List<KintaraApi.Listing> one = new ArrayList<>(); one.add(x);
        mergeSales(c, one);
        markUnreadSold(c, x);
    }


    private static synchronized void markUnreadSold(Context c, KintaraApi.Listing x) {
        String k = key(x);
        if (k == null || k.isEmpty()) return;
        Set<String> s = new HashSet<>(p(c).getStringSet(KEY_UNREAD_SOLD, Collections.<String>emptySet()));
        s.add(k);
        p(c).edit().putStringSet(KEY_UNREAD_SOLD, s).apply();
    }

    public static synchronized boolean hasUnreadSold(Context c) {
        return !p(c).getStringSet(KEY_UNREAD_SOLD, Collections.<String>emptySet()).isEmpty();
    }

    public static synchronized boolean isUnreadSold(Context c, KintaraApi.Listing x) {
        String k = key(x);
        if (k == null || k.isEmpty()) return false;
        return p(c).getStringSet(KEY_UNREAD_SOLD, Collections.<String>emptySet()).contains(k);
    }

    public static synchronized void clearUnreadSold(Context c) {
        p(c).edit().remove(KEY_UNREAD_SOLD).apply();
    }

    public static synchronized void markCancelled(Context c, String id) {
        if (id == null || id.trim().isEmpty()) return;
        Set<String> s = new HashSet<>(p(c).getStringSet(KEY_CANCELLED, Collections.<String>emptySet()));
        s.add(id.trim());
        p(c).edit().putStringSet(KEY_CANCELLED, s).apply();
    }

    private static synchronized boolean consumeCancelled(Context c, String id) {
        if (id == null || id.trim().isEmpty()) return false;
        Set<String> s = new HashSet<>(p(c).getStringSet(KEY_CANCELLED, Collections.<String>emptySet()));
        boolean hit = s.remove(id.trim());
        if (hit) p(c).edit().putStringSet(KEY_CANCELLED, s).apply();
        return hit;
    }

    public static synchronized List<KintaraApi.Listing> previousActive(Context c) {
        List<KintaraApi.Listing> out = new ArrayList<>();
        try {
            JSONArray a = new JSONArray(p(c).getString(KEY_ACTIVE, "[]"));
            for (int i=0;i<a.length();i++) {
                KintaraApi.Listing x = fromJson(a.optJSONObject(i));
                if (x != null) out.add(x);
            }
        } catch (Exception ignored) {}
        return out;
    }

    /**
     * Compare the last known active snapshot with the server's current active set.
     * A disappeared listing is retained as a completed sale unless this app just
     * cancelled it. This lets website-created listings remain trackable too.
     */
    public static synchronized void reconcileActive(Context c, List<KintaraApi.Listing> current) {
        List<KintaraApi.Listing> previous = previousActive(c);
        HashSet<String> now = new HashSet<>();
        if (current != null) for (KintaraApi.Listing x : current)
            if (x != null && x.id != null && !x.id.isEmpty()) now.add(x.id);

        long when = System.currentTimeMillis();
        for (KintaraApi.Listing old : previous) {
            if (old == null || old.id == null || old.id.isEmpty() || now.contains(old.id)) continue;
            if (consumeCancelled(c, old.id)) continue;
            recordSold(c, old, when);
        }

        JSONArray a = new JSONArray();
        if (current != null) for (KintaraApi.Listing x : current) if (x != null) a.put(toJson(x));
        p(c).edit().putString(KEY_ACTIVE, a.toString()).apply();
    }

    private static void sort(List<KintaraApi.Listing> rows) {
        Collections.sort(rows, new Comparator<KintaraApi.Listing>() {
            @Override public int compare(KintaraApi.Listing a, KintaraApi.Listing b) {
                long ta = a.finishedAtMs > 0 ? a.finishedAtMs : a.createdAtMs;
                long tb = b.finishedAtMs > 0 ? b.finishedAtMs : b.createdAtMs;
                return Long.compare(tb, ta);
            }
        });
    }
}
