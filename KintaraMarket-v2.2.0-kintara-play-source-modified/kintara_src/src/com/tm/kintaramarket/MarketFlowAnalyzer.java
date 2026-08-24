package com.tm.kintaramarket;

import android.content.Context;

import org.json.JSONArray;
import org.json.JSONObject;

import java.util.ArrayList;
import java.util.Collections;
import java.util.Comparator;
import java.util.List;
import java.util.concurrent.Callable;
import java.util.concurrent.ExecutorService;
import java.util.concurrent.Executors;
import java.util.concurrent.Future;

/** Aggregates completed-sale flow into the long-press Trends dashboard. */
public final class MarketFlowAnalyzer {
    public static final String[] PERIODS = new String[]{"1h", "12h", "24h", "30d"};
    public static final int PERIOD_1H = 0, PERIOD_12H = 1, PERIOD_24H = 2, PERIOD_30D = 3;

    public static final class FlowRow {
        public String itemType = "", label = "", currency = "token";
        public double spent, profit;
        public int units, sales;
        public void add(double amount, double margin, int qty, int saleCount) { spent += Math.max(0, amount); profit += Math.max(0, margin); units += Math.max(0, qty); sales += Math.max(0, saleCount); }
    }
    public static final class Snapshot {
        public long updatedAt;
        public final List<List<FlowRow>> periods = new ArrayList<List<FlowRow>>();
        public List<FlowRow> get(int p) { return p >= 0 && p < periods.size() ? periods.get(p) : new ArrayList<FlowRow>(); }
    }

    private MarketFlowAnalyzer() {}

    public static Snapshot analyze(final Context c) {
        final Snapshot out = new Snapshot(); for (int i = 0; i < PERIODS.length; i++) out.periods.add(new ArrayList<FlowRow>());
        final long now = System.currentTimeMillis();
        ExecutorService pool = Executors.newFixedThreadPool(8); List<Future<KintaraApi.MarketStatsTask>> futures = new ArrayList<Future<KintaraApi.MarketStatsTask>>();
        for (final KintaraApi.Item item : KintaraApi.CATALOG) {
            futures.add(pool.submit(new Callable<KintaraApi.MarketStatsTask>() { @Override public KintaraApi.MarketStatsTask call() { return KintaraApi.loadStatsTask(c, item.type, "token"); }}));
            if (!"gold".equals(item.type)) futures.add(pool.submit(new Callable<KintaraApi.MarketStatsTask>() { @Override public KintaraApi.MarketStatsTask call() { return KintaraApi.loadStatsTask(c, item.type, "gold"); }}));
        }
        for (Future<KintaraApi.MarketStatsTask> f : futures) {
            try { KintaraApi.MarketStatsTask task = f.get(); if (task != null && task.stats != null && task.stats.ok) add(out, task.itemType, task.currency, task.stats, now); }
            catch (Exception ignored) {}
        }
        pool.shutdown(); out.updatedAt = System.currentTimeMillis();
        for (List<FlowRow> rows : out.periods) Collections.sort(rows, new Comparator<FlowRow>() { @Override public int compare(FlowRow a, FlowRow b) { int c = Double.compare(b.spent, a.spent); return c != 0 ? c : Integer.compare(b.units, a.units); }});
        return out;
    }

    private static void add(Snapshot out, String itemType, String currency, KintaraApi.MarketStats s, long now) {
        KintaraApi.Item item = KintaraApi.findItem(itemType); double baseline = baseline(s, currency);
        FlowRow[] rows = new FlowRow[PERIODS.length]; for (int i = 0; i < rows.length; i++) { rows[i] = new FlowRow(); rows[i].itemType=itemType; rows[i].label=item.label; rows[i].currency=currency; out.periods.get(i).add(rows[i]); }
        boolean hadRecent = false;
        for (KintaraApi.RecentSale sale : s.recent) {
            if (sale == null || sale.unit <= 0 || sale.soldAtMs <= 0) continue;
            long age = Math.max(0, now - sale.soldAtMs); int qty = Math.max(1, sale.quantity); double total = sale.total > 0 ? sale.total : sale.unit * qty; double margin = (sale.unit - baseline) * qty;
            if (age <= 3600000L) rows[PERIOD_1H].add(total, margin, qty, 1);
            if (age <= 12L * 3600000L) rows[PERIOD_12H].add(total, margin, qty, 1);
            if (age <= 24L * 3600000L) rows[PERIOD_24H].add(total, margin, qty, 1);
            if (age <= 30L * 86400000L) rows[PERIOD_30D].add(total, margin, qty, 1);
            hadRecent = true;
        }
        // The stats endpoint sometimes exposes only a 24h aggregate. Keep the
        // dashboard useful without fabricating shorter windows.
        if (!hadRecent && s.units24h > 0 && s.floorFor(currency) != null) {
            double total = s.floorFor(currency) * s.units24h;
            rows[PERIOD_24H].add(total, 0, s.units24h, s.sales24h);
        }
        for (KintaraApi.HistoryPoint p : s.history) {
            if (p == null || p.unit <= 0 || p.dayMs <= 0) continue;
            long age = Math.max(0, now - p.dayMs); if (age > 30L * 86400000L) continue;
            int qty = Math.max(1, p.sales); double total = p.unit * qty, margin = (p.unit - baseline) * qty;
            rows[PERIOD_30D].add(total, margin, qty, p.sales);
        }
    }

    private static double baseline(KintaraApi.MarketStats s, String currency) {
        Double floor = s.floorFor(currency); if (floor != null && floor > 0) return floor;
        List<Double> values = new ArrayList<Double>(); for (KintaraApi.HistoryPoint p : s.history) if (p != null && p.unit > 0) values.add(p.unit);
        if (values.isEmpty()) return 0; Collections.sort(values); int n=values.size(); return n%2==1?values.get(n/2):(values.get(n/2-1)+values.get(n/2))/2.0;
    }

    public static JSONObject toJson(Snapshot s) {
        JSONObject root = new JSONObject(); try { root.put("updatedAt", s == null ? 0 : s.updatedAt); JSONArray all = new JSONArray(); if (s != null) for (List<FlowRow> rows : s.periods) { JSONArray a = new JSONArray(); for (FlowRow r : rows) { JSONObject j=new JSONObject(); j.put("itemType",r.itemType); j.put("label",r.label); j.put("currency",r.currency); j.put("spent",r.spent); j.put("profit",r.profit); j.put("units",r.units); j.put("sales",r.sales); a.put(j); } all.put(a); } root.put("periods",all); } catch (Exception ignored) {} return root;
    }
    public static Snapshot fromJson(JSONObject root) {
        if (root == null) return null; Snapshot s=new Snapshot(); s.updatedAt=root.optLong("updatedAt",0); JSONArray all=root.optJSONArray("periods"); if(all==null)return s; for(int i=0;i<PERIODS.length;i++){List<FlowRow> rows=new ArrayList<FlowRow>(); JSONArray a=all.optJSONArray(i); if(a!=null)for(int k=0;k<a.length();k++){JSONObject j=a.optJSONObject(k);if(j==null)continue;FlowRow r=new FlowRow();r.itemType=j.optString("itemType","");r.label=j.optString("label",KintaraApi.humanizeType(r.itemType));r.currency=j.optString("currency","token");r.spent=j.optDouble("spent",0);r.profit=j.optDouble("profit",0);r.units=j.optInt("units",0);r.sales=j.optInt("sales",0);rows.add(r);}s.periods.add(rows);} return s;
    }
}
