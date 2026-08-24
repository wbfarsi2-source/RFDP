package com.tm.kintaramarket;

import android.content.Context;
import android.content.SharedPreferences;
import android.security.keystore.KeyGenParameterSpec;
import android.security.keystore.KeyProperties;
import android.util.Base64;

import java.nio.charset.StandardCharsets;
import java.security.KeyStore;
import javax.crypto.Cipher;
import javax.crypto.KeyGenerator;
import javax.crypto.SecretKey;
import javax.crypto.spec.GCMParameterSpec;

/** Encrypted app-session and wallet-connection state backed by Android Keystore. */
public final class SecurePrefs {
    private static final String PREFS = "kintara_secure";
    private static final String KEY_ALIAS = "kintara_market_cookie_key"; // kept for seamless upgrades
    private static final String COOKIE = "cookie_enc";
    private static final String IV = "cookie_iv";
    private static final String WALLET_PROVIDER = "wallet_identity_provider";
    private static final String WALLET_PUBLIC = "wallet_identity_public";
    private static final String PLAYER_NAME = "wallet_player_name";
    private static final String PLAYER_ID = "wallet_player_id";
    private static final String MARKET_FLEET = "market_route_fleet";
    private static final String MARKET_SHARD = "market_route_shard";
    private static final String MARKET_SERVER_NAME = "market_route_server_name";
    private static final String MARKET_ROUTE_AT = "market_route_updated_at";

    private SecurePrefs() {}

    private static SecretKey getOrCreateKey() throws Exception {
        KeyStore ks = KeyStore.getInstance("AndroidKeyStore");
        ks.load(null);
        if (ks.containsAlias(KEY_ALIAS)) return ((KeyStore.SecretKeyEntry) ks.getEntry(KEY_ALIAS, null)).getSecretKey();
        KeyGenerator kg = KeyGenerator.getInstance(KeyProperties.KEY_ALGORITHM_AES, "AndroidKeyStore");
        kg.init(new KeyGenParameterSpec.Builder(KEY_ALIAS, KeyProperties.PURPOSE_ENCRYPT | KeyProperties.PURPOSE_DECRYPT)
                .setBlockModes(KeyProperties.BLOCK_MODE_GCM).setEncryptionPaddings(KeyProperties.ENCRYPTION_PADDING_NONE)
                .setRandomizedEncryptionRequired(true).build());
        return kg.generateKey();
    }

    public static synchronized void saveCookie(Context c, String cookie) throws Exception { saveEncryptedPair(c, COOKIE, IV, cookie==null?"":cookie); }
    public static synchronized String getCookie(Context c) { return readEncryptedPair(c, COOKIE, IV); }
    public static synchronized void clearCookie(Context c) { c.getSharedPreferences(PREFS,Context.MODE_PRIVATE).edit().remove(COOKIE).remove(IV).apply(); }

    public static synchronized void saveSecureString(Context c,String key,String value)throws Exception{
        saveEncryptedPair(c,key+"_enc",key+"_iv",value==null?"":value);
    }
    public static synchronized String getSecureString(Context c,String key){return readEncryptedPair(c,key+"_enc",key+"_iv");}
    public static synchronized void removeSecureStrings(Context c,String... keys){SharedPreferences.Editor e=c.getSharedPreferences(PREFS,Context.MODE_PRIVATE).edit();if(keys!=null)for(String k:keys){e.remove(k+"_enc");e.remove(k+"_iv");}e.apply();}

    public static synchronized void saveWalletIdentity(Context c,String provider,String publicKey){c.getSharedPreferences(PREFS,Context.MODE_PRIVATE).edit().putString(WALLET_PROVIDER,provider==null?"":provider).putString(WALLET_PUBLIC,publicKey==null?"":publicKey).apply();}
    public static synchronized String getWalletProvider(Context c){return c.getSharedPreferences(PREFS,Context.MODE_PRIVATE).getString(WALLET_PROVIDER,"");}
    public static synchronized String getWalletPublicKey(Context c){return c.getSharedPreferences(PREFS,Context.MODE_PRIVATE).getString(WALLET_PUBLIC,"");}
    public static synchronized boolean hasWalletIdentity(Context c){return !getWalletPublicKey(c).isEmpty()&&!getWalletProvider(c).isEmpty();}
    public static synchronized void saveWalletPlayer(Context c,String name,long id){c.getSharedPreferences(PREFS,Context.MODE_PRIVATE).edit().putString(PLAYER_NAME,name==null?"":name).putLong(PLAYER_ID,id).apply();}
    public static synchronized String getWalletPlayerName(Context c){return c.getSharedPreferences(PREFS,Context.MODE_PRIVATE).getString(PLAYER_NAME,"");}
    public static synchronized long getWalletPlayerId(Context c){return c.getSharedPreferences(PREFS,Context.MODE_PRIVATE).getLong(PLAYER_ID,0L);}

    /** Last real route confirmed by the authenticated background Presence socket. */
    public static synchronized void saveMarketRoute(Context c,String fleet,int shard,String serverName){
        if(c==null||fleet==null||fleet.trim().isEmpty()||shard<=0)return;
        c.getSharedPreferences(PREFS,Context.MODE_PRIVATE).edit()
                .putString(MARKET_FLEET,fleet.trim().toLowerCase(java.util.Locale.US))
                .putInt(MARKET_SHARD,shard)
                .putString(MARKET_SERVER_NAME,serverName==null?"":serverName.trim())
                .putLong(MARKET_ROUTE_AT,System.currentTimeMillis()).apply();
    }
    public static synchronized String getMarketFleet(Context c){return c.getSharedPreferences(PREFS,Context.MODE_PRIVATE).getString(MARKET_FLEET,"");}
    public static synchronized int getMarketShard(Context c){return c.getSharedPreferences(PREFS,Context.MODE_PRIVATE).getInt(MARKET_SHARD,0);}
    public static synchronized String getMarketServerName(Context c){return c.getSharedPreferences(PREFS,Context.MODE_PRIVATE).getString(MARKET_SERVER_NAME,"");}
    public static synchronized long getMarketRouteUpdatedAt(Context c){return c.getSharedPreferences(PREFS,Context.MODE_PRIVATE).getLong(MARKET_ROUTE_AT,0L);}

    /**
     * Clears only the active wallet session. The encrypted account vault and
     * encrypted Premium entitlement deliberately survive logout so reconnecting
     * the same wallet restores its access without exposing the session in plain
     * storage.
     */
    public static synchronized void clearActiveWalletAuth(Context c){
        SharedPreferences p=c.getSharedPreferences(PREFS,Context.MODE_PRIVATE);
        p.edit().remove(COOKIE).remove(IV)
                .remove(WALLET_PROVIDER).remove(WALLET_PUBLIC)
                .remove(PLAYER_NAME).remove(PLAYER_ID)
                .remove(MARKET_FLEET).remove(MARKET_SHARD)
                .remove(MARKET_SERVER_NAME).remove(MARKET_ROUTE_AT).apply();
        removeSecureStrings(c,
                "wallet_provider", "wallet_dapp_public", "wallet_dapp_secret", "wallet_shared",
                "wallet_public", "wallet_session", "auth_challenge_id", "auth_challenge_message",
                "auth_challenge_cookie");
    }

    /** Backwards-compatible name used by older callers. */
    public static synchronized void clearWalletAuth(Context c){ clearActiveWalletAuth(c); }

    private static void saveEncryptedPair(Context c,String encKey,String ivKey,String value)throws Exception{
        SecretKey key=getOrCreateKey();Cipher cipher=Cipher.getInstance("AES/GCM/NoPadding");cipher.init(Cipher.ENCRYPT_MODE,key);byte[] encrypted=cipher.doFinal(value.getBytes(StandardCharsets.UTF_8));
        boolean saved=c.getSharedPreferences(PREFS,Context.MODE_PRIVATE).edit().putString(encKey,Base64.encodeToString(encrypted,Base64.NO_WRAP)).putString(ivKey,Base64.encodeToString(cipher.getIV(),Base64.NO_WRAP)).commit();
        if(!saved)throw new Exception("Could not securely save transaction recovery state");
    }
    private static String readEncryptedPair(Context c,String encKey,String ivKey){
        try{SharedPreferences p=c.getSharedPreferences(PREFS,Context.MODE_PRIVATE);String enc=p.getString(encKey,"");String iv=p.getString(ivKey,"");if(enc.isEmpty()||iv.isEmpty())return"";Cipher cipher=Cipher.getInstance("AES/GCM/NoPadding");cipher.init(Cipher.DECRYPT_MODE,getOrCreateKey(),new GCMParameterSpec(128,Base64.decode(iv,Base64.NO_WRAP)));return new String(cipher.doFinal(Base64.decode(enc,Base64.NO_WRAP)),StandardCharsets.UTF_8);}catch(Exception e){return"";}
    }
}
