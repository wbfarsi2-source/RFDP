package com.tm.kintaramarket;

import android.app.Activity;
import android.os.Handler;
import android.os.Looper;
import android.webkit.JavascriptInterface;
import android.webkit.WebSettings;
import android.webkit.WebView;
import android.webkit.WebViewClient;

import org.json.JSONObject;

/** Builds an unsigned Solana USDC Premium payment from bundled, offline assets. */
public final class PremiumUsdcTxBuilder {
    public interface Callback { void done(Result result, Exception error); }
    public static final class Result { public String transactionBase64 = "", userAta = "", treasuryAta = "", amountRaw = ""; }
    private PremiumUsdcTxBuilder() {}

    public static void build(final Activity activity, final String payer58, final String destinationOwner58,
                             final String mint58, final long amountRaw, final String blockhash, final Callback callback) {
        activity.runOnUiThread(new Runnable(){ public void run(){
            final WebView web = new WebView(activity); final Handler h = new Handler(Looper.getMainLooper()); final boolean[] finished = {false};
            final Runnable timeout = new Runnable(){ public void run(){ if(finished[0])return; finished[0]=true; try{web.destroy();}catch(Exception ignored){} callback.done(null,new Exception("Premium USDC transaction builder timed out.")); }};
            final class Bridge {
                @JavascriptInterface public void onReady(){ h.post(new Runnable(){ public void run(){ if(finished[0])return; String js="window.buildPremiumUsdcTx("+JSONObject.quote(payer58)+","+JSONObject.quote(destinationOwner58)+","+JSONObject.quote(mint58)+","+amountRaw+","+JSONObject.quote(blockhash)+")"; web.evaluateJavascript(js,null); }}); }
                @JavascriptInterface public void onResult(final String raw){ h.post(new Runnable(){ public void run(){
                    if(finished[0])return; finished[0]=true; h.removeCallbacks(timeout);
                    try { JSONObject j=new JSONObject(raw); if(!j.optBoolean("ok",false))throw new Exception(j.optString("error","Could not build Premium USDC transaction."));
                        Result r=new Result(); r.transactionBase64=j.optString("transactionBase64",""); r.userAta=j.optString("userAta",""); r.treasuryAta=j.optString("treasuryAta",""); r.amountRaw=j.optString("amountRaw","");
                        if(r.transactionBase64.isEmpty()||r.userAta.isEmpty()||r.treasuryAta.isEmpty())throw new Exception("Premium USDC transaction was incomplete."); callback.done(r,null);
                    } catch(Exception e){ callback.done(null,e); } finally { try{web.destroy();}catch(Exception ignored){} }
                }}); }
            }
            WebSettings s=web.getSettings(); s.setJavaScriptEnabled(true); s.setAllowFileAccess(true); s.setAllowContentAccess(false); if(android.os.Build.VERSION.SDK_INT>=16)s.setAllowFileAccessFromFileURLs(true);
            web.addJavascriptInterface(new Bridge(),"AndroidBridge"); web.setWebViewClient(new WebViewClient()); h.postDelayed(timeout,12_000L); web.loadUrl("file:///android_asset/premium_usdc_tx_builder.html");
        }});
    }
}
