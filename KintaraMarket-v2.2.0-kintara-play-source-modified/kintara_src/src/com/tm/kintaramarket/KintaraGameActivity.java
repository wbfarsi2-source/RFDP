package com.tm.kintaramarket;

import android.annotation.SuppressLint;
import android.app.Activity;
import android.content.ActivityNotFoundException;
import android.content.Intent;
import android.content.pm.ActivityInfo;
import android.graphics.Color;
import android.graphics.Typeface;
import android.graphics.drawable.ColorDrawable;
import android.graphics.drawable.GradientDrawable;
import android.net.Uri;
import android.os.Build;
import android.os.Bundle;
import android.os.Handler;
import android.os.Looper;
import android.view.Gravity;
import android.view.View;
import android.view.ViewGroup;
import android.view.Window;
import android.webkit.CookieManager;
import android.webkit.WebChromeClient;
import android.webkit.WebSettings;
import android.webkit.WebView;
import android.webkit.WebViewClient;
import android.widget.Button;
import android.widget.FrameLayout;
import android.widget.LinearLayout;
import android.widget.ProgressBar;
import android.widget.TextView;

/**
 * Full-screen Android shell for Kintara's authenticated multiplayer client.
 *
 * The renderer remains the official Three.js client served by Kintara; this
 * Activity removes browser chrome, supplies the encrypted session cookie, locks
 * the game to portrait mobile HUD mode, and lets the same API/WebSocket game
 * servers handle the live world. It is intentionally separate from the tiny
 * background-presence WebView used by the market screens.
 */
public final class KintaraGameActivity extends Activity {
    private static WebView retainedWeb;
    private static final int BG = Color.rgb(13, 18, 24);
    private static final int TEXT = Color.rgb(239, 243, 248);
    private static final int MUTED = Color.rgb(164, 174, 187);
    private static final int ACCENT = Color.rgb(72, 205, 141);
    private static final int WARN = Color.rgb(255, 184, 77);
    private static final int RED = Color.rgb(244, 96, 96);
    private static final String GAME_URL = KintaraApi.BASE + "/play?app=android&embedded=1";

    private final Handler handler = new Handler(Looper.getMainLooper());
    private FrameLayout root;
    private WebView web;
    private TextView connectionLabel;
    private LinearLayout errorPanel;
    private Runnable hideConnection;
    private boolean closing;

    private int dp(int value) {
        return (int) (value * getResources().getDisplayMetrics().density + .5f);
    }

    private GradientDrawable panel(int color, int radius, int strokeColor) {
        GradientDrawable g = new GradientDrawable();
        g.setColor(color);
        g.setCornerRadius(dp(radius));
        if (strokeColor != Color.TRANSPARENT) g.setStroke(dp(1), strokeColor);
        return g;
    }

    private TextView label(String value, int size, int color, boolean bold) {
        TextView v = new TextView(this);
        v.setText(value);
        v.setTextSize(size);
        v.setTextColor(color);
        v.setTypeface(Typeface.DEFAULT, bold ? Typeface.BOLD : Typeface.NORMAL);
        v.setGravity(Gravity.CENTER_VERTICAL);
        return v;
    }

    @Override
    protected void onCreate(Bundle state) {
        super.onCreate(state);
        if (!PremiumManager.hasPremium(this) || SecurePrefs.getCookie(this).isEmpty()) {
            setResult(RESULT_CANCELED);
            finish();
            return;
        }
        // Kintara's mobile HUD is designed for the narrow layout. Android will
        // rotate the device into portrait unless the user has a system-level
        // orientation lock enabled.
        setRequestedOrientation(ActivityInfo.SCREEN_ORIENTATION_LANDSCAPE);
        Window window = getWindow();
        window.setStatusBarColor(Color.TRANSPARENT);
        window.setNavigationBarColor(Color.TRANSPARENT);
        window.addFlags(android.view.WindowManager.LayoutParams.FLAG_KEEP_SCREEN_ON);
        enterImmersiveMode();

        root = new FrameLayout(this);
        root.setBackgroundColor(BG);
        web = retainedWeb != null ? retainedWeb : createWebView();
        retainedWeb = web;
        if (web.getParent() instanceof ViewGroup) ((ViewGroup) web.getParent()).removeView(web);
        root.addView(web, new FrameLayout.LayoutParams(ViewGroup.LayoutParams.MATCH_PARENT, ViewGroup.LayoutParams.MATCH_PARENT));
        addNativeChrome();
        setContentView(root);

        syncSessionCookie();
        web.loadUrl(GAME_URL);
    }

    @SuppressLint({"SetJavaScriptEnabled", "AddJavascriptInterface"})
    private WebView createWebView() {
        final WebView view = new WebView(this);
        view.setBackgroundColor(BG);
        view.setOverScrollMode(View.OVER_SCROLL_NEVER);
        view.setVerticalScrollBarEnabled(false);
        view.setHorizontalScrollBarEnabled(false);
        view.setLayerType(View.LAYER_TYPE_HARDWARE, null);
        WebSettings settings = view.getSettings();
        settings.setJavaScriptEnabled(true);
        settings.setDomStorageEnabled(true);
        settings.setDatabaseEnabled(true);
        settings.setSupportZoom(false);
        settings.setBuiltInZoomControls(false);
        settings.setDisplayZoomControls(false);
        settings.setLoadWithOverviewMode(false);
        settings.setUseWideViewPort(false);
        settings.setAllowFileAccess(false);
        settings.setAllowContentAccess(false);
        settings.setMediaPlaybackRequiresUserGesture(false);
        settings.setLoadsImagesAutomatically(true);
        settings.setBlockNetworkImage(false);
        settings.setUserAgentString(KintaraApi.UA + " KintaraGameApp/2.1.0");
        if (Build.VERSION.SDK_INT >= 21) settings.setMixedContentMode(WebSettings.MIXED_CONTENT_NEVER_ALLOW);
        if (Build.VERSION.SDK_INT >= 23) settings.setOffscreenPreRaster(true);
        if (Build.VERSION.SDK_INT >= 26) view.setRendererPriorityPolicy(WebView.RENDERER_PRIORITY_IMPORTANT, false);

        CookieManager cookies = CookieManager.getInstance();
        cookies.setAcceptCookie(true);
        if (Build.VERSION.SDK_INT >= 21) cookies.setAcceptThirdPartyCookies(view, true);
        view.setWebChromeClient(new WebChromeClient());
        view.setWebViewClient(new WebViewClient() {
            @Override
            public boolean shouldOverrideUrlLoading(WebView v, String url) {
                if (url == null || url.trim().isEmpty()) return true;
                Uri u = Uri.parse(url);
                String scheme = u.getScheme() == null ? "" : u.getScheme().toLowerCase(java.util.Locale.US);
                if ("http".equals(scheme) || "https".equals(scheme)) return false;
                try {
                    startActivity(new Intent(Intent.ACTION_VIEW, u));
                } catch (ActivityNotFoundException ignored) {
                    showConnection("This link cannot be opened on this device", RED, false);
                }
                return true;
            }

            @Override
            public void onPageStarted(WebView v, String url, android.graphics.Bitmap icon) {
                showConnection("Connecting to Kintara…", ACCENT, true);
            }

            @Override
            public void onPageFinished(WebView v, String url) {
                injectNativeSkin();
                showConnection("Online game surface", ACCENT, true);
                if (hideConnection != null) handler.removeCallbacks(hideConnection);
                hideConnection = new Runnable() {
                    @Override public void run() { if (!closing && connectionLabel != null) connectionLabel.animate().alpha(0f).setDuration(260L).start(); }
                };
                handler.postDelayed(hideConnection, 1800L);
            }

            @SuppressWarnings("deprecation")
            @Override
            public void onReceivedError(WebView v, int code, String description, String failingUrl) {
                if (failingUrl == null || failingUrl.equals(v.getUrl())) {
                    showLoadError("Game connection failed. Check your internet and try again.");
                }
            }
        });
        return view;
    }

    private void addNativeChrome() {
        TextView exit = label("EXIT", 9, TEXT, true);
        exit.setGravity(Gravity.CENTER);
        exit.setPadding(dp(13), 0, dp(13), 0);
        exit.setBackground(panel(Color.argb(205, 16, 24, 32), 18, Color.argb(180, 132, 151, 169)));
        exit.setElevation(dp(8));
        exit.setContentDescription("Exit Kintara game");
        exit.setOnClickListener(new View.OnClickListener() {
            @Override public void onClick(View v) { closeGame(); }
        });
        FrameLayout.LayoutParams exitParams = new FrameLayout.LayoutParams(dp(62), dp(28), Gravity.TOP | Gravity.START);
        exitParams.setMargins(dp(20), dp(76), 0, 0);
        root.addView(exit, exitParams);

        connectionLabel = label("Connecting to Kintara…", 10, ACCENT, true);
        connectionLabel.setGravity(Gravity.CENTER);
        connectionLabel.setPadding(dp(10), 0, dp(10), 0);
        connectionLabel.setBackground(panel(Color.argb(185, 12, 21, 29), 16, Color.argb(150, 72, 205, 141)));
        FrameLayout.LayoutParams statusParams = new FrameLayout.LayoutParams(ViewGroup.LayoutParams.WRAP_CONTENT, dp(34), Gravity.TOP | Gravity.CENTER_HORIZONTAL);
        statusParams.setMargins(0, dp(14), 0, 0);
        root.addView(connectionLabel, statusParams);
    }

    private void syncSessionCookie() {
        String cookie = SecurePrefs.getCookie(this);
        if (cookie == null || cookie.trim().isEmpty()) return;
        CookieManager manager = CookieManager.getInstance();
        manager.setCookie(KintaraApi.BASE, cookie + "; Path=/; Secure; SameSite=Lax");
        if (Build.VERSION.SDK_INT >= 21) manager.flush();
    }

    private void injectNativeSkin() {
        if (web == null) return;
        String js = "(function(){try{" +
                "document.documentElement.classList.add('kintara-android-app');" +
                "var s=document.getElementById('__km_android_skin');" +
                "if(!s){s=document.createElement('style');s.id='__km_android_skin';document.head.appendChild(s);}" +
                "s.textContent='html,body{width:100%!important;height:100%!important;overflow:hidden!important;background:#121a22!important;-webkit-user-select:none!important;user-select:none!important;}canvas{touch-action:none!important;}';" +
                "try{if(screen.orientation&&screen.orientation.lock)screen.orientation.lock('portrait').catch(function(){});}catch(e){}" +
                "}catch(e){}})();";
        try { web.evaluateJavascript(js, null); } catch (Exception ignored) { }
    }

    private void showConnection(String message, int color, boolean transientMessage) {
        if (connectionLabel == null || closing) return;
        connectionLabel.setText(message);
        connectionLabel.setTextColor(color);
        connectionLabel.setAlpha(1f);
        if (!transientMessage) connectionLabel.setBackground(panel(Color.argb(220, 45, 22, 24), 16, color));
    }

    private void showLoadError(String message) {
        if (root == null || closing) return;
        if (errorPanel != null && errorPanel.getParent() instanceof ViewGroup) ((ViewGroup) errorPanel.getParent()).removeView(errorPanel);
        errorPanel = new LinearLayout(this);
        errorPanel.setOrientation(LinearLayout.VERTICAL);
        errorPanel.setGravity(Gravity.CENTER_HORIZONTAL);
        errorPanel.setPadding(dp(22), dp(20), dp(22), dp(18));
        errorPanel.setBackground(panel(Color.rgb(24, 30, 38), 20, RED));
        TextView title = label("KINTARA GAME", 17, TEXT, true); title.setGravity(Gravity.CENTER); errorPanel.addView(title);
        TextView copy = label(message, 11, MUTED, false); copy.setGravity(Gravity.CENTER); copy.setTextAlignment(View.TEXT_ALIGNMENT_CENTER); errorPanel.addView(copy, margins(ViewGroup.LayoutParams.MATCH_PARENT, ViewGroup.LayoutParams.WRAP_CONTENT, 0, 8, 0, 13));
        LinearLayout actions = new LinearLayout(this); actions.setGravity(Gravity.CENTER);
        Button retry = new Button(this); retry.setText("RETRY"); retry.setTextColor(Color.WHITE); retry.setAllCaps(false); retry.setBackground(panel(Color.rgb(38, 133, 96), 12, ACCENT)); retry.setOnClickListener(new View.OnClickListener(){@Override public void onClick(View v){removeError();syncSessionCookie();if(web!=null)web.reload();}}); actions.addView(retry, margins(0, dp(44), 0, 0, 6, 0, 1));
        Button exit = new Button(this); exit.setText("EXIT"); exit.setTextColor(MUTED); exit.setAllCaps(false); exit.setBackground(panel(Color.rgb(31, 38, 47), 12, Color.rgb(74, 87, 102))); exit.setOnClickListener(new View.OnClickListener(){@Override public void onClick(View v){closeGame();}}); actions.addView(exit, margins(0, dp(44), 6, 0, 0, 0, 1));
        errorPanel.addView(actions, new LinearLayout.LayoutParams(ViewGroup.LayoutParams.MATCH_PARENT, dp(44)));
        FrameLayout.LayoutParams p = new FrameLayout.LayoutParams((int)(getResources().getDisplayMetrics().widthPixels * .86f), ViewGroup.LayoutParams.WRAP_CONTENT, Gravity.CENTER);
        root.addView(errorPanel, p);
        showConnection("Game connection failed", RED, false);
    }

    private LinearLayout.LayoutParams margins(int w, int h, int l, int t, int r, int b) {
        LinearLayout.LayoutParams p = new LinearLayout.LayoutParams(w, h);
        p.setMargins(dp(l), dp(t), dp(r), dp(b));
        return p;
    }

    private LinearLayout.LayoutParams margins(int w, int h, int l, int t, int r, int b, float weight) {
        LinearLayout.LayoutParams p = margins(w, h, l, t, r, b); p.weight = weight; return p;
    }

    private void removeError() {
        if (errorPanel != null && errorPanel.getParent() instanceof ViewGroup) ((ViewGroup) errorPanel.getParent()).removeView(errorPanel);
        errorPanel = null;
    }

    private void enterImmersiveMode() {
        getWindow().getDecorView().setSystemUiVisibility(
                View.SYSTEM_UI_FLAG_IMMERSIVE_STICKY |
                View.SYSTEM_UI_FLAG_FULLSCREEN |
                View.SYSTEM_UI_FLAG_HIDE_NAVIGATION |
                View.SYSTEM_UI_FLAG_LAYOUT_FULLSCREEN |
                View.SYSTEM_UI_FLAG_LAYOUT_HIDE_NAVIGATION |
                View.SYSTEM_UI_FLAG_LAYOUT_STABLE);
    }

    private void closeGame() {
        if (closing) return;
        closing = true;
        if (web != null) { try { web.onPause(); } catch (Exception ignored) {} }
        setResult(RESULT_OK);
        finish();
    }

    @Override
    public void onBackPressed() { closeGame(); }

    @Override
    public void onWindowFocusChanged(boolean hasFocus) {
        super.onWindowFocusChanged(hasFocus);
        if (hasFocus) enterImmersiveMode();
    }

    @Override
    protected void onResume() {
        super.onResume();
        enterImmersiveMode();
        if (web != null) { web.onResume(); web.resumeTimers(); }
    }

    @Override
    protected void onPause() {
        if (web != null) { try { web.onResume(); web.resumeTimers(); } catch (Exception ignored) {} }
        super.onPause();
    }

    @Override
    protected void onDestroy() {
        if (hideConnection != null) handler.removeCallbacks(hideConnection);
        if (web != null) {
            try { web.removeAllViews(); } catch (Exception ignored) { }
            web = null;
        }
        super.onDestroy();
    }
}
