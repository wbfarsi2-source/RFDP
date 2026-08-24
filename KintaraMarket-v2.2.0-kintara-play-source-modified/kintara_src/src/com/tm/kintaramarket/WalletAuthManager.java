package com.tm.kintaramarket;

import android.app.Activity;
import android.content.Context;
import android.content.Intent;
import android.net.Uri;
import android.util.Base64;

import com.iwebpp.crypto.TweetNaclFast;

import org.json.JSONArray;
import org.json.JSONObject;

import java.io.BufferedReader;
import java.io.InputStream;
import java.io.InputStreamReader;
import java.io.OutputStream;
import java.net.HttpURLConnection;
import java.net.URL;
import java.nio.charset.StandardCharsets;
import java.security.SecureRandom;
import java.util.ArrayList;
import java.util.List;
import java.util.Locale;
import java.util.Map;

/**
 * Native Solana-wallet authentication for Kintara.
 * Wallet deeplink session is retained securely so future signed marketplace actions
 * can reuse the same wallet connection without ever storing a wallet private key.
 */
public final class WalletAuthManager {
    public static final String PHANTOM="Phantom";
    public static final String SOLFLARE="Solflare";
    private static final String REDIRECT_SCHEME="kintaramarket";
    private static final String REDIRECT_HOST="wallet";
    private static final String APP_URL="https://kintara.com/play";

    private static final String K_PROVIDER="wallet_provider";
    private static final String K_DAPP_PUBLIC="wallet_dapp_public";
    private static final String K_DAPP_SECRET="wallet_dapp_secret";
    private static final String K_SHARED="wallet_shared";
    private static final String K_WALLET_PUBLIC="wallet_public";
    private static final String K_WALLET_SESSION="wallet_session";
    private static final String K_CHALLENGE_ID="auth_challenge_id";
    private static final String K_CHALLENGE_MESSAGE="auth_challenge_message";
    private static final String K_CHALLENGE_COOKIE="auth_challenge_cookie";

    public static final class Challenge {
        public String id,message,cookie;
    }
    public static final class VerifyResult {
        public boolean ok;
        public String error="";
        public JSONObject json=new JSONObject();
    }

    private WalletAuthManager() {}

    public static boolean isWalletRedirect(Uri uri){
        return uri!=null && REDIRECT_SCHEME.equalsIgnoreCase(uri.getScheme()) && REDIRECT_HOST.equalsIgnoreCase(uri.getHost());
    }
    public static String step(Uri uri){
        if(!isWalletRedirect(uri))return "";
        List<String> s=uri.getPathSegments();return s.size()>0?s.get(0):"";
    }
    public static String providerFromRedirect(Uri uri){
        List<String> s=uri==null?new ArrayList<String>():uri.getPathSegments();
        if(s.size()>1)return normalizeProvider(s.get(1));
        return PHANTOM;
    }
    private static String normalizeProvider(String p){return p!=null&&p.toLowerCase(Locale.US).contains("solflare")?SOLFLARE:PHANTOM;}
    private static String providerSlug(String provider){return SOLFLARE.equals(provider)?"solflare":"phantom";}
    private static String encryptionReturnParam(String provider){return SOLFLARE.equals(provider)?"solflare_encryption_public_key":"phantom_encryption_public_key";}
    private static String providerBase(String provider){return SOLFLARE.equals(provider)?"https://solflare.com/ul/v1/":"https://phantom.app/ul/v1/";}
    private static String redirect(String step,String provider){return REDIRECT_SCHEME+"://"+REDIRECT_HOST+"/"+step+"/"+providerSlug(provider);}

    public static void startConnect(Activity a,String provider) throws Exception {
        provider=normalizeProvider(provider);
        // Keep the currently connected profile before replacing the encrypted
        // deeplink session with a new wallet. This is what makes Premium and
        // account switching survive a logout/reconnect cycle.
        WalletAccountStore.saveActive(a);
        SecurePrefs.clearActiveWalletAuth(a);
        TweetNaclFast.Box.KeyPair kp=TweetNaclFast.Box.keyPair();
        SecurePrefs.saveSecureString(a,K_PROVIDER,provider);
        SecurePrefs.saveSecureString(a,K_DAPP_PUBLIC,Base58.encode(kp.getPublicKey()));
        SecurePrefs.saveSecureString(a,K_DAPP_SECRET,Base64.encodeToString(kp.getSecretKey(),Base64.NO_WRAP));
        SecurePrefs.removeSecureStrings(a,K_SHARED,K_WALLET_PUBLIC,K_WALLET_SESSION,K_CHALLENGE_ID,K_CHALLENGE_MESSAGE,K_CHALLENGE_COOKIE);
        Uri uri=Uri.parse(providerBase(provider)+"connect").buildUpon()
                .appendQueryParameter("app_url",APP_URL)
                .appendQueryParameter("dapp_encryption_public_key",Base58.encode(kp.getPublicKey()))
                .appendQueryParameter("redirect_link",redirect("connect",provider))
                .appendQueryParameter("cluster","mainnet-beta").build();
        a.startActivity(new Intent(Intent.ACTION_VIEW,uri));
    }

    public static void acceptConnectReturn(Context c,Uri uri) throws Exception {
        throwIfWalletError(uri);
        String provider=providerFromStored(c,uri);
        String theirs=uri.getQueryParameter(encryptionReturnParam(provider));
        String nonce=uri.getQueryParameter("nonce");
        String data=uri.getQueryParameter("data");
        if(theirs==null||nonce==null||data==null)throw new Exception("Wallet returned incomplete connection data");
        byte[] secret=Base64.decode(required(c,K_DAPP_SECRET),Base64.NO_WRAP);
        TweetNaclFast.Box box=new TweetNaclFast.Box(Base58.decode(theirs),secret);
        byte[] shared=box.before();
        TweetNaclFast.SecretBox sbox=new TweetNaclFast.SecretBox(shared);
        byte[] plain=sbox.open(Base58.decode(data),Base58.decode(nonce));
        if(plain==null)throw new Exception("Could not decrypt wallet connection");
        JSONObject j=new JSONObject(new String(plain,StandardCharsets.UTF_8));
        String pub=j.optString("public_key","");String session=j.optString("session","");
        if(pub.isEmpty()||session.isEmpty())throw new Exception("Wallet connection did not include an account");
        SecurePrefs.saveSecureString(c,K_PROVIDER,provider);
        SecurePrefs.saveSecureString(c,K_SHARED,Base64.encodeToString(shared,Base64.NO_WRAP));
        SecurePrefs.saveSecureString(c,K_WALLET_PUBLIC,pub);
        SecurePrefs.saveSecureString(c,K_WALLET_SESSION,session);
    }

    public static Challenge requestKintaraChallenge(Context c) throws Exception {
        HttpResponse r=http("GET","/api/auth/challenge",null,"");
        if(r.status!=200||!r.json.optBoolean("ok",true))throw new Exception(r.json.optString("error","Could not start Kintara sign-in"));
        Challenge ch=new Challenge();ch.id=r.json.optString("challengeId","");ch.message=r.json.optString("message","");ch.cookie=r.cookies;
        if(ch.id.isEmpty()||ch.message.isEmpty())throw new Exception("Kintara challenge was incomplete");
        SecurePrefs.saveSecureString(c,K_CHALLENGE_ID,ch.id);
        SecurePrefs.saveSecureString(c,K_CHALLENGE_MESSAGE,ch.message);
        SecurePrefs.saveSecureString(c,K_CHALLENGE_COOKIE,ch.cookie==null?"":ch.cookie);
        return ch;
    }

    public static Uri buildSignMessageUri(Context c,Challenge ch) throws Exception {
        String provider=providerFromStored(c,null);
        byte[] shared=Base64.decode(required(c,K_SHARED),Base64.NO_WRAP);
        String session=required(c,K_WALLET_SESSION);
        JSONObject payload=new JSONObject();
        payload.put("message",Base58.encode(ch.message.getBytes(StandardCharsets.UTF_8)));
        payload.put("session",session);
        if(PHANTOM.equals(provider))payload.put("display","utf8");
        byte[] nonce=new byte[TweetNaclFast.SecretBox.nonceLength];new SecureRandom().nextBytes(nonce);
        byte[] cipher=new TweetNaclFast.SecretBox(shared).box(payload.toString().getBytes(StandardCharsets.UTF_8),nonce);
        if(cipher==null)throw new Exception("Could not encrypt wallet sign-in request");
        return Uri.parse(providerBase(provider)+"signMessage").buildUpon()
                .appendQueryParameter("dapp_encryption_public_key",required(c,K_DAPP_PUBLIC))
                .appendQueryParameter("nonce",Base58.encode(nonce))
                .appendQueryParameter("redirect_link",redirect("signin",provider))
                .appendQueryParameter("payload",Base58.encode(cipher)).build();
    }

    /** Builds a wallet deeplink for a serialized Solana transaction. The wallet signs only;
     * the app broadcasts the returned signed transaction through Kintara's session relay. */
    public static Uri buildSignTransactionUri(Context c,String transactionBase58) throws Exception {
        return buildSignTransactionUri(c,transactionBase58,"tx");
    }

    /** Same wallet-sign flow with a caller-selected callback step (for example, Premium USDC). */
    public static Uri buildSignTransactionUri(Context c,String transactionBase58,String callbackStep) throws Exception {
        String provider=providerFromStored(c,null);
        byte[] shared=Base64.decode(required(c,K_SHARED),Base64.NO_WRAP);
        JSONObject payload=new JSONObject();
        payload.put("transaction",transactionBase58);
        payload.put("session",required(c,K_WALLET_SESSION));
        byte[] nonce=new byte[TweetNaclFast.SecretBox.nonceLength];new SecureRandom().nextBytes(nonce);
        byte[] cipher=new TweetNaclFast.SecretBox(shared).box(payload.toString().getBytes(StandardCharsets.UTF_8),nonce);
        if(cipher==null)throw new Exception("Could not encrypt wallet transaction request");
        String step=(callbackStep==null||callbackStep.trim().isEmpty())?"tx":callbackStep.trim();
        return Uri.parse(providerBase(provider)+"signTransaction").buildUpon()
                .appendQueryParameter("dapp_encryption_public_key",required(c,K_DAPP_PUBLIC))
                .appendQueryParameter("nonce",Base58.encode(nonce))
                .appendQueryParameter("redirect_link",redirect(step,provider))
                .appendQueryParameter("payload",Base58.encode(cipher)).build();
    }

    /** Decrypts Phantom/Solflare's signed serialized transaction return. */
    public static String finishSignTransaction(Context c,Uri uri) throws Exception {
        throwIfWalletError(uri);
        String nonce=uri.getQueryParameter("nonce"),data=uri.getQueryParameter("data");
        if(nonce==null||data==null)throw new Exception("Wallet did not return the signed transaction");
        byte[] shared=Base64.decode(required(c,K_SHARED),Base64.NO_WRAP);
        byte[] plain=new TweetNaclFast.SecretBox(shared).open(Base58.decode(data),Base58.decode(nonce));
        if(plain==null)throw new Exception("Could not decrypt signed wallet transaction");
        JSONObject signed=new JSONObject(new String(plain,StandardCharsets.UTF_8));
        String tx=signed.optString("transaction","");
        if(tx.isEmpty())throw new Exception("Wallet returned an incomplete transaction");
        return tx;
    }

    public static VerifyResult finishSignIn(Context c,Uri uri) throws Exception {
        throwIfWalletError(uri);
        String nonce=uri.getQueryParameter("nonce"),data=uri.getQueryParameter("data");
        if(nonce==null||data==null)throw new Exception("Wallet did not return a signature");
        byte[] shared=Base64.decode(required(c,K_SHARED),Base64.NO_WRAP);
        byte[] plain=new TweetNaclFast.SecretBox(shared).open(Base58.decode(data),Base58.decode(nonce));
        if(plain==null)throw new Exception("Could not decrypt wallet signature");
        JSONObject signed=new JSONObject(new String(plain,StandardCharsets.UTF_8));
        String sig58=signed.optString("signature","");if(sig58.isEmpty())throw new Exception("Wallet signature was missing");
        byte[] sig=Base58.decode(sig58);
        JSONArray signature=new JSONArray();for(byte b:sig)signature.put(b&0xFF);
        String publicKey=required(c,K_WALLET_PUBLIC);
        String message=required(c,K_CHALLENGE_MESSAGE);
        String challengeId=required(c,K_CHALLENGE_ID);
        String provider=providerFromStored(c,uri);
        JSONObject body=new JSONObject();body.put("publicKey",publicKey);body.put("signature",signature);body.put("message",message);body.put("challengeId",challengeId);body.put("walletProvider",provider);
        HttpResponse r=http("POST","/api/auth/verify",body,SecurePrefs.getSecureString(c,K_CHALLENGE_COOKIE));
        VerifyResult vr=new VerifyResult();vr.json=r.json;
        if(r.status!=200||!r.json.optBoolean("ok",false)){vr.error=r.json.optString("error",r.status==403?"Kintara account requirements were not met":"Kintara sign-in failed");return vr;}
        String sessionCookie=extractSessionCookie(r.cookies);
        if(sessionCookie.isEmpty())throw new Exception("Kintara did not return a session");
        SecurePrefs.saveCookie(c,sessionCookie);
        SecurePrefs.saveWalletIdentity(c,provider,publicKey);
        SecurePrefs.removeSecureStrings(c,K_CHALLENGE_ID,K_CHALLENGE_MESSAGE,K_CHALLENGE_COOKIE);
        // Verify the newly-created server session before entering the app.
        JSONObject me=KintaraApi.getMe(c);
        JSONObject player=me.optJSONObject("player");
        if(player!=null)SecurePrefs.saveWalletPlayer(c,player.optString("display_name",player.optString("displayName","")),player.optLong("id",player.optLong("playerId",0L)));
        WalletAccountStore.saveActive(c);
        vr.ok=true;return vr;
    }

    public static String walletPublicKey(Context c){return SecurePrefs.getWalletPublicKey(c);}
    public static String walletProvider(Context c){String p=SecurePrefs.getWalletProvider(c);return p.isEmpty()?providerFromStored(c,null):p;}
    public static boolean hasReusableWalletSession(Context c){return !SecurePrefs.getSecureString(c,K_WALLET_SESSION).isEmpty()&&!SecurePrefs.getSecureString(c,K_SHARED).isEmpty()&&!SecurePrefs.getSecureString(c,K_DAPP_SECRET).isEmpty();}

    private static String providerFromStored(Context c,Uri uri){
        if(uri!=null){List<String>s=uri.getPathSegments();if(s.size()>1)return normalizeProvider(s.get(1));}
        String p=SecurePrefs.getSecureString(c,K_PROVIDER);if(p.isEmpty())p=SecurePrefs.getWalletProvider(c);return normalizeProvider(p);
    }
    private static String required(Context c,String k)throws Exception{String v=SecurePrefs.getSecureString(c,k);if(v.isEmpty())throw new Exception("Wallet sign-in state expired. Connect again.");return v;}
    private static void throwIfWalletError(Uri uri)throws Exception{String code=uri.getQueryParameter("errorCode");if(code!=null){String msg=uri.getQueryParameter("errorMessage");throw new Exception(msg==null||msg.isEmpty()?"Wallet request was cancelled":msg);}}

    private static final class HttpResponse{int status;JSONObject json;String raw,cookies;}
    private static HttpResponse http(String method,String path,JSONObject body,String cookie)throws Exception{
        HttpURLConnection con=null;try{
            con=(HttpURLConnection)new URL(KintaraApi.BASE+path).openConnection();con.setConnectTimeout(15000);con.setReadTimeout(18000);con.setRequestMethod(method);con.setRequestProperty("User-Agent",KintaraApi.UA);con.setRequestProperty("Accept","application/json,text/plain,*/*");con.setRequestProperty("Origin",KintaraApi.BASE);con.setRequestProperty("Referer",KintaraApi.BASE+"/play");
            if(cookie!=null&&!cookie.trim().isEmpty())con.setRequestProperty("Cookie",cookie);
            if(body!=null){con.setDoOutput(true);con.setRequestProperty("Content-Type","application/json");byte[] b=body.toString().getBytes(StandardCharsets.UTF_8);try(OutputStream os=con.getOutputStream()){os.write(b);}}
            HttpResponse out=new HttpResponse();out.status=con.getResponseCode();InputStream in=out.status>=400?con.getErrorStream():con.getInputStream();out.raw=read(in);try{out.json=out.raw.trim().isEmpty()?new JSONObject():new JSONObject(out.raw);}catch(Exception e){out.json=new JSONObject();}out.cookies=collectCookies(con);return out;
        }finally{if(con!=null)con.disconnect();}
    }
    private static String read(InputStream in)throws Exception{if(in==null)return"";StringBuilder b=new StringBuilder();try(BufferedReader r=new BufferedReader(new InputStreamReader(in,StandardCharsets.UTF_8))){String line;while((line=r.readLine())!=null)b.append(line).append('\n');}return b.toString();}
    private static String collectCookies(HttpURLConnection con){StringBuilder out=new StringBuilder();Map<String,List<String>> fields=con.getHeaderFields();if(fields==null)return"";for(Map.Entry<String,List<String>> e:fields.entrySet()){if(e.getKey()!=null&&"set-cookie".equalsIgnoreCase(e.getKey())&&e.getValue()!=null){for(String raw:e.getValue()){if(raw==null)continue;String first=raw.split(";",2)[0].trim();if(first.isEmpty())continue;if(out.length()>0)out.append("; ");out.append(first);}}}return out.toString();}
    private static String extractSessionCookie(String cookies){if(cookies==null)return"";for(String c:cookies.split(";\\s*")){String x=c.trim();if(x.startsWith("__Host-kintara_session="))return x;}return"";}
}
