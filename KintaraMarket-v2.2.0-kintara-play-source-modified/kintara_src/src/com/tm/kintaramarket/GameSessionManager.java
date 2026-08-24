package com.tm.kintaramarket;

import android.annotation.SuppressLint;
import android.app.Activity;
import android.graphics.Color;
import android.os.Build;
import android.os.Handler;
import android.os.Looper;
import android.view.Gravity;
import android.view.View;
import android.view.ViewGroup;
import android.webkit.CookieManager;
import android.webkit.JavascriptInterface;
import android.webkit.WebChromeClient;
import android.webkit.WebSettings;
import android.webkit.WebView;
import android.webkit.WebViewClient;
import android.widget.FrameLayout;

/**
 * Maintains the authenticated Kintara Queue/Presence connection in a tiny,
 * attached WebView. It intentionally does not load the game renderer: the
 * WebView supplies the official same-origin cookie, fetch and WebSocket
 * environment while a small controller joins a public shard and publishes the
 * real Bank Market position required by marketplace mutations.
 */
public final class GameSessionManager {
    public interface Listener { void onGameSessionChanged(); }

    private static final String SESSION_URL = KintaraApi.BASE + "/api/auth/me?km_background_presence=1";
    private final Activity activity;
    private final Listener listener;
    private final Handler handler = new Handler(Looper.getMainLooper());
    private FrameLayout layer;
    private WebView web;
    private boolean loaded, ready, destroyed, injected;
    private String status = "Starting background presence…";
    private String fleet = "", serverName = "";
    private int shardId;

    public GameSessionManager(Activity activity, Listener listener) {
        this.activity = activity;
        this.listener = listener;
    }

    private int dp(int n) {
        return (int) (n * activity.getResources().getDisplayMetrics().density + .5f);
    }

    @SuppressLint({"SetJavaScriptEnabled", "AddJavascriptInterface"})
    private void ensureCreated() {
        if (layer != null || destroyed) return;
        layer = new FrameLayout(activity);
        layer.setBackgroundColor(Color.TRANSPARENT);
        layer.setAlpha(.01f);
        layer.setClickable(false);
        layer.setFocusable(false);

        web = new WebView(activity);
        web.setBackgroundColor(Color.TRANSPARENT);
        web.setLayerType(View.LAYER_TYPE_HARDWARE, null);
        WebSettings s = web.getSettings();
        s.setJavaScriptEnabled(true);
        s.setDomStorageEnabled(true);
        s.setDatabaseEnabled(true);
        s.setAllowFileAccess(false);
        s.setAllowContentAccess(false);
        s.setMixedContentMode(WebSettings.MIXED_CONTENT_NEVER_ALLOW);
        s.setMediaPlaybackRequiresUserGesture(true);
        s.setLoadsImagesAutomatically(false);
        s.setBlockNetworkImage(true);
        s.setUserAgentString(KintaraApi.UA + " KintaraMarketPresence/1.1");
        if (Build.VERSION.SDK_INT >= 23) s.setOffscreenPreRaster(true);
        if (Build.VERSION.SDK_INT >= 26) web.setRendererPriorityPolicy(WebView.RENDERER_PRIORITY_IMPORTANT, false);

        CookieManager cm = CookieManager.getInstance();
        cm.setAcceptCookie(true);
        if (Build.VERSION.SDK_INT >= 21) cm.setAcceptThirdPartyCookies(web, true);
        web.addJavascriptInterface(new Bridge(), "AndroidGameBridge");
        web.setWebChromeClient(new WebChromeClient());
        web.setWebViewClient(new WebViewClient() {
            @Override public void onPageStarted(WebView view, String url, android.graphics.Bitmap icon) {
                loaded = false;
                injected = false;
                ready = false;
                setStatus("Authenticating background presence…");
            }

            @Override public void onPageFinished(WebView view, String url) {
                if (destroyed || view != web) return;
                loaded = true;
                injectController();
            }

            @SuppressWarnings("deprecation")
            @Override public void onReceivedError(WebView view, int code, String description, String failingUrl) {
                ready = false;
                setStatus("Background connection failed · tap Reconnect");
            }
        });
        layer.addView(web, new FrameLayout.LayoutParams(ViewGroup.LayoutParams.MATCH_PARENT, ViewGroup.LayoutParams.MATCH_PARENT));
    }

    private FrameLayout.LayoutParams tinyParams() {
        return new FrameLayout.LayoutParams(dp(2), dp(2), Gravity.TOP | Gravity.START);
    }

    private void syncSessionCookie() {
        String cookie = SecurePrefs.getCookie(activity);
        if (cookie == null || cookie.trim().isEmpty()) return;
        CookieManager cm = CookieManager.getInstance();
        cm.setCookie(KintaraApi.BASE, cookie + "; Path=/; Secure; HttpOnly; SameSite=Lax");
        if (Build.VERSION.SDK_INT >= 21) cm.flush();
    }

    public void attachTo(FrameLayout host) {
        ensureCreated();
        if (layer == null || host == null) return;
        ViewGroup old = (ViewGroup) layer.getParent();
        if (old != null) old.removeView(layer);
        host.addView(layer, tinyParams());
        layer.bringToFront();
        startIfNeeded();
    }

    private void startIfNeeded() {
        if (destroyed || web == null) return;
        syncSessionCookie();
        web.onResume();
        web.resumeTimers();
        if (!loaded) {
            setStatus("Authenticating background presence…");
            web.loadUrl(SESSION_URL + "&v=" + System.currentTimeMillis());
        } else if (!injected) {
            injectController();
        }
    }

    private void injectController() {
        if (destroyed || web == null || injected) return;
        injected = true;
        setStatus("Finding an available public server…");
        try { web.evaluateJavascript(controllerScript(), null); }
        catch (Exception e) {
            injected = false;
            ready = false;
            setStatus("Could not start background presence · tap Reconnect");
        }
    }

    /** Kept for MainActivity compatibility; there is deliberately no visible game surface. */
    public void show() { retry(); }

    /** The connection is permanently minimized because no game UI is rendered. */
    public void minimize() { }

    public void retry() {
        ensureCreated();
        if (web == null || destroyed) return;
        syncSessionCookie();
        ready = false;
        injected = false;
        setStatus("Reconnecting in the background…");
        try { web.evaluateJavascript("try{window.__kmPresenceStop&&window.__kmPresenceStop();}catch(e){}", null); }
        catch (Exception ignored) { }
        web.loadUrl(SESSION_URL + "&v=" + System.currentTimeMillis());
    }

    public boolean isExpanded() { return false; }
    public boolean isReady() { return ready; }
    public boolean isStarted() { return loaded || injected; }
    public String status() { return status; }
    public String routeLabel() {
        if (!ready) return "";
        String label = serverName == null || serverName.trim().isEmpty() ? "Public Server" : serverName.trim();
        return label + " · " + fleet.toUpperCase(java.util.Locale.US) + "/" + shardId + " · Bank Market";
    }

    public void onHostResume() {
        if (web == null || destroyed) return;
        web.onResume();
        web.resumeTimers();
        if (!ready) startIfNeeded();
        else {
            try { web.evaluateJavascript("try{window.__kmPresenceWake&&window.__kmPresenceWake();}catch(e){}", null); }
            catch (Exception ignored) { }
        }
    }

    public void destroy() {
        destroyed = true;
        ready = false;
        if (web != null) {
            try { web.evaluateJavascript("try{window.__kmPresenceStop&&window.__kmPresenceStop();}catch(e){}", null); }
            catch (Exception ignored) { }
            try { web.stopLoading(); } catch (Exception ignored) { }
            try { web.loadUrl("about:blank"); } catch (Exception ignored) { }
            try { web.destroy(); } catch (Exception ignored) { }
        }
        if (layer != null && layer.getParent() instanceof ViewGroup) ((ViewGroup) layer.getParent()).removeView(layer);
        web = null;
        layer = null;
        notifyListener();
    }

    private void setStatus(String next) {
        status = next == null || next.trim().isEmpty() ? "Checking background presence…" : next.trim();
        notifyListener();
    }

    private void notifyListener() {
        if (listener != null) listener.onGameSessionChanged();
    }

    /**
     * Mirrors the deployed server-select Queue/Presence protocol. The document
     * is loaded from kintara.com/play so fetch uses the authenticated host-only cookie
     * and cross-origin shard sockets carry the same Origin as the official game.
     */
    private static String controllerScript() {
        StringBuilder j = new StringBuilder(12500);
        j.append("(function(){'use strict';");
        j.append("try{if(window.__kmPresenceStop)window.__kmPresenceStop();}catch(_e){}");
        j.append("var stopped=false,qws=null,pws=null,qPing=null,posTick=null,watch=null,retryTimer=null,zeroTimer=null,retries=0,current=null;");
        j.append("function state(s){try{AndroidGameBridge.onState(String(s||''));}catch(e){}}");
        j.append("function clearTimer(t){try{if(t)clearTimeout(t);}catch(e){}}");
        j.append("function cleanup(){clearTimer(qPing);clearTimer(posTick);clearTimer(watch);clearTimer(retryTimer);clearTimer(zeroTimer);qPing=posTick=watch=retryTimer=zeroTimer=null;try{if(qws){qws.onclose=qws.onerror=qws.onmessage=null;qws.close();}}catch(e){}try{if(pws){pws.onclose=pws.onerror=pws.onmessage=null;pws.close();}}catch(e){}qws=pws=null;}");
        j.append("window.__kmPresenceStop=function(){stopped=true;cleanup();};");
        j.append("function norm(v){var x=String(v||'').trim().toLowerCase();if(!x)return'us';if(x==='usa'||x==='na'||x==='north-america'||x==='north_america')return'us';if(x==='europe')return'eu';if(x==='apac'||x==='asia-pacific'||x==='asia_pacific')return'asia';return x.replace(/[^a-z0-9_-]+/g,'-').replace(/^-+|-+$/g,'')||'us';}");
        j.append("function cross(base){if(!base)return false;try{return new URL(String(base).replace(/^wss:/i,'https:').replace(/^ws:/i,'http:'),location.href).origin!==location.origin;}catch(e){return true;}}");
        j.append("function wsurl(path,base,token){var b=String(base||'').trim(),u;if(b)u=b.replace(/^http/i,'ws').replace(/\\/+$/,'')+path;else u=(location.protocol==='https:'?'wss:':'ws:')+'//'+location.host+path;if(token)u+=(u.indexOf('?')>=0?'&':'?')+'kt='+encodeURIComponent(token);return u;}");
        j.append("async function token(purpose){if(!cross(current.base))return'';var q=new URLSearchParams({shard:String(current.shard),purpose:String(purpose)});q.set('zone',current.fleet);if(current.display>0)q.set('display',String(current.display));var r=await fetch('/api/lobby/connect-token?'+q.toString(),{credentials:'include',cache:'no-store'});if(r.status===404)return'';var x=await r.json().catch(function(){return null;});if(!r.ok||!x||x.ok!==true||!x.token)throw new Error(x&&x.error?x.error:'connect_token_failed');return String(x.token);}");
        j.append("function choose(a){var rows=(Array.isArray(a)?a:[]).filter(function(s){var m=/^Server (\\d+)$/.exec(String(s&&s.name||''));return !!m&&Number(m[1])>=9&&!s.unavailable&&!s.requiresMembership&&!(Number(s.minLevel)>0)&&!(s.full&&Number(s.queueLength)>80);});if(!rows.length)throw new Error('no_public_server');function pop(s){var p=String(s&&s.populationLabel||'').toLowerCase();return p==='low'?0:p==='medium'?1:p==='high'?2:1;}function shard(s){return Number(s.routeShardId||s.localShardId||s.id||0)|0;}rows.sort(function(a,b){return pop(a)-pop(b)||Number(a.queueLength||0)-Number(b.queueLength||0)||Number(a.id||0)-Number(b.id||0);});var bestPop=pop(rows[0]),quiet=rows.filter(function(s){return pop(s)===bestPop;}).slice(0,Math.min(4,rows.length)),last=Number(sessionStorage.getItem('__kmLastPresenceShard')||0)|0;if(quiet.length>1){var fresh=quiet.filter(function(s){return shard(s)!==last;});if(fresh.length)quiet=fresh;}var s=quiet[Math.floor(Math.random()*quiet.length)],sh=shard(s);if(sh<=0)throw new Error('invalid_server_route');try{sessionStorage.setItem('__kmLastPresenceShard',String(sh));}catch(e){}return{shard:sh,display:Number(s.id||0)|0,name:String(s.name||('Server '+s.id)),fleet:norm(s.zone||s.region),base:String(s.wsBaseUrl||'')};}");
        j.append("function schedule(reason){if(stopped)return;readyFalse(reason||'Connection interrupted');cleanup();var delay=Math.min(30000,1800*Math.pow(1.65,Math.min(7,retries++)))+Math.floor(Math.random()*700);state((reason||'Connection interrupted')+' · reconnecting…');retryTimer=setTimeout(start,delay);}");
        j.append("function readyFalse(s){try{AndroidGameBridge.onDisconnected(String(s||''));}catch(e){}}");
        j.append("function arm(ms,label){clearTimer(watch);watch=setTimeout(function(){schedule(label||'Server did not respond');},ms);}");
        j.append("function sendBank(){if(stopped||!pws||pws.readyState!==WebSocket.OPEN)return;clearTimer(posTick);var pos={t:'pos',region:'bank_shop',x:2.5,y:0.41000000000000003,z:-0.5,ry:-1.5707963267948966,mov:false,le:1,outfit:null};try{pws.send(JSON.stringify(pos));}catch(e){schedule('Could not publish Bank Market position');return;}posTick=setTimeout(sendBank,2000);}");
        j.append("async function presence(inherited){if(stopped)return;state('Opening Bank Market presence…');var pt=String(inherited||'');if(!pt)pt=await token('presence');var opened=false,u=wsurl('/ws/presence/s'+current.shard,current.base,pt);pws=new WebSocket(u);arm(18000,'Presence connection timed out');pws.onopen=function(){if(stopped)return;opened=true;clearTimer(watch);retries=0;sendBank();try{AndroidGameBridge.onReady(current.fleet,current.shard,current.name);}catch(e){}};pws.onmessage=function(){};pws.onerror=function(){if(!opened)schedule('Presence handshake failed');};pws.onclose=function(){if(!stopped)schedule(opened?'Presence disconnected':'Presence was rejected');};}");
        j.append("async function queue(admin){if(stopped)return;if(admin){await presence(await token('presence'));return;}state('Joining '+current.name+' in the background…');var qt=await token('queue'),opened=false,settled=false,zeroAt=0;qws=new WebSocket(wsurl('/ws/queue/s'+current.shard,current.base,qt));arm(18000,'Queue connection timed out');qws.onopen=function(){opened=true;arm(30000,'Queue stopped responding');qPing=setInterval(function(){try{if(qws&&qws.readyState===WebSocket.OPEN)qws.send(JSON.stringify({t:'q_ping'}));}catch(e){}},5000);try{qws.send(JSON.stringify({t:'q_ping'}));}catch(e){}};qws.onmessage=function(ev){var m;try{m=JSON.parse(typeof ev.data==='string'?ev.data:String(ev.data));}catch(e){return;}if(!m||typeof m!=='object')return;arm(30000,'Queue stopped responding');if(m.t==='queue_ready'){settled=true;var pt=String(m.connectToken||'');cleanup();presence(pt).catch(function(){schedule('Presence token failed');});return;}if(m.t==='queue_pos'){var ahead=Number(m.ahead||0),pos=Number(m.pos||0);state(ahead>0?('Waiting for '+current.name+' · '+ahead+' ahead'):('Entering '+current.name+'…'));if(ahead===0&&pos<=1){if(!zeroAt)zeroAt=Date.now();if(!zeroTimer)zeroTimer=setTimeout(function(){if(!settled&&zeroAt&&Date.now()-zeroAt>=25000){settled=true;cleanup();presence('').catch(function(){schedule('Presence token failed');});}},25500);}else{zeroAt=0;clearTimer(zeroTimer);zeroTimer=null;}return;}if(m.t==='queue_error'||m.t==='queue_evicted'){settled=true;schedule('Server queue rejected the session');}};qws.onerror=function(){if(!opened&&!settled){settled=true;schedule('Queue handshake failed');}};qws.onclose=function(){if(!stopped&&!settled){settled=true;schedule(opened?'Queue disconnected':'Queue was rejected');}};}");
        j.append("async function start(){if(stopped)return;cleanup();readyFalse('Connecting');state('Finding an available public server…');try{var r=await fetch('/api/servers',{credentials:'include',cache:'no-store'});var x=await r.json().catch(function(){return null;});if(r.status===401||r.status===403)throw new Error('auth_expired');if(!r.ok||!x||x.ok!==true||!Array.isArray(x.servers))throw new Error('server_list_failed');current=choose(x.servers);await queue(x.adminBypass===true);}catch(e){var m=String(e&&e.message||e);if(m==='auth_expired'){state('Kintara session expired · reconnect your wallet');readyFalse('Session expired');return;}schedule(m==='no_public_server'?'No public server is available':'Could not reach a public server');}}");
        j.append("window.__kmPresenceWake=function(){if(stopped)return;if(pws&&pws.readyState===WebSocket.OPEN){sendBank();return;}if(!retryTimer)start();};start();");
        j.append("})();");
        return j.toString();
    }

    private final class Bridge {
        @JavascriptInterface public void onState(final String next) {
            handler.post(new Runnable() { @Override public void run() { setStatus(next); }});
        }

        @JavascriptInterface public void onDisconnected(final String reason) {
            handler.post(new Runnable() { @Override public void run() {
                ready = false;
                if (reason != null && !reason.trim().isEmpty() && !"Connecting".equals(reason)) setStatus(reason);
                else notifyListener();
            }});
        }

        @JavascriptInterface public void onReady(final String nextFleet, final int nextShard, final String nextServerName) {
            handler.post(new Runnable() { @Override public void run() {
                if (nextShard <= 0 || nextFleet == null || nextFleet.trim().isEmpty()) return;
                fleet = nextFleet.trim().toLowerCase(java.util.Locale.US);
                shardId = nextShard;
                serverName = nextServerName == null ? "" : nextServerName.trim();
                ready = true;
                SecurePrefs.saveMarketRoute(activity, fleet, shardId, serverName);
                setStatus("Online at Bank Market in the background");
            }});
        }
    }
}
