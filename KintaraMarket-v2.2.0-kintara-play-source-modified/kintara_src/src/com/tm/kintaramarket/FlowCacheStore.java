package com.tm.kintaramarket;

import android.content.Context;
import android.content.SharedPreferences;

import org.json.JSONObject;

import java.nio.charset.StandardCharsets;
import java.security.MessageDigest;

/** Wallet-scoped cache for the premium long-press Trends flow dashboard. */
public final class FlowCacheStore {
    private static final String PREF = "kintara_flow_cache_v1_";
    private FlowCacheStore() {}
    private static String suffix(Context c) {
        String w = SecurePrefs.getWalletPublicKey(c); if (w == null || w.trim().isEmpty()) w = "anonymous";
        try { byte[] b=MessageDigest.getInstance("SHA-256").digest(w.getBytes(StandardCharsets.UTF_8)); StringBuilder s=new StringBuilder(); for(int i=0;i<8;i++)s.append(String.format(java.util.Locale.US,"%02x",b[i]&255)); return s.toString(); }
        catch(Exception e){return "anonymous";}
    }
    private static SharedPreferences p(Context c){return c.getSharedPreferences(PREF+suffix(c),Context.MODE_PRIVATE);}
    public static void save(Context c, MarketFlowAnalyzer.Snapshot s){if(s==null)return; p(c).edit().putString("snapshot",MarketFlowAnalyzer.toJson(s).toString()).putLong("updated",s.updatedAt).apply();}
    public static MarketFlowAnalyzer.Snapshot load(Context c){try{String raw=p(c).getString("snapshot","");return raw.isEmpty()?null:MarketFlowAnalyzer.fromJson(new JSONObject(raw));}catch(Exception e){return null;}}
    public static long updatedAt(Context c){return p(c).getLong("updated",0L);}
}
