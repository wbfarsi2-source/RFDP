package com.tm.kintaramarket;

import android.content.Context;

import org.json.JSONArray;
import org.json.JSONObject;

import java.io.File;
import java.io.FileInputStream;
import java.io.FileOutputStream;
import java.nio.charset.StandardCharsets;
import java.text.SimpleDateFormat;
import java.util.Calendar;
import java.util.Date;
import java.util.Locale;
import java.util.TimeZone;

public final class HistoryStore {
    public static final long RETENTION_MS = 48L * 60L * 60L * 1000L;
    private static final Object LOCK = new Object();
    private static final String FILE = "market_history_48h.json";
    public static final String[] TRACKED = {"gold", "molten_rock", "brute_horn"};

    public static final class SaleRef {
        public boolean available, exactSingle;
        public int newSales;
        public double unitPrice, normalizedTotal;
        public long ts;
    }
    public static final class WindowSummary {
        public boolean available;
        public long actualMs;
        public int completedSales;
        public Double fastStart, fastEnd, normalStart, normalEnd, profitStart, profitEnd;
        public int quoteQty;
        public long startTs, endTs;
    }

    private HistoryStore() {}

    private static String accountSuffix(Context c) {
        String wallet = SecurePrefs.getWalletPublicKey(c);
        if (wallet == null || wallet.trim().isEmpty()) wallet = "anonymous";
        try {
            java.security.MessageDigest md = java.security.MessageDigest.getInstance("SHA-256");
            byte[] b = md.digest(wallet.getBytes(StandardCharsets.UTF_8));
            StringBuilder out = new StringBuilder();
            for (int i = 0; i < 8 && i < b.length; i++) out.append(String.format(Locale.US, "%02x", b[i] & 0xff));
            return out.toString();
        } catch (Exception ignored) { return "anonymous"; }
    }
    private static File file(Context c) { return new File(c.getFilesDir(), FILE.replace(".json", "_" + accountSuffix(c) + ".json")); }
    private static JSONObject empty() throws Exception {
        JSONObject d=new JSONObject();d.put("version",1);d.put("snapshots",new JSONArray());d.put("dailyTotals",new JSONObject());d.put("lastSaleRefs",new JSONObject());return d;
    }
    private static JSONObject loadUnlocked(Context c) throws Exception {
        File f=file(c);if(!f.exists())return empty();byte[] b=new byte[(int)f.length()];try(FileInputStream in=new FileInputStream(f)){int off=0,n;while(off<b.length&&(n=in.read(b,off,b.length-off))>0)off+=n;}
        JSONObject d=new JSONObject(new String(b,StandardCharsets.UTF_8));if(d.optJSONArray("snapshots")==null)d.put("snapshots",new JSONArray());if(d.optJSONObject("dailyTotals")==null)d.put("dailyTotals",new JSONObject());if(d.optJSONObject("lastSaleRefs")==null)d.put("lastSaleRefs",new JSONObject());return d;
    }
    private static void saveUnlocked(Context c,JSONObject d) throws Exception {
        File f=file(c),tmp=new File(c.getFilesDir(),FILE.replace(".json","_"+accountSuffix(c)+".json.tmp"));byte[] b=d.toString().getBytes(StandardCharsets.UTF_8);try(FileOutputStream out=new FileOutputStream(tmp)){out.write(b);out.getFD().sync();}if(f.exists()&&!f.delete())throw new Exception("Could not replace history");if(!tmp.renameTo(f))throw new Exception("Could not commit history");
    }
    private static String utcDay(long ts) { SimpleDateFormat f=new SimpleDateFormat("yyyy-MM-dd",Locale.US);f.setTimeZone(TimeZone.getTimeZone("UTC"));return f.format(new Date(ts)); }
    private static long parseDay(String d) throws Exception { SimpleDateFormat f=new SimpleDateFormat("yyyy-MM-dd",Locale.US);f.setTimeZone(TimeZone.getTimeZone("UTC"));return f.parse(d).getTime(); }

    public static long lastSnapshotTime(Context c) {
        synchronized(LOCK){try{JSONObject d=loadUnlocked(c);JSONArray a=d.getJSONArray("snapshots");return a.length()==0?0:a.optJSONObject(a.length()-1).optLong("ts",0);}catch(Exception e){return 0;}}
    }

    public static boolean collectSnapshot(Context c) {
        final String walletAtStart=SecurePrefs.getWalletPublicKey(c);
        if(SecurePrefs.getCookie(c).isEmpty())return false;
        long now=System.currentTimeMillis();
        try {
            JSONObject snap=new JSONObject();snap.put("ts",now);snap.put("utc",new SimpleDateFormat("yyyy-MM-dd'T'HH:mm:ss'Z'",Locale.US){{setTimeZone(TimeZone.getTimeZone("UTC"));}}.format(new Date(now)));JSONObject items=new JSONObject();
            KintaraApi.Stats[] statsArr=new KintaraApi.Stats[TRACKED.length];
            for(int idx=0;idx<TRACKED.length;idx++){
                if(!walletAtStart.equals(SecurePrefs.getWalletPublicKey(c)))return false;
                String item=TRACKED[idx];int quoteQty=("molten_rock".equals(item)||"brute_horn".equals(item))?100:1;
                KintaraApi.Stats st=KintaraApi.getStats(c,item);statsArr[idx]=st;KintaraApi.Quote q=null;try{q=KintaraApi.getQuote(c,item,quoteQty);}catch(Exception ignored){}
                JSONObject x=new JSONObject();x.put("quoteQty",quoteQty);String day=utcDay(now);x.put("date",day);KintaraApi.Sample today=st.ok?st.sampleFor(day):null;x.put("sales",today==null?0:today.sales);if(today!=null&&today.avgUnitPrice!=null)x.put("avgUnitPrice",today.avgUnitPrice);if(st.avg30d!=null)x.put("avg30d",st.avg30d);
                if(q!=null){JSONObject l=new JSONObject();l.put("fast",q.fast);l.put("normal",q.normal);l.put("profit",q.profit);l.put("fastUnit",q.fastUnit);l.put("normalUnit",q.normalUnit);l.put("profitUnit",q.profitUnit);l.put("rowsSeen",q.rowsSeen);l.put("cleanRows",q.cleanRows);x.put("live",l);}items.put(item,x);
            }
            snap.put("items",items);
            if(!walletAtStart.equals(SecurePrefs.getWalletPublicKey(c)))return false;
            synchronized(LOCK){
                JSONObject d=loadUnlocked(c);JSONArray old=d.getJSONArray("snapshots");long cutoff=now-RETENTION_MS;JSONArray kept=new JSONArray();for(int i=0;i<old.length();i++){JSONObject s=old.optJSONObject(i);if(s!=null&&s.optLong("ts",0)>=cutoff)kept.put(s);}
                JSONObject prev=kept.length()>0?kept.optJSONObject(kept.length()-1):null;JSONObject refs=d.getJSONObject("lastSaleRefs");
                for(int idx=0;idx<TRACKED.length;idx++){
                    String item=TRACKED[idx];KintaraApi.Stats st=statsArr[idx];JSONObject totals=d.getJSONObject("dailyTotals");JSONObject itot=totals.optJSONObject(item);if(itot==null){itot=new JSONObject();totals.put(item,itot);}if(st!=null&&st.ok)for(KintaraApi.Sample sm:st.samples)itot.put(sm.date,sm.sales);
                    // Keep daily totals near the local 48-hour window plus a small boundary buffer.
                    java.util.Iterator<String> keys=itot.keys();java.util.ArrayList<String> drop=new java.util.ArrayList<>();while(keys.hasNext()){String k=keys.next();try{if(parseDay(k)<now-4L*24L*3600L*1000L)drop.add(k);}catch(Exception ignored){}}for(String k:drop)itot.remove(k);
                    if(prev!=null){JSONObject px=prev.optJSONObject("items")==null?null:prev.optJSONObject("items").optJSONObject(item);JSONObject cx=items.optJSONObject(item);if(px!=null&&cx!=null&&px.optString("date").equals(cx.optString("date"))&&px.has("avgUnitPrice")&&cx.has("avgUnitPrice")){
                        int n1=px.optInt("sales",0),n2=cx.optInt("sales",0),delta=n2-n1;double a1=px.optDouble("avgUnitPrice",0),a2=cx.optDouble("avgUnitPrice",0);if(delta>0&&a1>0&&a2>0){double u=((n2*a2)-(n1*a1))/delta;if((!Double.isNaN(u) && !Double.isInfinite(u))&&u>0){JSONObject r=new JSONObject();r.put("ts",now);r.put("newSales",delta);r.put("unitPrice",u);refs.put(item,r);}}}
                    }
                }
                kept.put(snap);d.put("snapshots",kept);d.put("updatedAt",now);
                // prune stale sale references
                java.util.Iterator<String> rk=refs.keys();java.util.ArrayList<String> rd=new java.util.ArrayList<>();while(rk.hasNext()){String k=rk.next();JSONObject r=refs.optJSONObject(k);if(r==null||r.optLong("ts",0)<cutoff)rd.add(k);}for(String k:rd)refs.remove(k);
                saveUnlocked(c,d);
            }
            return true;
        } catch(Exception e) { return false; }
    }

    public static JSONObject latestItem(Context c,String item) {
        synchronized(LOCK){try{JSONObject d=loadUnlocked(c);JSONArray a=d.getJSONArray("snapshots");if(a.length()==0)return null;JSONObject s=a.optJSONObject(a.length()-1);return s==null||s.optJSONObject("items")==null?null:s.optJSONObject("items").optJSONObject(item);}catch(Exception e){return null;}}
    }
    public static long latestTime(Context c) { return lastSnapshotTime(c); }

    public static SaleRef saleRef(Context c,String item,int normalizedQty) {
        synchronized(LOCK){try{JSONObject d=loadUnlocked(c);JSONObject r=d.getJSONObject("lastSaleRefs").optJSONObject(item);if(r==null)return null;long ts=r.optLong("ts",0);if(ts<System.currentTimeMillis()-RETENTION_MS)return null;SaleRef s=new SaleRef();s.available=true;s.ts=ts;s.newSales=Math.max(1,r.optInt("newSales",1));s.exactSingle=s.newSales==1;s.unitPrice=r.optDouble("unitPrice",0);s.normalizedTotal=Math.round(s.unitPrice*normalizedQty*100.0)/100.0;return s;}catch(Exception e){return null;}}
    }

    private static JSONObject closestSnapshot(JSONArray a,long target) {
        JSONObject best=null;long dist=Long.MAX_VALUE;for(int i=0;i<a.length();i++){JSONObject s=a.optJSONObject(i);if(s==null)continue;long t=s.optLong("ts",0),d=Math.abs(t-target);if(d<dist){dist=d;best=s;}}return best;
    }
    private static int salesAcross(JSONObject store,JSONObject start,JSONObject end,String item) throws Exception {
        JSONObject si=start.getJSONObject("items").getJSONObject(item),ei=end.getJSONObject("items").getJSONObject(item);String sd=si.optString("date"),ed=ei.optString("date");int sn=si.optInt("sales",0),en=ei.optInt("sales",0);if(sd.equals(ed))return Math.max(0,en-sn);
        JSONObject totals=store.getJSONObject("dailyTotals").optJSONObject(item);if(totals==null)return Math.max(0,en);
        int total=Math.max(0,totals.optInt(sd,sn)-sn)+Math.max(0,en);long cur=parseDay(sd)+24L*3600L*1000L,endDay=parseDay(ed);while(cur<endDay){String d=utcDay(cur);total+=Math.max(0,totals.optInt(d,0));cur+=24L*3600L*1000L;}return total;
    }
    private static Double live(JSONObject s,String item,String key){try{JSONObject x=s.getJSONObject("items").getJSONObject(item).optJSONObject("live");return x!=null&&x.has(key)?x.optDouble(key):null;}catch(Exception e){return null;}}

    public static WindowSummary window(Context c,String item,int hours) {
        synchronized(LOCK){try{JSONObject d=loadUnlocked(c);JSONArray a=d.getJSONArray("snapshots");if(a.length()<2)return new WindowSummary();JSONObject end=a.optJSONObject(a.length()-1);long target=end.optLong("ts",0)-hours*3600L*1000L;JSONObject start=closestSnapshot(a,target);WindowSummary w=new WindowSummary();if(start==null)return w;w.startTs=start.optLong("ts",0);w.endTs=end.optLong("ts",0);w.actualMs=w.endTs-w.startTs;long need=hours*3600L*1000L;if(w.actualMs<need*0.80)return w;w.available=true;w.completedSales=salesAcross(d,start,end,item);JSONObject ix=end.getJSONObject("items").getJSONObject(item);w.quoteQty=ix.optInt("quoteQty",("molten_rock".equals(item)||"brute_horn".equals(item))?100:1);w.fastStart=live(start,item,"fast");w.fastEnd=live(end,item,"fast");w.normalStart=live(start,item,"normal");w.normalEnd=live(end,item,"normal");w.profitStart=live(start,item,"profit");w.profitEnd=live(end,item,"profit");return w;}catch(Exception e){return new WindowSummary();}}
    }

    public static String historyPath(Context c) { return file(c).getAbsolutePath(); }
}
