package com.tm.kintaramarket;

import android.content.Context;
import android.util.Base64;

import org.json.JSONArray;
import org.json.JSONObject;

import java.io.BufferedReader;
import java.io.InputStream;
import java.io.InputStreamReader;
import java.io.OutputStream;
import java.net.HttpURLConnection;
import java.net.URL;
import java.net.URLEncoder;
import java.math.BigInteger;
import java.nio.charset.StandardCharsets;
import java.util.ArrayList;
import java.util.Collections;
import java.util.Comparator;
import java.util.List;
import java.util.Locale;
import java.util.LinkedHashMap;
import java.util.Map;
import java.util.regex.Matcher;
import java.util.regex.Pattern;
import java.util.concurrent.Callable;
import java.util.concurrent.ExecutorService;
import java.util.concurrent.Executors;
import java.util.concurrent.Future;

public final class KintaraApi {
    public static final String BASE = "https://kintara.com/play";
    public static final String UA = "Mozilla/5.0 (Linux; Android 14; KintaraMarket/2.1.0) AppleWebKit/537.36 Chrome/151.0.0.0 Mobile Safari/537.36";
    public static final int MARKET_STACK_MAX_NONMEMBER = 5000;
    public static final int MARKET_STACK_MAX_MEMBER = 10000;
    public static final int MARKET_STACK_MAX = MARKET_STACK_MAX_MEMBER;
    public static final int MAX_STACK = 10000;
    private static final int INV_LEN = 24;
    private static final int HOTBAR_LEN = 6;
    private static final int BANK_PAGE_SIZE = 28;

    public static final class Item {
        public final String section, group, label, type;
        public Item(String section, String group, String label, String type) {
            this.section = section; this.group = group; this.label = label; this.type = type;
        }
        @Override public String toString() { return group + "  •  " + label; }
    }

    public static final Item[] CATALOG = new Item[] {
        new Item("Gold & Fish", "Gold", "Gold", "gold"),
        new Item("Gold & Fish", "Materials", "Molten Rock", "molten_rock"),
        new Item("Gold & Fish", "Raw Fish", "Herring", "fish"),
        new Item("Gold & Fish", "Raw Fish", "Trout", "fish_trout"),
        new Item("Gold & Fish", "Raw Fish", "Bass", "fish_bass"),
        new Item("Gold & Fish", "Raw Fish", "Tuna", "fish_tuna"),
        new Item("Gold & Fish", "Cooked Fish", "Cooked Herring", "cooked_fish_meat"),
        new Item("Gold & Fish", "Cooked Fish", "Cooked Trout", "cooked_trout"),
        new Item("Gold & Fish", "Cooked Fish", "Cooked Bass", "cooked_bass"),
        new Item("Gold & Fish", "Cooked Fish", "Cooked Tuna", "cooked_tuna"),
        new Item("Gold & Fish", "Burnt Fish", "Burnt Herring", "burnt_herring"),
        new Item("Gold & Fish", "Burnt Fish", "Burnt Trout", "burnt_trout"),
        new Item("Gold & Fish", "Burnt Fish", "Burnt Bass", "burnt_bass"),
        new Item("Gold & Fish", "Burnt Fish", "Burnt Tuna", "burnt_tuna"),
        new Item("Gold & Fish", "Hunting", "Brute Horn", "brute_horn"),

        new Item("Other Items", "Fishing Rods", "Level 2 Fishing Rod", "tool_fishing_rod_t2"),
        new Item("Other Items", "Fishing Rods", "Fire Resistant Fishing Rod", "tool_fishing_rod_fireproof"),
        new Item("Other Items", "Baits", "Feather Bait", "bait_feather"),
        new Item("Other Items", "Baits", "Trout Bait", "bait_trout"),
        new Item("Other Items", "Baits", "Bass Bait", "bait_bass"),
        new Item("Other Items", "Baits", "Tuna Bait", "bait_tuna"),
        new Item("Other Items", "Materials", "Stone", "stone"),
        new Item("Other Items", "Materials", "Wood", "wood"),
        new Item("Other Items", "Materials", "Coal", "coal"),
        new Item("Other Items", "Materials", "Iron Ore", "metal"),
        new Item("Other Items", "Materials", "Copper Ingot", "copper_ingot"),
        new Item("Other Items", "Materials", "Iron Ingot", "iron_ore"),
        new Item("Other Items", "Materials", "Silver Ore", "silver_ore"),
        new Item("Other Items", "Materials", "Silver Ingot", "silver_ingot"),
        new Item("Other Items", "Materials", "Cacti", "cacti"),
        new Item("Other Items", "Materials", "Feather", "feather"),
        new Item("Other Items", "Food", "Raw Chicken", "raw_chicken"),
        new Item("Other Items", "Food", "Cooked Chicken", "cooked_chicken"),
        new Item("Other Items", "Other", "Angler Raffle Ticket", "angler_raffle_ticket"),
        new Item("Other Items", "Other", "Health Potion", "potion_health"),
        new Item("Other Items", "Other", "Health Potion+", "potion_health_l2"),
        new Item("Other Items", "Other", "Shield Potion", "potion_shield"),
        new Item("Other Items", "Other", "Strength Potion", "potion_strength"),
        new Item("Other Items", "Other", "Poison Potion", "potion_poison")
    };

    public static List<Item> itemsForSection(String section) {
        List<Item> out = new ArrayList<>();
        for (Item i : CATALOG) if (i.section.equals(section)) out.add(i);
        return out;
    }
    public static Item findItem(String type) {
        String normalized=normalizeItemType(type);
        for (Item i : CATALOG) if (i.type.equals(normalized)) return i;
        return new Item("Inventory", "Other", humanizeType(normalized), normalized);
    }

    public static String humanizeType(String type) {
        if (type == null || type.trim().isEmpty()) return "Unknown Item";
        String[] parts = type.replace('-', '_').split("_");
        StringBuilder out = new StringBuilder();
        for (String part : parts) {
            if (part.isEmpty()) continue;
            if (out.length() > 0) out.append(' ');
            if (part.length() <= 2 && ("t2".equalsIgnoreCase(part) || "hp".equalsIgnoreCase(part))) out.append(part.toUpperCase(Locale.US));
            else out.append(Character.toUpperCase(part.charAt(0))).append(part.substring(1));
        }
        return out.length() == 0 ? type : out.toString();
    }

    public static final class HttpResult {
        public int status; public JSONObject json; public String raw;
        HttpResult(int status, JSONObject json, String raw) { this.status=status; this.json=json; this.raw=raw; }
    }
    public static final class Stock {
        public int total, carry, bank;
        Stock(int carry, int bank) { this.carry=carry; this.bank=bank; this.total=carry+bank; }
    }
    public static final class InventoryEntry {
        public final Item item; public final Stock stock;
        InventoryEntry(Item item, Stock stock) { this.item=item; this.stock=stock; }
    }
    public static final class Quote {
        public double fast, normal, profit, fastUnit, normalUnit, profitUnit;
        public double floorUnit, recentUnit, historyUnit;
        public int rowsSeen, cleanRows, comparableRows;
        public String confidence = "LOW", basis = "";
    }
    public static final class Sample {
        public String date; public int sales; public Double avgUnitPrice;
    }
    public static final class Stats {
        public boolean ok; public String error; public Double avg30d; public final List<Sample> samples = new ArrayList<>();
        public Sample sampleFor(String date) { for (Sample s:samples) if (date.equals(s.date)) return s; return null; }
    }
    public static final class SellResult {
        public boolean ok; public String error, message; public Double medianTotal; public double price;
        public int movedFromBank; public String fleet; public int shardId;
    }
    public static final class Trend {
        public String dir = "flat";
        public double pct;
    }
    public static final class LastSale {
        public double unit;
        public long soldAtMs;
    }
    public static final class MarketItem {
        public String itemType;
        public int listings, available, sales24h, units24h;
        public double activityScore;
        public Double floorGold, floorToken;
        public LastSale lastGold, lastToken;
        public Trend trendGold, trendToken;
        public String label() { return findItem(itemType).label; }
    }
    public static final class HistoryPoint {
        public long dayMs;
        public double unit;
        public int sales;
    }
    public static final class RecentSale {
        public int quantity;
        public double unit, total;
        public long soldAtMs;
    }
    public static final class MarketStats {
        public boolean ok;
        public String error, currency;
        public Double floorGold, floorToken;
        public LastSale lastSaleGold, lastSaleToken;
        public int listingsGold, listingsToken, availableGold, availableToken, sales24h, units24h, historyDays = 30;
        public Trend trend;
        public final List<HistoryPoint> history = new ArrayList<>();
        public final List<RecentSale> recent = new ArrayList<>();
        public Double floorFor(String cur){ return "token".equals(cur) ? floorToken : floorGold; }
        public int listingsFor(String cur){ return "token".equals(cur) ? listingsToken : listingsGold; }
        public int availableFor(String cur){ return "token".equals(cur) ? availableToken : availableGold; }
        public LastSale lastFor(String cur){ return "token".equals(cur) ? lastSaleToken : lastSaleGold; }
    }
    /** Small immutable result used by the background Trends/flow collector. */
    public static final class MarketStatsTask {
        public String itemType = "", currency = "";
        public MarketStats stats;
    }
    public static final class SellerIntel {
        public int visibleListings, visibleUnits, floorListings, floorUnits, cheaperListings, cheaperUnits, atOrBelowListings, atOrBelowUnits, tradedDays;
        public int sales24h, units24h, marketAvailable;
        public double floorUnit, selectedUnit, deltaPct, supplyToDailySales, supplyCoverHours, floorClearHours, lastSaleVsFloorPct;
        public Double lastSaleUnit;
        public String pressure = "UNKNOWN", liquidity = "NO DATA", sellSignal = "NO SIGNAL";
    }

    public static final class Listing {
        public String id, itemType, currency, status, sellerName;
        public int quantity;
        public double priceUsd, priceGold;
        public long createdAtMs, finishedAtMs, reservedUntilMs;
        public Long reservedBy;
        public Double floorUnit;
        public Trend trend;
        public String label() { return findItem(itemType).label; }
        public double totalPrice(){ return "token".equals(currency) ? priceUsd : priceGold; }
        public double unitPrice(){ return totalPrice()/Math.max(1,quantity); }
        public boolean inCheckout(){ return reservedUntilMs > System.currentTimeMillis(); }
    }
    public static final class CancelResult {
        public boolean ok; public String error, message;
    }
    public static final class BuyReserve {
        public boolean ok; public String error, message; public long expiresAtMs;
    }
    public static final class BuyResult {
        public boolean ok, resultUnknown, retryable, networkError;
        public String error, message;
        public JSONObject backpack;
        public long stateSeq;
        public int quantity, httpStatus;
    }
    public static final class TokenQuoteResult {
        public boolean ok; public String error, message; public JSONObject quote; public long expiresAtMs;
    }

    private KintaraApi() {}

    public static HttpResult request(Context context, String method, String path, JSONObject body, int timeoutMs) {
        HttpURLConnection c = null;
        try {
            URL url = new URL(BASE + path);
            c = (HttpURLConnection) url.openConnection();
            c.setConnectTimeout(timeoutMs);
            c.setReadTimeout(timeoutMs);
            c.setRequestMethod(method);
            c.setRequestProperty("User-Agent", UA);
            c.setRequestProperty("Accept", "application/json,text/plain,*/*");
            c.setRequestProperty("Origin", BASE);
            c.setRequestProperty("Referer", BASE + "/play");
            String cookie = SecurePrefs.getCookie(context);
            if (!cookie.isEmpty()) c.setRequestProperty("Cookie", cookie);
            if (body != null) {
                c.setDoOutput(true);
                c.setRequestProperty("Content-Type", "application/json");
                byte[] bytes = body.toString().getBytes(StandardCharsets.UTF_8);
                try (OutputStream os = c.getOutputStream()) { os.write(bytes); }
            }
            int status = c.getResponseCode();
            InputStream is = status >= 400 ? c.getErrorStream() : c.getInputStream();
            String raw = readAll(is);
            JSONObject json;
            try { json = raw == null || raw.trim().isEmpty() ? new JSONObject() : new JSONObject(raw); }
            catch (Exception e) { json = new JSONObject(); }
            return new HttpResult(status, json, raw == null ? "" : raw);
        } catch (Exception e) {
            return new HttpResult(0, new JSONObject(), e.toString());
        } finally {
            if (c != null) c.disconnect();
        }
    }

    private static String readAll(InputStream is) throws Exception {
        if (is == null) return "";
        StringBuilder b = new StringBuilder();
        try (BufferedReader r = new BufferedReader(new InputStreamReader(is, StandardCharsets.UTF_8))) {
            String line; while ((line=r.readLine()) != null) b.append(line).append('\n');
        }
        return b.toString();
    }

    public static boolean validateCookie(Context context, String cookie) throws Exception {
        String old = SecurePrefs.getCookie(context);
        SecurePrefs.saveCookie(context, cookie.trim());
        HttpResult r = request(context, "GET", "/api/auth/me", null, 12000);
        boolean ok = r.status == 200 && r.json.optBoolean("ok", true) && r.json.opt("player") != null;
        if (!ok) {
            if (old.isEmpty()) SecurePrefs.clearCookie(context); else SecurePrefs.saveCookie(context, old);
        }
        return ok;
    }

    public static JSONObject getMe(Context context) throws Exception {
        HttpResult r = request(context, "GET", "/api/auth/me", null, 12000);
        if (r.status == 401 || r.status == 403) throw new Exception("Session expired — reconnect wallet");
        if (r.status != 200 || !r.json.optBoolean("ok", true) || r.json.opt("player") == null)
            throw new Exception("/api/auth/me failed: " + r.status + " " + r.json.optString("error", r.raw));
        return r.json;
    }

    private static String categoryFor(String item) {
        item=normalizeItemType(item);
        if ("gold".equals(item)) return "cat_gold";
        String[] food = {"fish","cooked_fish_meat","fish_trout","fish_bass","fish_tuna","cooked_trout","cooked_bass","cooked_tuna","raw_chicken","cooked_chicken"};
        for (String x:food) if (x.equals(item)) return "cat_food";
        String[] materials = {"wood","stone","coal","metal","copper_ingot","iron_ore","silver_ore","silver_ingot","molten_rock","brute_horn","cacti","feather","bait_feather","bait_trout","bait_bass","bait_tuna","angler_raffle_ticket","burnt_herring","burnt_trout","burnt_bass","burnt_tuna"};
        for (String x:materials) if (x.equals(item)) return "cat_materials";
        if (item.startsWith("potion_")) return "cat_potions";
        return "all";
    }

    private static String enc(String s) throws Exception { return URLEncoder.encode(s, "UTF-8"); }

    /** Normalize labels used by the public mirror and older API responses. */
    public static String normalizeItemType(String item) {
        if (item == null) return "";
        String t = item.trim().toLowerCase(Locale.US).replace('-', '_').replace(' ', '_');
        if ("trout".equals(t) || "raw_trout".equals(t)) return "fish_trout";
        if ("herring".equals(t) || "raw_herring".equals(t) || "fish_meat".equals(t)) return "fish";
        if ("bass".equals(t) || "raw_bass".equals(t)) return "fish_bass";
        if ("tuna".equals(t) || "raw_tuna".equals(t)) return "fish_tuna";
        if ("moltenrock".equals(t) || "molten_rock".equals(t) || "molten-rock".equals(t)) return "molten_rock";
        if ("brutehorn".equals(t) || "brute_horn".equals(t) || "brute-horn".equals(t)) return "brute_horn";
        if ("cook_trout".equals(t)) return "cooked_trout";
        if ("cook_herring".equals(t)) return "cooked_fish_meat";
        if ("burnt_trout".equals(t) || "burned_trout".equals(t)) return "burnt_trout";
        if ("gold_coins".equals(t) || "coins".equals(t)) return "gold";
        return t;
    }

    /** Load one stats response, preferring a recent per-wallet cache on failure. */
    public static MarketStatsTask loadStatsTask(Context context, String item, String currency) {
        MarketStatsTask out = new MarketStatsTask();
        final String walletAtStart = SecurePrefs.getWalletPublicKey(context);
        out.itemType = normalizeItemType(item); out.currency = "gold".equals(currency) ? "gold" : "token";
        MarketStats warm=MarketCacheStore.loadStats(context,out.itemType,out.currency);
        if(warm!=null&&warm.ok&&MarketCacheStore.statsAge(context,out.itemType,out.currency)<120000L){out.stats=warm;return out;}
        try {
            out.stats = getItemMarket(context, out.itemType, out.currency);
            // A wallet switch can happen while the network request is in flight.
            // Never write the old account's response into the newly active wallet's
            // cache namespace.
            if (out.stats != null && out.stats.ok && walletAtStart.equals(SecurePrefs.getWalletPublicKey(context)))
                MarketCacheStore.saveStats(context, out.itemType, out.currency, out.stats);
        } catch (Exception ignored) {
            out.stats = MarketCacheStore.loadStats(context, out.itemType, out.currency);
        }
        if (out.stats == null || !out.stats.ok) out.stats = warm != null && warm.ok ? warm : MarketCacheStore.loadStats(context, out.itemType, out.currency);
        return out;
    }

    private static JSONArray fetchListings(Context context, String item, String category, String currency, int limit) throws Exception {
        String cur = "gold".equals(currency) ? "gold" : "token";
        String path = "/api/marketplace/listings?sort=cheap&currency=" + enc(cur) + "&category=" + enc(category) + "&itemType=" + enc(item) + "&limit=" + Math.max(1,Math.min(100,limit)) + "&offset=0";
        HttpResult r = request(context, "GET", path, null, 30000);
        JSONObject j=unwrapData(r.json); if (r.status != 200 || !j.optBoolean("ok", true)) return new JSONArray();
        return firstArray(j,"listings","items","rows");
    }

    public static List<JSONObject> listings(Context context, String item, String currency) throws Exception {
        String category = categoryFor(item);
        JSONArray a = fetchListings(context, item, category, currency, 100);
        if (a.length()==0 && !"all".equals(category)) a = fetchListings(context, item, "all", currency, 100);
        List<JSONObject> out = new ArrayList<>();
        for (int i=0;i<a.length();i++) {
            JSONObject row = a.optJSONObject(i); if (row==null) continue;
            if (!item.equals(row.optString("itemType"))) continue;
            if (!currency.equals(row.optString("currency", "gold"))) continue;
            if ("token".equals(currency)) { if (row.has("priceUsd") && !row.isNull("priceUsd")) out.add(row); }
            else if (row.has("priceGold") || row.has("price") || "gold".equals(row.optString("currency"))) out.add(row);
        }
        return out;
    }
    public static List<JSONObject> listings(Context context, String item) throws Exception { return listings(context,item,"token"); }

    private static int qty(JSONObject row) { return Math.max(1, (int)Math.round(row.optDouble("quantity", 1))); }
    private static double unit(JSONObject row, String currency) {
        double total = "token".equals(currency) ? row.optDouble("priceUsd",0) : row.optDouble("priceGold",row.optDouble("price",0));
        return total / qty(row);
    }
    private static double unit(JSONObject row) { return unit(row,"token"); }

    private static double percentile(List<Double> sorted, double p) {
        if (sorted.isEmpty()) return 0;
        if (sorted.size()==1) return sorted.get(0);
        double pos=(sorted.size()-1)*Math.max(0,Math.min(1,p));
        int lo=(int)Math.floor(pos), hi=Math.min(sorted.size()-1,lo+1);
        double f=pos-lo; return sorted.get(lo)*(1-f)+sorted.get(hi)*f;
    }
    private static double median(List<Double> a) {
        if (a.isEmpty()) return 0;
        int n=a.size(); return n%2==1 ? a.get(n/2) : (a.get(n/2-1)+a.get(n/2))/2.0;
    }

    private static double clamp(double v,double lo,double hi){return Math.max(lo,Math.min(hi,v));}
    private static double quantizeTotal(double total,String currency){if("token".equals(currency))return Math.max(.01,Math.round(total*100.0)/100.0);return Math.max(1,Math.round(total));}
    private static double weightedRecentUnit(MarketStats stats){
        if(stats==null||stats.recent==null||stats.recent.isEmpty())return 0;
        List<RecentSale> rows=new ArrayList<RecentSale>();for(RecentSale x:stats.recent)if(x!=null&&x.unit>0)rows.add(x);if(rows.isEmpty())return 0;
        Collections.sort(rows,new Comparator<RecentSale>(){public int compare(RecentSale a,RecentSale b){return Double.compare(a.unit,b.unit);}});
        double total=0;long now=System.currentTimeMillis();for(RecentSale x:rows){double ageH=x.soldAtMs>0?Math.max(0,(now-x.soldAtMs)/3600000.0):12;double recency=1.0/(1.0+ageH/18.0);total+=Math.max(1,Math.min(200,x.quantity))*recency;}
        double half=total/2.0,run=0;for(RecentSale x:rows){double ageH=x.soldAtMs>0?Math.max(0,(now-x.soldAtMs)/3600000.0):12;double recency=1.0/(1.0+ageH/18.0);run+=Math.max(1,Math.min(200,x.quantity))*recency;if(run>=half)return x.unit;}return rows.get(rows.size()-1).unit;
    }
    private static double recentHistoryUnit(MarketStats stats){
        if(stats==null||stats.history==null||stats.history.isEmpty())return 0;List<HistoryPoint> h=new ArrayList<HistoryPoint>();for(HistoryPoint p:stats.history)if(p!=null&&p.unit>0&&p.sales>0)h.add(p);if(h.isEmpty())return 0;Collections.sort(h,new Comparator<HistoryPoint>(){public int compare(HistoryPoint a,HistoryPoint b){return Long.compare(a.dayMs,b.dayMs);}});int from=Math.max(0,h.size()-7);double sum=0,w=0;for(int i=from;i<h.size();i++){double ww=(i-from)+1;sum+=h.get(i).unit*ww;w+=ww;}return w>0?sum/w:0;
    }
    private static int floorDepthUnits(List<Listing> rows,String currency,double floor){int n=0;if(rows==null||!(floor>0))return 0;for(Listing x:rows){if(x==null||!currency.equals(x.currency))continue;double u=x.unitPrice();if(u>0&&Math.abs(u-floor)/floor<=.005)n+=Math.max(1,x.quantity);}return n;}
    private static double activePercentile(List<Listing> rows,String currency,double p){List<Double> u=new ArrayList<Double>();if(rows!=null)for(Listing x:rows){if(x==null||!currency.equals(x.currency))continue;double v=x.unitPrice();if(v>0&&Double.isFinite(v))u.add(v);}if(u.isEmpty())return 0;Collections.sort(u);if(u.size()>=4){double q1=percentile(u,.25),q3=percentile(u,.75),med=median(u),iqr=Math.max(0,q3-q1),lo=Math.max(Math.max(0,q1-1.5*iqr),med*.40),hi=Math.min(iqr>0?q3+1.5*iqr:med*2.5,med*2.5);List<Double> f=new ArrayList<Double>();for(double v:u)if(v>=lo&&v<=hi)f.add(v);if(!f.isEmpty())u=f;}return percentile(u,p);}
    public static Quote smartSellQuote(MarketStats stats,List<Listing> listings,int requestedQty,String currency){
        int q=Math.max(1,requestedQty);String cur="gold".equals(currency)?"gold":"token";Double floorObj=stats==null?null:stats.floorFor(cur);double floor=floorObj==null?0:Math.max(0,floorObj);if(floor<=0&&listings!=null&&!listings.isEmpty())for(Listing x:listings)if(x!=null&&cur.equals(x.currency)&&x.unitPrice()>0&&(floor<=0||x.unitPrice()<floor))floor=x.unitPrice();
        double recent=weightedRecentUnit(stats),history=recentHistoryUnit(stats),p25=activePercentile(listings,cur,.25),med=activePercentile(listings,cur,.50),p75=activePercentile(listings,cur,.75);
        int floorDepth=floorDepthUnits(listings,cur,floor);int units24=stats==null?0:Math.max(0,stats.units24h),sales24=stats==null?0:Math.max(0,stats.sales24h),available=stats==null?0:Math.max(0,stats.availableFor(cur));
        double effectiveFloor=floor;if(floor>0&&recent>0&&floor<recent*.70&&floorDepth<=Math.max(2,(int)Math.ceil(units24*.03))&&p25>floor*1.15)effectiveFloor=p25;
        double sum=0,w=0;if(effectiveFloor>0){sum+=effectiveFloor*.32;w+=.32;}if(recent>0){sum+=recent*.34;w+=.34;}if(history>0){sum+=history*.20;w+=.20;}if(p25>0){sum+=p25*.09;w+=.09;}if(med>0){sum+=med*.05;w+=.05;}double base=w>0?sum/w:0;if(base<=0)return null;
        double coverDays=units24>0?(double)available/(double)units24:99.0;double adj=0;if(stats!=null&&stats.trend!=null)adj+=clamp(stats.trend.pct*.0015,-.03,.03);if(units24>0){if(coverDays<=1)adj+=.015;else if(coverDays>=10)adj-=.04;else if(coverDays>=5)adj-=.02;else if(coverDays>=3)adj-=.01;}if(sales24<=1&&available>0)adj-=.01;
        double fastUnit=effectiveFloor>0?effectiveFloor:base*.985;boolean weak=coverDays>=4||(stats!=null&&stats.trend!=null&&"down".equals(stats.trend.dir));double tick="token".equals(cur)?.01:1.0;if(weak&&floor>0&&Math.abs(effectiveFloor-floor)/floor<.01){double floorTotal=quantizeTotal(floor*q,cur);double under=Math.max(tick,floorTotal-tick);fastUnit=under/q;}
        double balanceUnit=base*(1.0+adj);if(effectiveFloor>0)balanceUnit=Math.max(balanceUnit,effectiveFloor);double upper=0;if(p75>0)upper=p75;if(recent>0)upper=Math.max(upper,recent*1.08);if(upper>0)balanceUnit=Math.min(balanceUnit,upper);
        double profitUnit=Math.max(balanceUnit*1.035,recent>0?recent*1.025:0);if(history>0)profitUnit=Math.max(profitUnit,history*1.03);if(p75>0)profitUnit=Math.max(profitUnit,p75);double cap=Math.max(balanceUnit*1.15,Math.max(recent,history)*1.15);if(stats!=null&&stats.trend!=null&&"up".equals(stats.trend.dir)&&coverDays<2)cap=Math.max(cap,balanceUnit*1.25);if(cap>0)profitUnit=Math.min(profitUnit,cap);
        Quote z=new Quote();z.fast=quantizeTotal(fastUnit*q,cur);z.normal=quantizeTotal(balanceUnit*q,cur);z.profit=quantizeTotal(profitUnit*q,cur);if(z.normal<z.fast)z.normal=z.fast;if(z.profit<z.normal)z.profit=z.normal;z.fastUnit=z.fast/q;z.normalUnit=z.normal/q;z.profitUnit=z.profit/q;z.floorUnit=floor;z.recentUnit=recent;z.historyUnit=history;z.rowsSeen=listings==null?0:listings.size();z.comparableRows=z.rowsSeen;z.cleanRows=z.rowsSeen;
        int quality=0;if(z.rowsSeen>=4)quality++;if(stats!=null&&stats.recent.size()>=2)quality++;int traded=0;if(stats!=null)for(HistoryPoint hp:stats.history)if(hp!=null&&hp.sales>0&&hp.unit>0)traded++;if(traded>=5)quality++;if(units24>0&&sales24>0)quality++;z.confidence=quality>=4?"HIGH":quality>=2?"MEDIUM":"LOW";List<String> parts=new ArrayList<String>();if(floor>0)parts.add("live floor/depth");if(recent>0)parts.add("completed sales");if(history>0)parts.add("30d history");if(units24>0)parts.add("24h velocity");if(parts.isEmpty())z.basis="active listings";else{StringBuilder bb=new StringBuilder();for(String part:parts){if(bb.length()>0)bb.append(" + ");bb.append(part);}z.basis=bb.toString();}return z;
    }

    public static Quote getQuote(Context context, String item, int requestedQty, String currency) throws Exception {
        String cur="gold".equals(currency)?"gold":"token";MarketStats stats=null;List<Listing> listings=null;try{stats=getItemMarket(context,item,cur);}catch(Exception ignored){}try{listings=getItemListings(context,item,cur);}catch(Exception ignored){}Quote smart=smartSellQuote(stats,listings,requestedQty,cur);if(smart!=null)return smart;
        // Fallback for a temporarily unavailable stats endpoint: use current live listings only.
        int q=Math.max(1,requestedQty);List<JSONObject> rows=listings(context,item,cur);List<Double> units=new ArrayList<Double>();for(JSONObject row:rows){double u=unit(row,cur);if(u>0&&Double.isFinite(u))units.add(u);}if(units.isEmpty())return null;Collections.sort(units);Quote z=new Quote();z.fastUnit=percentile(units,.20);z.normalUnit=median(units);z.profitUnit=percentile(units,.80);z.fast=quantizeTotal(z.fastUnit*q,cur);z.normal=quantizeTotal(z.normalUnit*q,cur);z.profit=quantizeTotal(z.profitUnit*q,cur);z.fastUnit=z.fast/q;z.normalUnit=z.normal/q;z.profitUnit=z.profit/q;z.rowsSeen=rows.size();z.cleanRows=units.size();z.comparableRows=units.size();z.confidence="LOW";z.basis="live listings fallback";return z;
    }

    public static Quote getQuote(Context context, String item, int requestedQty) throws Exception { return getQuote(context,item,requestedQty,"token"); }

    public static Stats getStats(Context context, String item) throws Exception {
        String path="/api/marketplace/stats?itemType="+enc(item)+"&currency=token";
        HttpResult r=request(context,"GET",path,null,20000);
        Stats s=new Stats();
        JSONObject j=unwrapData(r.json); if(r.status!=200 || !j.optBoolean("ok",true)) { s.ok=false; s.error=j.optString("error","stats_unavailable"); return s; }
        s.ok=true; if(j.has("avg30d")&&!j.isNull("avg30d")) s.avg30d=j.optDouble("avg30d");
        JSONArray samples=j.optJSONArray("samples");
        if(samples!=null) for(int i=0;i<samples.length();i++) {
            JSONObject x=samples.optJSONObject(i); if(x==null) continue;
            Sample v=new Sample(); v.date=x.optString("date",""); if(v.date.isEmpty())continue;
            v.sales=Math.max(0,x.optInt("sales",0)); if(x.has("avgUnitPrice")&&!x.isNull("avgUnitPrice")) v.avgUnitPrice=x.optDouble("avgUnitPrice");
            s.samples.add(v);
        }
        if(s.samples.isEmpty()){JSONArray h=firstArray(j,"history","points");double weighted=0,weights=0;if(h!=null)for(int i=0;i<h.length();i++){JSONObject x=h.optJSONObject(i);if(x==null)continue;double unit=x.optDouble("unit",x.optDouble("avgUnitPrice",0));if(unit<=0)continue;long day=parseTimeMs(x.opt("dayMs"));if(day<=0)day=parseTimeMs(x.opt("day"));Sample v=new Sample();v.date=utcDate(day);v.sales=Math.max(0,x.optInt("sales",x.optInt("count",0)));v.avgUnitPrice=unit;s.samples.add(v);double w=Math.max(1,v.sales);weighted+=unit*w;weights+=w;}if(s.avg30d==null&&weights>0)s.avg30d=weighted/weights;}
        return s;
    }

    private static String utcDate(long ms){if(ms<=0)return"";java.text.SimpleDateFormat f=new java.text.SimpleDateFormat("yyyy-MM-dd",Locale.US);f.setTimeZone(java.util.TimeZone.getTimeZone("UTC"));return f.format(new java.util.Date(ms));}
    private static Double optDoubleObj(JSONObject j,String key){ return j!=null&&j.has(key)&&!j.isNull(key)?j.optDouble(key):null; }
    private static Trend parseTrend(JSONObject j){ if(j==null)return null; Trend t=new Trend();t.dir=j.optString("dir","flat");t.pct=j.optDouble("pct",0);return t; }
    private static LastSale parseLast(JSONObject j){ if(j==null)return null;LastSale x=new LastSale();x.unit=j.optDouble("unit",0);x.soldAtMs=parseTimeMs(j.opt("soldAtMs"));if(x.soldAtMs==0)x.soldAtMs=parseTimeMs(j.opt("soldAt"));return x; }

    public static List<MarketItem> getMarketItems(Context context,String sort,String currency,String category,String query,int limit,int offset) throws Exception {
        String so=sort==null?"latest":sort, cur=currency==null?"all":currency, cat=category==null?"all":category;
        String path="/api/marketplace/items?sort="+enc(so)+"&currency="+enc(cur)+"&category="+enc(cat)+"&limit="+Math.max(1,Math.min(100,limit))+"&offset="+Math.max(0,offset);
        if(query!=null&&!query.trim().isEmpty())path+="&q="+enc(query.trim());
        HttpResult r=request(context,"GET",path,null,25000);
        if(r.status==401||r.status==403)throw new Exception("Session expired — reconnect wallet");
        if(r.status!=200||!r.json.optBoolean("ok",true))throw new Exception("Could not load market board");
        JSONObject j=unwrapData(r.json); JSONArray a=firstArray(j,"items","market","rows");List<MarketItem> out=new ArrayList<>();if(a==null)return out;
        for(int i=0;i<a.length();i++){JSONObject row=a.optJSONObject(i);if(row==null)continue;MarketItem x=new MarketItem();x.itemType=normalizeItemType(row.optString("itemType",row.optString("item_type","")));if(x.itemType.isEmpty())continue;x.listings=Math.max(0,row.optInt("listings",0));x.available=Math.max(0,row.optInt("available",0));x.floorGold=optDoubleObj(row,"floorGold");x.floorToken=optDoubleObj(row,"floorToken");x.lastGold=parseLast(row.optJSONObject("lastGold"));if(x.lastGold==null)x.lastGold=parseLast(row.optJSONObject("lastSaleGold"));x.lastToken=parseLast(row.optJSONObject("lastToken"));if(x.lastToken==null)x.lastToken=parseLast(row.optJSONObject("lastSaleToken"));x.trendGold=parseTrend(row.optJSONObject("trendGold"));x.trendToken=parseTrend(row.optJSONObject("trendToken"));out.add(x);}return out;
    }

    private static List<Listing> latestListingsForCurrency(Context context,String currency,int limit) throws Exception {
        String cur="gold".equals(currency)?"gold":"token";
        String path="/api/marketplace/listings?sort=latest&currency="+enc(cur)+"&limit="+Math.max(1,Math.min(100,limit))+"&offset=0";
        HttpResult r=request(context,"GET",path,null,22000);
        if(r.status==401||r.status==403)throw new Exception("Session expired — reconnect wallet");
        if(r.status!=200||!r.json.optBoolean("ok",true))throw new Exception("Could not load latest listings");
        JSONArray a=firstArray(r.json,"listings","items","rows");LinkedHashMap<String,Listing> unique=new LinkedHashMap<>();
        for(int i=0;i<a.length();i++){Listing x=parseListing(a.optJSONObject(i));if(x==null||x.id==null||x.id.isEmpty()||inactiveStatus(x.status)||!cur.equals(x.currency))continue;unique.put(x.id,x);}
        List<Listing> out=new ArrayList<>(unique.values());Collections.sort(out,new Comparator<Listing>(){public int compare(Listing a,Listing b){return Long.compare(b.createdAtMs,a.createdAtMs);}});return out;
    }

    public static List<Listing> getLatestListings(Context context,String currency,String query,int limit) throws Exception {
        List<Listing> rows=new ArrayList<>();
        if("all".equals(currency)){rows.addAll(latestListingsForCurrency(context,"token",limit));rows.addAll(latestListingsForCurrency(context,"gold",limit));}
        else rows.addAll(latestListingsForCurrency(context,currency,limit));
        final String q=query==null?"":query.trim().toLowerCase(Locale.US);
        if(!q.isEmpty()){List<Listing> f=new ArrayList<>();for(Listing x:rows){String label=x.label().toLowerCase(Locale.US),type=x.itemType==null?"":x.itemType.toLowerCase(Locale.US);if(label.contains(q)||type.contains(q))f.add(x);}rows=f;}
        Collections.sort(rows,new Comparator<Listing>(){public int compare(Listing a,Listing b){return Long.compare(b.createdAtMs,a.createdAtMs);}});
        if(rows.size()>limit)return new ArrayList<Listing>(rows.subList(0,limit));return rows;
    }

    public static List<MarketItem> getHotMarketItems(final Context context,String currency,String category,String query,int limit) throws Exception {
        final String cur=currency==null?"token":currency;
        List<MarketItem> seed=getMarketItems(context,"latest",cur,category,query,Math.max(1,Math.min(100,limit)),0);
        if(seed.isEmpty())return seed;
        ExecutorService pool=Executors.newFixedThreadPool(8);List<Future<MarketItem>> fs=new ArrayList<>();
        for(final MarketItem x:seed){fs.add(pool.submit(new Callable<MarketItem>(){public MarketItem call(){try{
            MarketStats best=null;
            if("all".equals(cur)){
                MarketStats a=getItemMarket(context,x.itemType,"token"),b=getItemMarket(context,x.itemType,"gold");
                int au=a==null?0:a.units24h,bu=b==null?0:b.units24h,as=a==null?0:a.sales24h,bs=b==null?0:b.sales24h;
                x.units24h=au+bu;x.sales24h=as+bs;double tokenScore=au+(as*8.0),goldScore=bu+(bs*8.0);best=tokenScore>=goldScore?a:b;
            }else{best=getItemMarket(context,x.itemType,"gold".equals(cur)?"gold":"token");if(best!=null&&best.ok){x.units24h=best.units24h;x.sales24h=best.sales24h;}}
            double trend=best!=null&&best.trend!=null?("up".equals(best.trend.dir)?Math.max(0,best.trend.pct):"down".equals(best.trend.dir)?-Math.max(0,best.trend.pct):0):0;
            x.activityScore=x.units24h+(x.sales24h*8.0)+(Math.max(-20,Math.min(20,trend))*.25);return x;
        }catch(Exception e){return x;}}}));}
        List<MarketItem> out=new ArrayList<>();for(Future<MarketItem> f:fs)try{MarketItem x=f.get();if(x!=null)out.add(x);}catch(Exception ignored){}pool.shutdown();
        Collections.sort(out,new Comparator<MarketItem>(){public int compare(MarketItem a,MarketItem b){int c=Double.compare(b.activityScore,a.activityScore);if(c!=0)return c;c=Integer.compare(b.units24h,a.units24h);if(c!=0)return c;return Integer.compare(b.sales24h,a.sales24h);}});return out;
    }

    public static MarketStats getItemMarket(Context context,String item,String currency) throws Exception {
        String cur="token".equals(currency)?"token":"gold";
        String normalized = normalizeItemType(item);
        HttpResult r=null;
        // A transient 5xx/429 or a cold edge connection should not blank the detail page.
        for (int attempt=0; attempt<2; attempt++) {
            r=request(context,"GET","/api/marketplace/stats?currency="+enc(cur)+"&itemType="+enc(normalized),null,22000);
            if (r.status==200 || (r.status!=0 && r.status<500 && r.status!=429)) break;
        }
        MarketStats s=new MarketStats();s.currency=cur;
        JSONObject j=unwrapData(r==null?null:r.json);
        if(r==null||r.status!=200||!j.optBoolean("ok",r.status==200)){s.ok=false;s.error=j.optString("error",r==null?"stats_unavailable":("HTTP "+r.status));return s;}
        s.ok=true;s.floorGold=optDoubleObj(j,"floorGold");s.floorToken=optDoubleObj(j,"floorToken");s.lastSaleGold=parseLast(j.optJSONObject("lastSaleGold"));s.lastSaleToken=parseLast(j.optJSONObject("lastSaleToken"));s.listingsGold=Math.max(0,j.optInt("listingsGold",0));s.listingsToken=Math.max(0,j.optInt("listingsToken",0));s.availableGold=Math.max(0,j.optInt("availableGold",0));s.availableToken=Math.max(0,j.optInt("availableToken",0));s.sales24h=Math.max(0,j.optInt("sales24h",0));s.units24h=Math.max(0,j.optInt("units24h",0));s.historyDays=Math.max(2,j.optInt("historyDays",30));s.trend=parseTrend(j.optJSONObject("trend"));
        JSONArray h=firstArray(j,"history","points","series");if(h!=null)for(int i=0;i<h.length();i++){JSONObject z=h.optJSONObject(i);if(z==null)continue;double u=z.optDouble("unit",z.optDouble("avgUnitPrice",0));if(u<=0)continue;HistoryPoint p=new HistoryPoint();p.dayMs=parseTimeMs(z.opt("dayMs"));if(p.dayMs==0)p.dayMs=parseTimeMs(z.opt("day"));if(p.dayMs==0)p.dayMs=parseTimeMs(z.opt("timestamp"));p.unit=u;p.sales=Math.max(0,z.optInt("sales",z.optInt("count",0)));s.history.add(p);}
        JSONArray re=firstArray(j,"recent","recentSales","sales");if(re!=null)for(int i=0;i<re.length();i++){JSONObject z=re.optJSONObject(i);if(z==null)continue;JSONObject src=z.optJSONObject("sale");if(src!=null)z=src;RecentSale x=new RecentSale();x.quantity=Math.max(1,z.optInt("quantity",z.optInt("qty",1)));x.unit=z.optDouble("unit",z.optDouble("unitPrice",0));x.total=z.optDouble("total",z.optDouble("totalPrice",x.unit*x.quantity));x.soldAtMs=parseTimeMs(z.opt("soldAtMs"));if(x.soldAtMs==0)x.soldAtMs=parseTimeMs(z.opt("soldAt"));if(x.soldAtMs==0)x.soldAtMs=parseTimeMs(z.opt("createdAt"));s.recent.add(x);}return s;
    }

    private static JSONObject unwrapData(JSONObject source) {
        if (source == null) return new JSONObject();
        JSONObject data=source.optJSONObject("data");
        if (data != null && (data.has("ok") || data.has("floorGold") || data.has("history") || data.has("recent"))) return data;
        return source;
    }

    public static List<Listing> getItemListings(Context context,String item,String currency) throws Exception {
        String wanted=normalizeItemType(item); JSONArray a=fetchListings(context,wanted,"all",currency,60);List<Listing> out=new ArrayList<>();for(int i=0;i<a.length();i++){Listing x=parseListing(a.optJSONObject(i));if(x!=null&&wanted.equals(normalizeItemType(x.itemType))&&currency.equals(x.currency))out.add(x);}
        // Some edge nodes ignore itemType when category=all; use the generic endpoint once.
        if(out.isEmpty()) { try { a=fetchListings(context,wanted,categoryFor(wanted),currency,100); for(int i=0;i<a.length();i++){Listing x=parseListing(a.optJSONObject(i));if(x!=null&&wanted.equals(normalizeItemType(x.itemType))&&currency.equals(x.currency))out.add(x);} } catch(Exception ignored){} }
        Collections.sort(out,new Comparator<Listing>(){public int compare(Listing a,Listing b){return Double.compare(a.unitPrice(),b.unitPrice());}});return out;
    }

    public static List<Listing> getBoughtListings(Context context) throws Exception {
        HttpResult r=request(context,"GET","/api/marketplace/listings?mine=1&bought=1",null,18000);if(r.status==401||r.status==403)throw new Exception("Session expired — reconnect wallet");if(r.status!=200||!r.json.optBoolean("ok",true))throw new Exception("Could not sync bought history");JSONArray a=firstArray(r.json,"sales","listings","items","rows","history");List<Listing> out=new ArrayList<>();for(int i=0;i<a.length();i++){JSONObject row=a.optJSONObject(i);if(row==null)continue;JSONObject src=row.optJSONObject("listing");if(src==null)src=row;Listing x=parseListing(src);if(x==null)continue;x.status="bought";long done=listingFinishedAt(row);if(done<=0)done=parseTimeMs(row.opt("soldAtMs"));x.finishedAtMs=done>0?done:x.finishedAtMs;out.add(x);}Collections.sort(out,new Comparator<Listing>(){public int compare(Listing a,Listing b){long ta=a.finishedAtMs>0?a.finishedAtMs:a.createdAtMs,tb=b.finishedAtMs>0?b.finishedAtMs:b.createdAtMs;return Long.compare(tb,ta);}});return out;
    }

    public static int listingQtyLimit(Context context){try{JSONObject me=getMe(context);boolean club=me.optBoolean("clubMember",false);JSONObject p=me.optJSONObject("player");if(p!=null)club=club||p.optBoolean("clubMember",false);return club?MARKET_STACK_MAX_MEMBER:MARKET_STACK_MAX_NONMEMBER;}catch(Exception e){return MARKET_STACK_MAX_NONMEMBER;}}

    public static SellerIntel sellerIntel(MarketStats stats,List<Listing> listings,String currency,double selectedUnit) {
        SellerIntel z=new SellerIntel();z.selectedUnit=Math.max(0,selectedUnit);
        if(stats!=null){
            Double fl=stats.floorFor(currency);z.floorUnit=fl==null?0:Math.max(0,fl);z.sales24h=Math.max(0,stats.sales24h);z.units24h=Math.max(0,stats.units24h);z.marketAvailable=Math.max(0,stats.availableFor(currency));
            LastSale ls=stats.lastFor(currency);if(ls!=null&&ls.unit>0)z.lastSaleUnit=ls.unit;
            for(HistoryPoint p:stats.history)if(p!=null&&p.unit>0)z.tradedDays++;
        }
        if(listings!=null){for(Listing x:listings){if(x==null||!currency.equals(x.currency))continue;double u=x.unitPrice();if(!(u>0))continue;int q=Math.max(1,x.quantity);z.visibleListings++;z.visibleUnits+=q;if(z.floorUnit>0&&Math.abs(u-z.floorUnit)/z.floorUnit<=0.0005){z.floorListings++;z.floorUnits+=q;}if(z.selectedUnit>0&&u<z.selectedUnit-1e-9){z.cheaperListings++;z.cheaperUnits+=q;}if(z.selectedUnit>0&&u<=z.selectedUnit+1e-9){z.atOrBelowListings++;z.atOrBelowUnits+=q;}}}
        if(z.floorUnit>0&&z.selectedUnit>0)z.deltaPct=(z.selectedUnit-z.floorUnit)/z.floorUnit*100.0;
        if(z.floorUnit>0&&z.lastSaleUnit!=null)z.lastSaleVsFloorPct=(z.lastSaleUnit-z.floorUnit)/z.floorUnit*100.0;
        if(z.units24h>0){
            int supply=Math.max(z.marketAvailable,z.visibleUnits);z.supplyToDailySales=(double)supply/(double)z.units24h;z.supplyCoverHours=z.supplyToDailySales*24.0;z.floorClearHours=(double)z.floorUnits/(double)z.units24h*24.0;
            if(z.supplyToDailySales<=1.0)z.pressure="TIGHT SUPPLY";else if(z.supplyToDailySales<=3.0)z.pressure="BALANCED";else if(z.supplyToDailySales<=7.0)z.pressure="COMPETITIVE";else z.pressure="HEAVY SUPPLY";
        }else z.pressure=z.marketAvailable>0?"LOW LIQUIDITY":"NO SUPPLY";
        if(z.units24h>=100)z.liquidity="HIGH";else if(z.units24h>=20)z.liquidity="MEDIUM";else if(z.units24h>0)z.liquidity="LOW";
        String dir=stats==null||stats.trend==null?"flat":stats.trend.dir;
        if(z.units24h<=0)z.sellSignal="NO RECENT DEMAND";
        else if("TIGHT SUPPLY".equals(z.pressure)&&"up".equals(dir))z.sellSignal="STRONG PRICING POWER";
        else if("HEAVY SUPPLY".equals(z.pressure)||"LOW LIQUIDITY".equals(z.pressure))z.sellSignal="HIGH PRICE COMPETITION";
        else if("down".equals(dir))z.sellSignal="DEFENSIVE PRICING";
        else if("up".equals(dir))z.sellSignal="POSITIVE MOMENTUM";
        else z.sellSignal="NEUTRAL MARKET";
        return z;
    }

    public static Stock getStock(Context context, String item) throws Exception {
        JSONObject me=getMe(context); JSONObject bp=me.optJSONObject("backpack"); if(bp==null) bp=new JSONObject();
        int carry=countSlots(bp.optJSONArray("invSlots"),item)+countSlots(bp.optJSONArray("hotbar"),item);
        int bank=countSlots(bp.optJSONArray("bankSlots"),item); return new Stock(carry,bank);
    }

    private static void addSlotCounts(JSONArray slots, Map<String,Integer> counts) {
        if (slots == null) return;
        for (int i=0;i<slots.length();i++) {
            Object o=slots.opt(i); String t=slotType(o); int n=slotCount(o);
            if (t.isEmpty() || n<=0) continue;
            Integer old=counts.get(t); counts.put(t,(old==null?0:old)+n);
        }
    }

    public static List<InventoryEntry> getInventory(Context context) throws Exception {
        JSONObject me=getMe(context); JSONObject bp=me.optJSONObject("backpack"); if(bp==null) bp=new JSONObject();
        Map<String,Integer> carry=new LinkedHashMap<>(), bank=new LinkedHashMap<>();
        addSlotCounts(bp.optJSONArray("invSlots"),carry); addSlotCounts(bp.optJSONArray("hotbar"),carry); addSlotCounts(bp.optJSONArray("bankSlots"),bank);
        List<InventoryEntry> out=new ArrayList<>();
        Map<String,Boolean> seen=new LinkedHashMap<>();
        for (Item item:CATALOG) {
            int c=carry.containsKey(item.type)?carry.get(item.type):0, b=bank.containsKey(item.type)?bank.get(item.type):0;
            if (c+b>0) { out.add(new InventoryEntry(item,new Stock(c,b))); seen.put(item.type,true); }
        }
        List<String> unknown=new ArrayList<>();
        for (String t:carry.keySet()) if (!seen.containsKey(t)) unknown.add(t);
        for (String t:bank.keySet()) if (!seen.containsKey(t) && !unknown.contains(t)) unknown.add(t);
        Collections.sort(unknown);
        for (String t:unknown) {
            int c=carry.containsKey(t)?carry.get(t):0, b=bank.containsKey(t)?bank.get(t):0;
            if (c+b>0) out.add(new InventoryEntry(findItem(t),new Stock(c,b)));
        }
        return out;
    }

    private static String slotType(Object o) {
        if(!(o instanceof JSONObject))return ""; JSONObject s=(JSONObject)o;
        String x=s.optString("t",""); if(x.isEmpty())x=s.optString("type",""); if(x.isEmpty())x=s.optString("itemType",""); return normalizeItemType(x);
    }
    private static int slotCount(Object o) {
        if(!(o instanceof JSONObject))return 0; JSONObject s=(JSONObject)o;
        if(s.has("n"))return Math.max(0,s.optInt("n",0)); if(s.has("count"))return Math.max(0,s.optInt("count",0)); return Math.max(0,s.optInt("amount",0));
    }
    private static int countSlots(JSONArray a,String item) { int n=0;if(a==null)return 0;for(int i=0;i<a.length();i++){Object o=a.opt(i);if(item.equals(slotType(o)))n+=slotCount(o);}return n; }

    private static Object packSlot(Object o) throws Exception {
        if(!(o instanceof JSONObject)) return JSONObject.NULL;
        JSONObject s=(JSONObject)o; String t=slotType(s); int n=slotCount(s); if(t.isEmpty()||n<=0)return JSONObject.NULL;
        JSONObject p=new JSONObject();p.put("t",t);p.put("n",n);if(s.has("d"))p.put("d",s.opt("d"));return p;
    }
    private static JSONArray normalized(JSONArray source,int len) throws Exception {
        JSONArray a=new JSONArray(); for(int i=0;i<len;i++)a.put(packSlot(source!=null?source.opt(i):null)); return a;
    }
    private static int bankLength(JSONObject bp) { JSONArray a=bp.optJSONArray("bankSlots");int raw=a==null?0:a.length();int pages=Math.max(1,bp.optInt("bankPages",1));return Math.max(BANK_PAGE_SIZE,Math.max(raw,pages*BANK_PAGE_SIZE)); }
    private static JSONArray concat(JSONArray a,JSONArray b) throws Exception { JSONArray c=new JSONArray();for(int i=0;i<a.length();i++)c.put(a.opt(i));for(int i=0;i<b.length();i++)c.put(b.opt(i));return c; }
    private static JSONArray slice(JSONArray a,int start,int count) throws Exception { JSONArray o=new JSONArray();for(int i=0;i<count;i++)o.put(a.opt(start+i));return o; }

    private static int take(JSONArray slots,String item,int amount) throws Exception {
        int left=amount,moved=0;for(int i=0;i<slots.length()&&left>0;i++){Object o=slots.opt(i);if(!item.equals(slotType(o)))continue;int c=slotCount(o),t=Math.min(c,left);int remain=c-t;if(remain>0){JSONObject n=new JSONObject();n.put("t",item);n.put("n",remain);slots.put(i,n);}else slots.put(i,JSONObject.NULL);moved+=t;left-=t;}return moved;
    }
    private static int put(JSONArray slots,String item,int amount) throws Exception {
        int left=amount,moved=0;for(int i=0;i<slots.length()&&left>0;i++){Object o=slots.opt(i);if(!item.equals(slotType(o)))continue;int c=slotCount(o),room=MAX_STACK-c;if(room<=0)continue;int add=Math.min(room,left);JSONObject n=new JSONObject();n.put("t",item);n.put("n",c+add);slots.put(i,n);left-=add;moved+=add;}
        for(int i=0;i<slots.length()&&left>0;i++){Object o=slots.opt(i);if(!slotType(o).isEmpty())continue;int add=Math.min(MAX_STACK,left);JSONObject n=new JSONObject();n.put("t",item);n.put("n",add);slots.put(i,n);left-=add;moved+=add;}return moved;
    }

    private static JSONObject saveBackpackPayload(JSONObject me,JSONArray inv,JSONArray hot,JSONArray bank) throws Exception {
        JSONObject bp=me.optJSONObject("backpack");if(bp==null)bp=new JSONObject(); JSONObject p=new JSONObject();
        p.put("invSlots",inv);p.put("hotbar",hot);p.put("bankSlots",bank);
        Object seq=me.has("stateSeq")?me.opt("stateSeq"):bp.opt("stateSeq");p.put("baseSeq",seq==null?JSONObject.NULL:seq);p.put("intentionalRemovals",new JSONArray());
        String[] extras={"cosmeticSlots","mountSlots","petSlots","furnitureSlots"};for(String k:extras){JSONArray src=bp.optJSONArray(k);if(src!=null){JSONArray x=new JSONArray();for(int i=0;i<src.length();i++)x.put(packSlot(src.opt(i)));p.put(k,x);}}
        return p;
    }
    private static boolean saveBackpack(Context c,JSONObject me,JSONArray inv,JSONArray hot,JSONArray bank) throws Exception {
        HttpResult r=request(c,"POST","/api/auth/save-backpack",saveBackpackPayload(me,inv,hot,bank),10000);
        return r.status==200 && r.json.optBoolean("ok",true);
    }

    private static int moveBankToCarry(Context c,String item,int amount) throws Exception {
        for(int attempt=0;attempt<2;attempt++){
            JSONObject me=getMe(c),bp=me.optJSONObject("backpack");if(bp==null)bp=new JSONObject();
            JSONArray inv=normalized(bp.optJSONArray("invSlots"),INV_LEN),hot=normalized(bp.optJSONArray("hotbar"),HOTBAR_LEN),bank=normalized(bp.optJSONArray("bankSlots"),bankLength(bp));JSONArray carry=concat(inv,hot);
            int before=countSlots(carry,item),available=countSlots(bank,item),want=Math.min(amount,available);if(want<=0)return 0;
            int taken=take(bank,item,want),placed=put(carry,item,taken);if(placed<taken)put(bank,item,taken-placed);if(placed<=0)throw new Exception("Carry inventory is full");
            if(saveBackpack(c,me,slice(carry,0,INV_LEN),slice(carry,INV_LEN,HOTBAR_LEN),bank)){Stock verify=getStock(c,item);return Math.max(placed,verify.carry-before);} }
        throw new Exception("Could not move item from bank (stale state)");
    }

    private static boolean consolidateCarry(Context c,String item,int minStack) throws Exception {
        for(int attempt=0;attempt<2;attempt++){
            JSONObject me=getMe(c),bp=me.optJSONObject("backpack");if(bp==null)bp=new JSONObject();
            JSONArray inv=normalized(bp.optJSONArray("invSlots"),INV_LEN),hot=normalized(bp.optJSONArray("hotbar"),HOTBAR_LEN),bank=normalized(bp.optJSONArray("bankSlots"),bankLength(bp));JSONArray carry=concat(inv,hot);
            int total=countSlots(carry,item);if(total<minStack)return false;for(int i=0;i<carry.length();i++)if(item.equals(slotType(carry.opt(i)))&&slotCount(carry.opt(i))>=minStack)return true;
            for(int i=0;i<carry.length();i++)if(item.equals(slotType(carry.opt(i))))carry.put(i,JSONObject.NULL);put(carry,item,total);
            if(saveBackpack(c,me,slice(carry,0,INV_LEN),slice(carry,INV_LEN,HOTBAR_LEN),bank))return true;
        }return false;
    }

    private static JSONObject findSellSlot(JSONObject bp,String item,int minQty) {
        String[] keys={"invSlots","hotbar"};String[] kinds={"inv","hot"};for(int k=0;k<keys.length;k++){JSONArray a=bp.optJSONArray(keys[k]);if(a==null)continue;for(int i=0;i<a.length();i++){Object o=a.opt(i);if(item.equals(slotType(o))&&slotCount(o)>=minQty){JSONObject x=new JSONObject();try{x.put("kind",kinds[k]);x.put("index",i);}catch(Exception ignored){}return x;}}}return null;
    }

    /** Mirrors the official server picker's normalizeZoneId(). Marketplace
     * requests use the selected zone (us/eu/asia), not the box-local fleet id. */
    private static String marketplaceFleet(JSONObject s){
        String raw=s==null?"":s.optString("zone",s.optString("region","")).trim().toLowerCase(Locale.US);
        if(raw.isEmpty())raw="us";if("usa".equals(raw)||"na".equals(raw)||"north-america".equals(raw)||"north_america".equals(raw))return "us";if("europe".equals(raw))return "eu";if("apac".equals(raw)||"asia-pacific".equals(raw)||"asia_pacific".equals(raw))return "asia";String normalized=raw.replaceAll("[^a-z0-9_-]+","-").replaceAll("^-+|-+$","");return normalized.isEmpty()?"us":normalized;
    }

    private static JSONObject routeContext(Context c) throws Exception {
        HttpResult r=request(c,"GET","/api/servers",null,20000);if(r.status!=200||!r.json.optBoolean("ok",false))throw new Exception("Could not load server routing metadata");
        JSONArray servers=r.json.optJSONArray("servers");if(servers==null)throw new Exception("No servers");
        String savedFleet=SecurePrefs.getMarketFleet(c);int savedShard=SecurePrefs.getMarketShard(c);long savedAt=SecurePrefs.getMarketRouteUpdatedAt(c);
        if(!savedFleet.isEmpty()&&savedShard>0&&System.currentTimeMillis()-savedAt<86400000L){
            for(int i=0;i<servers.length();i++){JSONObject s=servers.optJSONObject(i);if(s==null)continue;String f=marketplaceFleet(s);int sh=s.optInt("routeShardId",0);if(sh<=0)sh=s.optInt("localShardId",0);if(sh<=0)sh=s.optInt("id",0);if(savedFleet.equals(f)&&savedShard==sh){JSONObject out=new JSONObject();out.put("fleet",savedFleet);out.put("shardId",savedShard);return out;}}
        }
        Pattern p=Pattern.compile("Server (\\d+)");JSONObject best=null;int bestQ=Integer.MAX_VALUE;
        for(int i=0;i<servers.length();i++){JSONObject s=servers.optJSONObject(i);if(s==null)continue;Matcher m=p.matcher(s.optString("name",""));if(!m.matches()||Integer.parseInt(m.group(1))<9)continue;int q=s.optInt("queueLength",0);if(q<bestQ){best=s;bestQ=q;}}
        if(best==null)throw new Exception("No selectable Normal/Free server >= 9");String fleet=marketplaceFleet(best);int shard=best.optInt("routeShardId",0);if(shard<=0)shard=best.optInt("localShardId",0);if(shard<=0)shard=best.optInt("id",0);if(fleet.isEmpty()||shard<=0)throw new Exception("Invalid market routing metadata");JSONObject out=new JSONObject();out.put("fleet",fleet);out.put("shardId",shard);return out;
    }

    public static SellResult sell(Context c,String item,int quantity,double totalPrice,String currency,boolean acceptLow) {
        SellResult out=new SellResult();out.price=totalPrice;
        try {
            String cur="gold".equals(currency)?"gold":"token";int max=listingQtyLimit(c);int q=Math.max(1,Math.min(MARKET_STACK_MAX_MEMBER,quantity));
            if(q>max){out.error="bad_quantity";out.message="Your account can list up to "+max+" items per listing.";return out;}
            if("gold".equals(item)&&"gold".equals(cur)){out.error="cannot_sell_gold_for_gold";out.message="Gold can only be listed for $KINS.";return out;}
            Stock st=getStock(c,item);if(st.total<q){out.error="not_enough_total";out.message="Not enough stock. Available="+st.total+", need="+q;return out;}
            int moved=0;if(st.carry<q){moved=moveBankToCarry(c,item,q-st.carry);st=getStock(c,item);if(st.carry<q){out.error="bank_move_incomplete";out.message="Could not prepare enough carry stock.";return out;}}
            if(!consolidateCarry(c,item,q)){out.error="stack_prepare_failed";out.message="Could not prepare one sell stack.";return out;}
            JSONObject me=getMe(c),bp=me.optJSONObject("backpack");if(bp==null)bp=new JSONObject();JSONObject slot=findSellSlot(bp,item,q);if(slot==null){out.error="sell_slot_not_ready";out.message="Sell slot is not ready.";return out;}
            JSONObject route=routeContext(c);JSONObject body=new JSONObject();body.put("itemType",item);body.put("slotKind",slot.getString("kind"));body.put("slotIndex",slot.getInt("index"));body.put("quantity",q);body.put("currency",cur);body.put("fleet",route.getString("fleet"));body.put("shardId",route.getInt("shardId"));
            if("token".equals(cur)){body.put("priceUsd",Math.round(totalPrice*100.0)/100.0);if(acceptLow)body.put("acceptLowPrice",true);}else body.put("priceGold",Math.max(1L,Math.round(totalPrice)));
            HttpResult r=request(c,"POST","/api/marketplace/sell",body,30000);if(r.status==200&&r.json.optBoolean("ok",true)){out.ok=true;out.movedFromBank=moved;out.fleet=route.getString("fleet");out.shardId=route.getInt("shardId");return out;}
            out.error=r.json.optString("error","market_sell_failed");out.message=prettyError(out.error,r.json);if(r.json.has("medianTotal")&&!r.json.isNull("medianTotal"))out.medianTotal=r.json.optDouble("medianTotal");return out;
        } catch(Exception e){out.error="exception";out.message=e.getMessage()==null?e.toString():e.getMessage();return out;}
    }
    public static SellResult sell(Context c,String item,int quantity,double totalPrice,boolean acceptLow){return sell(c,item,quantity,totalPrice,"token",acceptLow);}



    private static JSONArray firstArray(JSONObject j, String... keys) {
        if (j == null) return new JSONArray();
        for (String k : keys) {
            JSONArray a = j.optJSONArray(k);
            if (a != null) return a;
        }
        JSONObject data = j.optJSONObject("data");
        if (data != null) {
            for (String k : keys) {
                JSONArray a = data.optJSONArray(k);
                if (a != null) return a;
            }
        }
        return new JSONArray();
    }

    private static long parseTimeMs(Object v) {
        if (v == null || v == JSONObject.NULL) return 0L;
        if (v instanceof Number) {
            long n = ((Number)v).longValue();
            return n > 100000000000L ? n : n * 1000L;
        }
        String s = String.valueOf(v).trim();
        if (s.isEmpty()) return 0L;
        try {
            long n = Long.parseLong(s);
            return n > 100000000000L ? n : n * 1000L;
        } catch (Exception ignored) {}
        try {
            java.text.SimpleDateFormat f = new java.text.SimpleDateFormat("yyyy-MM-dd'T'HH:mm:ss.SSS'Z'", Locale.US);
            f.setTimeZone(java.util.TimeZone.getTimeZone("UTC"));
            return f.parse(s).getTime();
        } catch (Exception ignored) {}
        return 0L;
    }

    private static String listingId(JSONObject row) {
        if (row == null) return "";
        Object v = row.opt("id");
        if (v == null || v == JSONObject.NULL) v = row.opt("listingId");
        if (v == null || v == JSONObject.NULL) v = row.opt("listing_id");
        return v == null || v == JSONObject.NULL ? "" : String.valueOf(v);
    }

    private static boolean inactiveStatus(String status) {
        String s = status == null ? "" : status.trim().toLowerCase(Locale.US);
        return "sold".equals(s) || "completed".equals(s) || "cancelled".equals(s) ||
                "canceled".equals(s) || "expired".equals(s) || "closed".equals(s);
    }

    public static List<Listing> getMyListings(Context context) throws Exception {
        HttpResult r = request(context, "GET", "/api/marketplace/listings?mine=1", null, 18000);
        if (r.status == 401 || r.status == 403) throw new Exception("Session expired — reconnect wallet");
        if (r.status != 200 || !r.json.optBoolean("ok", true)) throw new Exception("Could not sync active listings");
        JSONArray a = firstArray(r.json, "listings", "items", "rows");LinkedHashMap<String,Listing> unique=new LinkedHashMap<>();
        for(int i=0;i<a.length();i++){JSONObject row=a.optJSONObject(i);Listing x=parseListing(row);if(x==null||x.id==null||x.id.trim().isEmpty()||x.itemType==null||x.itemType.isEmpty()||inactiveStatus(x.status))continue;unique.put(x.id.trim(),x);}
        List<Listing> out=new ArrayList<>(unique.values());Collections.sort(out,new Comparator<Listing>(){public int compare(Listing a,Listing b){return Long.compare(b.createdAtMs,a.createdAtMs);}});enrichListingMarketContext(context,out);return out;
    }

    private static void enrichListingMarketContext(Context context,List<Listing> rows){
        if(rows==null||rows.isEmpty())return;
        try{java.util.LinkedHashSet<String> set=new java.util.LinkedHashSet<>();for(Listing x:rows)if(x!=null&&x.itemType!=null&&!x.itemType.isEmpty()&&set.size()<80)set.add(x.itemType);if(set.isEmpty())return;StringBuilder joined=new StringBuilder();for(String t:set){if(joined.length()>0)joined.append(',');joined.append(t);}HttpResult r=request(context,"GET","/api/marketplace/items?types="+enc(joined.toString()),null,18000);if(r.status!=200||!r.json.optBoolean("ok",true))return;JSONArray a=r.json.optJSONArray("floors");if(a==null)return;Map<String,MarketItem> byType=new LinkedHashMap<>();for(int i=0;i<a.length();i++){JSONObject row=a.optJSONObject(i);if(row==null)continue;MarketItem m=new MarketItem();m.itemType=row.optString("itemType","");m.floorGold=optDoubleObj(row,"floorGold");m.floorToken=optDoubleObj(row,"floorToken");m.trendGold=parseTrend(row.optJSONObject("trendGold"));m.trendToken=parseTrend(row.optJSONObject("trendToken"));if(!m.itemType.isEmpty())byType.put(m.itemType,m);}for(Listing x:rows){MarketItem m=byType.get(x.itemType);if(m==null)continue;if("token".equals(x.currency)){x.floorUnit=m.floorToken;x.trend=m.trendToken;}else{x.floorUnit=m.floorGold;x.trend=m.trendGold;}}}catch(Exception ignored){}
    }

    private static boolean soldStatus(String status) {
        String s = status == null ? "" : status.trim().toLowerCase(Locale.US);
        return "sold".equals(s) || "completed".equals(s) || "complete".equals(s) || "filled".equals(s);
    }

    private static long listingFinishedAt(JSONObject row) {
        if (row == null) return 0L;
        for (String k : new String[]{"soldAtMs","completedAtMs","filledAtMs","soldAt","completedAt","filledAt","closedAt","updatedAt","createdAt"}) {
            long t = parseTimeMs(row.opt(k));
            if (t > 0) return t;
        }
        return 0L;
    }

    private static Listing parseListing(JSONObject row) {
        if (row == null) return null;
        String id = listingId(row);
        String type = row.optString("itemType", row.optString("item_type", row.optString("type", "")));
        String normalizedType=normalizeItemType(type);
        boolean known=false; for(Item item:CATALOG)if(item.type.equals(normalizedType)){known=true;break;}
        if (!known) {
            String label = row.optString("item", row.optString("itemName", row.optString("label", "")));
            String mapped = typeFromLabel(label);
            if (!mapped.isEmpty()) type = mapped;
        }
        if (type.isEmpty()) return null;
        Listing x = new Listing();
        x.id = id;
        x.itemType = normalizeItemType(type);
        x.status = row.optString("status", row.optString("state", ""));
        x.currency = row.optString("currency", "token");
        if ("kins".equalsIgnoreCase(x.currency) || "$kins".equalsIgnoreCase(x.currency) || "usdc".equalsIgnoreCase(x.currency)) x.currency="token";
        if ("coins".equalsIgnoreCase(x.currency)) x.currency="gold";
        x.quantity = Math.max(1, row.optInt("quantity", row.optInt("qty", row.optInt("amount", 1))));
        if (row.has("priceUsd") && !row.isNull("priceUsd")) x.priceUsd = row.optDouble("priceUsd", 0);
        else if (row.has("price_usd") && !row.isNull("price_usd")) x.priceUsd = row.optDouble("price_usd", 0);
        else if ("token".equalsIgnoreCase(x.currency) || "kins".equalsIgnoreCase(x.currency)) x.priceUsd = row.optDouble("price", 0);
        if (row.has("priceGold") && !row.isNull("priceGold")) x.priceGold = row.optDouble("priceGold", 0);
        else if (row.has("price_gold") && !row.isNull("price_gold")) x.priceGold = row.optDouble("price_gold", 0);
        else if ("gold".equalsIgnoreCase(x.currency)) x.priceGold = row.optDouble("price", 0);
        x.sellerName = row.optString("sellerName", row.optString("seller", ""));
        if (row.has("reservedBy") && !row.isNull("reservedBy")) try { x.reservedBy = row.getLong("reservedBy"); } catch(Exception ignored) {}
        x.reservedUntilMs = parseTimeMs(row.opt("reservedUntilMs"));
        if (x.reservedUntilMs == 0) x.reservedUntilMs = parseTimeMs(row.opt("reservedUntil"));
        x.createdAtMs = parseTimeMs(row.opt("createdAt"));
        x.finishedAtMs = listingFinishedAt(row);
        return x;
    }

    private static String typeFromLabel(String label) {
        if (label == null) return "";
        String q = label.trim();
        for (Item item : CATALOG) if (item.label.equalsIgnoreCase(q)) return item.type;
        return "";
    }

    private static Listing parseSoldText(String text, long when) {
        if (text == null) return null;
        java.util.regex.Matcher m = java.util.regex.Pattern.compile(
                "(?i)you\\s+sold\\s+(?:(\\d+)\\s*[x×]\\s*)?(.+?)\\s+for\\s+\\$?([0-9]+(?:\\.[0-9]+)?)"
        ).matcher(text.trim());
        if (!m.find()) return null;
        String type = typeFromLabel(m.group(2).trim());
        if (type.isEmpty()) return null;
        Listing x = new Listing();
        x.id = ""; x.itemType = type; x.status = "sold"; x.currency = "token";
        try { x.quantity = m.group(1)==null ? 1 : Math.max(1,Integer.parseInt(m.group(1))); } catch(Exception e){x.quantity=1;}
        try { x.priceUsd = Double.parseDouble(m.group(3)); } catch(Exception ignored){}
        x.finishedAtMs = when; x.createdAtMs = when;
        return x;
    }

    private static void addSoldRows(List<Listing> out, java.util.HashSet<String> seen, JSONObject json) {
        if (json == null) return;
        JSONArray a = firstArray(json, "history", "sales", "transactions", "listings", "items", "rows", "entries", "events", "activity");
        for (int i=0;i<a.length();i++) {
            Object raw = a.opt(i);
            JSONObject row = raw instanceof JSONObject ? (JSONObject)raw : null;
            Listing x = null; boolean looksSold = false;
            if (row != null) {
                // Some marketplace history responses wrap the original listing in a `listing` object.
                JSONObject source = row.optJSONObject("listing");
                if (source == null) source = row;
                x = parseListing(source);
                if (x != null) {
                    if ((x.status == null || x.status.isEmpty()) && row != source)
                        x.status = row.optString("status", row.optString("state", ""));
                    if (x.finishedAtMs <= 0 || x.finishedAtMs == x.createdAtMs) {
                        long outerTime = listingFinishedAt(row);
                        if (outerTime > 0) x.finishedAtMs = outerTime;
                    }
                    String status = x.status == null ? "" : x.status;
                    looksSold = soldStatus(status) || source.has("soldAtMs") || source.has("completedAtMs") || source.has("filledAtMs") || source.has("soldAt") || source.has("completedAt") || source.has("filledAt") ||
                            row.has("soldAtMs") || row.has("completedAtMs") || row.has("filledAtMs") || row.has("soldAt") || row.has("completedAt") || row.has("filledAt");
                    String action = row.optString("action", row.optString("event", row.optString("kind", row.optString("type", "")))).toLowerCase(Locale.US);
                    String side = row.optString("side", row.optString("role", "")).toLowerCase(Locale.US);
                    if (action.contains("sold") || action.contains("sell") || action.contains("filled") || action.contains("complete") ||
                            "sell".equals(side) || "seller".equals(side)) looksSold = true;
                }
                String msg = row.optString("message", row.optString("text", row.optString("description", "")));
                if ((x == null || !looksSold) && !msg.isEmpty()) {
                    Listing textSale = parseSoldText(msg, listingFinishedAt(row));
                    if (textSale != null) { x=textSale; looksSold=true; }
                }
            } else if (raw != null && raw != JSONObject.NULL) {
                x = parseSoldText(String.valueOf(raw),0L);looksSold=x!=null;
            }
            if (x == null || !looksSold) continue;
            if (x.finishedAtMs <= 0) x.finishedAtMs = x.createdAtMs;
            String key = x.id!=null&&!x.id.isEmpty() ? "id:"+x.id : x.itemType+"|"+x.quantity+"|"+x.priceUsd+"|"+x.priceGold+"|"+(x.finishedAtMs/60000L);
            if (seen.add(key)) out.add(x);
        }
    }

    private static int historyArrayLength(JSONObject json) {
        return firstArray(json, "history", "sales", "transactions", "listings", "items", "rows", "entries", "events", "activity").length();
    }

    public static List<Listing> getSoldListings(Context context) throws Exception {
        List<Listing> server = new ArrayList<>();
        java.util.HashSet<String> seen = new java.util.HashSet<>();

        // Kintara has changed marketplace response shapes over time. Probe the current
        // listing route plus the historical variants used by older builds. Unknown
        // query parameters are harmless and 404/unsupported variants are skipped.
        String[] templates = new String[]{
                "/api/marketplace/listings?mine=1&sold=1&limit=100&offset=%d",
                "/api/marketplace/listings?mine=1&status=sold&limit=100&offset=%d",
                "/api/marketplace/listings?mine=1&status=completed&limit=100&offset=%d",
                "/api/marketplace/listings?mine=1&status=all&includeInactive=1&includeClosed=1&limit=100&offset=%d",
                "/api/marketplace/listings?mine=1&includeCompleted=1&includeInactive=1&limit=100&offset=%d",
                "/api/marketplace/history?mine=1&limit=100&offset=%d",
                "/api/marketplace/completed?mine=1&limit=100&offset=%d"
        };
        Exception authError = null;
        for (String template : templates) {
            for (int offset=0; offset<=400; offset+=100) {
                String path = String.format(Locale.US, template, offset);
                HttpResult r;
                try { r = request(context, "GET", path, null, 18000); }
                catch (Exception ignored) { break; }
                if (r.status == 401 || r.status == 403) { authError = new Exception("Session expired — reconnect wallet"); break; }
                if (r.status < 200 || r.status >= 300 || r.json == null || !r.json.optBoolean("ok", true)) break;
                addSoldRows(server, seen, r.json);
                if (historyArrayLength(r.json) < 100) break;
            }
            if (authError != null) break;
        }
        if (authError != null) throw authError;

        // Persist server-returned sales, then merge with completed listings detected
        // from the account's Active Sales lifecycle. This keeps website-created sales
        // visible even after they disappear from the active endpoint.
        SaleHistoryStore.mergeSales(context, server);
        List<Listing> merged = SaleHistoryStore.getAll(context);
        Collections.sort(merged, new Comparator<Listing>() {
            @Override public int compare(Listing a, Listing b) {
                long ta = a.finishedAtMs > 0 ? a.finishedAtMs : a.createdAtMs;
                long tb = b.finishedAtMs > 0 ? b.finishedAtMs : b.createdAtMs;
                return Long.compare(tb, ta);
            }
        });
        return merged;
    }

    private static void putListingId(JSONObject body, String id) throws Exception {
        try { body.put("listingId", Long.parseLong(id)); }
        catch (Exception e) { body.put("listingId", id); }
    }

    private static String buyError(String e,JSONObject j){
        if(e==null)e="";
        if("marketplace_disabled".equals(e))return "Marketplace is temporarily disabled.";
        if("listing_gone".equals(e))return "That listing is gone.";
        if("listing_reserved".equals(e))return "Someone else is completing this purchase. Try again shortly.";
        if("reserve_cooldown".equals(e)){long ms=j==null?0:j.optLong("retryAfterMs",0);return ms>0?"Buying is on cooldown for about "+Math.max(1,(ms+59999)/60000)+" minute(s).":"Buying is temporarily on cooldown.";}
        if("listing_rebound_cooldown".equals(e))return "That listing was recently held and cannot be reserved again yet.";
        if("presence_required".equals(e))return "Kintara requires the account to be in-game for buying. Reconnect to the world and try again.";
        if("own_listing".equals(e))return "You cannot buy your own listing.";
        if("reserve_failed".equals(e))return "Could not reserve this listing.";
        if("insufficient_gold".equals(e))return "Not enough Gold.";
        if("buyer_full".equals(e))return "Inventory and bank are both full.";
        if("need_buy_reserve".equals(e)||"reserve_required".equals(e))return "Checkout reservation expired. Press Buy again.";
        if("reserve_too_short_for_token".equals(e))return "Not enough time remains in this checkout window for a safe $KINS payment. Press Buy again.";
        if("quote_expired".equals(e))return "The saved $KINS quote expired. If the wallet was charged, use recovery before starting another purchase.";
        if("recover_no_signature".equals(e))return "No matching on-chain payment has been found yet. Do not pay again; wait a moment and retry recovery.";
        if("price_unavailable".equals(e))return "Could not fetch the current $KINS quote.";
        if("signer_mismatch".equals(e)||"quote_mismatch".equals(e))return "The connected wallet does not match this Kintara account.";
        if("verify_failed".equals(e)||"tx_not_found_or_failed".equals(e)||"seller_transfer_short".equals(e)||"treasury_transfer_short".equals(e)||"network_timeout".equals(e)||"network_error".equals(e)||"token_confirm_failed".equals(e))return "Your payment signature is safely saved, but Kintara has not delivered the item yet. Do not pay again; retry recovery.";
        if("tx_failed_on_chain".equals(e)||"tx_dropped_not_charged".equals(e))return "The token transaction did not complete. You were not charged.";
        if("paid_listing_gone".equals(e))return "Payment was received but delivery could not complete. Do not buy again; use recovery/support.";
        if("signature_reused".equals(e)||"signature_used_other_flow".equals(e))return "This transaction signature was already used.";
        return e.isEmpty()?"Could not complete purchase.":e;
    }

    public static BuyReserve reserveListing(Context c,String listingId){
        BuyReserve out=new BuyReserve();try{JSONObject body=new JSONObject();putListingId(body,listingId);try{JSONObject route=routeContext(c);body.put("fleet",route.optString("fleet",""));body.put("shardId",route.optInt("shardId",0));}catch(Exception ignored){}HttpResult r=request(c,"POST","/api/marketplace/reserve",body,25000);if(r.status==200&&r.json.optBoolean("ok",true)){out.ok=true;out.expiresAtMs=r.json.optLong("expiresAtMs",System.currentTimeMillis()+60000L);return out;}out.error=r.json.optString("error","reserve_failed");out.message=buyError(out.error,r.json);return out;}catch(Exception e){out.error="exception";out.message=e.getMessage();return out;}
    }

    public static void releaseBuyReserve(Context c,String listingId,boolean abandonQuote){
        try{JSONObject body=new JSONObject();putListingId(body,listingId);if(abandonQuote)body.put("abandonQuote",true);request(c,"POST","/api/marketplace/release-reserve",body,12000);}catch(Exception ignored){}
    }

    public static BuyResult buyGold(Context c,String listingId){
        BuyResult out=new BuyResult();try{JSONObject body=new JSONObject();putListingId(body,listingId);try{JSONObject route=routeContext(c);body.put("fleet",route.optString("fleet",""));body.put("shardId",route.optInt("shardId",0));}catch(Exception ignored){}HttpResult r=request(c,"POST","/api/marketplace/buy",body,35000);if(r.status==200&&r.json.optBoolean("ok",true)){out.ok=true;out.backpack=r.json.optJSONObject("backpack");out.stateSeq=r.json.optLong("stateSeq",0);return out;}out.error=r.json.optString("error","buy_failed");out.message=buyError(out.error,r.json);return out;}catch(Exception e){out.error="exception";out.message=e.getMessage();return out;}
    }

    public static TokenQuoteResult tokenQuote(Context c,String listingId){
        TokenQuoteResult out=new TokenQuoteResult();try{JSONObject body=new JSONObject();putListingId(body,listingId);HttpResult r=request(c,"POST","/api/marketplace/token-quote",body,25000);JSONObject q=r.json.optJSONObject("quote");if(r.status==200&&r.json.optBoolean("ok",false)&&q!=null){out.ok=true;out.quote=q;out.expiresAtMs=q.optLong("expiresAtMs",r.json.optLong("expiresAtMs",0));return out;}out.error=r.json.optString("error","token_quote_failed");out.message=buyError(out.error,r.json);return out;}catch(Exception e){out.error="exception";out.message=e.getMessage();return out;}
    }

    private static boolean tokenConfirmRetryableCode(String e){
        return "verify_failed".equals(e)||"tx_not_found_or_failed".equals(e)||"seller_transfer_short".equals(e)||"treasury_transfer_short".equals(e)||"need_buy_reserve".equals(e)||"network_timeout".equals(e)||"network_error".equals(e)||"token_confirm_failed".equals(e);
    }

    private static BuyResult parseTokenBuyResult(HttpResult r,String fallback){
        BuyResult out=new BuyResult();out.httpStatus=r==null?0:r.status;JSONObject j=r==null?new JSONObject():r.json;
        if(r!=null&&r.status>=200&&r.status<300&&j.optBoolean("ok",true)){out.ok=true;out.backpack=j.optJSONObject("backpack");out.stateSeq=j.optLong("stateSeq",0);out.quantity=Math.max(0,j.optInt("quantity",0));return out;}
        out.networkError=r==null||r.status==0;out.resultUnknown=out.networkError||(r!=null&&r.status>=500)||j.optBoolean("resultUnknown",false);out.error=j.optString("error",out.networkError?"network_timeout":fallback);out.retryable=out.resultUnknown||j.optBoolean("retryable",false)||tokenConfirmRetryableCode(out.error);out.message=buyError(out.error,j);return out;
    }

    public static BuyResult tokenConfirm(Context c,String quoteId,String signature){
        try{JSONObject body=new JSONObject();body.put("quoteId",quoteId);body.put("signature",signature);return parseTokenBuyResult(request(c,"POST","/api/marketplace/token-buy-confirm",body,45000),"token_confirm_failed");}catch(Exception e){BuyResult out=new BuyResult();out.error="network_error";out.message="Your payment is saved, but Kintara confirmation could not be reached.";out.resultUnknown=true;out.retryable=true;out.networkError=true;return out;}
    }

    public static BuyResult tokenRecover(Context c,String quoteId){
        try{JSONObject body=new JSONObject();body.put("quoteId",quoteId);HttpResult r=request(c,"POST","/api/marketplace/token-buy-recover",body,45000);if(r.status==200&&r.json.optBoolean("ok",false)){String sig=r.json.optString("signature","");if(!sig.isEmpty())return tokenConfirm(c,quoteId,sig);BuyResult out=new BuyResult();out.error="recover_no_signature";out.message="No matching on-chain payment has been found yet.";out.retryable=true;return out;}return parseTokenBuyResult(r,"token_recover_failed");}catch(Exception e){BuyResult out=new BuyResult();out.error="network_error";out.message="Recovery could not reach Kintara. The saved purchase was not removed.";out.resultUnknown=true;out.retryable=true;out.networkError=true;return out;}
    }

    public static JSONObject solanaRpc(Context c,String method,JSONArray params)throws Exception{
        JSONObject body=new JSONObject();body.put("jsonrpc","2.0");body.put("id",1);body.put("method",method);body.put("params",params==null?new JSONArray():params);HttpResult r=request(c,"POST","/api/auth/solana-json-rpc",body,30000);if(r.status!=200)throw new Exception("Solana relay unavailable ("+r.status+")");if(r.json.has("error")&&!r.json.isNull("error"))throw new Exception(r.json.optJSONObject("error")!=null?r.json.optJSONObject("error").optString("message",r.json.optString("error")):r.json.optString("error"));return r.json;
    }

    public static String latestFinalizedBlockhash(Context c)throws Exception{
        JSONArray p=new JSONArray();JSONObject cfg=new JSONObject();cfg.put("commitment","finalized");p.put(cfg);JSONObject r=solanaRpc(c,"getLatestBlockhash",p);JSONObject result=r.optJSONObject("result"),value=result==null?null:result.optJSONObject("value");String b=value==null?"":value.optString("blockhash","");if(b.isEmpty())throw new Exception("Could not fetch a Solana blockhash");return b;
    }

    public static boolean hasTokenBalance(Context c,String ata,String requiredRaw)throws Exception{
        JSONArray p=new JSONArray();p.put(ata);JSONObject cfg=new JSONObject();cfg.put("commitment","confirmed");p.put(cfg);JSONObject r=solanaRpc(c,"getTokenAccountBalance",p);JSONObject result=r.optJSONObject("result"),value=result==null?null:result.optJSONObject("value");if(value==null)return false;String have=value.optString("amount","0");return new BigInteger(have).compareTo(new BigInteger(requiredRaw))>=0;
    }

    public static String sendSignedTransaction(Context c,String signedBase58)throws Exception{
        byte[] raw=Base58.decode(signedBase58);String b64=Base64.encodeToString(raw,Base64.NO_WRAP);JSONArray p=new JSONArray();p.put(b64);JSONObject cfg=new JSONObject();cfg.put("encoding","base64");cfg.put("preflightCommitment","confirmed");cfg.put("skipPreflight",false);cfg.put("maxRetries",5);p.put(cfg);JSONObject r=solanaRpc(c,"sendTransaction",p);String sig=r.optString("result","");if(sig.isEmpty())throw new Exception("Solana RPC did not return a transaction signature");return sig;
    }

    public static final class TransactionStatus {
        public boolean found, confirmed, finalized, failed, timedOut;
        public String confirmationStatus="", error="";
    }

    /** Polls the authoritative Solana status for the saved first signature.
     * sendTransaction only submits; it does not wait for cluster confirmation. */
    public static TransactionStatus waitForSignatureConfirmation(Context c,String signature,long timeoutMs){
        TransactionStatus last=new TransactionStatus();long deadline=System.currentTimeMillis()+Math.max(1000L,timeoutMs);String lastError="";
        while(System.currentTimeMillis()<deadline){
            try{
                JSONArray signatures=new JSONArray();signatures.put(signature);JSONArray params=new JSONArray();params.put(signatures);JSONObject cfg=new JSONObject();cfg.put("searchTransactionHistory",true);params.put(cfg);
                JSONObject rpc=solanaRpc(c,"getSignatureStatuses",params);JSONObject result=rpc.optJSONObject("result");JSONArray values=result==null?null:result.optJSONArray("value");Object raw=values==null||values.length()==0?null:values.opt(0);
                if(raw instanceof JSONObject){JSONObject value=(JSONObject)raw;last.found=true;Object err=value.opt("err");if(err!=null&&err!=JSONObject.NULL){last.failed=true;last.error=String.valueOf(err);return last;}last.confirmationStatus=value.optString("confirmationStatus","");last.finalized="finalized".equals(last.confirmationStatus);last.confirmed=last.finalized||"confirmed".equals(last.confirmationStatus);if(last.confirmed)return last;}
            }catch(Exception e){lastError=e.getMessage()==null?e.toString():e.getMessage();}
            try{Thread.sleep(650L);}catch(InterruptedException e){Thread.currentThread().interrupt();break;}
        }
        last.timedOut=true;if(last.error.isEmpty())last.error=lastError;return last;
    }

    public static boolean isListingInBoughtHistory(Context c,String listingId){
        if(listingId==null||listingId.trim().isEmpty())return false;try{for(Listing x:getBoughtListings(c))if(x!=null&&listingId.equals(x.id))return true;}catch(Exception ignored){}return false;
    }

    /** Extracts the first Solana signature before broadcast so a successful
     * payment can always be confirmed even if the relay response is lost. */
    public static String extractSignedTransactionSignature(String signedBase58)throws Exception{
        byte[] raw=Base58.decode(signedBase58);if(raw==null||raw.length<66)throw new Exception("Signed transaction was incomplete");
        int off=0,count=0,shift=0;while(off<raw.length&&shift<=21){int b=raw[off++]&255;count|=(b&127)<<shift;if((b&128)==0)break;shift+=7;}
        if(count<1||off+64>raw.length)throw new Exception("Signed transaction did not include a signature");byte[] sig=new byte[64];System.arraycopy(raw,off,sig,0,64);boolean any=false;for(byte b:sig)if(b!=0){any=true;break;}if(!any)throw new Exception("Wallet returned an unsigned transaction");return Base58.encode(sig);
    }

    public static CancelResult cancelListing(Context context, String id) {
        CancelResult out = new CancelResult();
        if (id == null || id.trim().isEmpty()) { out.error="bad_listing"; out.message="Invalid listing."; return out; }
        try {
            JSONObject body = new JSONObject(); putListingId(body, id.trim());
            HttpResult r = request(context, "POST", "/api/marketplace/cancel", body, 18000);
            if (r.status >= 200 && r.status < 300 && r.json.optBoolean("ok", true)) { out.ok=true; return out; }
            // Compatibility fallback for older server payload naming.
            JSONObject alt = new JSONObject();
            try { alt.put("id", Long.parseLong(id.trim())); } catch (Exception e) { alt.put("id", id.trim()); }
            HttpResult r2 = request(context, "POST", "/api/marketplace/cancel", alt, 18000);
            if (r2.status >= 200 && r2.status < 300 && r2.json.optBoolean("ok", true)) { out.ok=true; return out; }
            out.error = r2.json.optString("error", r.json.optString("error", "cancel_failed"));
            out.message = "Could not cancel listing.";
            return out;
        } catch (Exception e) {
            out.error="exception"; out.message=e.getMessage()==null?e.toString():e.getMessage(); return out;
        }
    }

    private static String prettyError(String e,JSONObject d){
        if("confirm_low_price".equals(e))return "Server price protection flagged this listing as unusually low.";
        if("marketplace_disabled".equals(e))return "Marketplace is disabled by the server right now.";
        if("slot_mismatch".equals(e))return "Item moved on the server; refresh and try again.";
        if("wallet_required_for_token".equals(e))return "A linked Solana wallet is required for token listings.";
        if("bad_slot".equals(e))return "The selected inventory slot is no longer valid.";
        if("invalid_item".equals(e))return "This item cannot be listed.";
        if("wild_zone_no_listing".equals(e))return "Marketplace listing is blocked while the account is in a wilderness zone.";
        if("kins_hold_required".equals(e))return "The account does not currently satisfy the $KINS holding requirement.";
        if("listing_limit".equals(e))return "Active listing limit reached (max "+d.optInt("maxActive",5)+").";
        if("gold_min_quantity".equals(e))return "Gold listing minimum is "+d.optInt("minQty",1)+".";
        if("cannot_sell_gold_for_gold".equals(e))return "Gold can only be listed for $KINS.";
        if("bad_price_usd".equals(e))return "Invalid $KINS listing price (0.01–500000).";
        if("bad_price".equals(e)||"bad_price_gold".equals(e))return "Invalid Gold listing price.";
        if("seller_skill_too_low".equals(e))return "Seller skill requirement not met.";
        return e==null||e.isEmpty()?"Market sell failed.":e;
    }
}
