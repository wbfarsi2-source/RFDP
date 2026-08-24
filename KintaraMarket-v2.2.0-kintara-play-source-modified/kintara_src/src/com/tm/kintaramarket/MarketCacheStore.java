package com.tm.kintaramarket;

import android.content.Context;
import android.content.SharedPreferences;

import org.json.JSONArray;
import org.json.JSONObject;

import java.nio.charset.StandardCharsets;
import java.security.MessageDigest;
import java.util.ArrayList;
import java.util.List;

/** Small persistent cache for public market responses, namespaced by wallet. */
public final class MarketCacheStore {
    private static final String PREF = "kintara_market_cache_v3_";
    private MarketCacheStore() {}

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

    private static SharedPreferences p(Context c) { return c.getSharedPreferences(PREF + suffix(c), Context.MODE_PRIVATE); }
    private static String key(String prefix, String currency, String category, String query) {
        String raw = (currency == null ? "" : currency) + "|" + (category == null ? "" : category) + "|" + (query == null ? "" : query);
        return prefix + Integer.toHexString(raw.hashCode());
    }

    public static synchronized void saveBoard(Context c, String currency, String category, String query, List<KintaraApi.MarketItem> rows) {
        try {
            JSONArray a = new JSONArray();
            if (rows != null) for (KintaraApi.MarketItem x : rows) {
                if (x == null || x.itemType == null || x.itemType.isEmpty()) continue;
                JSONObject j = new JSONObject(); j.put("itemType", x.itemType); j.put("listings", x.listings); j.put("available", x.available);
                putNullable(j, "floorGold", x.floorGold); putNullable(j, "floorToken", x.floorToken);
                putLast(j, "lastGold", x.lastGold); putLast(j, "lastToken", x.lastToken);
                putTrend(j, "trendGold", x.trendGold); putTrend(j, "trendToken", x.trendToken); a.put(j);
            }
            p(c).edit().putString(key("board_", currency, category, query), a.toString()).putLong("board_at", System.currentTimeMillis()).apply();
        } catch (Exception ignored) {}
    }

    public static synchronized List<KintaraApi.MarketItem> loadBoard(Context c, String currency, String category, String query) {
        List<KintaraApi.MarketItem> out = new ArrayList<KintaraApi.MarketItem>();
        try {
            String raw = p(c).getString(key("board_", currency, category, query), ""); if (raw.isEmpty()) return out;
            JSONArray a = new JSONArray(raw);
            for (int i = 0; i < a.length(); i++) { KintaraApi.MarketItem x = parseMarketItem(a.optJSONObject(i)); if (x != null) out.add(x); }
        } catch (Exception ignored) {}
        return out;
    }

    public static synchronized void saveLatest(Context c, String currency, String query, List<KintaraApi.Listing> rows) {
        try {
            JSONArray a = new JSONArray(); if (rows != null) for (KintaraApi.Listing x : rows) a.put(listingJson(x));
            p(c).edit().putString(key("latest_", currency, "", query), a.toString()).apply();
        } catch (Exception ignored) {}
    }

    public static synchronized List<KintaraApi.Listing> loadLatest(Context c, String currency, String query) {
        List<KintaraApi.Listing> out = new ArrayList<KintaraApi.Listing>();
        try {
            String raw = p(c).getString(key("latest_", currency, "", query), ""); if (raw.isEmpty()) return out;
            JSONArray a = new JSONArray(raw); for (int i = 0; i < a.length(); i++) { KintaraApi.Listing x = parseListing(a.optJSONObject(i)); if (x != null) out.add(x); }
        } catch (Exception ignored) {}
        return out;
    }

    public static synchronized void saveItemListings(Context c, String item, String currency, List<KintaraApi.Listing> rows) {
        try { JSONArray a=new JSONArray(); if(rows!=null)for(KintaraApi.Listing x:rows)a.put(listingJson(x)); p(c).edit().putString("item_listings_"+Integer.toHexString((item+"|"+currency).hashCode()),a.toString()).apply(); } catch(Exception ignored){}
    }
    public static synchronized List<KintaraApi.Listing> loadItemListings(Context c, String item, String currency) {
        List<KintaraApi.Listing> out=new ArrayList<KintaraApi.Listing>(); try {String raw=p(c).getString("item_listings_"+Integer.toHexString((item+"|"+currency).hashCode()),"");if(raw.isEmpty())return out;JSONArray a=new JSONArray(raw);for(int i=0;i<a.length();i++){KintaraApi.Listing x=parseListing(a.optJSONObject(i));if(x!=null)out.add(x);}}catch(Exception ignored){}return out;
    }

    public static synchronized void saveStats(Context c, String item, String currency, KintaraApi.MarketStats s) {
        if (s == null) return;
        try { String k="stats_" + Integer.toHexString((item + "|" + currency).hashCode()); p(c).edit().putString(k, statsJson(s).toString()).putLong(k+"_at",System.currentTimeMillis()).apply(); } catch (Exception ignored) {}
    }

    public static synchronized KintaraApi.MarketStats loadStats(Context c, String item, String currency) {
        try { String raw = p(c).getString("stats_" + Integer.toHexString((item + "|" + currency).hashCode()), ""); return raw.isEmpty() ? null : parseStats(new JSONObject(raw)); }
        catch (Exception ignored) { return null; }
    }
    public static synchronized long statsAge(Context c,String item,String currency){String k="stats_"+Integer.toHexString((item+"|"+currency).hashCode());long at=p(c).getLong(k+"_at",0L);return at<=0?Long.MAX_VALUE:Math.max(0,System.currentTimeMillis()-at);}

    public static synchronized long updatedAt(Context c) { return p(c).getLong("board_at", 0L); }

    private static void putNullable(JSONObject j, String k, Double v) throws Exception { if (v == null) j.put(k, JSONObject.NULL); else j.put(k, v.doubleValue()); }
    private static void putTrend(JSONObject j, String k, KintaraApi.Trend t) throws Exception { if (t == null) { j.put(k, JSONObject.NULL); return; } JSONObject x = new JSONObject(); x.put("dir", t.dir); x.put("pct", t.pct); j.put(k, x); }
    private static void putLast(JSONObject j, String k, KintaraApi.LastSale x) throws Exception { if (x == null) { j.put(k, JSONObject.NULL); return; } JSONObject a = new JSONObject(); a.put("unit", x.unit); a.put("soldAtMs", x.soldAtMs); j.put(k, a); }
    private static JSONObject listingJson(KintaraApi.Listing x) throws Exception { JSONObject j = new JSONObject(); if (x == null) return j; j.put("id", x.id); j.put("itemType", x.itemType); j.put("currency", x.currency); j.put("status", x.status); j.put("sellerName", x.sellerName); j.put("quantity", x.quantity); j.put("priceUsd", x.priceUsd); j.put("priceGold", x.priceGold); j.put("createdAtMs", x.createdAtMs); j.put("finishedAtMs", x.finishedAtMs); j.put("reservedUntilMs", x.reservedUntilMs); if (x.reservedBy != null) j.put("reservedBy", x.reservedBy); return j; }
    private static KintaraApi.Listing parseListing(JSONObject j) { if (j == null) return null; KintaraApi.Listing x = new KintaraApi.Listing(); x.id=j.optString("id",""); x.itemType=KintaraApi.normalizeItemType(j.optString("itemType",j.optString("item_type",""))); if (x.itemType.isEmpty()) return null; x.currency=j.optString("currency","token"); if("kins".equalsIgnoreCase(x.currency)||"$kins".equalsIgnoreCase(x.currency)||"usdc".equalsIgnoreCase(x.currency))x.currency="token"; if("coins".equalsIgnoreCase(x.currency))x.currency="gold"; x.status=j.optString("status",""); x.sellerName=j.optString("sellerName",""); x.quantity=Math.max(1,j.optInt("quantity",1)); x.priceUsd=j.optDouble("priceUsd",0); x.priceGold=j.optDouble("priceGold",0); x.createdAtMs=j.optLong("createdAtMs",0); x.finishedAtMs=j.optLong("finishedAtMs",0); x.reservedUntilMs=j.optLong("reservedUntilMs",0); if (j.has("reservedBy")&&!j.isNull("reservedBy")) x.reservedBy=j.optLong("reservedBy"); return x; }
    private static KintaraApi.MarketItem parseMarketItem(JSONObject j) { if (j == null) return null; String type=KintaraApi.normalizeItemType(j.optString("itemType",j.optString("item_type",""))); if (type.isEmpty()) return null; KintaraApi.MarketItem x=new KintaraApi.MarketItem(); x.itemType=type; x.listings=Math.max(0,j.optInt("listings",0)); x.available=Math.max(0,j.optInt("available",0)); x.floorGold=doubleOrNull(j,"floorGold"); x.floorToken=doubleOrNull(j,"floorToken"); x.lastGold=parseLast(j.optJSONObject("lastGold")); x.lastToken=parseLast(j.optJSONObject("lastToken")); x.trendGold=parseTrend(j.optJSONObject("trendGold")); x.trendToken=parseTrend(j.optJSONObject("trendToken")); return x; }
    private static Double doubleOrNull(JSONObject j,String k) { return j.has(k)&&!j.isNull(k)?j.optDouble(k):null; }
    private static KintaraApi.LastSale parseLast(JSONObject j) { if (j == null) return null; KintaraApi.LastSale x=new KintaraApi.LastSale(); x.unit=j.optDouble("unit",0); x.soldAtMs=j.optLong("soldAtMs",0); return x; }
    private static KintaraApi.Trend parseTrend(JSONObject j) { if (j == null) return null; KintaraApi.Trend x=new KintaraApi.Trend(); x.dir=j.optString("dir","flat"); x.pct=j.optDouble("pct",0); return x; }

    private static JSONObject statsJson(KintaraApi.MarketStats s) throws Exception {
        JSONObject j=new JSONObject(); j.put("ok",s.ok); j.put("currency",s.currency); j.put("listingsGold",s.listingsGold); j.put("listingsToken",s.listingsToken); j.put("availableGold",s.availableGold); j.put("availableToken",s.availableToken); j.put("sales24h",s.sales24h); j.put("units24h",s.units24h); j.put("historyDays",s.historyDays); putNullable(j,"floorGold",s.floorGold); putNullable(j,"floorToken",s.floorToken); putLast(j,"lastSaleGold",s.lastSaleGold); putLast(j,"lastSaleToken",s.lastSaleToken); putTrend(j,"trend",s.trend);
        JSONArray h=new JSONArray(); for(KintaraApi.HistoryPoint p:s.history){JSONObject x=new JSONObject();x.put("dayMs",p.dayMs);x.put("unit",p.unit);x.put("sales",p.sales);h.put(x);} j.put("history",h); JSONArray r=new JSONArray(); for(KintaraApi.RecentSale q:s.recent){JSONObject x=new JSONObject();x.put("quantity",q.quantity);x.put("unit",q.unit);x.put("total",q.total);x.put("soldAtMs",q.soldAtMs);r.put(x);} j.put("recent",r); return j;
    }
    private static KintaraApi.MarketStats parseStats(JSONObject j) { KintaraApi.MarketStats s=new KintaraApi.MarketStats(); s.ok=j.optBoolean("ok",false); s.currency=j.optString("currency",""); s.floorGold=doubleOrNull(j,"floorGold"); s.floorToken=doubleOrNull(j,"floorToken"); s.lastSaleGold=parseLast(j.optJSONObject("lastSaleGold")); s.lastSaleToken=parseLast(j.optJSONObject("lastSaleToken")); s.listingsGold=j.optInt("listingsGold",0); s.listingsToken=j.optInt("listingsToken",0); s.availableGold=j.optInt("availableGold",0); s.availableToken=j.optInt("availableToken",0); s.sales24h=j.optInt("sales24h",0); s.units24h=j.optInt("units24h",0); s.historyDays=j.optInt("historyDays",30); s.trend=parseTrend(j.optJSONObject("trend")); JSONArray h=j.optJSONArray("history"); if(h!=null)for(int i=0;i<h.length();i++){JSONObject x=h.optJSONObject(i);if(x==null)continue;KintaraApi.HistoryPoint pnt=new KintaraApi.HistoryPoint();pnt.dayMs=x.optLong("dayMs",0);pnt.unit=x.optDouble("unit",0);pnt.sales=x.optInt("sales",0);s.history.add(pnt);} JSONArray r=j.optJSONArray("recent"); if(r!=null)for(int i=0;i<r.length();i++){JSONObject x=r.optJSONObject(i);if(x==null)continue;KintaraApi.RecentSale q=new KintaraApi.RecentSale();q.quantity=Math.max(1,x.optInt("quantity",1));q.unit=x.optDouble("unit",0);q.total=x.optDouble("total",q.unit*q.quantity);q.soldAtMs=x.optLong("soldAtMs",0);s.recent.add(q);} return s; }
}
