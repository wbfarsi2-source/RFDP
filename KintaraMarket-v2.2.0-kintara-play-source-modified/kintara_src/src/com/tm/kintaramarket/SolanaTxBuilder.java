package com.tm.kintaramarket;

import android.app.Activity;
import android.os.Handler;
import android.os.Looper;
import android.webkit.JavascriptInterface;
import android.webkit.WebSettings;
import android.webkit.WebView;
import android.webkit.WebViewClient;

import org.json.JSONObject;

/**
 * Builds the unsigned Token-2022 marketplace payment transaction using the same
 * Solana/SPL JS primitives bundled in Kintara's current public client. The WebView
 * is never shown and has no remote page; it only loads APK assets.
 */
public final class SolanaTxBuilder {
    public interface Callback { void done(Result result, Exception error); }
    public static final class Result {
        public String transactionBase64="", userAta="", totalAmount="";
    }
    private SolanaTxBuilder() {}

    public static void build(final Activity activity, final JSONObject quote, final String payer58, final String blockhash, final Callback callback) {
        activity.runOnUiThread(new Runnable(){@Override public void run(){
            final WebView web=new WebView(activity);
            final Handler h=new Handler(Looper.getMainLooper());
            final boolean[] finished={false};
            final Runnable timeout=new Runnable(){@Override public void run(){if(finished[0])return;finished[0]=true;try{web.destroy();}catch(Exception ignored){}callback.done(null,new Exception("Solana transaction builder timed out"));}};
            final class Bridge {
                @JavascriptInterface public void onReady(){
                    h.post(new Runnable(){@Override public void run(){
                        if(finished[0])return;
                        String js="window.buildMarketplaceTx("+JSONObject.quote(quote.toString())+","+JSONObject.quote(payer58)+","+JSONObject.quote(blockhash)+")";
                        web.evaluateJavascript(js,null);
                    }});
                }
                @JavascriptInterface public void onResult(final String raw){
                    h.post(new Runnable(){@Override public void run(){
                        if(finished[0])return;finished[0]=true;h.removeCallbacks(timeout);
                        try{
                            JSONObject j=new JSONObject(raw);
                            if(!j.optBoolean("ok",false))throw new Exception(j.optString("error","Could not build token transaction"));
                            Result r=new Result();r.transactionBase64=j.optString("transactionBase64","");r.userAta=j.optString("userAta","");r.totalAmount=j.optString("totalAmount","");
                            if(r.transactionBase64.isEmpty()||r.userAta.isEmpty())throw new Exception("Token transaction builder returned incomplete data");
                            callback.done(r,null);
                        }catch(Exception e){callback.done(null,e);}finally{try{web.destroy();}catch(Exception ignored){}}
                    }});
                }
            }
            WebSettings s=web.getSettings();s.setJavaScriptEnabled(true);s.setAllowFileAccess(true);s.setAllowContentAccess(false);
            // Local ES modules import sibling APK assets. No network origin is granted.
            if(android.os.Build.VERSION.SDK_INT>=16)s.setAllowFileAccessFromFileURLs(true);
            web.addJavascriptInterface(new Bridge(),"AndroidBridge");
            web.setWebViewClient(new WebViewClient());
            h.postDelayed(timeout,12000L);
            web.loadUrl("file:///android_asset/tx_builder.html");
        }});
    }
}
