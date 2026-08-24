package com.tm.kintaramarket;

import android.app.Activity;
import android.app.Dialog;
import android.content.Intent;
import android.content.ClipData;
import android.content.ClipboardManager;
import android.content.pm.ActivityInfo;
import android.net.Uri;
import android.graphics.Color;
import android.graphics.Typeface;
import android.graphics.drawable.GradientDrawable;
import android.os.Bundle;
import android.os.Handler;
import android.os.Looper;
import android.text.InputType;
import android.text.InputFilter;
import android.text.Editable;
import android.text.TextWatcher;
import android.util.Base64;
import android.view.Gravity;
import android.view.MotionEvent;
import android.view.View;
import android.view.ViewGroup;
import android.view.Window;
import android.widget.AdapterView;
import android.widget.ArrayAdapter;
import android.widget.Button;
import android.widget.EditText;
import android.widget.FrameLayout;
import android.widget.ImageView;
import android.widget.LinearLayout;
import android.widget.ProgressBar;
import android.widget.ScrollView;
import android.widget.Spinner;
import android.widget.TextView;

import org.json.JSONObject;

import java.text.SimpleDateFormat;
import java.util.ArrayList;
import java.util.Calendar;
import java.util.Collections;
import java.util.Comparator;
import java.util.Date;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Locale;
import java.util.TimeZone;
import java.util.concurrent.Callable;
import java.util.concurrent.ExecutorService;
import java.util.concurrent.Executors;
import java.util.concurrent.Future;

public class MainActivity extends Activity {
    private int BG, CARD, CARD2, BORDER;
    private static final int TEXT = Color.rgb(238,242,247);
    private static final int MUTED = Color.rgb(154,164,178);
    private static final int ACCENT = Color.rgb(72,205,141);
    private static final int BLUE = ACCENT;
    private static final int WARN = Color.rgb(255,184,77);
    private static final int WARN_BG = Color.rgb(48,35,10);
    private static final int PURPLE = Color.rgb(191,111,255);
    private static final int RED = Color.rgb(244,96,96);
    private static final int RED_BG = Color.rgb(49,14,17);

    private final Handler handler = new Handler(Looper.getMainLooper());
    private LinearLayout root, body, navBar;
    private ScrollView mainScroll;
    private Runnable pullRefreshRunnable;
    private float pullStartY;
    private boolean pullArmed, pullTriggered;
    private int listingQtyLimit = KintaraApi.MARKET_STACK_MAX_NONMEMBER;
    private ProgressBar busy;
    private TextView collectorStatus;
    private Runnable foregroundCollector, listingPoll, inventoryPoll, historyHoldTick;
    private boolean listingSyncing, inventorySyncing;
    private final List<KintaraApi.Listing> latestActiveListings = new ArrayList<KintaraApi.Listing>();
    private LinearLayout inventoryList, historyContent;
    private LinearLayout trendScanOut;
    private EditText inventorySearch;
    private final List<KintaraApi.InventoryEntry> latestInventoryEntries = new ArrayList<KintaraApi.InventoryEntry>();
    private String inventoryFingerprint = "";
    private KintaraApi.InventoryEntry currentTradeEntry;
    private EditText currentTradeQtyInput;
    private LinearLayout currentTradeResult;
    private Runnable tradePriceDebounce;
    private boolean tradePriceSyncing;
    private int tradeRequestSerial=0;
    private FrameLayout contentFrame;
    private Button historyActiveTab, historySoldTab, historyBoughtTab;
    private String currentHistoryMode = "sold";
    private boolean soldAlertViewedInHistory = false;
    private final List<KintaraApi.Listing> historyHoldRows = new ArrayList<KintaraApi.Listing>();
    private final List<TextView> historyHoldViews = new ArrayList<TextView>();
    private final List<Button> historyHoldButtons = new ArrayList<Button>();
    private String currentPage = "market";
    private long lastBackPressMs = 0L;
    private final List<String> navHistory = new ArrayList<String>();
    private String detailReturnPage = "market";
    private final List<KintaraApi.MarketItem> marketBoardCache = new ArrayList<KintaraApi.MarketItem>();
    private int marketBoardCurrencyPos = 0;
    private int marketBoardSortPos = 0;
    private int marketBoardCategoryPos = 0;
    private String marketBoardQuery = "";
    private String marketBoardCacheKey = "";
    private int marketBoardRequestSerial = 0;
    private int marketBoardViewSerial = 0;
    private int marketBoardBusySerial = 0;
    private int marketDetailRequestSerial = 0;
    private long lastMarketLoadAt = 0L;
    private String lastMarketLoadKey = "";
    private boolean marketLatestMode = true;
    private int marketFlowPeriod = MarketFlowAnalyzer.PERIOD_24H;
    private TextView walletLoginStatus;
    private boolean walletFlowBusy = false;
    private Runnable marketSearchDebounce;
    private boolean buyFlowBusy = false;
    private boolean tokenWalletHandoff = false;
    private boolean premiumPaymentBusy = false;
    private Dialog paymentProgressDialog;
    private View activeNotice;
    private Runnable hideNoticeRunnable;
    private GameSessionManager gameSession;
    private LinearLayout gameSessionCard;
    private Button gameSessionAction;
    private long silentTapAtMs = 0L;
    private int silentTapCount = 0;
    private static final String PENDING_BUY_QUOTE="pending_buy_quote";
    private static final String PENDING_BUY_SIGNATURE="pending_buy_signature";
    private static final String PENDING_BUY_LISTING="pending_buy_listing";
    private static final String PENDING_BUY_ITEM="pending_buy_item";
    private static final String PENDING_BUY_CURRENCY="pending_buy_currency";
    private static final String PENDING_BUY_QTY="pending_buy_quantity";
    private static final String PENDING_BUY_TS="pending_buy_ts";
    private static final String PENDING_BUY_SIGNED_TX="pending_buy_signed_tx";
    private static final String PENDING_BUY_WALLET="pending_buy_wallet";

    interface Work<T> { T run() throws Exception; }
    interface Done<T> { void done(T value, Exception error); }

    private void applyThemePalette() {
        boolean amoled=UiPrefs.isAmoled(this);
        BG=amoled?Color.BLACK:Color.rgb(13,16,21);
        CARD=amoled?Color.rgb(8,8,8):Color.rgb(24,29,37);
        CARD2=amoled?Color.rgb(16,16,16):Color.rgb(31,37,47);
        BORDER=amoled?Color.rgb(42,42,42):Color.rgb(49,59,72);
    }

    private int drawableId(String name){return getResources().getIdentifier(name,"drawable",getPackageName());}
    private boolean isStack100(String type){String t=KintaraApi.normalizeItemType(type);return "molten_rock".equals(t)||"brute_horn".equals(t)||"fish".equals(t)||t.startsWith("fish_")||t.startsWith("cooked_")||t.startsWith("burnt_");}
    private int itemDrawableId(String type){
        String t=KintaraApi.normalizeItemType(type); String safe=t.replaceAll("[^a-z0-9_]","_");int exact=drawableId("item_"+safe);if(exact!=0)return exact;
        // Public mirror names omit the API prefixes; try the same aliases before generic art.
        String compact=safe.replace("_",""); int compactId=drawableId("item_"+compact); if(compactId!=0)return compactId;
        int pref=drawableId("item_tool_"+safe);if(pref!=0)return pref;pref=drawableId("item_tool_"+compact);if(pref!=0)return pref;
        pref=drawableId("item_mount_"+safe);if(pref!=0)return pref;pref=drawableId("item_mount_"+compact);if(pref!=0)return pref;
        pref=drawableId("item_pet_"+safe);if(pref!=0)return pref;pref=drawableId("item_pet_"+compact);if(pref!=0)return pref;
        pref=drawableId("item_cosmetic_"+safe);if(pref!=0)return pref;pref=drawableId("item_cosmetic_"+compact);if(pref!=0)return pref;
        // The public mirror names keys as goldkey/bronzekey and some tool
        // payloads omit their category prefix. Keep those assets visible too.
        if(t.endsWith("_key")){String k=t.substring(0,t.length()-4);pref=drawableId("item_key_"+k);if(pref!=0)return pref;}
        if(t.endsWith("key")){String k=t.substring(0,t.length()-3);pref=drawableId("item_key_"+k);if(pref!=0)return pref;}
        if("brute_horn".equals(t)) { int x=drawableId("item_brutehorn"); if(x!=0)return x; }
        if("molten_rock".equals(t)) { int x=drawableId("item_moltenrock"); if(x!=0)return x; }
        if(t.startsWith("fish_")){int x=drawableId("item_"+t.substring(5));if(x!=0)return x;}
        if("wild_sword".equals(t))return drawableId("item_tool_sword");
        if("wild_sword_l2".equals(t))return drawableId("item_tool_ironsword");
        if("tool_pickaxe".equals(t))return drawableId("item_tool_pickaxe");
        if("tool_pickaxe_l2".equals(t))return drawableId("item_tool_ironpickaxe");
        if("tool_axe".equals(t))return drawableId("item_tool_axe");
        if("tool_axe_l2".equals(t))return drawableId("item_tool_ironaxe");
        if("copper_pickaxe".equals(t))return drawableId("item_tool_copperpickaxe");
        if("copper_axe".equals(t))return drawableId("item_tool_copperaxe");
        if("copper_sword".equals(t))return drawableId("item_tool_coppersword");
        if("silver_pickaxe".equals(t))return drawableId("item_tool_silverpickaxe");
        if("silver_axe".equals(t))return drawableId("item_tool_silveraxe");
        if("silver_sword".equals(t))return drawableId("item_tool_silversword");
        if("tool_wooden_raft".equals(t))return drawableId("item_tool_wooden_raft");
        if(t.startsWith("key_mansion_"))return drawableId("item_key_gold");
        if(t.startsWith("key_house_")||t.startsWith("key_flat_"))return drawableId("item_key_silver");
        if(t.startsWith("key_trailer_"))return drawableId("item_key_bronze");
        if("pet_uwu_unicorn".equals(t))return drawableId("item_uwu_unicorn");
        if("furniture_worldcup".equals(t))return drawableId("item_worldcup");
        return drawableId("item_generic");
    }
    private ImageView itemImage(String type,int size){ImageView v=new ImageView(this);v.setImageResource(itemDrawableId(type));v.setScaleType(ImageView.ScaleType.CENTER_INSIDE);v.setAdjustViewBounds(false);v.setBackground(outlineBg(Color.rgb(17,24,32),14,Color.rgb(46,61,75)));v.setPadding(dp(7),dp(7),dp(7),dp(7));v.setContentDescription(type==null?"Item":KintaraApi.humanizeType(type));v.setLayoutParams(new LinearLayout.LayoutParams(dp(size),dp(size)));return v;}
    private int defaultQtyForItem(KintaraApi.Item it){if(it==null)return 1;String t=KintaraApi.normalizeItemType(it.type); if("gold".equals(t))return 1;return isStack100(t)?100:1;}

    @Override public void onCreate(Bundle b) {
        super.onCreate(b);
        applyThemePalette();
        Window w=getWindow();
        w.setStatusBarColor(BG);
        w.setNavigationBarColor(BG);
        // v1.4 migrates away from manually pasted cookies. A legacy cookie without
        // wallet identity is intentionally discarded so the user authenticates once by wallet.
        if(!SecurePrefs.hasWalletIdentity(this) && !SecurePrefs.getCookie(this).isEmpty()) SecurePrefs.clearCookie(this);
        showLogin();
        Uri incoming=getIntent()==null?null:getIntent().getData();
        if(WalletAuthManager.isWalletRedirect(incoming)) handleWalletRedirect(incoming);
        else if(SecurePrefs.hasWalletIdentity(this) && !SecurePrefs.getCookie(this).isEmpty()) restoreSecureSession();
    }

    @Override protected void onNewIntent(Intent intent){
        super.onNewIntent(intent);setIntent(intent);Uri uri=intent==null?null:intent.getData();if(WalletAuthManager.isWalletRedirect(uri))handleWalletRedirect(uri);
    }

    @Override protected void onResume() { super.onResume(); setRequestedOrientation(ActivityInfo.SCREEN_ORIENTATION_UNSPECIFIED); startForegroundCollector(); startListingPoll(); if("inventory".equals(currentPage)) startInventoryLive(false); ensureBackgroundGameSession(); if(gameSession!=null)gameSession.onHostResume(); handler.postDelayed(new Runnable(){public void run(){autoRecoverPendingPremiumPayment();}},650L); handler.postDelayed(new Runnable(){public void run(){cancelUnreturnedTokenWalletHandoff();}},900L); }
    @Override protected void onPause() { super.onPause(); stopForegroundCollector(); stopListingPoll(); stopInventoryLive(); stopHistoryHoldTick(); if(tradePriceDebounce!=null)handler.removeCallbacks(tradePriceDebounce); }
    @Override protected void onDestroy(){
        if(hideNoticeRunnable!=null)handler.removeCallbacks(hideNoticeRunnable);
        hideNoticeRunnable=null;activeNotice=null;
        if(gameSession!=null){gameSession.destroy();gameSession=null;}
        super.onDestroy();
    }

    @Override public void onBackPressed() {
        if(gameSession!=null&&gameSession.isExpanded()){gameSession.minimize();return;}
        if ("inventory_trade".equals(currentPage)) { showInventory(); return; }
        if ("market_detail".equals(currentPage)) { navigateTop(detailReturnPage,false); return; }
        if (!navHistory.isEmpty()) {
            String previous=navHistory.remove(navHistory.size()-1);
            navigateTop(previous,false);
            return;
        }
        long now=System.currentTimeMillis();
        if (now-lastBackPressMs <= 2000L) { super.onBackPressed(); return; }
        lastBackPressMs=now;
        toast("Press Back again to exit");
    }

    private String topPage(String page){
        if(page==null)return "market";
        if("market_detail".equals(page))return detailReturnPage==null?"market":detailReturnPage;
        if(page.startsWith("inventory"))return "inventory";
        if(page.startsWith("trends"))return "trends";
        if(page.startsWith("history"))return "history";
        if(page.startsWith("settings"))return "settings";
        return "market";
    }
    private void rememberTopPage(String target){
        String from=topPage(currentPage),to=topPage(target);
        if(from.equals(to))return;
        if(navHistory.isEmpty()||!from.equals(navHistory.get(navHistory.size()-1)))navHistory.add(from);
        if(navHistory.size()>12)navHistory.remove(0);
        lastBackPressMs=0L;
    }
    private void navigateTop(String page,boolean remember){
        String target=topPage(page);
        String from=topPage(currentPage);
        // Do not rebuild an already-visible tab. Rebuilding here used to fire a
        // second automatic market request when the user tapped the same bottom
        // tab again; the pull gesture remains the explicit refresh action.
        if(target.equals(currentPage)){
            refreshBottomNav();
            return;
        }
        if("history".equals(from)&&!"history".equals(target)&&soldAlertViewedInHistory&&SaleHistoryStore.hasUnreadSold(this)){
            SaleHistoryStore.clearUnreadSold(this);
            soldAlertViewedInHistory=false;
        }
        if(remember)rememberTopPage(target);
        if("inventory".equals(target))showInventory();
        else if("trends".equals(target))showTrends();
        else if("history".equals(target))showHistory();
        else if("settings".equals(target))showSettings();
        else showMarket();
    }

    private int dp(int n){return (int)(n*getResources().getDisplayMetrics().density+.5f);}
    private GradientDrawable bg(int color,int radius){GradientDrawable g=new GradientDrawable();g.setColor(color);g.setCornerRadius(dp(radius));return g;}
    private GradientDrawable outlineBg(int color,int radius,int stroke){GradientDrawable g=bg(color,radius);g.setStroke(dp(1),stroke);return g;}
    private TextView txt(String s,int sp,int color,boolean bold){TextView t=new TextView(this);t.setText(s);t.setTextSize(sp);t.setTextColor(color);t.setTypeface(Typeface.DEFAULT,bold?Typeface.BOLD:Typeface.NORMAL);t.setLineSpacing(0,1.12f);return t;}
    private LinearLayout.LayoutParams lp(int w,int h,int l,int t,int r,int b){LinearLayout.LayoutParams p=new LinearLayout.LayoutParams(w,h);p.setMargins(dp(l),dp(t),dp(r),dp(b));return p;}
    private Button button(String s,int color){Button b=new Button(this);b.setText(s);b.setTextColor(Color.WHITE);b.setTextSize(13);b.setAllCaps(false);b.setTypeface(Typeface.DEFAULT,Typeface.BOLD);b.setBackground(bg(color,12));b.setPadding(dp(12),0,dp(12),0);return b;}
    private Button outlineButton(String s,int color){Button b=button(s,CARD2);b.setTextColor(color);b.setBackground(outlineBg(CARD2,12,color));return b;}
    private Button miniButton(String s){Button b=outlineButton(s,ACCENT);b.setTextSize(11);b.setPadding(dp(6),0,dp(6),0);return b;}
    private LinearLayout card(){LinearLayout c=new LinearLayout(this);c.setOrientation(LinearLayout.VERTICAL);c.setPadding(dp(16),dp(14),dp(16),dp(14));c.setBackground(bg(CARD,16));c.setLayoutParams(lp(ViewGroup.LayoutParams.MATCH_PARENT,ViewGroup.LayoutParams.WRAP_CONTENT,12,8,12,8));return c;}
    private EditText input(String hint){EditText e=new EditText(this);e.setHint(hint);e.setHintTextColor(Color.rgb(103,113,128));e.setTextColor(TEXT);e.setTextSize(15);e.setSingleLine(true);e.setPadding(dp(14),dp(10),dp(14),dp(10));e.setBackground(bg(CARD2,12));return e;}
    private int noticeKind(String message){
        String m=message==null?"":message.toLowerCase(Locale.US);
        if(m.contains("cancel")||m.contains("could not")||m.contains("failed")||m.contains("invalid")||m.contains("error")||m.contains("expired")||m.contains("not enough")||m.contains("do not have")||m.contains("unavailable")||m.contains("denied"))return NoticeIconView.ERROR;
        if(m.contains("pending")||m.contains("waiting")||m.contains("try again")||m.contains("reconnect")||m.contains("hold")||m.contains("locked")||m.contains("limit")||m.contains("must be")||m.contains("checkout"))return NoticeIconView.WARNING;
        if(m.contains("listed")||m.contains("sold")||m.contains("complete")||m.contains("copied")||m.contains("connected")||m.contains("activated")||m.contains("saved")||m.contains("ready")||m.contains("success"))return NoticeIconView.SUCCESS;
        return NoticeIconView.INFO;
    }

    private int noticeColor(int kind){
        if(kind==NoticeIconView.ERROR)return RED;
        if(kind==NoticeIconView.WARNING)return WARN;
        if(kind==NoticeIconView.SUCCESS)return ACCENT;
        return Color.rgb(87,183,255);
    }

    /** Replaces Android's system toast so every message has branded art and motion. */
    private void toast(final String raw){
        if(Looper.myLooper()!=Looper.getMainLooper()){
            handler.post(new Runnable(){public void run(){toast(raw);}});return;
        }
        final String message=raw==null?"":raw.trim();
        if(message.isEmpty())return;
        final FrameLayout host=(FrameLayout)findViewById(android.R.id.content);
        if(host==null)return;
        if(hideNoticeRunnable!=null)handler.removeCallbacks(hideNoticeRunnable);
        if(activeNotice!=null&&activeNotice.getParent() instanceof ViewGroup)((ViewGroup)activeNotice.getParent()).removeView(activeNotice);

        final int kind=noticeKind(message),accent=noticeColor(kind);
        final LinearLayout notice=new LinearLayout(this);
        notice.setOrientation(LinearLayout.HORIZONTAL);
        notice.setGravity(Gravity.CENTER_VERTICAL);
        notice.setPadding(dp(12),dp(10),dp(14),dp(10));
        int panel=UiPrefs.isAmoled(this)?Color.rgb(12,14,17):Color.rgb(28,34,43);
        GradientDrawable surface=new GradientDrawable(GradientDrawable.Orientation.TL_BR,new int[]{panel,Color.rgb(20,25,33)});
        surface.setCornerRadius(dp(18));surface.setStroke(dp(1),Color.argb(190,Color.red(accent),Color.green(accent),Color.blue(accent)));
        notice.setBackground(surface);notice.setElevation(dp(18));

        NoticeIconView icon=new NoticeIconView(this,kind,accent);
        notice.addView(icon,new LinearLayout.LayoutParams(dp(48),dp(48)));
        TextView messageView=txt(message,12,TEXT,true);
        messageView.setMaxLines(3);messageView.setGravity(Gravity.CENTER_VERTICAL);
        notice.addView(messageView,lp(0,ViewGroup.LayoutParams.WRAP_CONTENT,11,0,0,0));
        LinearLayout.LayoutParams messageParams=(LinearLayout.LayoutParams)messageView.getLayoutParams();messageParams.weight=1f;messageView.setLayoutParams(messageParams);

        FrameLayout.LayoutParams params=new FrameLayout.LayoutParams(ViewGroup.LayoutParams.MATCH_PARENT,ViewGroup.LayoutParams.WRAP_CONTENT,Gravity.BOTTOM);
        params.setMargins(dp(22),0,dp(22),dp(88));
        host.addView(notice,params);activeNotice=notice;
        notice.setContentDescription(message);notice.setAlpha(0f);notice.setTranslationY(dp(24));notice.setScaleX(.96f);notice.setScaleY(.96f);
        notice.animate().alpha(1f).translationY(0f).scaleX(1f).scaleY(1f).setDuration(280L).start();
        notice.announceForAccessibility(message);

        hideNoticeRunnable=new Runnable(){public void run(){
            if(activeNotice!=notice)return;
            notice.animate().alpha(0f).translationY(dp(18)).scaleX(.98f).scaleY(.98f).setDuration(220L).withEndAction(new Runnable(){public void run(){
                if(notice.getParent() instanceof ViewGroup)((ViewGroup)notice.getParent()).removeView(notice);
                if(activeNotice==notice)activeNotice=null;
            }}).start();
        }};
        handler.postDelayed(hideNoticeRunnable,3200L);
    }

    private void showPaymentProgress(String title,String message){
        hidePaymentProgress();
        final Dialog d=new Dialog(this);d.requestWindowFeature(Window.FEATURE_NO_TITLE);d.setCancelable(false);
        LinearLayout c=new LinearLayout(this);c.setOrientation(LinearLayout.VERTICAL);c.setGravity(Gravity.CENTER_HORIZONTAL);c.setPadding(dp(24),dp(22),dp(24),dp(20));c.setBackground(outlineBg(CARD,18,BORDER));
        SecurePulseView secure=new SecurePulseView(this);c.addView(secure,new LinearLayout.LayoutParams(dp(104),dp(104)));
        String cleanTitle=title==null||title.trim().isEmpty()?"SECURING YOUR PURCHASE":title.trim().toUpperCase(Locale.US);
        TextView t=txt(cleanTitle,16,TEXT,true);t.setGravity(Gravity.CENTER);c.addView(t,lp(ViewGroup.LayoutParams.MATCH_PARENT,ViewGroup.LayoutParams.WRAP_CONTENT,0,12,0,0));
        d.setContentView(c);d.show();Window w=d.getWindow();if(w!=null){w.setBackgroundDrawable(new android.graphics.drawable.ColorDrawable(Color.TRANSPARENT));w.setDimAmount(.72f);w.addFlags(android.view.WindowManager.LayoutParams.FLAG_DIM_BEHIND);w.setLayout((int)(getResources().getDisplayMetrics().widthPixels*.88f),ViewGroup.LayoutParams.WRAP_CONTENT);}paymentProgressDialog=d;
    }

    private void hidePaymentProgress(){if(paymentProgressDialog!=null){try{paymentProgressDialog.dismiss();}catch(Exception ignored){}paymentProgressDialog=null;}}

    private void showGraphicMessage(String icon,String title,String message,int color){
        hidePaymentProgress();
        final Dialog d=new Dialog(this);d.requestWindowFeature(Window.FEATURE_NO_TITLE);d.setCancelable(true);
        LinearLayout c=new LinearLayout(this);c.setOrientation(LinearLayout.VERTICAL);c.setGravity(Gravity.CENTER_HORIZONTAL);c.setPadding(dp(24),dp(22),dp(24),dp(18));c.setBackground(outlineBg(CARD,18,color));
        TextView i=txt(icon,34,color,true);i.setGravity(Gravity.CENTER);i.setBackground(outlineBg(CARD2,40,color));c.addView(i,new LinearLayout.LayoutParams(dp(66),dp(66)));
        TextView t=txt(title,18,TEXT,true);t.setGravity(Gravity.CENTER);c.addView(t,lp(ViewGroup.LayoutParams.MATCH_PARENT,ViewGroup.LayoutParams.WRAP_CONTENT,0,13,0,0));
        TextView m=txt(message,12,MUTED,false);m.setGravity(Gravity.CENTER);c.addView(m,lp(ViewGroup.LayoutParams.MATCH_PARENT,ViewGroup.LayoutParams.WRAP_CONTENT,0,7,0,14));
        Button ok=button("OK",color);c.addView(ok,new LinearLayout.LayoutParams(ViewGroup.LayoutParams.MATCH_PARENT,dp(46)));ok.setOnClickListener(new View.OnClickListener(){public void onClick(View v){d.dismiss();}});
        d.setContentView(c);d.show();Window w=d.getWindow();if(w!=null){w.setBackgroundDrawable(new android.graphics.drawable.ColorDrawable(Color.TRANSPARENT));w.setDimAmount(.72f);w.addFlags(android.view.WindowManager.LayoutParams.FLAG_DIM_BEHIND);w.setLayout((int)(getResources().getDisplayMetrics().widthPixels*.88f),ViewGroup.LayoutParams.WRAP_CONTENT);}
    }

    private <T> void async(final String label, final Work<T> work, final Done<T> done) {
        setBusy(true,label);
        new Thread(new Runnable(){@Override public void run(){T v=null;Exception err=null;try{v=work.run();}catch(Exception e){err=e;}final T fv=v;final Exception fe=err;handler.post(new Runnable(){@Override public void run(){setBusy(false,"");done.done(fv,fe);}});}},"KintaraUI").start();
    }

    private void setBusy(boolean on,String label){if(busy!=null)busy.setVisibility(on?View.VISIBLE:View.GONE);if(collectorStatus!=null&&on)collectorStatus.setText(label);else updateCollectorStatus();}

    private static final class DarkSpinnerAdapter<T> extends ArrayAdapter<T> {
        private final MainActivity a;
        DarkSpinnerAdapter(MainActivity a,List<T> data){super(a,android.R.layout.simple_spinner_item,data);this.a=a;}
        private View row(int position,boolean dropdown){
            T raw=getItem(position);
            if(raw instanceof KintaraApi.Item){
                KintaraApi.Item it=(KintaraApi.Item)raw;
                LinearLayout line=new LinearLayout(a);line.setGravity(Gravity.CENTER_VERTICAL);line.setPadding(a.dp(10),a.dp(6),a.dp(12),a.dp(6));line.setBackground(a.bg(dropdown?a.CARD:a.CARD2,10));
                ImageView icon=a.itemImage(it.type,40);line.addView(icon,a.lp(a.dp(40),a.dp(40),0,0,10,0));
                LinearLayout text=new LinearLayout(a);text.setOrientation(LinearLayout.VERTICAL);text.addView(a.txt(it.label,dropdown?14:15,TEXT,true));text.addView(a.txt(it.group,10,MUTED,false));line.addView(text,new LinearLayout.LayoutParams(0,ViewGroup.LayoutParams.WRAP_CONTENT,1));
                return line;
            }
            TextView v=new TextView(a);v.setText(String.valueOf(raw));v.setTextColor(TEXT);v.setTextSize(dropdown?14:12);v.setGravity(Gravity.CENTER_VERTICAL);v.setPadding(a.dp(dropdown?14:10),a.dp(10),a.dp(dropdown?14:8),a.dp(10));v.setSingleLine(true);v.setHorizontallyScrolling(false);v.setBackground(a.bg(dropdown?a.CARD:a.CARD2,10));return v;
        }
        @Override public View getView(int position,View convertView,ViewGroup parent){return row(position,false);}
        @Override public View getDropDownView(int position,View convertView,ViewGroup parent){return row(position,true);}
    }

    private void showLogin() {
        stopForegroundCollector();stopListingPoll();stopInventoryLive();stopHistoryHoldTick();
        walletFlowBusy=false;root=null;body=null;navBar=null;
        FrameLayout frame=new FrameLayout(this);frame.setBackgroundColor(BG);
        ScrollView scroll=new ScrollView(this);scroll.setFillViewport(true);frame.addView(scroll,new FrameLayout.LayoutParams(ViewGroup.LayoutParams.MATCH_PARENT,ViewGroup.LayoutParams.MATCH_PARENT));
        LinearLayout c=new LinearLayout(this);c.setOrientation(LinearLayout.VERTICAL);c.setGravity(Gravity.CENTER_HORIZONTAL);c.setPadding(dp(24),dp(34),dp(24),dp(32));scroll.addView(c,new ScrollView.LayoutParams(ViewGroup.LayoutParams.MATCH_PARENT,ViewGroup.LayoutParams.WRAP_CONTENT));

        FrameLayout hero=new FrameLayout(this);c.addView(hero,new LinearLayout.LayoutParams(dp(210),dp(210)));
        WalletPulseView pulse=new WalletPulseView(this);hero.addView(pulse,new FrameLayout.LayoutParams(ViewGroup.LayoutParams.MATCH_PARENT,ViewGroup.LayoutParams.MATCH_PARENT));
        ImageView logo=new ImageView(this);logo.setImageResource(drawableId("app_icon_v172"));logo.setScaleType(ImageView.ScaleType.CENTER_INSIDE);logo.setElevation(dp(8));FrameLayout.LayoutParams lpLogo=new FrameLayout.LayoutParams(dp(96),dp(96),Gravity.CENTER);hero.addView(logo,lpLogo);
        TextView title=txt("KINTARA MARKET",26,TEXT,true);title.setGravity(Gravity.CENTER);c.addView(title);
        TextView sub=txt("Your market, inventory and trends in one place",13,MUTED,false);sub.setGravity(Gravity.CENTER);c.addView(sub,lp(ViewGroup.LayoutParams.MATCH_PARENT,ViewGroup.LayoutParams.WRAP_CONTENT,0,7,0,22));

        LinearLayout box=card();box.setLayoutParams(lp(ViewGroup.LayoutParams.MATCH_PARENT,ViewGroup.LayoutParams.WRAP_CONTENT,0,0,0,0));c.addView(box);
        box.addView(txt("CONNECT",16,TEXT,true));
        box.addView(txt("Choose your wallet to continue.",12,MUTED,false),lp(ViewGroup.LayoutParams.MATCH_PARENT,ViewGroup.LayoutParams.WRAP_CONTENT,0,6,0,14));

        Button phantom=button("CONNECT PHANTOM",ACCENT);box.addView(phantom,lp(ViewGroup.LayoutParams.MATCH_PARENT,dp(52),0,0,0,0));
        Button solflare=outlineButton("CONNECT SOLFLARE",ACCENT);box.addView(solflare,lp(ViewGroup.LayoutParams.MATCH_PARENT,dp(50),0,9,0,0));
        walletLoginStatus=txt("Your approval is always required for purchases.",11,MUTED,false);walletLoginStatus.setGravity(Gravity.CENTER);box.addView(walletLoginStatus,lp(ViewGroup.LayoutParams.MATCH_PARENT,ViewGroup.LayoutParams.WRAP_CONTENT,0,12,0,0));
        phantom.setOnClickListener(new View.OnClickListener(){public void onClick(View v){startWalletLogin(WalletAuthManager.PHANTOM);}});
        solflare.setOnClickListener(new View.OnClickListener(){public void onClick(View v){startWalletLogin(WalletAuthManager.SOLFLARE);}});

        List<WalletAccountStore.AccountSummary> savedAccounts=WalletAccountStore.summaries(this);
        if(!savedAccounts.isEmpty()){
            LinearLayout saved=card(); saved.setBackground(outlineBg(CARD,16,PURPLE)); saved.addView(txt("SAVED ACCOUNTS",12,PURPLE,true)); saved.addView(txt("Encrypted on this device • switch without mixing inventory or trends.",10,MUTED,false),lp(ViewGroup.LayoutParams.MATCH_PARENT,ViewGroup.LayoutParams.WRAP_CONTENT,0,4,0,8));
            for(final WalletAccountStore.AccountSummary a:savedAccounts){Button sw=outlineButton((a.playerName==null||a.playerName.isEmpty()?shortWallet(a.publicKey):a.playerName)+"  •  "+shortWallet(a.publicKey),ACCENT);saved.addView(sw,lp(ViewGroup.LayoutParams.MATCH_PARENT,dp(44),0,5,0,0));sw.setOnClickListener(new View.OnClickListener(){public void onClick(View v){if(walletFlowBusy)return;walletFlowBusy=true;if(WalletAccountStore.activate(getApplicationContext(),a.publicKey)){restoreSecureSession();}else{walletFlowBusy=false;setWalletLoginStatus("Saved account could not be restored.",RED);}}});}
            c.addView(saved,lp(ViewGroup.LayoutParams.MATCH_PARENT,ViewGroup.LayoutParams.WRAP_CONTENT,0,12,0,0));
        }

        LinearLayout secure=card();secure.addView(txt("SECURE BY DESIGN",12,ACCENT,true));secure.addView(txt("Your wallet stays in your control. The app never asks for your recovery phrase or private key.",11,MUTED,false),lp(ViewGroup.LayoutParams.MATCH_PARENT,ViewGroup.LayoutParams.WRAP_CONTENT,0,6,0,0));c.addView(secure);
        setContentView(frame);
    }

    private void setWalletLoginStatus(final String text,final int color){handler.post(new Runnable(){public void run(){if(walletLoginStatus!=null){walletLoginStatus.setText(text);walletLoginStatus.setTextColor(color);}}});}

    private void startWalletLogin(String provider){
        if(walletFlowBusy)return;walletFlowBusy=true;setWalletLoginStatus("Opening "+provider+"…",ACCENT);
        try{WalletAuthManager.startConnect(this,provider);}catch(Exception e){walletFlowBusy=false;setWalletLoginStatus("Could not open "+provider+". Please try again.",RED);}
    }

    private void handleWalletRedirect(final Uri uri){
        if(uri==null)return;String step=WalletAuthManager.step(uri);
        if("premiumtx".equals(step)){handlePremiumTransactionReturn(uri);return;}
        if("tx".equals(step)){handleTokenTransactionReturn(uri);return;}
        walletFlowBusy=true;
        if("connect".equals(step)){
            setWalletLoginStatus("Wallet connected • preparing Kintara sign-in…",ACCENT);
            new Thread(new Runnable(){public void run(){try{
                WalletAuthManager.acceptConnectReturn(getApplicationContext(),uri);
                final WalletAuthManager.Challenge ch=WalletAuthManager.requestKintaraChallenge(getApplicationContext());
                final Uri sign=WalletAuthManager.buildSignMessageUri(getApplicationContext(),ch);
                handler.post(new Runnable(){public void run(){try{setWalletLoginStatus("Approve the Kintara sign-in message in your wallet…",ACCENT);startActivity(new Intent(Intent.ACTION_VIEW,sign));}catch(Exception e){walletFlowBusy=false;setWalletLoginStatus("Could not open wallet for signing",RED);}}});
            }catch(final Exception e){handler.post(new Runnable(){public void run(){walletFlowBusy=false;setWalletLoginStatus("Connection failed • "+safeMessage(e),RED);}});}}},"WalletConnectReturn").start();
            return;
        }
        if("signin".equals(step)){
            setWalletLoginStatus("Completing connection…",ACCENT);
            new Thread(new Runnable(){public void run(){try{
                final WalletAuthManager.VerifyResult r=WalletAuthManager.finishSignIn(getApplicationContext(),uri);
                if(r.ok)PremiumManager.autoLinkCurrentAccount(getApplicationContext());
                handler.post(new Runnable(){public void run(){walletFlowBusy=false;if(r.ok){setWalletLoginStatus("Connected • opening market…",ACCENT);enterApp();}else setWalletLoginStatus(userMessage(r.error,"Could not connect. Please try again."),RED);}});
            }catch(final Exception e){handler.post(new Runnable(){public void run(){walletFlowBusy=false;setWalletLoginStatus("Sign-in failed • "+safeMessage(e),RED);}});}}},"WalletSignInReturn").start();
        }
    }

    private boolean isPremium(){return PremiumManager.hasPremium(this);}
    private boolean premiumPendingBelongsToCurrentWallet(){
        PremiumManager.Quote q=PremiumManager.pending(this);
        String current=WalletAuthManager.walletPublicKey(this);
        return q!=null&&!q.wallet.isEmpty()&&!current.isEmpty()&&q.wallet.equals(current)&&q.amountRaw>0;
    }

    private void showPremiumPaywall(String reason){
        final boolean active=isPremium(); final boolean admin=PremiumManager.premiumUntil(this)==Long.MAX_VALUE;
        final String wallet=WalletAuthManager.walletPublicKey(this); final boolean hasPending=!PremiumManager.pendingSignature(this).isEmpty()&&premiumPendingBelongsToCurrentWallet();
        final Dialog d=new Dialog(this); d.requestWindowFeature(Window.FEATURE_NO_TITLE); d.setCancelable(true); d.setCanceledOnTouchOutside(true);
        ScrollView scroll=new ScrollView(this); scroll.setFillViewport(true);
        LinearLayout shell=new LinearLayout(this); shell.setOrientation(LinearLayout.VERTICAL); shell.setPadding(dp(14),dp(14),dp(14),dp(14)); shell.setBackground(outlineBg(CARD,26,PURPLE)); scroll.addView(shell);
        LinearLayout hero=new LinearLayout(this); hero.setOrientation(LinearLayout.VERTICAL); hero.setPadding(dp(18),dp(17),dp(18),dp(17));
        GradientDrawable hg=new GradientDrawable(GradientDrawable.Orientation.TL_BR,new int[]{Color.rgb(42,20,68),Color.rgb(11,31,42),Color.rgb(9,45,36)}); hg.setCornerRadius(dp(21)); hg.setStroke(dp(1),PURPLE); hero.setBackground(hg);
        LinearLayout brand=new LinearLayout(this); brand.setGravity(Gravity.CENTER_VERTICAL); ImageView icon=new ImageView(this); icon.setImageResource(drawableId("app_icon_v172")); brand.addView(icon,lp(dp(58),dp(58),0,0,12,0));
        LinearLayout names=new LinearLayout(this); names.setOrientation(LinearLayout.VERTICAL); names.addView(txt("KINTARA PREMIUM",19,TEXT,true)); names.addView(txt("TRENDS + BUY NOW ACCESS",10,PURPLE,true)); brand.addView(names,new LinearLayout.LayoutParams(0,ViewGroup.LayoutParams.WRAP_CONTENT,1));
        TextView badge=txt(admin?"ADMIN":(active?"ACTIVE":"PREMIUM"),9,admin?PURPLE:(active?ACCENT:WARN),true); badge.setGravity(Gravity.CENTER); badge.setBackground(outlineBg(CARD2,10,admin?PURPLE:(active?ACCENT:WARN))); brand.addView(badge,lp(dp(76),dp(30),8,0,0,0)); hero.addView(brand);
        hero.addView(txt(reason==null||reason.trim().isEmpty()?"Unlock full Market Trends and protected marketplace actions.":reason.trim(),12,TEXT,false),lp(ViewGroup.LayoutParams.MATCH_PARENT,ViewGroup.LayoutParams.WRAP_CONTENT,0,13,0,0)); shell.addView(hero);
        TextView included=txt("PREMIUM FEATURES",10,MUTED,true); shell.addView(included,lp(ViewGroup.LayoutParams.MATCH_PARENT,ViewGroup.LayoutParams.WRAP_CONTENT,4,16,4,7));
        LinearLayout features=new LinearLayout(this); features.setOrientation(LinearLayout.VERTICAL); features.setPadding(dp(12),dp(10),dp(12),dp(10)); features.setBackground(outlineBg(CARD2,16,BORDER));
        features.addView(premiumFeature("Seller flow dashboard","Buyer spend, sold volume and seller profit for 1h / 12h / 24h / 30d.")); features.addView(premiumFeature("Live charts and opportunity ranking","Warm cache plus silent background refresh.")); features.addView(premiumFeature("Buy Now protection","Premium verification starts at the final purchase step.")); shell.addView(features);
        LinearLayout facts=new LinearLayout(this); facts.setOrientation(LinearLayout.HORIZONTAL); facts.addView(premiumFact("WEEKLY","3.99 USDC",PURPLE),weighted(0,dp(70),0,10,4,0,1)); facts.addView(premiumFact("MONTHLY","9.99 USDC",ACCENT),weighted(0,dp(70),4,10,0,0,1)); shell.addView(facts);
        LinearLayout account=new LinearLayout(this); account.setOrientation(LinearLayout.VERTICAL); account.setPadding(dp(12),dp(10),dp(12),dp(10)); account.setBackground(outlineBg(CARD2,15,BORDER));
        account.addView(premiumDetailRow("NETWORK","Solana",ACCENT)); account.addView(premiumDetailRow("WALLET",wallet==null||wallet.isEmpty()?"Not connected":shortWallet(wallet),TEXT)); account.addView(premiumDetailRow("STATUS",PremiumManager.statusLabel(this),active?ACCENT:MUTED));
        account.addView(premiumDetailRow("CONNECTED ACCOUNTS",PremiumManager.linkedAccountCount(this)+" / "+PremiumManager.accountLimit(this),PURPLE)); if(hasPending)account.addView(premiumDetailRow("PAYMENT","Waiting for confirmation",WARN)); shell.addView(account);
        shell.addView(txt("Two accounts are included after activation. Each additional account is 5.00 USDC; admin mode supports up to five.",9,MUTED,false),lp(ViewGroup.LayoutParams.MATCH_PARENT,ViewGroup.LayoutParams.WRAP_CONTENT,4,9,4,0));
        if(hasPending){Button check=outlineButton("CHECK PENDING PAYMENT",WARN); shell.addView(check,lp(ViewGroup.LayoutParams.MATCH_PARENT,dp(46),0,13,0,0)); check.setOnClickListener(new View.OnClickListener(){public void onClick(View v){d.dismiss();checkPendingPremiumPayment();}});}
        if(!admin){Button weekly=button("UNLOCK WEEKLY • 3.99 USDC",Color.rgb(103,52,158)); shell.addView(weekly,lp(ViewGroup.LayoutParams.MATCH_PARENT,dp(48),0,hasPending?7:13,0,0)); weekly.setOnClickListener(new View.OnClickListener(){public void onClick(View v){d.dismiss();startPremiumQuote("weekly");}}); Button monthly=button(active?"RENEW MONTHLY • 9.99 USDC":"UNLOCK MONTHLY • 9.99 USDC",Color.rgb(26,139,94)); shell.addView(monthly,lp(ViewGroup.LayoutParams.MATCH_PARENT,dp(48),0,7,0,0)); monthly.setOnClickListener(new View.OnClickListener(){public void onClick(View v){d.dismiss();startPremiumQuote("monthly");}}); if(active&&PremiumManager.linkedAccountCount(this)>=PremiumManager.accountLimit(this)){Button extra=outlineButton("ADD ACCOUNT SLOT • 5.00 USDC",PURPLE);shell.addView(extra,lp(ViewGroup.LayoutParams.MATCH_PARENT,dp(46),0,7,0,0));extra.setOnClickListener(new View.OnClickListener(){public void onClick(View v){d.dismiss();startAccountSlotQuote();}});}}
        Button close=outlineButton(admin?"DONE":"NOT NOW",MUTED); shell.addView(close,lp(ViewGroup.LayoutParams.MATCH_PARENT,dp(44),0,8,0,0)); close.setOnClickListener(new View.OnClickListener(){public void onClick(View v){d.dismiss();}});
        d.setContentView(scroll); d.show(); Window w=d.getWindow(); if(w!=null){w.setBackgroundDrawable(new android.graphics.drawable.ColorDrawable(Color.TRANSPARENT));w.setDimAmount(.78f);w.addFlags(android.view.WindowManager.LayoutParams.FLAG_DIM_BEHIND);w.setLayout((int)(getResources().getDisplayMetrics().widthPixels*.92f),(int)(getResources().getDisplayMetrics().heightPixels*.88f));}
    }

    private View premiumFeature(String title,String detail){LinearLayout row=new LinearLayout(this);row.setGravity(Gravity.CENTER_VERTICAL);row.setPadding(0,dp(6),0,dp(6));TextView mark=txt("✓",13,ACCENT,true);mark.setGravity(Gravity.CENTER);mark.setBackground(bg(Color.rgb(11,54,43),18));row.addView(mark,lp(dp(34),dp(34),0,0,10,0));LinearLayout copy=new LinearLayout(this);copy.setOrientation(LinearLayout.VERTICAL);copy.addView(txt(title,12,TEXT,true));copy.addView(txt(detail,9,MUTED,false),lp(ViewGroup.LayoutParams.MATCH_PARENT,ViewGroup.LayoutParams.WRAP_CONTENT,0,2,0,0));row.addView(copy,new LinearLayout.LayoutParams(0,ViewGroup.LayoutParams.WRAP_CONTENT,1));return row;}
    private View premiumFact(String label,String value,int color){LinearLayout box=new LinearLayout(this);box.setOrientation(LinearLayout.VERTICAL);box.setGravity(Gravity.CENTER);box.setPadding(dp(6),dp(8),dp(6),dp(8));box.setBackground(outlineBg(CARD2,14,color));TextView k=txt(label,9,MUTED,true);k.setGravity(Gravity.CENTER);box.addView(k);TextView v=txt(value,14,color,true);v.setGravity(Gravity.CENTER);box.addView(v,lp(ViewGroup.LayoutParams.MATCH_PARENT,ViewGroup.LayoutParams.WRAP_CONTENT,0,3,0,0));return box;}
    private View premiumDetailRow(String label,String value,int color){LinearLayout row=new LinearLayout(this);row.setGravity(Gravity.CENTER_VERTICAL);row.setPadding(0,dp(4),0,dp(4));row.addView(txt(label,9,MUTED,true),new LinearLayout.LayoutParams(0,ViewGroup.LayoutParams.WRAP_CONTENT,1));TextView v=txt(value,11,color,true);v.setGravity(Gravity.RIGHT);row.addView(v);return row;}

    /** Branded confirmation surface used instead of platform AlertDialogs. */
    private void showBrandedConfirm(String title,String message,String positive,String negative,final View.OnClickListener yes){
        final Dialog d=new Dialog(this);d.requestWindowFeature(Window.FEATURE_NO_TITLE);d.setCancelable(true);d.setCanceledOnTouchOutside(true);
        LinearLayout box=new LinearLayout(this);box.setOrientation(LinearLayout.VERTICAL);box.setPadding(dp(20),dp(18),dp(20),dp(14));box.setBackground(outlineBg(CARD,20,PURPLE));
        TextView icon=txt("✦",30,PURPLE,true);icon.setGravity(Gravity.CENTER);box.addView(icon,lp(ViewGroup.LayoutParams.MATCH_PARENT,dp(38),0,0,0,4));TextView h=txt(title,20,TEXT,true);h.setGravity(Gravity.CENTER);box.addView(h);TextView m=txt(message,14,TEXT,false);m.setGravity(Gravity.CENTER);box.addView(m,lp(ViewGroup.LayoutParams.MATCH_PARENT,ViewGroup.LayoutParams.WRAP_CONTENT,0,12,0,12));
        LinearLayout actions=new LinearLayout(this);actions.setGravity(Gravity.CENTER);Button no=outlineButton(negative==null?"CANCEL":negative,MUTED);Button ok=button(positive==null?"OK":positive,PURPLE);actions.addView(no,weighted(0,dp(48),0,0,5,0,1));actions.addView(ok,weighted(0,dp(48),5,0,0,0,1));box.addView(actions);no.setOnClickListener(new View.OnClickListener(){public void onClick(View v){d.dismiss();}});ok.setOnClickListener(new View.OnClickListener(){public void onClick(View v){d.dismiss();if(yes!=null)yes.onClick(v);}});d.setContentView(box);d.show();Window w=d.getWindow();if(w!=null){w.setBackgroundDrawable(new android.graphics.drawable.ColorDrawable(Color.TRANSPARENT));w.setLayout((int)(getResources().getDisplayMetrics().widthPixels*.84f),ViewGroup.LayoutParams.WRAP_CONTENT);}
    }

    private void startPremiumQuote(){startPremiumQuote("monthly");}
    private void startPremiumQuote(final String plan){
        if(premiumPaymentBusy)return;
        if(!WalletAuthManager.hasReusableWalletSession(this)){showGraphicMessage("!","Wallet session expired","Log out, reconnect your wallet, and try again.",RED);return;}
        premiumPaymentBusy=true;showPaymentProgress("Preparing payment","Getting the latest Solana payment details…");
        new Thread(new Runnable(){public void run(){PremiumManager.Quote q=null;Exception error=null;try{q=PremiumManager.createQuote(getApplicationContext(),plan,"subscription",0);}catch(Exception e){error=e;}final PremiumManager.Quote fq=q;final Exception fe=error;handler.post(new Runnable(){public void run(){premiumPaymentBusy=false;hidePaymentProgress();if(fe!=null||fq==null){showGraphicMessage("!","Payment unavailable",fe==null?"Could not prepare the Premium payment.":safeMessage(fe),RED);return;}String amount=String.format(Locale.US,"%.2f",fq.amountRaw/1000000.0d);String period="weekly".equals(fq.planId)?"7 days":"30 days";showBrandedConfirm("Confirm Premium payment","Premium • "+period+"\n\nYou pay: "+amount+" USDC\n\nYour wallet will open for approval.","OPEN WALLET","CANCEL",new View.OnClickListener(){public void onClick(View v){launchPremiumPayment(fq);}});}});}} ,"PremiumUsdcQuote").start();
    }
    private void startAccountSlotQuote(){
        if(premiumPaymentBusy)return; if(!isPremium()){showPremiumPaywall("Connect the first Premium account before adding a slot.");return;}
        premiumPaymentBusy=true;showPaymentProgress("Preparing account slot","Getting the latest Solana payment details…");
        new Thread(new Runnable(){public void run(){PremiumManager.Quote q=null;Exception error=null;try{q=PremiumManager.createQuote(getApplicationContext(),"monthly","account",PremiumManager.linkedAccountCount(getApplicationContext())+1);}catch(Exception e){error=e;}final PremiumManager.Quote fq=q;final Exception fe=error;handler.post(new Runnable(){public void run(){premiumPaymentBusy=false;hidePaymentProgress();if(fe!=null||fq==null){showGraphicMessage("!","Payment unavailable",fe==null?"Could not prepare the account slot payment.":safeMessage(fe),RED);return;}showBrandedConfirm("Add Premium account slot","Additional connected wallet\n\nYou pay: 5.00 USDC\n\nThis raises the account limit by one (up to five).", "OPEN WALLET","CANCEL",new View.OnClickListener(){public void onClick(View v){launchPremiumPayment(fq);}});}});}},"PremiumAccountQuote").start();
    }

    private void launchPremiumPayment(final PremiumManager.Quote q){
        if(q==null||premiumPaymentBusy)return;premiumPaymentBusy=true;PremiumManager.savePending(this,q);showPaymentProgress("Preparing USDC payment","Building and checking the Solana transaction…");
        PremiumUsdcTxBuilder.build(this,q.wallet,PremiumManager.TREASURY,PremiumManager.USDC_MINT,q.amountRaw,q.blockhash,new PremiumUsdcTxBuilder.Callback(){public void done(final PremiumUsdcTxBuilder.Result r,final Exception e){
            if(e!=null||r==null){premiumPaymentBusy=false;PremiumManager.clearPending(getApplicationContext());showGraphicMessage("!","Payment could not start",e==null?"Could not build the Premium payment.":safeMessage(e),RED);return;}
            PremiumManager.savePendingAccounts(getApplicationContext(),q,r.userAta,r.treasuryAta);
            new Thread(new Runnable(){public void run(){boolean enough=false;Exception balanceError=null;try{enough=PremiumManager.hasUsdcBalance(getApplicationContext(),r.userAta,q.amountRaw);}catch(Exception ex){balanceError=ex;}final boolean fEnough=enough;final Exception fError=balanceError;handler.post(new Runnable(){public void run(){
                if(fError!=null||!fEnough){premiumPaymentBusy=false;PremiumManager.clearPending(getApplicationContext());showGraphicMessage("!","USDC balance","The connected wallet does not have enough USDC for this plan.",RED);return;}
                try{String tx58=Base58.encode(Base64.decode(r.transactionBase64,Base64.DEFAULT));Uri sign=WalletAuthManager.buildSignTransactionUri(getApplicationContext(),tx58,"premiumtx");premiumPaymentBusy=false;hidePaymentProgress();startActivity(new Intent(Intent.ACTION_VIEW,sign));}
                catch(Exception openErr){premiumPaymentBusy=false;PremiumManager.clearPending(getApplicationContext());showGraphicMessage("!","Wallet could not open",safeMessage(openErr),RED);}
            }});}},"PremiumUsdcBalance").start();
        }});
    }

    private void handlePremiumTransactionReturn(final Uri uri){
        if(premiumPaymentBusy)return;
        premiumPaymentBusy=true;showPaymentProgress("Confirming payment","Checking your USDC transfer on Solana…");
        new Thread(new Runnable(){
            public void run(){
                String error="";boolean ok=false;boolean safeToRetry=false;
                try{
                    PremiumManager.Quote q=PremiumManager.pending(getApplicationContext());
                    String current=WalletAuthManager.walletPublicKey(getApplicationContext());
                    if(q.wallet.isEmpty()||q.amountRaw<=0||q.treasuryAta.isEmpty()||!q.wallet.equals(current))throw new Exception("Premium payment state expired. Start again.");
                    String signed58=WalletAuthManager.finishSignTransaction(getApplicationContext(),uri);
                    String sig=PremiumManager.extractSignature(signed58);
                    PremiumManager.savePendingSignature(getApplicationContext(),sig);
                    try{PremiumManager.sendSignedTransaction(getApplicationContext(),signed58);}catch(Exception ignored){}
                    PremiumManager.PaymentVerification v=waitForPremiumVerification(sig,q,24);
                    if(v!=null&&v.ok){PremiumManager.activatePaid(getApplicationContext(),q.wallet,sig,v.blockTimeMs);ok=true;}
                    else{error=v==null?"Payment is still being checked.":userMessage(v.error,"Payment is still being checked.");safeToRetry=v!=null&&v.safeToRetry;}
                }catch(Exception e){error=safeMessage(e);}
                final boolean fok=ok,fretry=safeToRetry;final String ferr=error;
                handler.post(new Runnable(){
                    public void run(){
                        premiumPaymentBusy=false;hidePaymentProgress();
                        if(fok){
                            refreshPremiumUi();showGraphicMessage("✓","Premium activated","Premium access is active for the selected plan.",ACCENT);
                        }else if(fretry){PremiumManager.clearPending(getApplicationContext());showGraphicMessage("!","Payment not completed",userMessage(ferr,"No payment was completed. You can try again."),RED);}
                        else showGraphicMessage("…","Confirmation pending",userMessage(ferr,"Payment is still being checked.")+"\n\nDo not pay again. The app will check automatically.",WARN);
                    }
                });
            }
        },"PremiumUsdcReturn").start();
    }

    private void checkPendingPremiumPayment(){
        final String sig=PremiumManager.pendingSignature(this);final PremiumManager.Quote q=PremiumManager.pending(this);
        if(sig==null||sig.isEmpty()||q.wallet.isEmpty()||q.amountRaw<=0){showGraphicMessage("…","No pending payment","There is no Premium payment waiting for confirmation.",WARN);return;}
        String current=WalletAuthManager.walletPublicKey(this);
        if(current==null||!current.equals(q.wallet)){showGraphicMessage("!","Different wallet","Reconnect the wallet that started this Premium payment before checking it.",WARN);return;}
        if(premiumPaymentBusy)return;premiumPaymentBusy=true;showPaymentProgress("Checking payment","Reading the latest confirmation from Solana…");
        new Thread(new Runnable(){public void run(){PremiumManager.PaymentVerification v=null;Exception error=null;try{v=waitForPremiumVerification(sig,q,7);}catch(Exception e){error=e;}final PremiumManager.PaymentVerification fv=v;final Exception fe=error;handler.post(new Runnable(){public void run(){premiumPaymentBusy=false;hidePaymentProgress();if(fe==null&&fv!=null&&fv.ok){PremiumManager.activatePaid(getApplicationContext(),q.wallet,sig,fv.blockTimeMs);refreshPremiumUi();showGraphicMessage("✓","Premium activated","Premium access is active for the selected plan.",ACCENT);return;}if(fv!=null&&fv.safeToRetry){PremiumManager.clearPending(getApplicationContext());showGraphicMessage("!","Payment not completed",userMessage(fv.error,"No payment was completed. You can try again."),RED);return;}showGraphicMessage("…","Confirmation pending",(fe!=null?safeMessage(fe):(fv==null?"Payment is still being checked.":userMessage(fv.error,"Payment is still being checked.")))+"\n\nDo not pay again. The app will check automatically.",WARN);}});}} ,"PremiumUsdcManualCheck").start();
    }

    private PremiumManager.PaymentVerification waitForPremiumVerification(String sig,PremiumManager.Quote q,int attempts)throws Exception{
        PremiumManager.PaymentVerification v=null;Exception last=null;
        for(int i=0;i<attempts;i++){if(i>0)try{Thread.sleep(i<8?1400L:2300L);}catch(InterruptedException ignored){}try{v=PremiumManager.verifyPayment(getApplicationContext(),sig,q);last=null;}catch(Exception e){last=e;}if(v!=null&&(v.ok||v.safeToRetry))return v;}
        if(v==null&&last!=null)throw last;return v;
    }

    private void autoRecoverPendingPremiumPayment(){
        final PremiumManager.Quote pendingQuote=PremiumManager.pending(this); String current=WalletAuthManager.walletPublicKey(this); if(root==null||premiumPaymentBusy||current==null||!current.equals(pendingQuote.wallet)||(isPremium()&&!"account".equals(pendingQuote.purpose)))return;final String sig=PremiumManager.pendingSignature(this);final PremiumManager.Quote q=pendingQuote;
        if(sig==null||sig.isEmpty()||q.wallet.isEmpty()||q.amountRaw<=0)return;premiumPaymentBusy=true;
        new Thread(new Runnable(){public void run(){PremiumManager.PaymentVerification v=null;try{v=waitForPremiumVerification(sig,q,3);}catch(Exception ignored){}final PremiumManager.PaymentVerification fv=v;handler.post(new Runnable(){public void run(){premiumPaymentBusy=false;if(fv!=null&&fv.ok){PremiumManager.activatePaid(getApplicationContext(),q.wallet,sig,fv.blockTimeMs);refreshPremiumUi();showGraphicMessage("✓","Premium activated","Your USDC payment was found automatically.",ACCENT);}else if(fv!=null&&fv.safeToRetry){PremiumManager.clearPending(getApplicationContext());showGraphicMessage("!","Payment not completed",userMessage(fv.error,"No payment was completed. You can try again."),RED);}}});}},"PremiumUsdcAutoRecovery").start();
    }

    private void refreshPremiumUi(){refreshBottomNav();if("trends".equals(currentPage))showTrends();else if("trends_flow".equals(currentPage))showMarketFlow();else if("history".equals(currentPage))showHistory();else if("settings".equals(currentPage))showSettings();else refreshCurrent();}

    private String userMessage(String raw,String fallback){
        String m=raw==null?"":raw.trim();if(m.isEmpty())return fallback;
        String l=m.toLowerCase(Locale.US);
        if(l.contains("cancel"))return "The action was cancelled.";
        if(l.contains("expired")||l.contains("blockhash"))return "This request expired. Please try again.";
        if(l.contains("insufficient")||l.contains("not enough"))return "Your balance is not enough for this action.";
        if(l.contains("session")&&(l.contains("expired")||l.contains("401")||l.contains("403")))return "Your connection expired. Please connect again.";
        if(l.contains("timeout")||l.contains("timed out")||l.contains("network")||l.contains("unreachable"))return "The connection took too long. Please try again.";
        if(l.contains("listing")&&l.contains("gone"))return "This listing is no longer available.";
        if(m.matches(".*[a-z0-9]+_[a-z0-9_]+.*")||l.contains("rpc")||l.contains("relay")||l.contains("websocket")||l.contains("http ")||l.contains("status=")||l.contains("signature")||l.contains("quote")||l.contains("shard")||l.contains("fleet")||l.contains("stateseq")||m.startsWith("{")||m.startsWith("["))return fallback;
        return m;
    }
    private String safeMessage(Exception e){return userMessage(e==null?"":e.getMessage(),"Something went wrong. Please try again.");}

    private void restoreSecureSession(){
        walletFlowBusy=true;setWalletLoginStatus("Restoring secure Kintara session…",ACCENT);
        new Thread(new Runnable(){public void run(){try{JSONObject me=KintaraApi.getMe(getApplicationContext());JSONObject player=me.optJSONObject("player");if(player!=null)SecurePrefs.saveWalletPlayer(getApplicationContext(),player.optString("display_name",player.optString("displayName","")),player.optLong("id",player.optLong("playerId",0L)));PremiumManager.autoLinkCurrentAccount(getApplicationContext());handler.post(new Runnable(){public void run(){walletFlowBusy=false;enterApp();}});}catch(final Exception e){SecurePrefs.clearCookie(getApplicationContext());handler.post(new Runnable(){public void run(){walletFlowBusy=false;setWalletLoginStatus("Session expired • connect your wallet to sign in again",WARN);}});}}},"RestoreWalletSession").start();
    }

    private void enterApp() {
        applyThemePalette();
        MarketJobService.schedule(getApplicationContext());
        buildShell();
        showMarket();
        warmTrendCache();
        async("Starting market collector…",new Work<Boolean>(){public Boolean run(){return HistoryStore.collectSnapshot(getApplicationContext());}},new Done<Boolean>(){public void done(Boolean v,Exception e){updateCollectorStatus();if("trends".equals(currentPage))refreshTrendsInPlace();}});
        startForegroundCollector();
        startListingPoll();
        async("Checking marketplace limits…",new Work<Integer>(){public Integer run(){return KintaraApi.listingQtyLimit(getApplicationContext());}},new Done<Integer>(){public void done(Integer v,Exception e){if(v!=null)listingQtyLimit=v;}});
        handler.postDelayed(new Runnable(){public void run(){autoRecoverPendingPremiumPayment();}},900L);
    }

    private void warmTrendCache(){
        final String wallet=SecurePrefs.getWalletPublicKey(this); if(wallet==null||wallet.isEmpty())return;
        new Thread(new Runnable(){public void run(){for(String item:HistoryStore.TRACKED){KintaraApi.loadStatsTask(getApplicationContext(),item,"token");if(!"gold".equals(item))KintaraApi.loadStatsTask(getApplicationContext(),item,"gold");}}},"WarmTrendCache").start();
    }

    private void buildShell(){
        root=new LinearLayout(this);root.setOrientation(LinearLayout.VERTICAL);root.setBackgroundColor(BG);
        LinearLayout head=new LinearLayout(this);head.setGravity(Gravity.CENTER_VERTICAL);head.setPadding(dp(14),dp(10),dp(12),dp(7));
        ImageView icon=new ImageView(this);icon.setImageResource(drawableId("app_icon_v172"));icon.setScaleType(ImageView.ScaleType.CENTER_INSIDE);head.addView(icon,lp(dp(42),dp(42),0,0,10,0));
        TextView appTitle=txt("KINTARA MARKET",20,TEXT,true);
        appTitle.setGravity(Gravity.CENTER_VERTICAL);
        appTitle.setIncludeFontPadding(false);
        head.addView(appTitle,new LinearLayout.LayoutParams(0,dp(42),1));
        collectorStatus=null;
        root.addView(head);
        busy=new ProgressBar(this,null,android.R.attr.progressBarStyleHorizontal);busy.setIndeterminate(true);busy.setVisibility(View.GONE);root.addView(busy,new LinearLayout.LayoutParams(ViewGroup.LayoutParams.MATCH_PARENT,dp(3)));
        contentFrame=new FrameLayout(this);root.addView(contentFrame,new LinearLayout.LayoutParams(ViewGroup.LayoutParams.MATCH_PARENT,0,1));
        mainScroll=new ScrollView(this);mainScroll.setFillViewport(true);mainScroll.setOverScrollMode(View.OVER_SCROLL_ALWAYS);contentFrame.addView(mainScroll,new FrameLayout.LayoutParams(ViewGroup.LayoutParams.MATCH_PARENT,ViewGroup.LayoutParams.MATCH_PARENT));
        body=new LinearLayout(this);body.setOrientation(LinearLayout.VERTICAL);body.setPadding(0,dp(4),0,dp(24));mainScroll.addView(body,new ScrollView.LayoutParams(ViewGroup.LayoutParams.MATCH_PARENT,ViewGroup.LayoutParams.WRAP_CONTENT));
        installPullToRefresh();

        if(gameSession==null)gameSession=new GameSessionManager(this,new GameSessionManager.Listener(){public void onGameSessionChanged(){handler.post(new Runnable(){public void run(){refreshGameSessionCard();}});}});
        gameSession.attachTo(contentFrame);

        navBar=new LinearLayout(this);navBar.setPadding(dp(6),dp(5),dp(6),dp(6));navBar.setGravity(Gravity.CENTER);navBar.setBackgroundColor(CARD);root.addView(navBar,new LinearLayout.LayoutParams(ViewGroup.LayoutParams.MATCH_PARENT,dp(72)));
        refreshBottomNav();
        setContentView(root);updateCollectorStatus();
    }

    /** Re-attach the lightweight authenticated presence after returning from the visible game. */
    private void ensureBackgroundGameSession(){
        if(root==null||contentFrame==null||gameSession!=null||SecurePrefs.getCookie(this).isEmpty())return;
        gameSession=new GameSessionManager(this,new GameSessionManager.Listener(){public void onGameSessionChanged(){handler.post(new Runnable(){public void run(){refreshGameSessionCard();}});}});
        gameSession.attachTo(contentFrame);
    }

    private void installPullToRefresh(){
        if(mainScroll==null)return;
        mainScroll.setOnTouchListener(new View.OnTouchListener(){public boolean onTouch(View v,MotionEvent ev){
            switch(ev.getActionMasked()){
                case MotionEvent.ACTION_DOWN: pullStartY=ev.getY();pullArmed=false;pullTriggered=false;cancelPullRefresh();break;
                case MotionEvent.ACTION_MOVE:
                    if(mainScroll.getScrollY()==0){float dy=ev.getY()-pullStartY;if(dy>dp(62)&&!pullTriggered){if(!pullArmed){pullArmed=true;pullRefreshRunnable=new Runnable(){public void run(){if(!pullArmed||pullTriggered)return;pullTriggered=true;refreshCurrent();syncActiveListings();}};handler.postDelayed(pullRefreshRunnable,200);}}else if(dy<dp(36)&&pullArmed){cancelPullRefresh();}}
                    break;
                case MotionEvent.ACTION_UP: case MotionEvent.ACTION_CANCEL: if(!pullTriggered)cancelPullRefresh();else pullArmed=false;break;
            }
            return false;
        }});
    }
    private void cancelPullRefresh(){pullArmed=false;if(pullRefreshRunnable!=null)handler.removeCallbacks(pullRefreshRunnable);pullRefreshRunnable=null;}

    private void showRefreshHintOnce(){ /* Refresh gesture is intentionally silent. */ }

    private void refreshBottomNav(){
        if(navBar==null)return;navBar.removeAllViews();
        addNav("Market","nav_market","market");
        addNav("Inventory","nav_inventory","inventory");
        addNav("Trends","nav_trends","trends");
        addNav("History","nav_history","history");
        addNav("Settings","nav_settings","settings");
    }

    private void addNav(String label,String iconName,final String page){
        boolean selected=currentPage!=null&&currentPage.startsWith(page);
        boolean historyPage="history".equals(page);
        boolean soldAlert=historyPage&&SaleHistoryStore.hasUnreadSold(this);
        boolean activeAlert=historyPage&&!latestActiveListings.isEmpty();
        int navColor=soldAlert?WARN:(activeAlert?RED:(selected?("trends".equals(page)&&"trends_flow".equals(currentPage)?MarketFlowStyle.metricColor(MarketFlowChartView.METRIC_SPENT):ACCENT):MUTED));
        boolean alert=soldAlert||activeAlert;
        LinearLayout item=new LinearLayout(this);item.setOrientation(LinearLayout.VERTICAL);item.setGravity(Gravity.CENTER);item.setPadding(dp(3),dp(4),dp(3),dp(2));
        if(soldAlert&&selected)item.setBackground(outlineBg(WARN_BG,13,WARN));
        else if(activeAlert&&selected)item.setBackground(outlineBg(RED_BG,13,RED));
        else item.setBackground(selected?("trends".equals(page)&&"trends_flow".equals(currentPage)?outlineBg(Color.rgb(45,35,13),13,MarketFlowStyle.metricColor(MarketFlowChartView.METRIC_SPENT)):outlineBg(Color.rgb(10,45,38),13,Color.rgb(24,118,91))):bg(Color.TRANSPARENT,13));
        ImageView icon=new ImageView(this);icon.setImageResource(drawableId(iconName));icon.setScaleType(ImageView.ScaleType.CENTER_INSIDE);icon.setColorFilter(navColor);icon.setAlpha((selected||alert)?1.0f:0.78f);item.addView(icon,new LinearLayout.LayoutParams(dp(25),dp(25)));
        TextView t=txt(label,9,navColor,selected||alert);t.setGravity(Gravity.CENTER);item.addView(t,lp(ViewGroup.LayoutParams.MATCH_PARENT,dp(18),0,2,0,0));
        View marker=new View(this);marker.setBackgroundColor((selected||alert)?navColor:Color.TRANSPARENT);item.addView(marker,lp(dp(24),dp(2),0,1,0,0));
        item.setOnClickListener(new View.OnClickListener(){public void onClick(View v){navigateTop(page,true);}});
        if("trends".equals(page)) item.setOnLongClickListener(new View.OnLongClickListener(){public boolean onLongClick(View v){
            v.setBackground(outlineBg(Color.rgb(45,35,13),13,MarketFlowStyle.metricColor(MarketFlowChartView.METRIC_SPENT))); showMarketFlow(); return true;
        }});
        if("settings".equals(page)) item.setOnLongClickListener(new View.OnLongClickListener(){public boolean onLongClick(View v){
            if(!isPremium()){showPremiumPaywall("Kintara Game is available with Premium access.");return true;}
            v.setBackground(outlineBg(Color.BLACK,13,ACCENT));
            icon.setColorFilter(Color.WHITE); t.setTextColor(Color.WHITE); marker.setBackgroundColor(ACCENT);
            handler.postDelayed(new Runnable(){public void run(){launchKintaraGame();}},90L);
            return true;
        }});
        LinearLayout.LayoutParams p=new LinearLayout.LayoutParams(0,ViewGroup.LayoutParams.MATCH_PARENT,1);p.setMargins(dp(2),0,dp(2),0);navBar.addView(item,p);
    }

    /** Opens the official multiplayer renderer in a dedicated, immersive app Activity. */
    private void launchKintaraGame(){
        if(!isPremium()){showPremiumPaywall("Kintara Game is available with Premium access.");return;}
        if(SecurePrefs.getCookie(this).isEmpty()){showGraphicMessage("!","Reconnect wallet","The Kintara session has expired. Connect your wallet again before opening the game.",RED);return;}
        stopForegroundCollector(); stopListingPoll(); stopInventoryLive(); stopHistoryHoldTick();
        if(gameSession!=null){gameSession.destroy();gameSession=null;}
        try{startActivity(new Intent(this,KintaraGameActivity.class));}
        catch(Exception e){showGraphicMessage("!","Game unavailable","The Android game surface could not be opened. Please try again.",RED);}
    }

    private void refreshCurrent(){
        if(currentPage==null||currentPage.startsWith("market"))showMarket();
        else if("inventory_trade".equals(currentPage)){refreshInventoryTradePrice(true);}
        else if("inventory".equals(currentPage)){syncInventoryLive(true,true);}
        else if("trends".equals(currentPage)){refreshTrendsInPlace();}
        else if(currentPage.startsWith("trends"))showTrends();
        else if(currentPage.startsWith("history"))showHistory();
        else showSettings();
    }

    private void updateCollectorStatus(){if(collectorStatus==null)return;long t=HistoryStore.latestTime(this);String last=t<=0?"Waiting for data":"Updated "+age(System.currentTimeMillis()-t)+" ago";collectorStatus.setText(last);}
    private String age(long ms){long s=Math.max(0,ms/1000);if(s<60)return s+"s";if(s<3600)return(s/60)+"m";return String.format(Locale.US,"%.1fh",s/3600.0);}
    private String money(Double v){return v==null?"—":String.format(Locale.US,"$%.2f",v);}
    private String utcDay(){SimpleDateFormat f=new SimpleDateFormat("yyyy-MM-dd",Locale.US);f.setTimeZone(TimeZone.getTimeZone("UTC"));return f.format(new Date());}

    private void clearBody(){if(body!=null)body.removeAllViews();}
    private void pageTitle(String t,String sub){TextView a=txt(t,22,TEXT,true);body.addView(a,lp(ViewGroup.LayoutParams.MATCH_PARENT,ViewGroup.LayoutParams.WRAP_CONTENT,16,8,16,sub==null||sub.trim().isEmpty()?8:0));if(sub!=null&&!sub.trim().isEmpty())body.addView(txt(sub,12,MUTED,false),lp(ViewGroup.LayoutParams.MATCH_PARENT,ViewGroup.LayoutParams.WRAP_CONTENT,16,4,16,8));}
    private <T> DarkSpinnerAdapter<T> spinnerAdapter(List<T> items){return new DarkSpinnerAdapter<T>(this,items);}

    private void showMarket(){
        stopInventoryLive();stopHistoryHoldTick();
        currentPage="market";clearBody();refreshBottomNav();pageTitle("Market","");
        addGameSessionCard();
        addMarketBoard();
    }

    private void addGameSessionCard(){
        boolean live=gameSession!=null&&gameSession.isReady();
        LinearLayout shell=card();gameSessionCard=shell;shell.setPadding(dp(16),dp(12),dp(16),dp(12));shell.setBackground(outlineBg(live?Color.rgb(12,35,31):Color.rgb(42,33,13),18,live?ACCENT:WARN));
        LinearLayout head=new LinearLayout(this);head.setGravity(Gravity.CENTER_VERTICAL);
        TextView label=txt("BACKGROUND GAME PRESENCE",13,live?ACCENT:WARN,true);head.addView(label,new LinearLayout.LayoutParams(0,ViewGroup.LayoutParams.WRAP_CONTENT,1));
        gameSessionAction=outlineButton("RECONNECT",live?ACCENT:WARN);gameSessionAction.setOnClickListener(new View.OnClickListener(){public void onClick(View v){if(gameSession!=null)gameSession.retry();}});head.addView(gameSessionAction,lp(dp(116),dp(44),8,0,0,0));shell.addView(head);
        body.addView(shell);refreshGameSessionCard();
    }

    private void refreshGameSessionCard(){
        if(gameSessionCard==null||gameSessionAction==null)return;
        boolean live=gameSession!=null&&gameSession.isReady();int color=live?ACCENT:WARN;
        gameSessionCard.setBackground(outlineBg(live?Color.rgb(12,35,31):Color.rgb(42,33,13),18,color));
        gameSessionAction.setText("RECONNECT");gameSessionAction.setTextColor(color);gameSessionAction.setBackground(outlineBg(CARD2,12,color));
        if(gameSessionCard.getChildCount()>0&&gameSessionCard.getChildAt(0)instanceof LinearLayout){LinearLayout row=(LinearLayout)gameSessionCard.getChildAt(0);if(row.getChildCount()>0&&row.getChildAt(0)instanceof TextView)((TextView)row.getChildAt(0)).setTextColor(color);}
    }

    private void showPresenceRequired(){
        final Dialog d=new Dialog(this);d.requestWindowFeature(Window.FEATURE_NO_TITLE);d.setCancelable(true);
        LinearLayout c=new LinearLayout(this);c.setOrientation(LinearLayout.VERTICAL);c.setGravity(Gravity.CENTER_HORIZONTAL);c.setPadding(dp(22),dp(20),dp(22),dp(18));c.setBackground(outlineBg(CARD,20,WARN));
        TextView title=txt("Connection needed",18,TEXT,true);title.setGravity(Gravity.CENTER);c.addView(title);
        TextView msg=txt("Reconnect, then try again.",11,MUTED,false);msg.setGravity(Gravity.CENTER);c.addView(msg,lp(ViewGroup.LayoutParams.MATCH_PARENT,ViewGroup.LayoutParams.WRAP_CONTENT,0,7,0,14));
        Button open=button("RECONNECT",Color.rgb(36,151,105));c.addView(open,new LinearLayout.LayoutParams(ViewGroup.LayoutParams.MATCH_PARENT,dp(48)));open.setOnClickListener(new View.OnClickListener(){public void onClick(View v){d.dismiss();if(gameSession!=null)gameSession.retry();}});
        Button cancel=outlineButton("NOT NOW",MUTED);c.addView(cancel,lp(ViewGroup.LayoutParams.MATCH_PARENT,dp(44),0,8,0,0));cancel.setOnClickListener(new View.OnClickListener(){public void onClick(View v){d.dismiss();}});
        d.setContentView(c);d.show();Window w=d.getWindow();if(w!=null){w.setBackgroundDrawable(new android.graphics.drawable.ColorDrawable(Color.TRANSPARENT));w.setDimAmount(.75f);w.addFlags(android.view.WindowManager.LayoutParams.FLAG_DIM_BEHIND);w.setLayout((int)(getResources().getDisplayMetrics().widthPixels*.9f),ViewGroup.LayoutParams.WRAP_CONTENT);}
    }

    private void addMarketBoard(){
        final int viewSerial=++marketBoardViewSerial;
        final LinearLayout card=card();body.addView(card);LinearLayout title=new LinearLayout(this);title.setGravity(Gravity.CENTER_VERTICAL);title.addView(txt("LIVE MARKET BOARD",16,TEXT,true),new LinearLayout.LayoutParams(0,ViewGroup.LayoutParams.WRAP_CONTENT,1));TextView live=txt("LIVE",10,ACCENT,true);live.setGravity(Gravity.CENTER);live.setBackground(outlineBg(Color.rgb(10,45,38),10,Color.rgb(24,118,91)));title.addView(live,lp(dp(48),dp(28),8,0,0,0));card.addView(title);
        if(hasPendingToken()){LinearLayout pending=new LinearLayout(this);pending.setGravity(Gravity.CENTER_VERTICAL);pending.setPadding(dp(10),dp(8),dp(10),dp(8));pending.setBackground(outlineBg(WARN_BG,12,WARN));pending.addView(txt("Pending $KINS purchase",11,WARN,true),new LinearLayout.LayoutParams(0,ViewGroup.LayoutParams.WRAP_CONTENT,1));Button recover=outlineButton("RECOVER",WARN);recover.setOnClickListener(new View.OnClickListener(){public void onClick(View v){recoverPendingTokenPurchase();}});pending.addView(recover,lp(dp(100),dp(40),8,0,0,0));card.addView(pending,lp(ViewGroup.LayoutParams.MATCH_PARENT,ViewGroup.LayoutParams.WRAP_CONTENT,0,9,0,0));}

        final Button categories=outlineButton("CATEGORIES",ACCENT),latest=outlineButton("LATEST LISTINGS",ACCENT);
        final LinearLayout modeRow=new LinearLayout(this);modeRow.addView(categories,weighted(0,dp(46),0,10,4,0,1));modeRow.addView(latest,weighted(0,dp(46),4,10,0,0,1));card.addView(modeRow);
        final EditText search=input("Search market items");search.setText(marketBoardQuery);card.addView(search,lp(ViewGroup.LayoutParams.MATCH_PARENT,dp(48),0,7,0,0));
        final LinearLayout filters=new LinearLayout(this);filters.setOrientation(LinearLayout.VERTICAL);card.addView(filters);
        final LinearLayout out=new LinearLayout(this);out.setOrientation(LinearLayout.VERTICAL);card.addView(out,lp(ViewGroup.LayoutParams.MATCH_PARENT,ViewGroup.LayoutParams.WRAP_CONTENT,0,7,0,0));

        final Runnable[] rebuildFilters=new Runnable[1];
        final Runnable[] load=new Runnable[1];
        final Spinner[] currencyRef=new Spinner[1];
        final Spinner[] categoryRef=new Spinner[1];
        rebuildFilters[0]=new Runnable(){public void run(){
            filters.removeAllViews();
            final Spinner currency=new Spinner(MainActivity.this);currencyRef[0]=currency;currency.setBackground(bg(CARD2,12));List<String> curs=new ArrayList<>();Collections.addAll(curs,"Gold + $KINS","Gold","$KINS");currency.setAdapter(spinnerAdapter(curs));currency.setSelection(Math.max(0,Math.min(2,marketBoardCurrencyPos)),false);filters.addView(currency,lp(ViewGroup.LayoutParams.MATCH_PARENT,dp(54),0,7,0,0));
            if(!marketLatestMode){final Spinner category=new Spinner(MainActivity.this);categoryRef[0]=category;category.setBackground(bg(CARD2,12));List<String> cats=new ArrayList<>();Collections.addAll(cats,"All categories","Gold","Mounts","Armor","Cosmetics","Materials","Potions","Food","Keys","Pets","Furni");category.setAdapter(spinnerAdapter(cats));category.setSelection(Math.max(0,Math.min(10,marketBoardCategoryPos)),false);filters.addView(category,lp(ViewGroup.LayoutParams.MATCH_PARENT,dp(54),0,7,0,0));}else categoryRef[0]=null;
            Button apply=outlineButton(marketLatestMode?"REFRESH LATEST":"REFRESH CATEGORIES",ACCENT);filters.addView(apply,lp(ViewGroup.LayoutParams.MATCH_PARENT,dp(46),0,7,0,0));apply.setOnClickListener(new View.OnClickListener(){public void onClick(View v){if(load[0]!=null)load[0].run();}});
            currency.setOnItemSelectedListener(new AdapterView.OnItemSelectedListener(){public void onNothingSelected(AdapterView<?> p){}public void onItemSelected(AdapterView<?> p,View v,int pos,long id){if(pos!=marketBoardCurrencyPos){marketBoardCurrencyPos=pos;if(load[0]!=null)load[0].run();}}});
            if(categoryRef[0]!=null)categoryRef[0].setOnItemSelectedListener(new AdapterView.OnItemSelectedListener(){public void onNothingSelected(AdapterView<?> p){}public void onItemSelected(AdapterView<?> p,View v,int pos,long id){if(pos!=marketBoardCategoryPos){marketBoardCategoryPos=pos;if(load[0]!=null)load[0].run();}}});
        }};

        final Runnable paintMode=new Runnable(){public void run(){
            categories.setBackground(marketLatestMode?outlineBg(CARD2,12,ACCENT):bg(Color.rgb(17,76,57),12));categories.setTextColor(marketLatestMode?ACCENT:Color.WHITE);
            latest.setBackground(marketLatestMode?bg(Color.rgb(17,76,57),12):outlineBg(CARD2,12,ACCENT));latest.setTextColor(marketLatestMode?Color.WHITE:ACCENT);
            rebuildFilters[0].run();
        }};

        load[0]=new Runnable(){public void run(){
            marketBoardQuery=search.getText().toString().trim();
            if(currencyRef[0]!=null)marketBoardCurrencyPos=Math.max(0,currencyRef[0].getSelectedItemPosition());
            if(categoryRef[0]!=null)marketBoardCategoryPos=Math.max(0,categoryRef[0].getSelectedItemPosition());
            final String[] cu={"all","gold","token"};final String[] ca={"all","cat_gold","cat_mounts","cat_armor","cat_cosmetics","cat_materials","cat_potions","cat_food","cat_keys","cat_pets","cat_furni"};
            final String fc=cu[Math.min(cu.length-1,marketBoardCurrencyPos)],fcat=ca[Math.min(ca.length-1,marketBoardCategoryPos)],fq=marketBoardQuery;final boolean latestMode=marketLatestMode;final String walletAtRequest=SecurePrefs.getWalletPublicKey(MainActivity.this);final String cacheKey=walletAtRequest+"|"+(latestMode?"latest|":"board|")+fc+"|"+fcat+"|"+fq; if(cacheKey.equals(lastMarketLoadKey)&&System.currentTimeMillis()-lastMarketLoadAt<5000L)return; lastMarketLoadKey=cacheKey;lastMarketLoadAt=System.currentTimeMillis(); final int requestSerial=++marketBoardRequestSerial;
            out.removeAllViews();
            if(latestMode){List<KintaraApi.Listing> cached=MarketCacheStore.loadLatest(getApplicationContext(),fc,fq);if(cached!=null&&!cached.isEmpty())renderLatestListingRows(out,cached);else out.addView(txt("Loading market…",11,MUTED,false));}
            else {List<KintaraApi.MarketItem> cached=MarketCacheStore.loadBoard(getApplicationContext(),fc,fcat,fq);if(cached!=null&&!cached.isEmpty())renderHotMarketRows(out,cached);else out.addView(txt("Loading market…",11,MUTED,false));}
            marketBoardBusySerial=requestSerial;setBusy(true,"Refreshing market…");
            new Thread(new Runnable(){public void run(){Exception error=null;List<KintaraApi.MarketItem> hot=null;List<KintaraApi.Listing> freshListings=null;try{
                if(latestMode)freshListings=KintaraApi.getLatestListings(getApplicationContext(),fc,fq,60);
                else hot=KintaraApi.getHotMarketItems(getApplicationContext(),fc,fcat,fq,60);
            }catch(Exception e){error=e;}final Exception err=error;final List<KintaraApi.MarketItem> hotRows=hot;final List<KintaraApi.Listing> listingRows=freshListings;handler.post(new Runnable(){public void run(){
                if(marketBoardBusySerial==requestSerial){setBusy(false,"");marketBoardBusySerial=0;}if(requestSerial!=marketBoardRequestSerial)return;if(!"market".equals(currentPage)||viewSerial!=marketBoardViewSerial||!walletAtRequest.equals(SecurePrefs.getWalletPublicKey(MainActivity.this)))return;
                if(err!=null){if((latestMode&&listingRows==null)||( !latestMode&&hotRows==null)){out.addView(txt(userMessage(safeMessage(err),"Market is unavailable right now."),11,RED,true));}return;}
                out.removeAllViews();if(latestMode){MarketCacheStore.saveLatest(getApplicationContext(),fc,fq,listingRows);renderLatestListingRows(out,listingRows);}else{MarketCacheStore.saveBoard(getApplicationContext(),fc,fcat,fq,hotRows);renderHotMarketRows(out,hotRows);}
            }});}} ,latestMode?"LatestMarketListings":"HotMarket24h").start();
        }};

        categories.setOnClickListener(new View.OnClickListener(){public void onClick(View v){if(marketLatestMode){marketLatestMode=false;paintMode.run();load[0].run();}}});
        latest.setOnClickListener(new View.OnClickListener(){public void onClick(View v){if(!marketLatestMode){marketLatestMode=true;paintMode.run();load[0].run();}}});
        search.addTextChangedListener(new TextWatcher(){public void beforeTextChanged(CharSequence s,int st,int c,int a){}public void onTextChanged(CharSequence s,int st,int before,int count){}public void afterTextChanged(Editable e){marketBoardQuery=e==null?"":e.toString().trim();if(marketSearchDebounce!=null)handler.removeCallbacks(marketSearchDebounce);marketSearchDebounce=new Runnable(){public void run(){if("market".equals(currentPage)&&load[0]!=null)load[0].run();}};handler.postDelayed(marketSearchDebounce,320L);}});
        paintMode.run();load[0].run();
    }

    private void renderHotMarketRows(LinearLayout out,List<KintaraApi.MarketItem> rows){
        if(out==null)return;out.removeAllViews();if(rows==null||rows.isEmpty()){out.addView(txt("No market items match these filters.",11,MUTED,false));return;}int rank=1;for(final KintaraApi.MarketItem x:rows){LinearLayout shell=new LinearLayout(this);shell.setOrientation(LinearLayout.VERTICAL);TextView badge=txt((rank<=3?"🔥 ":"")+"#"+rank,9,rank<=3?ACCENT:MUTED,rank<=3);shell.addView(badge,lp(ViewGroup.LayoutParams.MATCH_PARENT,ViewGroup.LayoutParams.WRAP_CONTENT,8,4,8,2));shell.addView(marketBoardRow(x));out.addView(shell,lp(ViewGroup.LayoutParams.MATCH_PARENT,ViewGroup.LayoutParams.WRAP_CONTENT,0,0,0,4));rank++;}
    }

    private void renderLatestListingRows(LinearLayout out,List<KintaraApi.Listing> rows){
        if(out==null)return;out.removeAllViews();if(rows==null||rows.isEmpty()){out.addView(txt("No fresh listings match this search.",11,MUTED,false));return;}for(final KintaraApi.Listing x:rows){LinearLayout shell=new LinearLayout(this);shell.setOrientation(LinearLayout.VERTICAL);shell.setPadding(dp(9),dp(8),dp(9),dp(8));shell.setBackground(outlineBg(CARD2,12,BORDER));LinearLayout top=new LinearLayout(this);top.setGravity(Gravity.CENTER_VERTICAL);top.addView(itemImage(x.itemType,42),lp(dp(42),dp(42),0,0,10,0));LinearLayout info=new LinearLayout(this);info.setOrientation(LinearLayout.VERTICAL);info.addView(txt(x.label(),13,TEXT,true));String who=x.sellerName==null||x.sellerName.isEmpty()?"seller":x.sellerName;info.addView(txt("×"+x.quantity+" • "+who+" • "+relativeTime(x.createdAtMs),10,MUTED,false));info.addView(txt(fmtMarketPrice(x.unitPrice(),x.currency)+" each • "+fmtMarketPrice(x.totalPrice(),x.currency)+" total",10,ACCENT,true));top.addView(info,new LinearLayout.LayoutParams(0,ViewGroup.LayoutParams.WRAP_CONTENT,1));Button buy=miniButton(x.inCheckout()?"HELD":"BUY");boolean mine=x.sellerName!=null&&!x.sellerName.isEmpty()&&x.sellerName.equalsIgnoreCase(SecurePrefs.getWalletPlayerName(this));buy.setEnabled(!mine&&!x.inCheckout()&&!buyFlowBusy);if(mine){buy.setText("YOURS");buy.setAlpha(.55f);}else if(x.inCheckout())buy.setAlpha(.55f);buy.setOnClickListener(new View.OnClickListener(){public void onClick(View v){beginPurchase(x,x.itemType,x.currency);}});top.addView(buy,lp(dp(92),dp(40),8,0,0,0));shell.addView(top);shell.setOnClickListener(new View.OnClickListener(){public void onClick(View v){showMarketItemDetail(x.itemType,x.currency);}});out.addView(shell,lp(ViewGroup.LayoutParams.MATCH_PARENT,ViewGroup.LayoutParams.WRAP_CONTENT,0,0,0,6));}
    }

    private void renderMarketBoardRows(LinearLayout out,List<KintaraApi.MarketItem> rows){
        if(out==null)return;out.removeAllViews();if(rows==null||rows.isEmpty()){out.addView(txt("No items match these filters.",11,MUTED,false));return;}for(final KintaraApi.MarketItem x:rows)out.addView(marketBoardRow(x));
    }

    private View marketBoardRow(final KintaraApi.MarketItem x){
        LinearLayout row=new LinearLayout(this);row.setGravity(Gravity.CENTER_VERTICAL);row.setPadding(dp(8),dp(8),dp(8),dp(8));row.setBackground(outlineBg(CARD2,12,BORDER));row.addView(itemImage(x.itemType,44),lp(dp(44),dp(44),0,0,10,0));LinearLayout info=new LinearLayout(this);info.setOrientation(LinearLayout.VERTICAL);info.addView(txt(x.label(),14,TEXT,true));String meta=x.listings+" listings • "+x.available+" available";info.addView(txt(meta,10,MUTED,false));String floors=(x.floorGold==null?"no Gold floor":fmtMarketPrice(x.floorGold,"gold")+" floor")+"  •  "+(x.floorToken==null?"no $KINS floor":fmtMarketPrice(x.floorToken,"token")+" floor");info.addView(txt(floors,10,MUTED,false));KintaraApi.LastSale ls=x.lastToken!=null?x.lastToken:x.lastGold;if(ls!=null)info.addView(txt("Last sale "+fmtMarketPrice(ls.unit,x.lastToken!=null?"token":"gold")+"  •  "+relativeTime(ls.soldAtMs),9,MUTED,false));row.addView(info,new LinearLayout.LayoutParams(0,ViewGroup.LayoutParams.WRAP_CONTENT,1));KintaraApi.Trend tr=x.floorToken!=null?x.trendToken:x.trendGold;TextView trend=txt(trendText(tr),11,trendColor(tr),true);trend.setGravity(Gravity.CENTER);row.addView(trend,lp(dp(62),dp(36),8,0,0,0));row.setOnClickListener(new View.OnClickListener(){public void onClick(View v){String cur=marketBoardCurrencyPos==1?"gold":marketBoardCurrencyPos==2?"token":x.floorToken!=null?"token":"gold";if("token".equals(cur)&&x.floorToken==null&&x.floorGold!=null)cur="gold";if("gold".equals(cur)&&x.floorGold==null&&x.floorToken!=null)cur="token";showMarketItemDetail(x.itemType,cur);}});return row;
    }

    private String fmtMarketPrice(double v,String currency){return "token".equals(currency)?String.format(Locale.US,"$%.4f",v).replaceAll("0+$","").replaceAll("\\.$",""):String.format(Locale.US,"%,.0f Gold",v);}
    private String trendText(KintaraApi.Trend t){if(t==null||t.dir==null||"flat".equals(t.dir))return "=";String a="up".equals(t.dir)?"▲":"▼";double p=Math.abs(t.pct);return a+" "+(p>=10?String.format(Locale.US,"%.0f%%",p):String.format(Locale.US,"%.1f%%",p));}
    private int trendColor(KintaraApi.Trend t){if(t==null||"flat".equals(t.dir))return MUTED;return "up".equals(t.dir)?ACCENT:RED;}

    private void showMarketItemDetail(final String itemType,final String initialCurrency){
        stopInventoryLive();stopHistoryHoldTick();
        if(!"market_detail".equals(currentPage))detailReturnPage=topPage(currentPage);
        currentPage="market_detail";clearBody();refreshBottomNav();pageTitle(KintaraApi.findItem(itemType).label,"");
        LinearLayout hero=card();GradientDrawable heroBg=new GradientDrawable(GradientDrawable.Orientation.TL_BR,new int[]{Color.rgb(11,45,40),Color.rgb(19,29,40),Color.rgb(26,23,42)});heroBg.setCornerRadius(dp(19));heroBg.setStroke(dp(1),Color.rgb(44,133,105));hero.setBackground(heroBg);hero.setElevation(dp(4));LinearLayout hr=new LinearLayout(this);hr.setGravity(Gravity.CENTER_VERTICAL);hr.addView(itemImage(itemType,78),lp(dp(78),dp(78),0,0,15,0));LinearLayout ht=new LinearLayout(this);ht.setOrientation(LinearLayout.VERTICAL);ht.addView(txt(KintaraApi.findItem(itemType).label,20,TEXT,true));ht.addView(txt("Live listings, recent sales and 30-day history",10,MUTED,false),lp(ViewGroup.LayoutParams.MATCH_PARENT,ViewGroup.LayoutParams.WRAP_CONTENT,0,3,0,0));boolean gameLive=gameSession!=null&&gameSession.isReady();TextView state=txt(gameLive?"● READY":"◌ CONNECTING",9,gameLive?ACCENT:WARN,true);state.setGravity(Gravity.CENTER);state.setBackground(outlineBg(gameLive?Color.rgb(9,50,39):WARN_BG,10,gameLive?Color.rgb(44,155,112):WARN));ht.addView(state,lp(ViewGroup.LayoutParams.WRAP_CONTENT,dp(30),0,9,0,0));hr.addView(ht,new LinearLayout.LayoutParams(0,ViewGroup.LayoutParams.WRAP_CONTENT,1));hero.addView(hr);body.addView(hero);
        final LinearLayout out=new LinearLayout(this);out.setOrientation(LinearLayout.VERTICAL);final LinearLayout cur=card();LinearLayout cr=new LinearLayout(this);final Button gold=outlineButton("Gold",ACCENT),token=outlineButton("$KINS",ACCENT);cr.addView(gold,weighted(0,dp(44),0,0,4,0,1));cr.addView(token,weighted(0,dp(44),4,0,0,0,1));cur.addView(cr);body.addView(cur);body.addView(out);
        final String[] selected={"token".equals(initialCurrency)?"token":"gold"};final Runnable reload=new Runnable(){public void run(){gold.setBackground(selected[0].equals("gold")?bg(Color.rgb(30,82,62),12):outlineBg(CARD2,12,ACCENT));token.setBackground(selected[0].equals("token")?bg(Color.rgb(30,82,62),12):outlineBg(CARD2,12,ACCENT));loadMarketItemDetail(itemType,selected[0],out);}};gold.setOnClickListener(new View.OnClickListener(){public void onClick(View v){selected[0]="gold";reload.run();}});token.setOnClickListener(new View.OnClickListener(){public void onClick(View v){selected[0]="token";reload.run();}});reload.run();
    }

    static final class DetailData{KintaraApi.MarketStats stats;List<KintaraApi.Listing> listings;}
    private void loadMarketItemDetail(final String itemType,final String currency,final LinearLayout out){
        final int request=++marketDetailRequestSerial;
        out.removeAllViews();final String walletAtRequest=SecurePrefs.getWalletPublicKey(this);KintaraApi.MarketStats cached=MarketCacheStore.loadStats(this,itemType,currency);List<KintaraApi.Listing> cachedRows=MarketCacheStore.loadItemListings(this,itemType,currency);if(cached!=null&&cached.ok){DetailData cd=new DetailData();cd.stats=cached;cd.listings=cachedRows;renderMarketDetail(out,itemType,currency,cd);}else{LinearLayout loading=card();loading.addView(txt("Loading "+("token".equals(currency)?"$KINS":"Gold")+" market data…",12,MUTED,false));out.addView(loading);}async("Loading item market…",new Work<DetailData>(){public DetailData run(){DetailData d=new DetailData();d.stats=KintaraApi.loadStatsTask(getApplicationContext(),itemType,currency).stats;try{d.listings=KintaraApi.getItemListings(getApplicationContext(),itemType,currency);if(walletAtRequest.equals(SecurePrefs.getWalletPublicKey(getApplicationContext())))MarketCacheStore.saveItemListings(getApplicationContext(),itemType,currency,d.listings);}catch(Exception ignored){d.listings=MarketCacheStore.loadItemListings(getApplicationContext(),itemType,currency);}return d;}},new Done<DetailData>(){public void done(DetailData d,Exception e){if(request!=marketDetailRequestSerial||!"market_detail".equals(currentPage)||!walletAtRequest.equals(SecurePrefs.getWalletPublicKey(MainActivity.this)))return;if(d==null||d.stats==null||!d.stats.ok){if(cached!=null&&cached.ok)return;out.removeAllViews();LinearLayout er=card();er.addView(txt("Could not load item market details.",12,RED,true));Button retry=outlineButton("RETRY",ACCENT);er.addView(retry,lp(ViewGroup.LayoutParams.MATCH_PARENT,dp(44),0,10,0,0));retry.setOnClickListener(new View.OnClickListener(){public void onClick(View v){loadMarketItemDetail(itemType,currency,out);}});out.addView(er);return;}out.removeAllViews();renderMarketDetail(out,itemType,currency,d);}});}

    private void renderMarketDetail(LinearLayout out,String itemType,String currency,DetailData d){
        KintaraApi.MarketStats s=d.stats;LinearLayout stats=card();stats.addView(txt("MARKET SNAPSHOT",12,MUTED,true));LinearLayout r1=new LinearLayout(this),r2=new LinearLayout(this);r1.addView(statTile("FLOOR",s.floorFor(currency)==null?"—":fmtMarketPrice(s.floorFor(currency),currency),s.floorFor(currency)==null?"no listings":("token".equals(currency)?"$KINS / item":"Gold / item"),WARN),weighted(0,dp(78),0,8,4,0,1));KintaraApi.LastSale last=s.lastFor(currency);r1.addView(statTile("LAST SALE",last==null?"—":fmtMarketPrice(last.unit,currency),last==null?"never sold":relativeTime(last.soldAtMs),ACCENT),weighted(0,dp(78),4,8,0,0,1));r2.addView(statTile("LISTINGS",String.valueOf(s.listingsFor(currency)),s.sales24h>0?s.units24h+" sold 24h":"active",TEXT),weighted(0,dp(78),0,8,4,0,1));r2.addView(statTile("AVAILABLE",String.valueOf(s.availableFor(currency)),"items",TEXT),weighted(0,dp(78),4,8,0,0,1));stats.addView(r1);stats.addView(r2);out.addView(stats);
        LinearLayout seller=card();seller.addView(txt("MARKET INSIGHT",12,ACCENT,true));KintaraApi.SellerIntel si=KintaraApi.sellerIntel(s,d.listings,currency,s.floorFor(currency)==null?0:s.floorFor(currency));seller.addView(txt(si.sellSignal+"  •  "+si.pressure,11,sellerPressureColor(si.pressure),true),lp(ViewGroup.LayoutParams.MATCH_PARENT,ViewGroup.LayoutParams.WRAP_CONTENT,0,5,0,0));String sellRead=s.units24h+" items sold in the last 24 hours"+(s.sales24h>0?" across "+s.sales24h+" sales":"");seller.addView(txt(sellRead,10,TEXT,false),lp(ViewGroup.LayoutParams.MATCH_PARENT,ViewGroup.LayoutParams.WRAP_CONTENT,0,3,0,0));seller.addView(txt(s.availableFor(currency)+" items currently available",10,MUTED,false),lp(ViewGroup.LayoutParams.MATCH_PARENT,ViewGroup.LayoutParams.WRAP_CONTENT,0,3,0,0));if(si.lastSaleUnit!=null&&si.floorUnit>0)seller.addView(txt("Last sale vs current floor: "+signedPct(si.lastSaleVsFloorPct),10,MUTED,false),lp(ViewGroup.LayoutParams.MATCH_PARENT,ViewGroup.LayoutParams.WRAP_CONTENT,0,3,0,0));out.addView(seller);
        LinearLayout chartCard=card();LinearLayout ch=new LinearLayout(this);ch.setGravity(Gravity.CENTER_VERTICAL);ch.addView(txt("PRICE HISTORY",12,MUTED,true),new LinearLayout.LayoutParams(0,ViewGroup.LayoutParams.WRAP_CONTENT,1));ch.addView(txt(trendText(s.trend),11,trendColor(s.trend),true));chartCard.addView(ch);MarketChartView chart=new MarketChartView(this);chart.setData(s.history,"token".equals(currency));chartCard.addView(chart,new LinearLayout.LayoutParams(ViewGroup.LayoutParams.MATCH_PARENT,dp(204)));out.addView(chartCard);
        LinearLayout recent=card();recent.addView(txt("RECENT SALES",13,TEXT,true));if(s.recent.isEmpty())recent.addView(txt("No recorded sales yet.",11,MUTED,false));else{int n=0;for(KintaraApi.RecentSale x:s.recent){if(n++>=12)break;LinearLayout rr=new LinearLayout(this);rr.setGravity(Gravity.CENTER_VERTICAL);TextView left=txt(x.quantity+" @ "+fmtMarketPrice(x.unit,currency)+" ea\n"+relativeTime(x.soldAtMs),11,TEXT,false);rr.addView(left,new LinearLayout.LayoutParams(0,ViewGroup.LayoutParams.WRAP_CONTENT,1));TextView total=txt(fmtMarketPrice(x.total,currency),11,ACCENT,true);total.setGravity(Gravity.RIGHT);rr.addView(total,lp(dp(110),ViewGroup.LayoutParams.WRAP_CONTENT,8,0,0,0));recent.addView(rr,lp(ViewGroup.LayoutParams.MATCH_PARENT,ViewGroup.LayoutParams.WRAP_CONTENT,0,7,0,0));}}out.addView(recent);
        LinearLayout listings=card();
        listings.addView(txt("CURRENT LISTINGS"+(d.listings==null?"":" ("+d.listings.size()+")"),13,TEXT,true));
        if(d.listings==null||d.listings.isEmpty()) listings.addView(txt("No current listings for this currency.",11,MUTED,false));
        else {
            int n=0;double floor=s.floorFor(currency)==null?Double.NaN:s.floorFor(currency);
            for(KintaraApi.Listing x:d.listings){if(n++>=20)break;listings.addView(marketListingRow(x,currency,floor,itemType),lp(ViewGroup.LayoutParams.MATCH_PARENT,ViewGroup.LayoutParams.WRAP_CONTENT,0,7,0,0));}
        }
        out.addView(listings);
        addInlineSellPriceCheck(out,itemType);
    }

    private static final class TokenPrep { KintaraApi.TokenQuoteResult quoteResult; String blockhash; }

    private String pendingSecure(String k){return SecurePrefs.getSecureString(this,k);}
    private boolean savePendingToken(JSONObject quote,KintaraApi.Listing x,String itemType,String currency){
        try{SecurePrefs.saveSecureString(this,PENDING_BUY_QUOTE,quote.optString("quoteId",""));SecurePrefs.saveSecureString(this,PENDING_BUY_SIGNATURE,"");SecurePrefs.saveSecureString(this,PENDING_BUY_SIGNED_TX,"");SecurePrefs.saveSecureString(this,PENDING_BUY_LISTING,x.id==null?"":x.id);SecurePrefs.saveSecureString(this,PENDING_BUY_ITEM,itemType);SecurePrefs.saveSecureString(this,PENDING_BUY_CURRENCY,currency);SecurePrefs.saveSecureString(this,PENDING_BUY_QTY,String.valueOf(Math.max(1,x.quantity)));SecurePrefs.saveSecureString(this,PENDING_BUY_TS,String.valueOf(System.currentTimeMillis()));SecurePrefs.saveSecureString(this,PENDING_BUY_WALLET,WalletAuthManager.walletPublicKey(this));return true;}catch(Exception ignored){clearPendingToken();return false;}
    }
    private boolean savePendingTokenSignature(String sig){try{SecurePrefs.saveSecureString(this,PENDING_BUY_SIGNATURE,sig==null?"":sig);return sig!=null&&sig.equals(pendingSecure(PENDING_BUY_SIGNATURE));}catch(Exception ignored){return false;}}
    private boolean savePendingTokenSignedTransaction(String tx){try{SecurePrefs.saveSecureString(this,PENDING_BUY_SIGNED_TX,tx==null?"":tx);return tx!=null&&tx.equals(pendingSecure(PENDING_BUY_SIGNED_TX));}catch(Exception ignored){return false;}}
    private void clearPendingToken(){SecurePrefs.removeSecureStrings(this,PENDING_BUY_QUOTE,PENDING_BUY_SIGNATURE,PENDING_BUY_SIGNED_TX,PENDING_BUY_LISTING,PENDING_BUY_ITEM,PENDING_BUY_CURRENCY,PENDING_BUY_QTY,PENDING_BUY_TS,PENDING_BUY_WALLET);}
    private boolean pendingTokenBelongsToOtherWallet(){String pending=pendingSecure(PENDING_BUY_WALLET),current=WalletAuthManager.walletPublicKey(this);return !pending.isEmpty()&&!pending.equals(current);}
    private boolean hasPendingToken(){
        String q=pendingSecure(PENDING_BUY_QUOTE);if(q.isEmpty()||pendingTokenBelongsToOtherWallet())return false;
        // An unsigned reservation can expire normally. Once a wallet signature exists,
        // never age the evidence out: it represents a potentially completed payment
        // and is removed only after delivery or a definitive failed-on-chain result.
        if(pendingSecure(PENDING_BUY_SIGNATURE).isEmpty())try{long ts=Long.parseLong(pendingSecure(PENDING_BUY_TS));if(ts>0&&System.currentTimeMillis()-ts>86400000L){clearPendingToken();return false;}}catch(Exception ignored){}
        return true;
    }
    private boolean pendingNoCharge(String e){return "tx_failed_on_chain".equals(e)||"tx_dropped_not_charged".equals(e);}
    private boolean pendingSignatureConflict(String e){return "signature_reused".equals(e)||"signature_used_other_flow".equals(e);}
    private boolean pendingPaidUndeliverable(String e){return "paid_listing_gone".equals(e);}
    private boolean pendingTerminal(String e){return pendingNoCharge(e)||pendingSignatureConflict(e)||pendingPaidUndeliverable(e);}
    private boolean confirmShouldRetry(KintaraApi.BuyResult r){return r==null||r.resultUnknown||r.retryable||"verify_failed".equals(r.error)||"tx_not_found_or_failed".equals(r.error)||"seller_transfer_short".equals(r.error)||"treasury_transfer_short".equals(r.error)||"need_buy_reserve".equals(r.error)||"token_confirm_failed".equals(r.error)||"network_timeout".equals(r.error)||"network_error".equals(r.error);}
    private int pendingQuantity(){try{return Math.max(1,Integer.parseInt(pendingSecure(PENDING_BUY_QTY)));}catch(Exception ignored){return 1;}}

    private KintaraApi.BuyResult confirmSavedTokenPayment(String quoteId,String sig,String signedTx,String listing,boolean broadcastFirst){
        if(sig==null||sig.isEmpty())return KintaraApi.tokenRecover(getApplicationContext(),quoteId);
        if(broadcastFirst&&signedTx!=null&&!signedTx.isEmpty())try{KintaraApi.sendSignedTransaction(getApplicationContext(),signedTx);}catch(Exception ignored){}
        KintaraApi.TransactionStatus chain=KintaraApi.waitForSignatureConfirmation(getApplicationContext(),sig,95000L);
        if(chain.failed){KintaraApi.BuyResult failed=new KintaraApi.BuyResult();failed.error="tx_failed_on_chain";failed.message="Solana reports that the saved transaction failed. No token transfer was completed.";return failed;}
        KintaraApi.BuyResult result=null;
        for(int i=0;i<3;i++){
            if(i>0)try{Thread.sleep(4000L);}catch(InterruptedException ignored){Thread.currentThread().interrupt();break;}
            result=KintaraApi.tokenConfirm(getApplicationContext(),quoteId,sig);
            if(result!=null&&result.ok)break;
            if(result!=null&&pendingSignatureConflict(result.error)&&KintaraApi.isListingInBoughtHistory(getApplicationContext(),listing)){result.ok=true;result.error="";result.message="";break;}
            if(result!=null&&pendingTerminal(result.error))break;
            if(!confirmShouldRetry(result))break;
        }
        return result;
    }
    private boolean listingIdMatches(JSONObject q,String id){
        if(q==null||!q.has("listingId"))return true;String a=String.valueOf(q.opt("listingId")),b=String.valueOf(id);try{return Long.parseLong(a.replace(".0",""))==Long.parseLong(b.replace(".0",""));}catch(Exception e){return a.equals(b);}
    }

    private void beginPurchase(final KintaraApi.Listing x,final String itemType,final String currency){
        if(x==null||x.id==null||x.id.isEmpty()||buyFlowBusy)return;
        if(gameSession==null||!gameSession.isReady()){if(gameSession!=null)gameSession.retry();showPresenceRequired();return;}
        if("token".equals(currency)&&pendingTokenBelongsToOtherWallet()){
            showGraphicMessage("!","Different wallet","Reconnect the wallet that started the saved $KINS purchase before starting another one.",WARN);return;
        }
        if("token".equals(currency)&&hasPendingToken()){
            showPendingBuyDialog("Finish the saved $KINS purchase before starting another one.");return;
        }
        final Dialog d=new Dialog(this);d.requestWindowFeature(Window.FEATURE_NO_TITLE);d.setCancelable(true);d.setCanceledOnTouchOutside(true);
        LinearLayout shell=new LinearLayout(this);shell.setOrientation(LinearLayout.VERTICAL);shell.setPadding(dp(20),dp(18),dp(20),dp(18));shell.setBackground(outlineBg(CARD,22,Color.rgb(48,122,96)));
        LinearLayout hero=new LinearLayout(this);hero.setGravity(Gravity.CENTER_VERTICAL);hero.addView(itemImage(itemType,70),lp(dp(70),dp(70),0,0,14,0));LinearLayout copy=new LinearLayout(this);copy.setOrientation(LinearLayout.VERTICAL);copy.addView(txt("REVIEW PURCHASE",10,ACCENT,true));copy.addView(txt(KintaraApi.findItem(itemType).label,20,TEXT,true),lp(ViewGroup.LayoutParams.MATCH_PARENT,ViewGroup.LayoutParams.WRAP_CONTENT,0,3,0,0));copy.addView(txt("×"+Math.max(1,x.quantity)+" from "+(x.sellerName==null||x.sellerName.isEmpty()?"Kintara seller":x.sellerName),11,MUTED,false),lp(ViewGroup.LayoutParams.MATCH_PARENT,ViewGroup.LayoutParams.WRAP_CONTENT,0,3,0,0));hero.addView(copy,new LinearLayout.LayoutParams(0,ViewGroup.LayoutParams.WRAP_CONTENT,1));shell.addView(hero);
        LinearLayout price=new LinearLayout(this);price.setOrientation(LinearLayout.VERTICAL);price.setPadding(dp(14),dp(12),dp(14),dp(12));price.setBackground(outlineBg(CARD2,14,BORDER));price.addView(txt("TOTAL",9,MUTED,true));price.addView(txt(fmtMarketPrice(x.totalPrice(),currency),22,"token".equals(currency)?PURPLE:WARN,true));price.addView(txt(fmtMarketPrice(x.unitPrice(),currency)+" each",10,MUTED,false));shell.addView(price,lp(ViewGroup.LayoutParams.MATCH_PARENT,ViewGroup.LayoutParams.WRAP_CONTENT,0,14,0,0));
        LinearLayout steps=new LinearLayout(this);steps.setGravity(Gravity.CENTER);steps.addView(purchaseStep("1","Reserve"),weighted(0,dp(64),0,12,4,0,1));steps.addView(purchaseStep("2","token".equals(currency)?"Approve":"Pay"),weighted(0,dp(64),4,12,4,0,1));steps.addView(purchaseStep("3","Deliver"),weighted(0,dp(64),4,12,0,0,1));shell.addView(steps);
        boolean live=gameSession!=null&&gameSession.isReady();TextView presence=txt(live?"● READY":"◌ CONNECTING",10,live?ACCENT:WARN,true);presence.setPadding(dp(10),dp(9),dp(10),dp(9));presence.setBackground(outlineBg(live?Color.rgb(10,45,38):WARN_BG,12,live?Color.rgb(30,128,94):WARN));shell.addView(presence,lp(ViewGroup.LayoutParams.MATCH_PARENT,ViewGroup.LayoutParams.WRAP_CONTENT,0,10,0,14));
        LinearLayout actions=new LinearLayout(this);Button cancel=outlineButton("CANCEL",MUTED),confirm=button("token".equals(currency)?"CONNECT":"BUY NOW",Color.rgb(36,151,105));actions.addView(cancel,weighted(0,dp(48),0,0,5,0,1));actions.addView(confirm,weighted(0,dp(48),5,0,0,0,1));shell.addView(actions);cancel.setOnClickListener(new View.OnClickListener(){public void onClick(View v){d.dismiss();}});confirm.setOnClickListener(new View.OnClickListener(){public void onClick(View v){d.dismiss();if(!isPremium()){showPremiumPaywall("Premium access is required from the final Buy Now step.");return;}reserveThenPurchase(x,itemType,currency);}});
        d.setContentView(shell);d.show();Window w=d.getWindow();if(w!=null){w.setBackgroundDrawable(new android.graphics.drawable.ColorDrawable(Color.TRANSPARENT));w.setDimAmount(.76f);w.addFlags(android.view.WindowManager.LayoutParams.FLAG_DIM_BEHIND);w.setLayout((int)(getResources().getDisplayMetrics().widthPixels*.92f),ViewGroup.LayoutParams.WRAP_CONTENT);}
    }

    private View purchaseStep(String number,String label){LinearLayout s=new LinearLayout(this);s.setOrientation(LinearLayout.VERTICAL);s.setGravity(Gravity.CENTER);TextView n=txt(number,12,ACCENT,true);n.setGravity(Gravity.CENTER);n.setBackground(outlineBg(Color.rgb(10,45,38),20,Color.rgb(31,133,98)));s.addView(n,new LinearLayout.LayoutParams(dp(34),dp(34)));TextView l=txt(label,9,MUTED,true);l.setGravity(Gravity.CENTER);s.addView(l,lp(ViewGroup.LayoutParams.MATCH_PARENT,ViewGroup.LayoutParams.WRAP_CONTENT,0,5,0,0));return s;}

    private void reserveThenPurchase(final KintaraApi.Listing x,final String itemType,final String currency){
        if(buyFlowBusy)return;buyFlowBusy=true;
        async("Reserving listing…",new Work<KintaraApi.BuyReserve>(){public KintaraApi.BuyReserve run(){return KintaraApi.reserveListing(getApplicationContext(),x.id);}},new Done<KintaraApi.BuyReserve>(){public void done(KintaraApi.BuyReserve r,Exception e){
            if(e!=null||r==null||!r.ok){buyFlowBusy=false;if(r!=null&&"presence_required".equals(r.error))showPresenceRequired();else showGraphicMessage("!","Purchase unavailable",e!=null?safeMessage(e):userMessage(r==null?"":r.message,"This item is unavailable. Please refresh and try again."),RED);refreshCurrentMarketItem(itemType,currency);return;}
            if("token".equals(currency))prepareTokenPurchase(x,itemType,currency);else completeGoldPurchase(x,itemType,currency,r.expiresAtMs);
        }});
    }

    private void completeGoldPurchase(final KintaraApi.Listing x,final String itemType,final String currency,final long expiresAtMs){
        if(expiresAtMs>0&&System.currentTimeMillis()>expiresAtMs-3000L){KintaraApi.releaseBuyReserve(this,x.id,false);buyFlowBusy=false;toast("Checkout window expired. Press Buy again.");refreshCurrentMarketItem(itemType,currency);return;}
        async("Buying for Gold…",new Work<KintaraApi.BuyResult>(){public KintaraApi.BuyResult run(){return KintaraApi.buyGold(getApplicationContext(),x.id);}},new Done<KintaraApi.BuyResult>(){public void done(KintaraApi.BuyResult r,Exception e){
            buyFlowBusy=false;if(e!=null||r==null||!r.ok){KintaraApi.releaseBuyReserve(getApplicationContext(),x.id,false);toast(e!=null?safeMessage(e):userMessage(r==null?"":r.message,"Could not complete the purchase. Please try again."));refreshCurrentMarketItem(itemType,currency);return;}afterPurchaseSuccess(itemType,currency,x.quantity);
        }});
    }

    private void prepareTokenPurchase(final KintaraApi.Listing x,final String itemType,final String currency){
        if(!WalletAuthManager.hasReusableWalletSession(this)){KintaraApi.releaseBuyReserve(this,x.id,true);buyFlowBusy=false;toast("Wallet session expired. Log out and reconnect your wallet.");return;}
        async("Preparing purchase…",new Work<TokenPrep>(){public TokenPrep run()throws Exception{TokenPrep p=new TokenPrep();p.quoteResult=KintaraApi.tokenQuote(getApplicationContext(),x.id);if(p.quoteResult==null||!p.quoteResult.ok)throw new Exception(p.quoteResult==null?"Could not prepare purchase":p.quoteResult.message);p.blockhash=KintaraApi.latestFinalizedBlockhash(getApplicationContext());return p;}},new Done<TokenPrep>(){public void done(final TokenPrep prep,Exception e){
            if(e!=null||prep==null||prep.quoteResult==null||prep.quoteResult.quote==null){KintaraApi.releaseBuyReserve(getApplicationContext(),x.id,true);buyFlowBusy=false;toast(e==null?"Could not prepare token purchase":safeMessage(e));refreshCurrentMarketItem(itemType,currency);return;}
            final JSONObject q=prep.quoteResult.quote;String quoteId=q.optString("quoteId","");boolean changed=!listingIdMatches(q,x.id)||(q.has("itemType")&&!itemType.equals(q.optString("itemType")))||(q.has("quantity")&&q.optInt("quantity",x.quantity)!=x.quantity)||(q.has("priceUsd")&&Math.abs(q.optDouble("priceUsd",x.priceUsd)-x.priceUsd)>0.000001);
            if(quoteId.isEmpty()||changed){KintaraApi.releaseBuyReserve(getApplicationContext(),x.id,true);buyFlowBusy=false;toast(changed?"This listing changed. Reopen it and try again.":"Could not prepare the purchase. Please try again.");refreshCurrentMarketItem(itemType,currency);return;}
            if(!savePendingToken(q,x,itemType,currency)){KintaraApi.releaseBuyReserve(getApplicationContext(),x.id,true);buyFlowBusy=false;showGraphicMessage("!","Secure storage unavailable","The purchase was stopped before opening your wallet because recovery state could not be stored.",RED);return;}
            final String payer=WalletAuthManager.walletPublicKey(getApplicationContext());
            SolanaTxBuilder.build(MainActivity.this,q,payer,prep.blockhash,new SolanaTxBuilder.Callback(){public void done(final SolanaTxBuilder.Result tx,Exception buildError){
                if(buildError!=null||tx==null){KintaraApi.releaseBuyReserve(getApplicationContext(),x.id,true);clearPendingToken();buyFlowBusy=false;toast(buildError==null?"Could not build token payment":safeMessage(buildError));return;}
                async("Checking balance…",new Work<Boolean>(){public Boolean run()throws Exception{return KintaraApi.hasTokenBalance(getApplicationContext(),tx.userAta,tx.totalAmount);}},new Done<Boolean>(){public void done(Boolean enough,Exception balErr){
                    if(balErr!=null||!Boolean.TRUE.equals(enough)){KintaraApi.releaseBuyReserve(getApplicationContext(),x.id,true);clearPendingToken();buyFlowBusy=false;toast(balErr==null?"Not enough $KINS.":"Could not verify $KINS balance: "+safeMessage(balErr));return;}
                    try{String tx58=Base58.encode(Base64.decode(tx.transactionBase64,Base64.DEFAULT));Uri sign=WalletAuthManager.buildSignTransactionUri(getApplicationContext(),tx58);tokenWalletHandoff=true;startActivity(new Intent(Intent.ACTION_VIEW,sign));setBusy(false,"");}catch(Exception openErr){tokenWalletHandoff=false;KintaraApi.releaseBuyReserve(getApplicationContext(),x.id,true);clearPendingToken();buyFlowBusy=false;toast("Could not open wallet: "+safeMessage(openErr));}
                }});
            }});
        }});
    }

    private void handleTokenTransactionReturn(final Uri uri){
        tokenWalletHandoff=false;String pendingWallet=pendingSecure(PENDING_BUY_WALLET),currentWallet=WalletAuthManager.walletPublicKey(this);if(!pendingWallet.isEmpty()&&!pendingWallet.equals(currentWallet)){showGraphicMessage("!","Different wallet","Reconnect the wallet that started this purchase before approving it.",WARN);return;}buyFlowBusy=true;showPaymentProgress("Securing your purchase","");
        new Thread(new Runnable(){public void run(){
            final String item=pendingSecure(PENDING_BUY_ITEM),currency=pendingSecure(PENDING_BUY_CURRENCY),listing=pendingSecure(PENDING_BUY_LISTING),quoteId=pendingSecure(PENDING_BUY_QUOTE);final int quantity=pendingQuantity();boolean durablePayment=false;
            try{
                if(quoteId.isEmpty())throw new Exception("Purchase state expired. No transaction was sent.");
                String signed58=WalletAuthManager.finishSignTransaction(getApplicationContext(),uri);
                if(!savePendingTokenSignedTransaction(signed58))throw new Exception("The signed transaction could not be securely saved. It was not broadcast.");
                final String sig=KintaraApi.extractSignedTransactionSignature(signed58);if(!savePendingTokenSignature(sig))throw new Exception("The payment signature could not be securely saved. It was not broadcast.");
                durablePayment=true;
                handler.post(new Runnable(){public void run(){showPaymentProgress("Securing your purchase","");}});
                final KintaraApi.BuyResult result=confirmSavedTokenPayment(quoteId,sig,signed58,listing,true);
                final KintaraApi.BuyResult fr=result;
                handler.post(new Runnable(){public void run(){buyFlowBusy=false;hidePaymentProgress();if(fr!=null&&fr.ok){clearPendingToken();afterPurchaseSuccess(item,currency,fr.quantity>0?fr.quantity:quantity);}else if(fr!=null&&pendingNoCharge(fr.error)){clearPendingToken();showGraphicMessage("!","Purchase not completed","No $KINS was transferred. You can try again.",RED);returnToMarketAfterWallet();}else{showPendingBuyDialog(friendlyPendingDetail(fr,null));returnToMarketAfterWallet();}}});
            }catch(final Exception e){final boolean keep=durablePayment;if(!keep){if(!listing.isEmpty())KintaraApi.releaseBuyReserve(getApplicationContext(),listing,true);clearPendingToken();}handler.post(new Runnable(){public void run(){buyFlowBusy=false;hidePaymentProgress();if(keep)showPendingBuyDialog("Your payment is saved, but delivery is not finished yet.");else showGraphicMessage("!","Wallet approval cancelled","No payment was sent. "+safeMessage(e),RED);returnToMarketAfterWallet();}});}
        }},"TokenBuyReturn").start();
    }

    private void cancelUnreturnedTokenWalletHandoff(){
        if(!tokenWalletHandoff)return;tokenWalletHandoff=false;buyFlowBusy=false;String listing=pendingSecure(PENDING_BUY_LISTING);if(!listing.isEmpty())KintaraApi.releaseBuyReserve(getApplicationContext(),listing,true);clearPendingToken();showGraphicMessage("!","Wallet approval not completed","The wallet did not return a signed transaction. The listing hold was released and no payment was sent.",WARN);
    }

    private void recoverPendingTokenPurchase(){
        if(!hasPendingToken()){toast("No pending token purchase.");return;}if(buyFlowBusy)return;buyFlowBusy=true;
        final String quoteId=pendingSecure(PENDING_BUY_QUOTE),sig=pendingSecure(PENDING_BUY_SIGNATURE),signedTx=pendingSecure(PENDING_BUY_SIGNED_TX),listing=pendingSecure(PENDING_BUY_LISTING),item=pendingSecure(PENDING_BUY_ITEM),currency=pendingSecure(PENDING_BUY_CURRENCY);final int quantity=pendingQuantity();
        showPaymentProgress("Recovering purchase","");
        new Thread(new Runnable(){public void run(){KintaraApi.BuyResult r=null;Exception err=null;try{r=confirmSavedTokenPayment(quoteId,sig,signedTx,listing,true);}catch(Exception e){err=e;}final KintaraApi.BuyResult fr=r;final Exception fe=err;handler.post(new Runnable(){public void run(){buyFlowBusy=false;hidePaymentProgress();if(fe==null&&fr!=null&&fr.ok){clearPendingToken();afterPurchaseSuccess(item,currency,fr.quantity>0?fr.quantity:quantity);return;}String code=fr==null?"":fr.error;if(pendingNoCharge(code)){clearPendingToken();showGraphicMessage("!","Purchase not completed","No $KINS was transferred. You can try again.",RED);showMarket();return;}showPendingBuyDialog(friendlyPendingDetail(fr,fe));showMarket();}});}},"TokenBuyRecovery").start();
    }

    private String friendlyPendingDetail(KintaraApi.BuyResult r,Exception e){
        if(e!=null)return "The check could not finish. Your payment details are still safely saved.";
        if(r==null)return "Delivery is still pending. Your payment details are safely saved.";
        if(pendingPaidUndeliverable(r.error))return "Payment was received, but the item has not arrived yet. Keep this purchase for recovery.";
        if(pendingSignatureConflict(r.error))return "This purchase is still being matched with your history. Keep it saved and try recovery again later.";
        if(r.resultUnknown||r.networkError||"token_confirm_failed".equals(r.error)||"network_timeout".equals(r.error))return "Delivery is still pending. Do not buy again; try recovery later.";
        return userMessage(r.message,"Delivery is still pending. Do not buy again.");
    }

    private void showPendingBuyDialog(String detail){
        final Dialog d=new Dialog(this);d.requestWindowFeature(Window.FEATURE_NO_TITLE);d.setCancelable(true);
        LinearLayout c=new LinearLayout(this);c.setOrientation(LinearLayout.VERTICAL);c.setPadding(dp(22),dp(20),dp(22),dp(18));c.setBackground(outlineBg(CARD,20,WARN));
        SecurePulseView shield=new SecurePulseView(this);c.addView(shield,new LinearLayout.LayoutParams(ViewGroup.LayoutParams.MATCH_PARENT,dp(84)));TextView title=txt("Purchase pending",18,TEXT,true);title.setGravity(Gravity.CENTER);c.addView(title);TextView msg=txt((detail==null||detail.trim().isEmpty()?"Delivery is still pending.":detail)+"\n\nDo not buy this item again.",11,MUTED,false);msg.setGravity(Gravity.CENTER);c.addView(msg,lp(ViewGroup.LayoutParams.MATCH_PARENT,ViewGroup.LayoutParams.WRAP_CONTENT,0,8,0,15));Button recover=button("RECOVER PURCHASE",Color.rgb(180,126,34));c.addView(recover,new LinearLayout.LayoutParams(ViewGroup.LayoutParams.MATCH_PARENT,dp(48)));recover.setOnClickListener(new View.OnClickListener(){public void onClick(View v){d.dismiss();recoverPendingTokenPurchase();}});final String savedSig=pendingSecure(PENDING_BUY_SIGNATURE);if(!savedSig.isEmpty()){Button copy=outlineButton("COPY TRANSACTION ID",ACCENT);c.addView(copy,lp(ViewGroup.LayoutParams.MATCH_PARENT,dp(44),0,8,0,0));copy.setOnClickListener(new View.OnClickListener(){public void onClick(View v){ClipboardManager cm=(ClipboardManager)getSystemService(CLIPBOARD_SERVICE);if(cm!=null)cm.setPrimaryClip(ClipData.newPlainText("Kintara transaction ID",savedSig));toast("Transaction ID copied");}});}Button later=outlineButton("CHECK LATER",MUTED);c.addView(later,lp(ViewGroup.LayoutParams.MATCH_PARENT,dp(44),0,8,0,0));later.setOnClickListener(new View.OnClickListener(){public void onClick(View v){d.dismiss();}});d.setContentView(c);d.show();Window w=d.getWindow();if(w!=null){w.setBackgroundDrawable(new android.graphics.drawable.ColorDrawable(Color.TRANSPARENT));w.setDimAmount(.76f);w.addFlags(android.view.WindowManager.LayoutParams.FLAG_DIM_BEHIND);w.setLayout((int)(getResources().getDisplayMetrics().widthPixels*.9f),ViewGroup.LayoutParams.WRAP_CONTENT);}
    }

    private void returnToMarketAfterWallet(){hidePaymentProgress();if(root==null||body==null){if(!SecurePrefs.getCookie(this).isEmpty())enterApp();else showLogin();}else showMarket();}

    private void afterPurchaseSuccess(String itemType,String currency,int qty){
        buyFlowBusy=false;marketBoardCache.clear();marketBoardCacheKey="";inventoryFingerprint="";toast("Purchase complete"+(itemType==null||itemType.isEmpty()?"":" • "+KintaraApi.findItem(itemType).label)+" is in your inventory.");
        if(root==null||body==null)enterApp();
        if(itemType!=null&&!itemType.isEmpty())showMarketItemDetail(itemType,"gold".equals(currency)?"gold":"token");else showMarket();
    }
    private void refreshCurrentMarketItem(String itemType,String currency){if("market_detail".equals(currentPage)&&itemType!=null&&!itemType.isEmpty())showMarketItemDetail(itemType,currency);}

    private View marketListingRow(final KintaraApi.Listing x,final String currency,double floor,final String itemType){
        LinearLayout wrap=new LinearLayout(this);wrap.setOrientation(LinearLayout.VERTICAL);wrap.setPadding(dp(10),dp(9),dp(10),dp(9));wrap.setBackground(outlineBg(CARD2,12,BORDER));
        LinearLayout top=new LinearLayout(this);top.setGravity(Gravity.CENTER_VERTICAL);
        String delta="";if(Double.isFinite(floor)&&floor>0){double pct=(x.unitPrice()-floor)/floor*100;if(Math.abs(pct)<.5)delta=" • FLOOR";else delta=" • "+String.format(Locale.US,"%.1f%% above floor",pct);}
        long me=SecurePrefs.getWalletPlayerId(this);boolean mine=x.sellerName!=null&&!x.sellerName.isEmpty()&&x.sellerName.equalsIgnoreCase(SecurePrefs.getWalletPlayerName(this));boolean myHold=x.inCheckout()&&x.reservedBy!=null&&me>0&&x.reservedBy.longValue()==me;
        String held=x.inCheckout()?(myHold?" • YOUR CHECKOUT":" • IN CHECKOUT"):"";
        TextView left=txt("×"+x.quantity+(x.sellerName==null||x.sellerName.isEmpty()?"":" • "+x.sellerName)+delta+held,11,x.inCheckout()?WARN:TEXT,x.inCheckout());
        top.addView(left,new LinearLayout.LayoutParams(0,ViewGroup.LayoutParams.WRAP_CONTENT,1));
        TextView px=txt(fmtMarketPrice(x.totalPrice(),currency),12,ACCENT,true);px.setGravity(Gravity.RIGHT);top.addView(px,lp(dp(112),ViewGroup.LayoutParams.WRAP_CONTENT,8,0,0,0));wrap.addView(top);
        LinearLayout bottom=new LinearLayout(this);bottom.setGravity(Gravity.CENTER_VERTICAL);
        bottom.addView(txt(fmtMarketPrice(x.unitPrice(),currency)+" each",10,MUTED,false),new LinearLayout.LayoutParams(0,ViewGroup.LayoutParams.WRAP_CONTENT,1));
        Button buy=miniButton(mine?"YOUR LISTING":myHold?"YOUR HOLD":x.inCheckout()?"HELD":"BUY");buy.setEnabled(!mine&&!x.inCheckout()&&!buyFlowBusy);
        if(mine||x.inCheckout())buy.setAlpha(.55f);
        buy.setOnClickListener(new View.OnClickListener(){public void onClick(View v){beginPurchase(x,itemType,currency);}});
        bottom.addView(buy,lp(dp(104),dp(40),8,5,0,0));wrap.addView(bottom);return wrap;
    }

    private void addInlineSellPriceCheck(final LinearLayout out,final String itemType){
        final KintaraApi.Item item=KintaraApi.findItem(itemType);if(item==null)return;
        final LinearLayout shell=card();final Button menu=outlineButton("SELL / PRICE CHECK  ⌄",ACCENT);shell.addView(menu,new LinearLayout.LayoutParams(ViewGroup.LayoutParams.MATCH_PARENT,dp(48)));
        final LinearLayout panel=new LinearLayout(this);panel.setOrientation(LinearLayout.VERTICAL);panel.setVisibility(View.GONE);shell.addView(panel);out.addView(shell);
        final boolean[] built={false};
        menu.setOnClickListener(new View.OnClickListener(){public void onClick(View v){
            if(panel.getVisibility()==View.VISIBLE){panel.setVisibility(View.GONE);menu.setText("SELL / PRICE CHECK  ⌄");return;}
            panel.setVisibility(View.VISIBLE);menu.setText("SELL / PRICE CHECK  ⌃");if(built[0])return;built[0]=true;
            panel.addView(txt("Quantity",12,MUTED,true),lp(ViewGroup.LayoutParams.MATCH_PARENT,ViewGroup.LayoutParams.WRAP_CONTENT,0,10,0,0));
            final EditText qty=input("Quantity");qty.setInputType(InputType.TYPE_CLASS_NUMBER);qty.setText(String.valueOf(defaultQtyForItem(item)));panel.addView(qty,new LinearLayout.LayoutParams(ViewGroup.LayoutParams.MATCH_PARENT,dp(52)));
            panel.addView(txt("Single listing limit: "+listingQtyLimit+(listingQtyLimit>=10000?" (Club)":""),10,MUTED,false),lp(ViewGroup.LayoutParams.MATCH_PARENT,ViewGroup.LayoutParams.WRAP_CONTENT,0,5,0,0));
            Button check=button("CHECK",BLUE);panel.addView(check,lp(ViewGroup.LayoutParams.MATCH_PARENT,dp(52),0,10,0,0));
            final LinearLayout result=new LinearLayout(MainActivity.this);result.setOrientation(LinearLayout.VERTICAL);panel.addView(result);
            check.setOnClickListener(new View.OnClickListener(){public void onClick(View v){Integer q=readQty(qty,item);if(q==null)return;final int fq=q;async("Loading prices…",new Work<MarketData>(){public MarketData run()throws Exception{return loadMarketData(item,fq);}},new Done<MarketData>(){public void done(MarketData d,Exception e){if(e!=null){toast(safeMessage(e));return;}renderTradeResult(result,d,isStack100(item.type),false,false,false);}});}});
        }});
    }

    private View statTile(String key,String value,String sub,int color){LinearLayout x=new LinearLayout(this);x.setOrientation(LinearLayout.VERTICAL);x.setPadding(dp(10),dp(7),dp(10),dp(7));x.setBackground(outlineBg(CARD2,12,BORDER));x.addView(txt(key,9,MUTED,true));x.addView(txt(value,14,color,true));x.addView(txt(sub,9,MUTED,false));return x;}
    private String relativeTime(long ms){long d=System.currentTimeMillis()-ms;if(ms<=0||d<0)return"just now";long m=d/60000;if(m<1)return"just now";if(m<60)return m+"m ago";long h=m/60;if(h<24)return h+"h ago";return(h/24)+"d ago";}

    private Integer readQty(EditText qty,KintaraApi.Item it){int q;try{q=Integer.parseInt(qty.getText().toString());}catch(Exception e){toast("Invalid quantity");return null;}int min=1;if(q<min||q>listingQtyLimit){toast("Quantity must be "+min+"–"+listingQtyLimit);return null;}return q;}
    private void fillAllQuantity(final KintaraApi.Item it,final EditText qty){async("Reading stock…",new Work<KintaraApi.Stock>(){public KintaraApi.Stock run()throws Exception{return KintaraApi.getStock(getApplicationContext(),it.type);}},new Done<KintaraApi.Stock>(){public void done(KintaraApi.Stock st,Exception e){if(e!=null||st==null){toast("Could not read stock");return;}if(st.total<=0){toast("You do not have this item.");return;}int q=Math.min(st.total,listingQtyLimit);qty.setText(String.valueOf(q));if(st.total>listingQtyLimit)toast("ALL uses your "+listingQtyLimit+" item single-listing limit.");}});}

    static final class MarketData {KintaraApi.Item item;int qty;KintaraApi.Stock stock;KintaraApi.Quote quoteToken,quoteGold;KintaraApi.Stats stats;KintaraApi.MarketStats marketToken,marketGold;List<KintaraApi.Listing> listingsToken,listingsGold;}
    private MarketData loadMarketData(KintaraApi.Item it,int q)throws Exception{MarketData d=new MarketData();d.item=it;d.qty=q;try{d.stock=KintaraApi.getStock(this,it.type);}catch(Exception e){d.stock=null;}try{d.stats=KintaraApi.getStats(this,it.type);}catch(Exception ignored){}try{d.marketToken=KintaraApi.getItemMarket(this,it.type,"token");}catch(Exception ignored){}try{d.listingsToken=KintaraApi.getItemListings(this,it.type,"token");}catch(Exception ignored){}try{d.quoteToken=KintaraApi.smartSellQuote(d.marketToken,d.listingsToken,q,"token");}catch(Exception ignored){}try{if(!"gold".equals(it.type))d.marketGold=KintaraApi.getItemMarket(this,it.type,"gold");}catch(Exception ignored){}try{if(!"gold".equals(it.type))d.listingsGold=KintaraApi.getItemListings(this,it.type,"gold");}catch(Exception ignored){}try{if(!"gold".equals(it.type))d.quoteGold=KintaraApi.smartSellQuote(d.marketGold,d.listingsGold,q,"gold");}catch(Exception ignored){}return d;}

    private void renderTradeResult(final LinearLayout target,final MarketData d,boolean moltenNormalized){renderTradeResult(target,d,moltenNormalized,true,true,true);}
    private void renderTradeResult(final LinearLayout target,final MarketData d,boolean moltenNormalized,boolean showItemHeader,boolean showDetailButton){renderTradeResult(target,d,moltenNormalized,showItemHeader,showDetailButton,true);}
    private void renderTradeResult(final LinearLayout target,final MarketData d,boolean moltenNormalized,boolean showItemHeader,boolean showDetailButton,boolean allowSell){
        target.removeAllViews();LinearLayout c=card();target.addView(c);if(showItemHeader){LinearLayout itemHead=new LinearLayout(this);itemHead.setGravity(Gravity.CENTER_VERTICAL);itemHead.addView(itemImage(d.item.type,54),lp(dp(54),dp(54),0,0,12,0));LinearLayout itemText=new LinearLayout(this);itemText.setOrientation(LinearLayout.VERTICAL);itemText.addView(txt(d.item.label,19,TEXT,true));itemText.addView(txt(d.item.group,10,MUTED,false));itemHead.addView(itemText,new LinearLayout.LayoutParams(0,ViewGroup.LayoutParams.WRAP_CONTENT,1));c.addView(itemHead);}String stock=d.stock==null?"Stock unavailable":"Stock  •  Carry "+d.stock.carry+"  •  Bank "+d.stock.bank+"  •  Total "+d.stock.total;c.addView(txt(stock,12,MUTED,false),lp(ViewGroup.LayoutParams.MATCH_PARENT,ViewGroup.LayoutParams.WRAP_CONTENT,0,showItemHeader?7:0,0,10));
        addSaleReference(c,d.item.type,moltenNormalized?100:d.qty,d.stats,moltenNormalized);
        if(d.quoteToken==null&&d.quoteGold==null){c.addView(txt("No comparable live listing found in Gold or $KINS.",14,WARN,true));return;}
        if(d.quoteToken!=null)addCurrencySellBox(c,d.item,d.qty,d.quoteToken,d.marketToken,d.listingsToken,"token",allowSell);
        if(!"gold".equals(d.item.type)&&d.quoteGold!=null)addCurrencySellBox(c,d.item,d.qty,d.quoteGold,d.marketGold,d.listingsGold,"gold",allowSell);
        if(showDetailButton){Button detail=outlineButton("Open 30-day charts + market detail",ACCENT);c.addView(detail,lp(ViewGroup.LayoutParams.MATCH_PARENT,dp(46),0,12,0,0));detail.setOnClickListener(new View.OnClickListener(){public void onClick(View v){showMarketItemDetail(d.item.type,d.quoteToken!=null?"token":"gold");}});}
    }

    private void addCurrencySellBox(LinearLayout parent,final KintaraApi.Item item,final int qty,final KintaraApi.Quote q,final KintaraApi.MarketStats stats,final List<KintaraApi.Listing> visibleListings,final String currency,final boolean allowSell){
        LinearLayout sell=new LinearLayout(this);sell.setOrientation(LinearLayout.VERTICAL);sell.setPadding(dp(10),dp(10),dp(10),dp(10));sell.setBackground(outlineBg(CARD2,15,Color.rgb(67,78,92)));parent.addView(sell,lp(ViewGroup.LayoutParams.MATCH_PARENT,ViewGroup.LayoutParams.WRAP_CONTENT,0,12,0,0));
        String curLabel="token".equals(currency)?"$KINS":"GOLD";TextView head=txt((allowSell?"SELL FOR ":"PRICE CHECK • ")+curLabel,13,TEXT,true);head.setGravity(Gravity.CENTER);sell.addView(head,lp(ViewGroup.LayoutParams.MATCH_PARENT,dp(28),0,0,0,2));KintaraApi.Trend tr=stats==null?null:stats.trend;Double fl=stats==null?null:stats.floorFor(currency);String market=fl==null?"No floor available":"Floor "+fmtMarketPrice(fl,currency)+" / item  "+trendText(tr);sell.addView(txt(market,10,trendColor(tr),true),lp(ViewGroup.LayoutParams.MATCH_PARENT,ViewGroup.LayoutParams.WRAP_CONTENT,0,0,0,4));
        if(q.basis!=null&&!q.basis.isEmpty())sell.addView(txt("LIVE PRICE ENGINE • "+q.confidence+" confidence • "+q.basis,9,MUTED,true),lp(ViewGroup.LayoutParams.MATCH_PARENT,ViewGroup.LayoutParams.WRAP_CONTENT,0,0,0,6));
        addSellerIntelligence(sell,stats,visibleListings,currency,q.normalUnit,qty);
        LinearLayout row=new LinearLayout(this);sell.addView(row,new LinearLayout.LayoutParams(ViewGroup.LayoutParams.MATCH_PARENT,ViewGroup.LayoutParams.WRAP_CONTENT));
        View.OnClickListener fastClick=allowSell?new View.OnClickListener(){public void onClick(View v){confirmSell(item,qty,q.fast,currency);}}:null;
        View.OnClickListener normalClick=allowSell?new View.OnClickListener(){public void onClick(View v){confirmSell(item,qty,q.normal,currency);}}:null;
        View.OnClickListener profitClick=allowSell?new View.OnClickListener(){public void onClick(View v){confirmSell(item,qty,q.profit,currency);}}:null;
        row.addView(priceTile("FAST",q.fast,ACCENT,"Quick sell",currency,fastClick),weighted(0,dp(92),2,0,4,0,1));
        row.addView(priceTile("BALANCE",q.normal,BLUE,"Recommended",currency,normalClick),weighted(0,dp(92),4,0,4,0,1));
        row.addView(priceTile("PROFIT",q.profit,PURPLE,"Higher ask",currency,profitClick),weighted(0,dp(92),4,0,2,0,1));
        LinearLayout comp=new LinearLayout(this);comp.setOrientation(LinearLayout.VERTICAL);comp.setPadding(dp(8),dp(6),dp(8),dp(4));comp.setBackground(outlineBg(BG,11,BORDER));comp.addView(txt("VISIBLE COMPETITION AT YOUR SELL PRICE",9,MUTED,true));comp.addView(txt("FAST  •  "+competitionText(visibleListings,currency,q.fastUnit),10,ACCENT,false),lp(ViewGroup.LayoutParams.MATCH_PARENT,ViewGroup.LayoutParams.WRAP_CONTENT,0,3,0,0));comp.addView(txt("BALANCE  •  "+competitionText(visibleListings,currency,q.normalUnit),10,BLUE,false),lp(ViewGroup.LayoutParams.MATCH_PARENT,ViewGroup.LayoutParams.WRAP_CONTENT,0,2,0,0));comp.addView(txt("PROFIT  •  "+competitionText(visibleListings,currency,q.profitUnit),10,PURPLE,false),lp(ViewGroup.LayoutParams.MATCH_PARENT,ViewGroup.LayoutParams.WRAP_CONTENT,0,2,0,0));sell.addView(comp,lp(ViewGroup.LayoutParams.MATCH_PARENT,ViewGroup.LayoutParams.WRAP_CONTENT,0,8,0,0));
        if(fl!=null&&fl>0){final double floorTotal="gold".equals(currency)?Math.ceil(fl*qty):Math.round(fl*qty*100.0)/100.0;if(allowSell){Button match=outlineButton("Match floor  •  "+formatTotal(floorTotal,currency),WARN);sell.addView(match,lp(ViewGroup.LayoutParams.MATCH_PARENT,dp(44),0,8,0,0));match.setOnClickListener(new View.OnClickListener(){public void onClick(View v){confirmSell(item,qty,floorTotal,currency);}});}else{LinearLayout floorInfo=new LinearLayout(this);floorInfo.setOrientation(LinearLayout.VERTICAL);floorInfo.setPadding(dp(9),dp(8),dp(9),dp(8));floorInfo.setBackground(outlineBg(BG,11,BORDER));floorInfo.addView(txt("MATCH-FLOOR REFERENCE",9,MUTED,true));floorInfo.addView(txt(formatTotal(floorTotal,currency)+" total for "+qty+"x",12,WARN,true),lp(ViewGroup.LayoutParams.MATCH_PARENT,ViewGroup.LayoutParams.WRAP_CONTENT,0,3,0,0));sell.addView(floorInfo,lp(ViewGroup.LayoutParams.MATCH_PARENT,ViewGroup.LayoutParams.WRAP_CONTENT,0,8,0,0));}}
        if(allowSell){final EditText custom=input("Custom TOTAL price in "+curLabel);custom.setInputType(InputType.TYPE_CLASS_NUMBER|("token".equals(currency)?InputType.TYPE_NUMBER_FLAG_DECIMAL:0));sell.addView(custom,lp(ViewGroup.LayoutParams.MATCH_PARENT,dp(48),0,8,0,0));Button customBtn=outlineButton("Sell custom price",MUTED);sell.addView(customBtn,lp(ViewGroup.LayoutParams.MATCH_PARENT,dp(46),0,7,0,0));customBtn.setOnClickListener(new View.OnClickListener(){public void onClick(View v){try{double p=Double.parseDouble(custom.getText().toString());if(p<=0)throw new Exception();if("gold".equals(currency))p=Math.max(1,Math.round(p));confirmSell(item,qty,p,currency);}catch(Exception e){toast("Enter a valid total price");}}});}else{sell.addView(txt("Read-only price check • create listings from Inventory.",9,MUTED,false),lp(ViewGroup.LayoutParams.MATCH_PARENT,ViewGroup.LayoutParams.WRAP_CONTENT,0,8,0,0));}
    }
    private void addSellerIntelligence(LinearLayout parent,KintaraApi.MarketStats stats,List<KintaraApi.Listing> listings,String currency,double selectedUnit,int qty){KintaraApi.SellerIntel z=KintaraApi.sellerIntel(stats,listings,currency,selectedUnit);LinearLayout intel=new LinearLayout(this);intel.setOrientation(LinearLayout.VERTICAL);intel.setPadding(dp(9),dp(8),dp(9),dp(8));intel.setBackground(outlineBg(Color.rgb(12,28,35),12,Color.rgb(41,91,105)));LinearLayout h=new LinearLayout(this);h.setGravity(Gravity.CENTER_VERTICAL);h.addView(txt("SELLER INTELLIGENCE",10,ACCENT,true),new LinearLayout.LayoutParams(0,ViewGroup.LayoutParams.WRAP_CONTENT,1));h.addView(txt(z.sellSignal,9,sellerPressureColor(z.pressure),true));intel.addView(h);String demand=z.units24h>0?(z.units24h+" completed units / 24h"+(z.sales24h>0?" • "+z.sales24h+" sales":"")):(z.sales24h>0?z.sales24h+" completed sales / 24h":"no completed sales in 24h");intel.addView(txt("Demand "+z.liquidity+"  •  "+demand,10,TEXT,false),lp(ViewGroup.LayoutParams.MATCH_PARENT,ViewGroup.LayoutParams.WRAP_CONTENT,0,4,0,0));String supply="Sell supply "+z.marketAvailable+" units  •  "+z.pressure;if(z.units24h>0)supply+="  •  cover "+formatHours(z.supplyCoverHours);intel.addView(txt(supply,10,MUTED,false),lp(ViewGroup.LayoutParams.MATCH_PARENT,ViewGroup.LayoutParams.WRAP_CONTENT,0,2,0,0));if(z.floorUnit>0)intel.addView(txt("Visible floor depth: "+z.floorUnits+" units in "+z.floorListings+" listing"+(z.floorListings==1?"":"s")+(z.units24h>0&&z.floorUnits>0?"  •  rough cover "+formatHours(z.floorClearHours):""),10,MUTED,false),lp(ViewGroup.LayoutParams.MATCH_PARENT,ViewGroup.LayoutParams.WRAP_CONTENT,0,2,0,0));if(z.lastSaleUnit!=null&&z.floorUnit>0)intel.addView(txt("Last completed sale vs current floor: "+signedPct(z.lastSaleVsFloorPct),10,MUTED,false),lp(ViewGroup.LayoutParams.MATCH_PARENT,ViewGroup.LayoutParams.WRAP_CONTENT,0,2,0,0));intel.addView(txt("30d traded days: "+z.tradedDays+(stats!=null&&stats.trend!=null?"  •  momentum "+trendText(stats.trend):""),10,MUTED,false),lp(ViewGroup.LayoutParams.MATCH_PARENT,ViewGroup.LayoutParams.WRAP_CONTENT,0,2,0,0));intel.addView(txt("Current listings are supply/competition. Demand signals come from completed-sale data; Buy actions are available only on eligible current listings above.",9,MUTED,false),lp(ViewGroup.LayoutParams.MATCH_PARENT,ViewGroup.LayoutParams.WRAP_CONTENT,0,4,0,0));parent.addView(intel,lp(ViewGroup.LayoutParams.MATCH_PARENT,ViewGroup.LayoutParams.WRAP_CONTENT,0,2,0,8));}
    private int sellerPressureColor(String p){if("TIGHT SUPPLY".equals(p))return ACCENT;if("BALANCED".equals(p))return BLUE;if("COMPETITIVE".equals(p))return WARN;if("HEAVY SUPPLY".equals(p)||"LOW LIQUIDITY".equals(p))return RED;return MUTED;}
    private String formatHours(double h){if(!(h>0)||Double.isInfinite(h)||Double.isNaN(h))return "—";if(h<1)return String.format(Locale.US,"%.0fm",h*60.0);if(h<48)return String.format(Locale.US,"%.1fh",h);return String.format(Locale.US,"%.1fd",h/24.0);}
    private String signedPct(double p){if(Double.isNaN(p)||Double.isInfinite(p))return "—";if(Math.abs(p)<0.05)return "≈ 0%";return String.format(Locale.US,"%+.1f%%",p);}

    private String competitionText(List<KintaraApi.Listing> rows,String currency,double unit){int listings=0,units=0;if(rows!=null)for(KintaraApi.Listing x:rows){if(x==null||!currency.equals(x.currency))continue;double u=x.unitPrice();if(u>0&&u<unit-1e-9){listings++;units+=Math.max(1,x.quantity);}}return units+" cheaper units in "+listings+" listing"+(listings==1?"":"s");}

    private LinearLayout.LayoutParams weighted(int w,int h,int l,int t,int r,int b,float weight){LinearLayout.LayoutParams p=lp(w,h,l,t,r,b);p.weight=weight;return p;}
    private String formatTotal(double price,String currency){return "token".equals(currency)?money(price):String.format(Locale.US,"%,.0f Gold",price);}
    private View priceTile(String label,double price,int color,String sub,String currency,View.OnClickListener click){LinearLayout x=new LinearLayout(this);x.setOrientation(LinearLayout.VERTICAL);x.setGravity(Gravity.CENTER);x.setPadding(dp(4),dp(6),dp(4),dp(6));x.setBackground(outlineBg(BG,12,color));TextView l=txt(label,11,color,true);l.setGravity(Gravity.CENTER);x.addView(l);TextView p=txt(formatTotal(price,currency),15,TEXT,true);p.setGravity(Gravity.CENTER);x.addView(p,lp(ViewGroup.LayoutParams.MATCH_PARENT,ViewGroup.LayoutParams.WRAP_CONTENT,0,3,0,0));TextView s=txt(sub,9,MUTED,false);s.setGravity(Gravity.CENTER);x.addView(s,lp(ViewGroup.LayoutParams.MATCH_PARENT,ViewGroup.LayoutParams.WRAP_CONTENT,0,3,0,0));if(click!=null)x.setOnClickListener(click);return x;}

    private void addSaleReference(LinearLayout c,String item,int qty,KintaraApi.Stats stats,boolean moltenNormalized){
        int target=moltenNormalized?100:qty;HistoryStore.SaleRef r=HistoryStore.saleRef(this,item,target);if(r!=null&&r.available){String name=r.exactSingle?"LAST SOLD":"RECENT SOLD AVG ("+r.newSales+" sales)";c.addView(txt(name+"  "+money(r.normalizedTotal)+" for "+target+"x  • "+age(System.currentTimeMillis()-r.ts)+" ago",12,ACCENT,true),lp(ViewGroup.LayoutParams.MATCH_PARENT,ViewGroup.LayoutParams.WRAP_CONTENT,0,6,0,0));}
        if(stats!=null&&stats.ok){KintaraApi.Sample today=stats.sampleFor(utcDay());if(today!=null&&today.avgUnitPrice!=null)c.addView(txt("TODAY AVG  "+money(today.avgUnitPrice*target)+" for "+target+"x  • sales="+today.sales,12,MUTED,false));if(stats.avg30d!=null)c.addView(txt("30D AVG  "+money(stats.avg30d*target)+" for "+target+"x",12,MUTED,false));}
    }

    private void confirmSell(final KintaraApi.Item item,final int qty,final double price,final String currency){showBrandedConfirm("Create listing?",qty+"x "+item.label+"\nTotal price: "+formatTotal(price,currency)+"\nCurrency: "+("token".equals(currency)?"$KINS":"Gold")+"\n\nIf stock is in bank, the required amount will be moved to carry first.","SELL","CANCEL",new View.OnClickListener(){public void onClick(View v){doSell(item,qty,price,currency,false);}});}
    private void doSell(final KintaraApi.Item item,final int qty,final double price,final String currency,final boolean acceptLow){if(gameSession==null||!gameSession.isReady()){if(gameSession!=null)gameSession.retry();showPresenceRequired();return;}async("Creating listing…",new Work<KintaraApi.SellResult>(){public KintaraApi.SellResult run(){return KintaraApi.sell(getApplicationContext(),item.type,qty,price,currency,acceptLow);}},new Done<KintaraApi.SellResult>(){public void done(final KintaraApi.SellResult r,Exception e){if(e!=null){toast(safeMessage(e));return;}if(r.ok){toast("Listed "+qty+"x "+item.label+" at "+formatTotal(price,currency));syncActiveListings();if("inventory_trade".equals(currentPage))showInventory();return;}if("confirm_low_price".equals(r.error)&&!acceptLow&&"token".equals(currency)){String extra=r.medianTotal==null?"":"\nTypical total: "+money(r.medianTotal);showBrandedConfirm("Low price protection","This price looks unusually low."+extra+"\n\nList anyway?","LIST ANYWAY","CANCEL",new View.OnClickListener(){public void onClick(View v){doSell(item,qty,price,currency,true);}});}else showBrandedConfirm("Listing failed",userMessage(r.message,"Could not create the listing. Please try again."),"OK",null,null);}});}

    private void showInventory(){
        stopHistoryHoldTick();
        currentPage="inventory";clearBody();refreshBottomNav();pageTitle("Inventory","Carry + bank stock. Search an item or tap it to price-check and sell it.");

        LinearLayout searchCard=card();searchCard.setBackground(outlineBg(CARD,16,BORDER));
        inventorySearch=input("Search item…");inventorySearch.setSingleLine(true);searchCard.addView(inventorySearch,new LinearLayout.LayoutParams(ViewGroup.LayoutParams.MATCH_PARENT,dp(50)));body.addView(searchCard);
        inventorySearch.addTextChangedListener(new TextWatcher(){public void beforeTextChanged(CharSequence x,int st,int c,int a){}public void onTextChanged(CharSequence x,int st,int before,int count){renderInventoryFiltered(x==null?"":x.toString());}public void afterTextChanged(Editable e){}});

        inventoryList=new LinearLayout(this);inventoryList.setOrientation(LinearLayout.VERTICAL);body.addView(inventoryList);
        latestInventoryEntries.clear(); latestInventoryEntries.addAll(InventoryCacheStore.load(this)); inventoryFingerprint=inventoryFingerprint(latestInventoryEntries); if(!latestInventoryEntries.isEmpty())renderInventoryFiltered("");
        startInventoryLive(true);
    }

    private void startInventoryLive(boolean showLoading){
        if(inventoryPoll!=null)handler.removeCallbacks(inventoryPoll);inventoryPoll=null;inventorySyncing=false;inventoryFingerprint="";syncInventoryLive(showLoading,true);inventoryPoll=new Runnable(){public void run(){if(!"inventory".equals(currentPage))return;syncInventoryLive(false,false);handler.postDelayed(this,2500);}};handler.postDelayed(inventoryPoll,2500);
    }
    private void stopInventoryLive(){if(inventoryPoll!=null)handler.removeCallbacks(inventoryPoll);inventoryPoll=null;inventorySyncing=false;inventoryList=null;inventorySearch=null;}
    private String inventoryFingerprint(List<KintaraApi.InventoryEntry> entries){StringBuilder b=new StringBuilder();if(entries!=null)for(KintaraApi.InventoryEntry e:entries)b.append(e.item.type).append(':').append(e.stock.carry).append(':').append(e.stock.bank).append(';');return b.toString();}
    private void syncInventoryLive(final boolean showLoading,final boolean force){
        if(inventorySyncing||inventoryList==null||SecurePrefs.getCookie(this).isEmpty())return;final String walletAtRequest=SecurePrefs.getWalletPublicKey(this)==null?"":SecurePrefs.getWalletPublicKey(this);inventorySyncing=true;if(showLoading&&inventoryList.getChildCount()==0){LinearLayout loading=card();loading.addView(txt("Loading inventory…",13,MUTED,false));inventoryList.addView(loading);}new Thread(new Runnable(){public void run(){List<KintaraApi.InventoryEntry> rows=null;Exception err=null;try{rows=KintaraApi.getInventory(getApplicationContext());}catch(Exception e){err=e;}final List<KintaraApi.InventoryEntry> result=rows;final Exception error=err;handler.post(new Runnable(){public void run(){inventorySyncing=false;String currentWallet=SecurePrefs.getWalletPublicKey(MainActivity.this);if(!"inventory".equals(currentPage)||inventoryList==null||!walletAtRequest.equals(currentWallet==null?"":currentWallet))return;if(error!=null){if(inventoryList.getChildCount()==0){LinearLayout x=card();x.addView(txt("Could not load inventory. Please try again.",12,RED,true));inventoryList.addView(x);}return;}InventoryCacheStore.save(getApplicationContext(),result);String fp=inventoryFingerprint(result);if(showLoading||force||!fp.equals(inventoryFingerprint)){inventoryFingerprint=fp;latestInventoryEntries.clear();if(result!=null)latestInventoryEntries.addAll(result);renderInventoryFiltered(inventorySearch==null?"":inventorySearch.getText().toString());}}});}} ,"LiveInventory").start();
    }
    private void renderInventoryFiltered(String query){
        if(inventoryList==null)return;String q=query==null?"":query.trim().toLowerCase(Locale.US);List<KintaraApi.InventoryEntry> filtered=new ArrayList<KintaraApi.InventoryEntry>();for(KintaraApi.InventoryEntry e:latestInventoryEntries){String label=e.item.label==null?"":e.item.label.toLowerCase(Locale.US);String type=e.item.type==null?"":e.item.type.toLowerCase(Locale.US);String group=e.item.group==null?"":e.item.group.toLowerCase(Locale.US);if(q.isEmpty()||label.contains(q)||type.contains(q)||group.contains(q))filtered.add(e);}renderInventoryList(filtered,q);
    }
    private void renderInventoryList(List<KintaraApi.InventoryEntry> entries,String query){
        if(inventoryList==null)return;inventoryList.removeAllViews();if(entries==null||entries.isEmpty()){LinearLayout x=card();x.addView(txt(query==null||query.isEmpty()?"No sellable inventory items were found.":"No inventory item matches “"+query+"”.",13,MUTED,false));inventoryList.addView(x);return;}String lastGroup="";for(final KintaraApi.InventoryEntry entry:entries){if(!entry.item.group.equals(lastGroup)){TextView gh=txt(entry.item.group.isEmpty()?"Other":entry.item.group,12,MUTED,true);inventoryList.addView(gh,lp(ViewGroup.LayoutParams.MATCH_PARENT,ViewGroup.LayoutParams.WRAP_CONTENT,18,12,18,2));lastGroup=entry.item.group;}LinearLayout row=card();row.setPadding(dp(12),dp(11),dp(12),dp(11));row.setBackground(outlineBg(CARD,16,BORDER));LinearLayout rr=new LinearLayout(MainActivity.this);rr.setGravity(Gravity.CENTER_VERTICAL);rr.addView(itemImage(entry.item.type,52),lp(dp(52),dp(52),0,0,12,0));LinearLayout info=new LinearLayout(MainActivity.this);info.setOrientation(LinearLayout.VERTICAL);info.addView(txt(entry.item.label,15,TEXT,true));info.addView(txt("Carry "+entry.stock.carry+"  •  Bank "+entry.stock.bank+"  •  Total "+entry.stock.total,11,MUTED,false),lp(ViewGroup.LayoutParams.MATCH_PARENT,ViewGroup.LayoutParams.WRAP_CONTENT,0,4,0,0));rr.addView(info,new LinearLayout.LayoutParams(0,ViewGroup.LayoutParams.WRAP_CONTENT,1));TextView chevron=txt("›",24,ACCENT,false);chevron.setGravity(Gravity.CENTER);rr.addView(chevron,lp(dp(24),dp(36),8,0,0,0));row.addView(rr);row.setOnClickListener(new View.OnClickListener(){public void onClick(View v){showInventoryTrade(entry);}});inventoryList.addView(row);}}

    private void showInventoryTrade(final KintaraApi.InventoryEntry entry){
        stopInventoryLive();stopHistoryHoldTick();
        currentTradeEntry=entry;tradePriceSyncing=false;if(tradePriceDebounce!=null)handler.removeCallbacks(tradePriceDebounce);tradePriceDebounce=null;
        currentPage="inventory_trade";clearBody();refreshBottomNav();pageTitle(entry.item.label,"Inventory market flow • live FAST / BALANCE / PROFIT pricing.");
        LinearLayout c=card();body.addView(c);Button back=outlineButton("‹ Back to Inventory",MUTED);c.addView(back,lp(ViewGroup.LayoutParams.MATCH_PARENT,dp(42),0,0,0,10));back.setOnClickListener(new View.OnClickListener(){public void onClick(View v){showInventory();}});LinearLayout hero=new LinearLayout(this);hero.setGravity(Gravity.CENTER_VERTICAL);hero.addView(itemImage(entry.item.type,58),lp(dp(58),dp(58),0,0,12,0));LinearLayout heroText=new LinearLayout(this);heroText.setOrientation(LinearLayout.VERTICAL);heroText.addView(txt(entry.item.label,17,TEXT,true));heroText.addView(txt("Carry "+entry.stock.carry+"  •  Bank "+entry.stock.bank+"  •  Total "+entry.stock.total,11,MUTED,false));hero.addView(heroText,new LinearLayout.LayoutParams(0,ViewGroup.LayoutParams.WRAP_CONTENT,1));c.addView(hero);
        c.addView(txt("Quantity",12,MUTED,true),lp(ViewGroup.LayoutParams.MATCH_PARENT,ViewGroup.LayoutParams.WRAP_CONTENT,0,10,0,0));LinearLayout qrow=new LinearLayout(this);final EditText qty=input("Quantity");currentTradeQtyInput=qty;qty.setInputType(InputType.TYPE_CLASS_NUMBER);int def=Math.min(entry.stock.total,listingQtyLimit);qty.setText(String.valueOf(Math.max(1,def)));qrow.addView(qty,new LinearLayout.LayoutParams(0,dp(52),1));Button all=miniButton("ALL");qrow.addView(all,lp(dp(68),dp(52),8,0,0,0));c.addView(qrow);currentTradeResult=new LinearLayout(this);currentTradeResult.setOrientation(LinearLayout.VERTICAL);body.addView(currentTradeResult);
        all.setOnClickListener(new View.OnClickListener(){public void onClick(View v){int q=Math.min(entry.stock.total,listingQtyLimit);qty.setText(String.valueOf(q));if(entry.stock.total>listingQtyLimit)toast("ALL uses your "+listingQtyLimit+" item single-listing limit.");}});
        qty.addTextChangedListener(new TextWatcher(){public void beforeTextChanged(CharSequence x,int st,int c,int a){}public void onTextChanged(CharSequence x,int st,int before,int count){scheduleTradePriceRefresh();}public void afterTextChanged(Editable e){}});
        handler.postDelayed(new Runnable(){public void run(){refreshInventoryTradePrice(false);}},220);
    }
    private void scheduleTradePriceRefresh(){if(!"inventory_trade".equals(currentPage))return;tradeRequestSerial++;if(currentTradeResult!=null)currentTradeResult.removeAllViews();if(tradePriceDebounce!=null)handler.removeCallbacks(tradePriceDebounce);tradePriceDebounce=new Runnable(){public void run(){refreshInventoryTradePrice(false);}};handler.postDelayed(tradePriceDebounce,280);}
    private void refreshInventoryTradePrice(final boolean force){
        if(!"inventory_trade".equals(currentPage)||currentTradeEntry==null||currentTradeQtyInput==null||currentTradeResult==null||tradePriceSyncing)return;
        Integer q=readQty(currentTradeQtyInput,currentTradeEntry.item);if(q==null){currentTradeResult.removeAllViews();return;} final int fq=q; final int request=++tradeRequestSerial; final KintaraApi.Item itemAtRequest=currentTradeEntry.item; tradePriceSyncing=true;
        if(currentTradeResult.getChildCount()==0){LinearLayout loading=card();loading.addView(txt("Loading prices…",13,MUTED,false));currentTradeResult.addView(loading);}
        new Thread(new Runnable(){public void run(){MarketData data=null;Exception err=null;try{data=loadMarketData(itemAtRequest,fq);}catch(Exception e){err=e;}final MarketData d=data;final Exception error=err;handler.post(new Runnable(){public void run(){tradePriceSyncing=false;if(request!=tradeRequestSerial){if("inventory_trade".equals(currentPage))refreshInventoryTradePrice(false);return;}if(!"inventory_trade".equals(currentPage)||currentTradeResult==null||currentTradeEntry==null||!itemAtRequest.type.equals(currentTradeEntry.item.type))return;currentTradeResult.removeAllViews();if(error!=null){LinearLayout x=card();x.addView(txt("Could not load prices. Please try again.",12,RED,true));currentTradeResult.addView(x);return;}renderTradeResult(currentTradeResult,d,isStack100(itemAtRequest.type));}});}} ,"LiveTradePrice").start();
    }

    private void showTrends(){
        stopInventoryLive();stopHistoryHoldTick();
        currentPage="trends";clearBody();refreshBottomNav();pageTitle("Market Trends","Live seller ranking + local high-frequency history + official 30-day Gold / $KINS charts.");
        if(!isPremium()){showTrendsPremiumLock();return;}
        LinearLayout live=card();body.addView(live);live.addView(txt("LIVE SELLER PICKS",16,TEXT,true));live.addView(txt("Best overall selling opportunity first, then the fastest market by completed buyer activity. Scores combine completed 24h demand, sell supply, floor strength and 30-day momentum. Data refreshes silently in the background.",11,MUTED,false),lp(ViewGroup.LayoutParams.MATCH_PARENT,ViewGroup.LayoutParams.WRAP_CONTENT,0,4,0,8));trendScanOut=new LinearLayout(this);trendScanOut.setOrientation(LinearLayout.VERTICAL);live.addView(trendScanOut);scanSellerOpportunitiesFast(trendScanOut,false);
        LinearLayout controls=card();body.addView(controls);TextView path=txt("Collector: foreground ≈60s • Android background schedule ≈15m\nLocal storage: Gold + Molten + Brute Horn • 48h • official charts: 30 days",12,MUTED,false);controls.addView(path);
        trendItem("Gold","gold",1);trendItem("Molten Rock","molten_rock",100);trendItem("Brute Horn","brute_horn",100);
        updateCollectorStatus();
    }

    private void refreshTrendsInPlace(){
        if(!"trends".equals(currentPage)||trendScanOut==null)return;
        scanSellerOpportunitiesFast(trendScanOut,true);
    }

    private void showTrendsPremiumLock(){
        LinearLayout lock=card();lock.setPadding(dp(16),dp(16),dp(16),dp(16));GradientDrawable panel=new GradientDrawable(GradientDrawable.Orientation.TL_BR,new int[]{Color.rgb(10,51,43),Color.rgb(9,27,29),Color.rgb(20,21,34)});panel.setCornerRadius(dp(22));panel.setStroke(dp(1),Color.rgb(48,181,133));lock.setBackground(panel);
        LinearLayout top=new LinearLayout(this);top.setGravity(Gravity.CENTER_VERTICAL);ImageView icon=new ImageView(this);icon.setImageResource(drawableId("app_icon_v172"));icon.setScaleType(ImageView.ScaleType.CENTER_CROP);top.addView(icon,lp(dp(72),dp(72),0,0,13,0));LinearLayout copy=new LinearLayout(this);copy.setOrientation(LinearLayout.VERTICAL);copy.addView(txt("MARKET TRENDS",19,TEXT,true));copy.addView(txt("PREMIUM ACCESS",10,ACCENT,true),lp(ViewGroup.LayoutParams.MATCH_PARENT,ViewGroup.LayoutParams.WRAP_CONTENT,0,3,0,0));copy.addView(txt("Seller opportunity ranking, verified market charts, and locally collected signals.",10,MUTED,false),lp(ViewGroup.LayoutParams.MATCH_PARENT,ViewGroup.LayoutParams.WRAP_CONTENT,0,7,0,0));top.addView(copy,new LinearLayout.LayoutParams(0,ViewGroup.LayoutParams.WRAP_CONTENT,1));lock.addView(top);
        LinearLayout facts=new LinearLayout(this);facts.setOrientation(LinearLayout.HORIZONTAL);facts.addView(premiumFact("WEEKLY","3.99 USDC",PURPLE),weighted(0,dp(66),0,11,4,0,1));facts.addView(premiumFact("MONTHLY","9.99 USDC",ACCENT),weighted(0,dp(66),4,11,0,0,1));lock.addView(facts);
        Button unlock=button("VIEW PREMIUM ACCESS",Color.rgb(26,139,94));lock.addView(unlock,new LinearLayout.LayoutParams(ViewGroup.LayoutParams.MATCH_PARENT,dp(50)));unlock.setOnClickListener(new View.OnClickListener(){public void onClick(View v){showPremiumPaywall("Market Trends requires Premium access.");}});body.addView(lock);
    }

    private void trendItem(final String label,final String item,int qty){
        final String walletAtRequest=SecurePrefs.getWalletPublicKey(this);
        final LinearLayout c=card();body.addView(c);LinearLayout th=new LinearLayout(this);th.setGravity(Gravity.CENTER_VERTICAL);th.addView(itemImage(item,46),lp(dp(46),dp(46),0,0,11,0));LinearLayout tt=new LinearLayout(this);tt.setOrientation(LinearLayout.VERTICAL);tt.addView(txt(label,18,TEXT,true));tt.addView(txt("local normalized "+qty+"x • official 30-day market",10,MUTED,false));th.addView(tt,new LinearLayout.LayoutParams(0,ViewGroup.LayoutParams.WRAP_CONTENT,1));c.addView(th);
        JSONObject latest=HistoryStore.latestItem(this,item);if(latest!=null){JSONObject l=latest.optJSONObject("live");String now=l==null?"Live quote: —":"Now  FAST "+money(l.optDouble("fast"))+"  • BALANCE "+money(l.optDouble("normal"))+"  • PROFIT "+money(l.optDouble("profit"));c.addView(txt(now,12,MUTED,false),lp(ViewGroup.LayoutParams.MATCH_PARENT,ViewGroup.LayoutParams.WRAP_CONTENT,0,5,0,6));c.addView(txt("Today completed sales: "+latest.optInt("sales",0),12,ACCENT,true));}
        for(int h:new int[]{1,12,24}){HistoryStore.WindowSummary w=HistoryStore.window(this,item,h);LinearLayout r=new LinearLayout(this);r.setOrientation(LinearLayout.VERTICAL);r.setPadding(dp(12),dp(10),dp(12),dp(10));r.setBackground(bg(CARD2,12));c.addView(r,lp(ViewGroup.LayoutParams.MATCH_PARENT,ViewGroup.LayoutParams.WRAP_CONTENT,0,8,0,0));r.addView(txt(h+"h",14,TEXT,true));if(!w.available){r.addView(txt("Collecting local history…",12,MUTED,false));}else{r.addView(txt("Completed sales: "+w.completedSales+"  • span "+age(w.actualMs),12,ACCENT,true));r.addView(txt("FAST  "+money(w.fastStart)+" → "+money(w.fastEnd),11,MUTED,false));r.addView(txt("BALANCE  "+money(w.normalStart)+" → "+money(w.normalEnd),11,MUTED,false));r.addView(txt("PROFIT  "+money(w.profitStart)+" → "+money(w.profitEnd),11,MUTED,false));}}
        HistoryStore.SaleRef sr=HistoryStore.saleRef(this,item,qty);if(sr!=null)c.addView(txt((sr.exactSingle?"Last sold":"Recent sold avg")+": "+money(sr.normalizedTotal)+" for "+qty+"x • "+age(System.currentTimeMillis()-sr.ts)+" ago",11,WARN,true),lp(ViewGroup.LayoutParams.MATCH_PARENT,ViewGroup.LayoutParams.WRAP_CONTENT,0,10,0,0));
        final LinearLayout charts=new LinearLayout(this);charts.setOrientation(LinearLayout.VERTICAL);charts.addView(txt("Loading official charts…",10,MUTED,false));c.addView(charts,lp(ViewGroup.LayoutParams.MATCH_PARENT,ViewGroup.LayoutParams.WRAP_CONTENT,0,10,0,0));
        KintaraApi.MarketStats cachedToken=MarketCacheStore.loadStats(this,item,"token"),cachedGold=MarketCacheStore.loadStats(this,item,"gold"); if(cachedToken!=null||cachedGold!=null){charts.removeAllViews();addOfficialTrendChart(charts,"$KINS",cachedToken,true);if(!"gold".equals(item))addOfficialTrendChart(charts,"Gold",cachedGold,false);}
        new Thread(new Runnable(){public void run(){KintaraApi.MarketStats token=null,gold=null;KintaraApi.MarketStatsTask tt=KintaraApi.loadStatsTask(getApplicationContext(),item,"token");if(tt!=null)token=tt.stats;if(!"gold".equals(item)){KintaraApi.MarketStatsTask gg=KintaraApi.loadStatsTask(getApplicationContext(),item,"gold");if(gg!=null)gold=gg.stats;}final KintaraApi.MarketStats ft=token,fg=gold;handler.post(new Runnable(){public void run(){String currentWallet=SecurePrefs.getWalletPublicKey(MainActivity.this);if(!"trends".equals(currentPage)||!walletAtRequest.equals(currentWallet))return;charts.removeAllViews();addOfficialTrendChart(charts,"$KINS",ft,true);if(!"gold".equals(item))addOfficialTrendChart(charts,"Gold",fg,false);}});}},"OfficialTrend").start();
    }

    private void addOfficialTrendChart(LinearLayout host,String label,KintaraApi.MarketStats s,boolean token){if(s==null||!s.ok)return;LinearLayout box=new LinearLayout(this);box.setOrientation(LinearLayout.VERTICAL);box.setPadding(dp(9),dp(8),dp(9),dp(8));box.setBackground(outlineBg(CARD2,12,BORDER));LinearLayout h=new LinearLayout(this);h.setGravity(Gravity.CENTER_VERTICAL);h.addView(txt(label+" • 30 days",11,TEXT,true),new LinearLayout.LayoutParams(0,ViewGroup.LayoutParams.WRAP_CONTENT,1));h.addView(txt(trendText(s.trend),10,trendColor(s.trend),true));box.addView(h);MarketChartView chart=new MarketChartView(this);chart.setData(s.history,token);box.addView(chart,new LinearLayout.LayoutParams(ViewGroup.LayoutParams.MATCH_PARENT,dp(178)));host.addView(box,lp(ViewGroup.LayoutParams.MATCH_PARENT,ViewGroup.LayoutParams.WRAP_CONTENT,0,6,0,0));}

    /** Alternate Market Flow dashboard opened by holding the Trends tab. */
    private void showMarketFlow(){
        if(!isPremium()){showPremiumPaywall("Market Flow is a Premium-only Trends view.");return;}
        final String walletAtStart=SecurePrefs.getWalletPublicKey(this);
        stopInventoryLive(); stopHistoryHoldTick(); currentPage="trends_flow"; clearBody(); refreshBottomNav(); pageTitle("Market Flow","Hold Trends again to return to the standard seller ranking.");
        final LinearLayout host=card(); host.setBackground(outlineBg(Color.rgb(25,31,34),17,MarketFlowStyle.metricColor(MarketFlowChartView.METRIC_SPENT))); body.addView(host);
        host.addView(txt("WHAT THE MARKET IS BUYING",16,TEXT,true)); host.addView(txt("Buyer spend, sold volume and seller profit, grouped by item and currency.",11,MUTED,false),lp(ViewGroup.LayoutParams.MATCH_PARENT,ViewGroup.LayoutParams.WRAP_CONTENT,0,4,0,8));
        final LinearLayout periodRow=new LinearLayout(this); periodRow.setGravity(Gravity.CENTER); final Button[] tabs=new Button[4]; for(int i=0;i<4;i++){final int p=i;tabs[i]=outlineButton(MarketFlowAnalyzer.PERIODS[i].toUpperCase(Locale.US),MarketFlowStyle.metricColor(MarketFlowChartView.METRIC_SPENT));periodRow.addView(tabs[i],weighted(0,dp(40),i==0?0:3,0,i==3?0:3,0,1));tabs[i].setOnClickListener(new View.OnClickListener(){public void onClick(View v){marketFlowPeriod=p;styleFlowPeriodTabs(tabs);renderMarketFlow(host,p);}});} host.addView(periodRow); styleFlowPeriodTabs(tabs);
        final LinearLayout content=new LinearLayout(this);content.setOrientation(LinearLayout.VERTICAL);host.addView(content,lp(ViewGroup.LayoutParams.MATCH_PARENT,ViewGroup.LayoutParams.WRAP_CONTENT,0,10,0,0));
        renderMarketFlow(host,marketFlowPeriod);
        final MarketFlowAnalyzer.Snapshot cached=FlowCacheStore.load(this); if(cached!=null) renderFlowContent(content,cached,marketFlowPeriod);
        setBusy(true,"Refreshing market flow…"); new Thread(new Runnable(){public void run(){final MarketFlowAnalyzer.Snapshot s=MarketFlowAnalyzer.analyze(getApplicationContext());if(walletAtStart.equals(SecurePrefs.getWalletPublicKey(getApplicationContext())))FlowCacheStore.save(getApplicationContext(),s);handler.post(new Runnable(){public void run(){setBusy(false,"");if("trends_flow".equals(currentPage)&&walletAtStart.equals(SecurePrefs.getWalletPublicKey(MainActivity.this)))renderFlowContent(content,s,marketFlowPeriod);}});}},"MarketFlowCollector").start();
    }
    private void styleFlowPeriodTabs(Button[] tabs){if(tabs==null)return;int accent=MarketFlowStyle.metricColor(MarketFlowChartView.METRIC_SPENT);for(int i=0;i<tabs.length;i++){boolean selected=i==marketFlowPeriod;tabs[i].setTextColor(selected?Color.WHITE:accent);tabs[i].setBackground(selected?bg(Color.rgb(83,66,22),12):outlineBg(Color.rgb(29,34,38),12,accent));}}
    private void renderMarketFlow(final LinearLayout host,final int period){if(host==null)return;LinearLayout content=null;for(int i=0;i<host.getChildCount();i++){View v=host.getChildAt(i);if(v instanceof LinearLayout&&i>0){content=(LinearLayout)v;}}if(content!=null){MarketFlowAnalyzer.Snapshot s=FlowCacheStore.load(this);if(s!=null)renderFlowContent(content,s,period);}}
    private void renderFlowContent(LinearLayout out,MarketFlowAnalyzer.Snapshot snap,int period){
        if(out==null||snap==null)return;out.removeAllViews();List<MarketFlowAnalyzer.FlowRow> rows=snap.get(period);MarketFlowAnalyzer.FlowRow spend=null,units=null,profit=null;for(MarketFlowAnalyzer.FlowRow r:rows){if(spend==null||r.spent>spend.spent)spend=r;if(units==null||r.units>units.units)units=r;if(profit==null||r.profit>profit.profit)profit=r;}
        LinearLayout cards=new LinearLayout(this);cards.setOrientation(LinearLayout.VERTICAL);cards.addView(flowMetric("MOST BUYER SPEND",spend,MarketFlowStyle.metricColor(MarketFlowChartView.METRIC_SPENT),"spent"));cards.addView(flowMetric("MOST SOLD VOLUME",units,MarketFlowStyle.metricColor(MarketFlowChartView.METRIC_UNITS),"units"),lp(ViewGroup.LayoutParams.MATCH_PARENT,ViewGroup.LayoutParams.WRAP_CONTENT,0,6,0,0));cards.addView(flowMetric("SELLER PROFIT SIGNAL",profit,MarketFlowStyle.metricColor(MarketFlowChartView.METRIC_PROFIT),"profit"),lp(ViewGroup.LayoutParams.MATCH_PARENT,ViewGroup.LayoutParams.WRAP_CONTENT,0,6,0,0));out.addView(cards);
        out.addView(txt("BUYER SPEND • $KINS / GOLD",10,MarketFlowStyle.metricColor(MarketFlowChartView.METRIC_SPENT),true),lp(ViewGroup.LayoutParams.MATCH_PARENT,ViewGroup.LayoutParams.WRAP_CONTENT,0,10,0,0));MarketFlowChartView spendChart=new MarketFlowChartView(this);spendChart.setData(rows,MarketFlowChartView.METRIC_SPENT,MarketFlowStyle.metricColor(MarketFlowChartView.METRIC_SPENT));out.addView(spendChart,new LinearLayout.LayoutParams(ViewGroup.LayoutParams.MATCH_PARENT,dp(230)));
        out.addView(txt("SOLD VOLUME",10,MarketFlowStyle.metricColor(MarketFlowChartView.METRIC_UNITS),true),lp(ViewGroup.LayoutParams.MATCH_PARENT,ViewGroup.LayoutParams.WRAP_CONTENT,0,8,0,0));MarketFlowChartView unitsChart=new MarketFlowChartView(this);unitsChart.setData(rows,MarketFlowChartView.METRIC_UNITS,MarketFlowStyle.metricColor(MarketFlowChartView.METRIC_UNITS));out.addView(unitsChart,new LinearLayout.LayoutParams(ViewGroup.LayoutParams.MATCH_PARENT,dp(230)));
        out.addView(txt("SELLER PROFIT OPPORTUNITY",10,MarketFlowStyle.metricColor(MarketFlowChartView.METRIC_PROFIT),true),lp(ViewGroup.LayoutParams.MATCH_PARENT,ViewGroup.LayoutParams.WRAP_CONTENT,0,8,0,0));MarketFlowChartView profitChart=new MarketFlowChartView(this);profitChart.setData(rows,MarketFlowChartView.METRIC_PROFIT,MarketFlowStyle.metricColor(MarketFlowChartView.METRIC_PROFIT));out.addView(profitChart,new LinearLayout.LayoutParams(ViewGroup.LayoutParams.MATCH_PARENT,dp(230)));out.addView(txt("Updated "+(snap.updatedAt<=0?"—":age(System.currentTimeMillis()-snap.updatedAt)+" ago")+" • values are aggregated from official completed-sale signals.",9,MUTED,false),lp(ViewGroup.LayoutParams.MATCH_PARENT,ViewGroup.LayoutParams.WRAP_CONTENT,0,6,0,0));
    }
    private View flowMetric(String title,MarketFlowAnalyzer.FlowRow r,int color,String mode){LinearLayout c=new LinearLayout(this);c.setGravity(Gravity.CENTER_VERTICAL);c.setPadding(dp(10),dp(9),dp(10),dp(9));c.setBackground(outlineBg(Color.rgb(14,23,32),12,color));LinearLayout copy=new LinearLayout(this);copy.setOrientation(LinearLayout.VERTICAL);copy.addView(txt(title,9,color,true));String name=r==null?"Collecting signals…":MarketFlowStyle.shortLabel(r.itemType,r.label)+" • "+("token".equals(r.currency)?"$KINS":"Gold");copy.addView(txt(name,14,TEXT,true),lp(ViewGroup.LayoutParams.MATCH_PARENT,ViewGroup.LayoutParams.WRAP_CONTENT,0,3,0,0));if(r!=null){String value="units".equals(mode)?String.format(Locale.US,"%,d units",r.units):("profit".equals(mode)?money(r.profit):money(r.spent));copy.addView(txt(value+"  •  "+r.sales+" sale"+(r.sales==1?"":"s"),10,MUTED,false),lp(ViewGroup.LayoutParams.MATCH_PARENT,ViewGroup.LayoutParams.WRAP_CONTENT,0,2,0,0));}c.addView(copy);return c;}

    static final class OpportunityRank {String label,itemType,currency,pressure;int sales,units,available,tradedDays;Double floor,lastUnit,historyMedian;KintaraApi.Trend trend;double turnover,priceStrengthPct,overallScore,speedScore;OpportunityRank(String l,String t,String c){label=l;itemType=t;currency=c;}}
    private static double clampScore(double v){return Math.max(0,Math.min(100,v));}
    private static double logDemand(int units,int sales){return clampScore(Math.log1p(Math.max(0,units))*11.0+Math.log1p(Math.max(0,sales))*9.0);}
    private static double histMedian(KintaraApi.MarketStats s){if(s==null||s.history==null||s.history.isEmpty())return 0;List<Double> v=new ArrayList<Double>();for(KintaraApi.HistoryPoint p:s.history)if(p!=null&&p.unit>0&&p.sales>0)v.add(p.unit);if(v.isEmpty())return 0;Collections.sort(v);int n=v.size();return n%2==1?v.get(n/2):(v.get(n/2-1)+v.get(n/2))/2.0;}
    private void scoreOpportunity(OpportunityRank r){double demand=logDemand(r.units,r.sales);r.turnover=r.units<=0?0:(double)r.units/(double)(Math.max(0,r.available)+r.units);double turnover=clampScore(r.turnover*100.0);double cover=r.units<=0?99.0:(double)Math.max(0,r.available)/(double)r.units;double supply=clampScore(100.0/(1.0+cover/3.0));double momentum=50.0;if(r.trend!=null)momentum=clampScore(50.0+r.trend.pct*2.0);r.priceStrengthPct=(r.floor!=null&&r.floor>0&&r.historyMedian!=null&&r.historyMedian>0)?(r.floor/r.historyMedian-1.0)*100.0:0;double priceStrength=clampScore(50.0+r.priceStrengthPct*2.0);r.overallScore=clampScore(.35*demand+.25*turnover+.15*supply+.15*momentum+.10*priceStrength);r.speedScore=clampScore(.40*demand+.45*turnover+.15*supply);}
    private LinearLayout featuredOpportunity(OpportunityRank r,String title,String subtitle,int color){LinearLayout row=new LinearLayout(this);row.setOrientation(LinearLayout.VERTICAL);row.setPadding(dp(11),dp(10),dp(11),dp(10));row.setBackground(outlineBg(Color.rgb(12,31,28),13,color));LinearLayout h=new LinearLayout(this);h.setGravity(Gravity.CENTER_VERTICAL);h.addView(txt(title,10,color,true),new LinearLayout.LayoutParams(0,ViewGroup.LayoutParams.WRAP_CONTENT,1));h.addView(txt(trendText(r.trend),10,trendColor(r.trend),true));row.addView(h);String cur="token".equals(r.currency)?"$KINS":"Gold";row.addView(txt(r.label+" • "+cur,16,TEXT,true),lp(ViewGroup.LayoutParams.MATCH_PARENT,ViewGroup.LayoutParams.WRAP_CONTENT,0,4,0,0));row.addView(txt(subtitle,10,MUTED,false),lp(ViewGroup.LayoutParams.MATCH_PARENT,ViewGroup.LayoutParams.WRAP_CONTENT,0,2,0,0));String f=r.floor==null?"no live floor":fmtMarketPrice(r.floor,r.currency)+" floor";String score=title.contains("FASTEST")?String.format(Locale.US,"buyer-activity score %.0f/100",r.speedScore):String.format(Locale.US,"seller score %.0f/100",r.overallScore);row.addView(txt(r.units+" units / 24h • "+r.sales+" completed sales • "+r.available+" active sell supply",10,TEXT,false),lp(ViewGroup.LayoutParams.MATCH_PARENT,ViewGroup.LayoutParams.WRAP_CONTENT,0,4,0,0));row.addView(txt(f+" • "+r.pressure+" • "+score,10,color,true),lp(ViewGroup.LayoutParams.MATCH_PARENT,ViewGroup.LayoutParams.WRAP_CONTENT,0,2,0,0));if(r.historyMedian!=null&&r.historyMedian>0)row.addView(txt("Floor vs traded 30d median: "+signedPct(r.priceStrengthPct),9,MUTED,false),lp(ViewGroup.LayoutParams.MATCH_PARENT,ViewGroup.LayoutParams.WRAP_CONTENT,0,2,0,0));row.setOnClickListener(new View.OnClickListener(){public void onClick(View v){showMarketItemDetail(r.itemType,r.currency);}});return row;}
    private LinearLayout opportunityRow(OpportunityRank r,int rank){LinearLayout row=new LinearLayout(this);row.setOrientation(LinearLayout.VERTICAL);row.setPadding(dp(9),dp(8),dp(9),dp(8));row.setBackground(outlineBg(CARD2,11,BORDER));String cur="token".equals(r.currency)?"$KINS":"Gold";LinearLayout head=new LinearLayout(this);head.setGravity(Gravity.CENTER_VERTICAL);head.addView(txt(rank+". "+r.label+" • "+cur,11,rank<=5?ACCENT:TEXT,true),new LinearLayout.LayoutParams(0,ViewGroup.LayoutParams.WRAP_CONTENT,1));head.addView(txt(trendText(r.trend),10,trendColor(r.trend),true));row.addView(head);String f=r.floor==null?"no floor":fmtMarketPrice(r.floor,r.currency)+" floor";row.addView(txt(r.units+" units / 24h • "+r.sales+" completed sales • "+r.available+" active supply",10,MUTED,false),lp(ViewGroup.LayoutParams.MATCH_PARENT,ViewGroup.LayoutParams.WRAP_CONTENT,0,3,0,0));row.addView(txt(f+" • "+r.pressure+String.format(Locale.US," • seller %.0f • speed %.0f",r.overallScore,r.speedScore),10,sellerPressureColor(r.pressure),true),lp(ViewGroup.LayoutParams.MATCH_PARENT,ViewGroup.LayoutParams.WRAP_CONTENT,0,2,0,0));row.setOnClickListener(new View.OnClickListener(){public void onClick(View v){showMarketItemDetail(r.itemType,r.currency);}});return row;}
    private void scanSellerOpportunities(final LinearLayout out){out.removeAllViews();out.addView(txt("Scanning live completed-sale demand + supply depth…",12,MUTED,false),lp(ViewGroup.LayoutParams.MATCH_PARENT,ViewGroup.LayoutParams.WRAP_CONTENT,0,10,0,0));setBusy(true,"Scanning seller opportunities…");new Thread(new Runnable(){public void run(){final List<OpportunityRank> ranks=new ArrayList<>();ExecutorService pool=Executors.newFixedThreadPool(8);List<Future<OpportunityRank>> fs=new ArrayList<>();for(final KintaraApi.Item it:KintaraApi.CATALOG){fs.add(opportunityTask(pool,it,"token"));if(!"gold".equals(it.type))fs.add(opportunityTask(pool,it,"gold"));}for(Future<OpportunityRank> f:fs)try{OpportunityRank r=f.get();if(r!=null){scoreOpportunity(r);ranks.add(r);}}catch(Exception ignored){}pool.shutdown();Collections.sort(ranks,new Comparator<OpportunityRank>(){public int compare(OpportunityRank a,OpportunityRank b){return Double.compare(b.overallScore,a.overallScore);}});handler.post(new Runnable(){public void run(){setBusy(false,"");if(!"trends".equals(currentPage))return;out.removeAllViews();List<OpportunityRank> valid=new ArrayList<>();for(OpportunityRank r:ranks)if(r.units>0||r.sales>0)valid.add(r);if(valid.isEmpty()){out.addView(txt("No completed 24h sales returned by the marketplace.",12,MUTED,false));return;}OpportunityRank best=valid.get(0),fast=null;for(OpportunityRank r:valid){if(r==best)continue;if(fast==null||r.speedScore>fast.speedScore)fast=r;}out.addView(featuredOpportunity(best,"#1 BEST OVERALL SELL","Best combined demand, price strength, supply pressure and momentum.",ACCENT),lp(ViewGroup.LayoutParams.MATCH_PARENT,ViewGroup.LayoutParams.WRAP_CONTENT,0,10,0,0));if(fast!=null)out.addView(featuredOpportunity(fast,"#2 FASTEST SELL / BUYER ACTIVITY","Highest live turnover and completed buyer activity for a faster sale.",BLUE),lp(ViewGroup.LayoutParams.MATCH_PARENT,ViewGroup.LayoutParams.WRAP_CONTENT,0,7,0,0));out.addView(txt("MORE SELLER OPPORTUNITIES",10,MUTED,true),lp(ViewGroup.LayoutParams.MATCH_PARENT,ViewGroup.LayoutParams.WRAP_CONTENT,0,12,0,3));int shown=0,rank=3;for(OpportunityRank r:valid){if(r==best||r==fast)continue;out.addView(opportunityRow(r,rank++),lp(ViewGroup.LayoutParams.MATCH_PARENT,ViewGroup.LayoutParams.WRAP_CONTENT,0,5,0,0));if(++shown>=13)break;}}});}},"SellerOpportunityScan").start();}
    private org.json.JSONArray trendRanksJson(List<OpportunityRank> rows){org.json.JSONArray a=new org.json.JSONArray();if(rows==null)return a;for(OpportunityRank r:rows){if(r==null)continue;try{org.json.JSONObject j=new org.json.JSONObject();j.put("label",r.label);j.put("itemType",r.itemType);j.put("currency",r.currency);j.put("pressure",r.pressure);j.put("sales",r.sales);j.put("units",r.units);j.put("available",r.available);j.put("tradedDays",r.tradedDays);j.put("floor",r.floor==null?org.json.JSONObject.NULL:r.floor);j.put("lastUnit",r.lastUnit==null?org.json.JSONObject.NULL:r.lastUnit);j.put("historyMedian",r.historyMedian==null?org.json.JSONObject.NULL:r.historyMedian);j.put("overallScore",r.overallScore);j.put("speedScore",r.speedScore);j.put("turnover",r.turnover);j.put("priceStrengthPct",r.priceStrengthPct);if(r.trend==null)j.put("trend",org.json.JSONObject.NULL);else{org.json.JSONObject t=new org.json.JSONObject();t.put("dir",r.trend.dir);t.put("pct",r.trend.pct);j.put("trend",t);}a.put(j);}catch(Exception ignored){}}return a;}
    private List<OpportunityRank> cachedTrendRanks(){List<OpportunityRank> out=new ArrayList<OpportunityRank>();try{org.json.JSONObject root=TrendRankCacheStore.load(this);if(root==null)return out;org.json.JSONArray a=root.optJSONArray("rows");if(a==null)return out;for(int i=0;i<a.length();i++){org.json.JSONObject j=a.optJSONObject(i);if(j==null)continue;String type=j.optString("itemType","");if(type.isEmpty())continue;OpportunityRank r=new OpportunityRank(j.optString("label",KintaraApi.humanizeType(type)),type,j.optString("currency","token"));r.pressure=j.optString("pressure","UNKNOWN");r.sales=j.optInt("sales",0);r.units=j.optInt("units",0);r.available=j.optInt("available",0);r.tradedDays=j.optInt("tradedDays",0);if(j.has("floor")&&!j.isNull("floor"))r.floor=j.optDouble("floor");if(j.has("lastUnit")&&!j.isNull("lastUnit"))r.lastUnit=j.optDouble("lastUnit");if(j.has("historyMedian")&&!j.isNull("historyMedian"))r.historyMedian=j.optDouble("historyMedian");r.overallScore=j.optDouble("overallScore",0);r.speedScore=j.optDouble("speedScore",0);r.turnover=j.optDouble("turnover",0);r.priceStrengthPct=j.optDouble("priceStrengthPct",0);org.json.JSONObject t=j.optJSONObject("trend");if(t!=null){r.trend=new KintaraApi.Trend();r.trend.dir=t.optString("dir","flat");r.trend.pct=t.optDouble("pct",0);}out.add(r);}}catch(Exception ignored){}Collections.sort(out,new Comparator<OpportunityRank>(){public int compare(OpportunityRank a,OpportunityRank b){return Double.compare(b.overallScore,a.overallScore);}});return out;}
    private void renderTrendRanks(LinearLayout out,List<OpportunityRank> ranks){if(out==null)return;out.removeAllViews();List<OpportunityRank> valid=new ArrayList<OpportunityRank>();if(ranks!=null)for(OpportunityRank r:ranks)if(r!=null&&(r.units>0||r.sales>0))valid.add(r);if(valid.isEmpty()){out.addView(txt("No completed 24h sales returned by the marketplace.",12,MUTED,false));return;}OpportunityRank best=valid.get(0),fast=null;for(OpportunityRank r:valid){if(r==best)continue;if(fast==null||r.speedScore>fast.speedScore)fast=r;}out.addView(featuredOpportunity(best,"#1 BEST OVERALL SELL","Best combined demand, price strength, supply pressure and momentum.",ACCENT),lp(ViewGroup.LayoutParams.MATCH_PARENT,ViewGroup.LayoutParams.WRAP_CONTENT,0,10,0,0));if(fast!=null)out.addView(featuredOpportunity(fast,"#2 FASTEST SELL / BUYER ACTIVITY","Highest live turnover and completed buyer activity for a faster sale.",BLUE),lp(ViewGroup.LayoutParams.MATCH_PARENT,ViewGroup.LayoutParams.WRAP_CONTENT,0,7,0,0));out.addView(txt("MORE SELLER OPPORTUNITIES",10,MUTED,true),lp(ViewGroup.LayoutParams.MATCH_PARENT,ViewGroup.LayoutParams.WRAP_CONTENT,0,12,0,3));int shown=0,rank=3;for(OpportunityRank r:valid){if(r==best||r==fast)continue;out.addView(opportunityRow(r,rank++),lp(ViewGroup.LayoutParams.MATCH_PARENT,ViewGroup.LayoutParams.WRAP_CONTENT,0,5,0,0));if(++shown>=13)break;}}
    /** Paint cached rankings immediately, then refresh them silently in the background. */
    private void scanSellerOpportunitiesFast(final LinearLayout out){scanSellerOpportunitiesFast(out,true);}
    private void scanSellerOpportunitiesFast(final LinearLayout out,boolean force){
        final String walletAtStart=SecurePrefs.getWalletPublicKey(this);
        List<OpportunityRank> cached=cachedTrendRanks();long cacheAge=TrendRankCacheStore.age(this);if(cached.isEmpty()){out.removeAllViews();out.addView(txt("Refreshing seller opportunities…",12,MUTED,false),lp(ViewGroup.LayoutParams.MATCH_PARENT,ViewGroup.LayoutParams.WRAP_CONTENT,0,10,0,0));}else renderTrendRanks(out,cached);if(!force&&!cached.isEmpty()&&cacheAge<90_000L)return;setBusy(true,"Refreshing seller opportunities…");new Thread(new Runnable(){public void run(){final List<OpportunityRank> ranks=new ArrayList<OpportunityRank>();ExecutorService pool=Executors.newFixedThreadPool(8);List<Future<OpportunityRank>> fs=new ArrayList<Future<OpportunityRank>>();for(final KintaraApi.Item it:KintaraApi.CATALOG){fs.add(opportunityTask(pool,it,"token"));if(!"gold".equals(it.type))fs.add(opportunityTask(pool,it,"gold"));}for(Future<OpportunityRank> f:fs)try{OpportunityRank r=f.get();if(r!=null){scoreOpportunity(r);ranks.add(r);}}catch(Exception ignored){}pool.shutdown();Collections.sort(ranks,new Comparator<OpportunityRank>(){public int compare(OpportunityRank a,OpportunityRank b){return Double.compare(b.overallScore,a.overallScore);}});if(walletAtStart.equals(SecurePrefs.getWalletPublicKey(getApplicationContext())))TrendRankCacheStore.save(getApplicationContext(),trendRanksJson(ranks));handler.post(new Runnable(){public void run(){setBusy(false,"");if("trends".equals(currentPage)&&walletAtStart.equals(SecurePrefs.getWalletPublicKey(MainActivity.this)))renderTrendRanks(out,ranks);}});}},"SellerOpportunityWarm").start();}
    private Future<OpportunityRank> opportunityTask(ExecutorService pool,final KintaraApi.Item it,final String currency){return pool.submit(new Callable<OpportunityRank>(){public OpportunityRank call(){try{KintaraApi.MarketStatsTask task=KintaraApi.loadStatsTask(getApplicationContext(),it.type,currency);KintaraApi.MarketStats s=task==null?null:task.stats;if(s==null||!s.ok)return null;OpportunityRank r=new OpportunityRank(it.label,it.type,currency);r.sales=s.sales24h;r.units=s.units24h;r.available=s.availableFor(currency);r.floor=s.floorFor(currency);r.trend=s.trend;r.pressure=KintaraApi.sellerIntel(s,null,currency,r.floor==null?0:r.floor).pressure;r.historyMedian=histMedian(s);KintaraApi.LastSale ls=s.lastFor(currency);if(ls!=null&&ls.unit>0)r.lastUnit=ls.unit;for(KintaraApi.HistoryPoint hp:s.history)if(hp!=null&&hp.sales>0&&hp.unit>0)r.tradedDays++;return r;}catch(Exception e){return null;}}});}

    private void showHistory(){
        boolean enteringHistory=currentPage==null||!currentPage.startsWith("history");
        if(enteringHistory)soldAlertViewedInHistory=false;
        stopInventoryLive();stopHistoryHoldTick();
        currentPage="history";clearBody();refreshBottomNav();pageTitle("Market History","Active sales, sold and bought account history.");
        LinearLayout tabs=card();LinearLayout tr=new LinearLayout(this);historyActiveTab=outlineButton("ACTIVE",ACCENT);historySoldTab=outlineButton("SOLD",ACCENT);historyBoughtTab=outlineButton("BOUGHT",ACCENT);tr.addView(historyActiveTab,weighted(0,dp(44),0,0,4,0,1));tr.addView(historySoldTab,weighted(0,dp(44),4,0,4,0,1));tr.addView(historyBoughtTab,weighted(0,dp(44),4,0,0,0,1));tabs.addView(tr);body.addView(tabs);historyContent=new LinearLayout(this);historyContent.setOrientation(LinearLayout.VERTICAL);body.addView(historyContent);
        historyActiveTab.setOnClickListener(new View.OnClickListener(){public void onClick(View v){loadHistoryTab(historyContent,"active");}});historySoldTab.setOnClickListener(new View.OnClickListener(){public void onClick(View v){loadHistoryTab(historyContent,"sold");}});historyBoughtTab.setOnClickListener(new View.OnClickListener(){public void onClick(View v){loadHistoryTab(historyContent,"bought");}});
        currentHistoryMode=!latestActiveListings.isEmpty()?"active":"sold";styleHistoryTabs();loadHistoryTab(historyContent,currentHistoryMode);
    }

    private void styleHistoryTabs(){
        if(historyActiveTab==null)return;
        boolean activeAlert=!latestActiveListings.isEmpty();
        boolean soldAlert=SaleHistoryStore.hasUnreadSold(this);
        styleHistoryTab(historyActiveTab,"active".equals(currentHistoryMode),activeAlert?RED:ACCENT,activeAlert);
        styleHistoryTab(historySoldTab,"sold".equals(currentHistoryMode),soldAlert?WARN:ACCENT,soldAlert);
        styleHistoryTab(historyBoughtTab,"bought".equals(currentHistoryMode),ACCENT,false);
    }
    private void styleHistoryTab(Button b,boolean selected,int color,boolean alert){if(b==null)return;int stroke=(selected||alert)?color:BORDER;int alertFill=color==RED?RED_BG:WARN_BG;int fill=(alert&&selected)?alertFill:(selected?Color.rgb(10,45,38):CARD2);b.setTextColor((selected||alert)?color:MUTED);b.setTypeface(Typeface.DEFAULT,(selected||alert)?Typeface.BOLD:Typeface.NORMAL);b.setBackground(outlineBg(fill,12,stroke));}

    private void loadHistoryTab(final LinearLayout out,final String mode){currentHistoryMode=mode;if("sold".equals(mode)&&SaleHistoryStore.hasUnreadSold(this))soldAlertViewedInHistory=true;stopHistoryHoldTick();styleHistoryTabs();out.removeAllViews();if("active".equals(mode)&&!latestActiveListings.isEmpty()){renderHistoryList(out,mode,new ArrayList<KintaraApi.Listing>(latestActiveListings));return;}LinearLayout loading=card();loading.addView(txt("Loading history…",13,MUTED,false));out.addView(loading);async("Market history",new Work<List<KintaraApi.Listing>>(){public List<KintaraApi.Listing> run()throws Exception{if("active".equals(mode))return KintaraApi.getMyListings(getApplicationContext());if("bought".equals(mode))return KintaraApi.getBoughtListings(getApplicationContext());return KintaraApi.getSoldListings(getApplicationContext());}},new Done<List<KintaraApi.Listing>>(){public void done(List<KintaraApi.Listing> rows,Exception e){if(!currentPage.startsWith("history")||!mode.equals(currentHistoryMode))return;out.removeAllViews();if(e!=null){LinearLayout c=card();c.addView(txt("Could not load history",13,RED,true));c.addView(txt("Please try again.",11,MUTED,false),lp(ViewGroup.LayoutParams.MATCH_PARENT,ViewGroup.LayoutParams.WRAP_CONTENT,0,5,0,0));out.addView(c);return;}if(rows==null)rows=new ArrayList<KintaraApi.Listing>();if("active".equals(mode))applyActiveListingsState(rows,false);renderHistoryList(out,mode,rows);}});}

    private void renderHistoryList(LinearLayout out,String mode,List<KintaraApi.Listing> rows){stopHistoryHoldTick();out.removeAllViews();historyHoldRows.clear();historyHoldViews.clear();historyHoldButtons.clear();double usd=0,gold=0;int qtyTotal=0,checkout=0;for(KintaraApi.Listing x:rows){usd+=Math.max(0,x.priceUsd);gold+=Math.max(0,x.priceGold);qtyTotal+=Math.max(0,x.quantity);if(x.inCheckout())checkout++;}boolean activeAlert="active".equals(mode)&&!rows.isEmpty();boolean soldAlert="sold".equals(mode)&&SaleHistoryStore.hasUnreadSold(this);int summaryColor=activeAlert?RED:(soldAlert?WARN:ACCENT);LinearLayout summary=card();if(activeAlert)summary.setBackground(outlineBg(RED_BG,16,RED));else if(soldAlert)summary.setBackground(outlineBg(WARN_BG,16,WARN));summary.addView(txt(rows.size()+" "+mode+" listing"+(rows.size()==1?"":"s"),16,summaryColor,true));String totals="Items "+qtyTotal;if(usd>0)totals+="  •  "+money(usd);if(gold>0)totals+="  •  "+String.format(Locale.US,"%.0f Gold",gold);if(checkout>0)totals+="  •  "+checkout+" in checkout";summary.addView(txt(totals,11,MUTED,false),lp(ViewGroup.LayoutParams.MATCH_PARENT,ViewGroup.LayoutParams.WRAP_CONTENT,0,5,0,0));out.addView(summary);if(rows.isEmpty()){LinearLayout empty=card();empty.addView(txt("No "+mode+" marketplace entries found.",12,MUTED,false));out.addView(empty);return;}for(KintaraApi.Listing x:rows)out.addView(historyCard(x,mode));if("active".equals(mode)&&!historyHoldRows.isEmpty())startHistoryHoldTick();}

    private LinearLayout historyCard(final KintaraApi.Listing x,String mode){
        if("active".equals(mode))return activeHistoryCard(x);boolean freshSold="sold".equals(mode)&&SaleHistoryStore.isUnreadSold(this,x);LinearLayout c=card();c.setPadding(dp(12),dp(10),dp(12),dp(10));if(freshSold)c.setBackground(outlineBg(WARN_BG,16,WARN));LinearLayout r=new LinearLayout(this);r.setGravity(Gravity.CENTER_VERTICAL);r.addView(itemImage(x.itemType,46),lp(dp(46),dp(46),0,0,10,0));LinearLayout left=new LinearLayout(this);left.setOrientation(LinearLayout.VERTICAL);left.addView(txt(x.label(),15,freshSold?WARN:TEXT,true));String meta="Quantity "+x.quantity+" • "+("token".equals(x.currency)?"$KINS":"Gold");left.addView(txt(meta,11,MUTED,false));long t=x.finishedAtMs>0?x.finishedAtMs:x.createdAtMs;if(t>0)left.addView(txt(formatSaleTime(t),10,MUTED,false));if(freshSold)left.addView(txt("NEW SOLD",9,WARN,true),lp(ViewGroup.LayoutParams.MATCH_PARENT,ViewGroup.LayoutParams.WRAP_CONTENT,0,3,0,0));r.addView(left,new LinearLayout.LayoutParams(0,ViewGroup.LayoutParams.WRAP_CONTENT,1));String price=x.totalPrice()>0?formatTotal(x.totalPrice(),x.currency):"—";TextView priceView=txt(price,14,freshSold?WARN:ACCENT,true);priceView.setGravity(Gravity.RIGHT);r.addView(priceView,lp(dp(108),ViewGroup.LayoutParams.WRAP_CONTENT,8,0,0,0));c.addView(r);return c;
    }
    private LinearLayout activeHistoryCard(final KintaraApi.Listing x){
        LinearLayout c=card();c.setPadding(dp(12),dp(11),dp(12),dp(11));c.setBackground(outlineBg(CARD,16,x.inCheckout()?WARN:BORDER));LinearLayout row=new LinearLayout(this);row.setGravity(Gravity.CENTER_VERTICAL);row.addView(itemImage(x.itemType,48),lp(dp(48),dp(48),0,0,11,0));LinearLayout info=new LinearLayout(this);info.setOrientation(LinearLayout.VERTICAL);info.addView(txt(x.label(),15,TEXT,true));String meta="Qty "+x.quantity+"  •  "+("token".equals(x.currency)?"$KINS":"Gold");info.addView(txt(meta,10,MUTED,false),lp(ViewGroup.LayoutParams.MATCH_PARENT,ViewGroup.LayoutParams.WRAP_CONTENT,0,3,0,0));info.addView(txt(formatTotal(x.totalPrice(),x.currency)+" total  •  "+fmtMarketPrice(x.unitPrice(),x.currency)+" each",12,ACCENT,true),lp(ViewGroup.LayoutParams.MATCH_PARENT,ViewGroup.LayoutParams.WRAP_CONTENT,0,4,0,0));if(x.floorUnit!=null&&x.floorUnit>0){double pct=(x.unitPrice()-x.floorUnit)/x.floorUnit*100.0;String delta=Math.abs(pct)<.5?"at floor":String.format(Locale.US,"%.1f%% %s floor",Math.abs(pct),pct>0?"above":"below");info.addView(txt("Floor "+fmtMarketPrice(x.floorUnit,x.currency)+"  •  "+delta+"  "+trendText(x.trend),10,trendColor(x.trend),true),lp(ViewGroup.LayoutParams.MATCH_PARENT,ViewGroup.LayoutParams.WRAP_CONTENT,0,3,0,0));}if(x.createdAtMs>0)info.addView(txt("Listed "+relativeTime(x.createdAtMs),9,MUTED,false),lp(ViewGroup.LayoutParams.MATCH_PARENT,ViewGroup.LayoutParams.WRAP_CONTENT,0,2,0,0));TextView hold=null;if(x.inCheckout()){hold=txt("IN CHECKOUT  •  "+checkoutRemaining(x.reservedUntilMs)+" remaining",10,WARN,true);info.addView(hold,lp(ViewGroup.LayoutParams.MATCH_PARENT,ViewGroup.LayoutParams.WRAP_CONTENT,0,3,0,0));}row.addView(info,new LinearLayout.LayoutParams(0,ViewGroup.LayoutParams.WRAP_CONTENT,1));Button cancel=outlineButton(x.inCheckout()?"Locked":"Cancel",x.inCheckout()?WARN:RED);cancel.setEnabled(!x.inCheckout());cancel.setTextSize(11);row.addView(cancel,lp(dp(82),dp(40),10,0,0,0));c.addView(row);if(hold!=null){historyHoldRows.add(x);historyHoldViews.add(hold);historyHoldButtons.add(cancel);}cancel.setOnClickListener(new View.OnClickListener(){public void onClick(View v){if(x.inCheckout()){toast("A buyer is in checkout; cancel unlocks when the hold ends.");return;}cancelListing(x);}});return c;
    }
    private void startHistoryHoldTick(){if(historyHoldTick!=null)handler.removeCallbacks(historyHoldTick);historyHoldTick=new Runnable(){public void run(){if(!"history".equals(currentPage)||!"active".equals(currentHistoryMode))return;for(int i=0;i<historyHoldRows.size();i++){KintaraApi.Listing x=historyHoldRows.get(i);TextView hv=historyHoldViews.get(i);Button cb=historyHoldButtons.get(i);if(x.inCheckout()){hv.setText("IN CHECKOUT  •  "+checkoutRemaining(x.reservedUntilMs)+" remaining");hv.setTextColor(WARN);cb.setEnabled(false);cb.setText("Locked");}else{hv.setText("Checkout hold expired  •  cancel available");hv.setTextColor(MUTED);cb.setEnabled(true);cb.setText("Cancel");}}handler.postDelayed(this,1000);}};handler.post(historyHoldTick);}
    private void stopHistoryHoldTick(){if(historyHoldTick!=null)handler.removeCallbacks(historyHoldTick);historyHoldTick=null;historyHoldRows.clear();historyHoldViews.clear();historyHoldButtons.clear();}

    private boolean isToday(long ms){if(ms<=0)return false;Calendar now=Calendar.getInstance();Calendar t=Calendar.getInstance();t.setTimeInMillis(ms);return now.get(Calendar.ERA)==t.get(Calendar.ERA)&&now.get(Calendar.YEAR)==t.get(Calendar.YEAR)&&now.get(Calendar.DAY_OF_YEAR)==t.get(Calendar.DAY_OF_YEAR);}
    private String formatSaleTime(long ms){SimpleDateFormat f=new SimpleDateFormat("yyyy-MM-dd  HH:mm",Locale.US);return f.format(new Date(ms));}

    private void showSettings(){
        stopInventoryLive();stopHistoryHoldTick();
        currentPage="settings";clearBody();refreshBottomNav();pageTitle("Settings","");
        LinearLayout theme=card();theme.addView(txt("Theme",15,TEXT,true));LinearLayout tr=new LinearLayout(this);boolean amoled=UiPrefs.isAmoled(this);Button dark=!amoled?button("Dark",Color.rgb(30,82,62)):outlineButton("Dark",MUTED);if(!amoled)dark.setTextColor(ACCENT);Button black=amoled?button("AMOLED",Color.rgb(30,82,62)):outlineButton("AMOLED",MUTED);if(amoled)black.setTextColor(ACCENT);tr.addView(dark,weighted(0,dp(44),0,8,4,0,1));tr.addView(black,weighted(0,dp(44),4,8,0,0,1));theme.addView(tr);body.addView(theme);dark.setOnClickListener(new View.OnClickListener(){public void onClick(View v){setTheme(false);}});black.setOnClickListener(new View.OnClickListener(){public void onClick(View v){setTheme(true);}});
        LinearLayout account=card();LinearLayout cr=new LinearLayout(this);cr.setGravity(Gravity.CENTER_VERTICAL);LinearLayout ct=new LinearLayout(this);ct.setOrientation(LinearLayout.VERTICAL);String wp=SecurePrefs.getWalletProvider(this),wk=SecurePrefs.getWalletPublicKey(this),pn=SecurePrefs.getWalletPlayerName(this);ct.addView(txt("Wallet Account",15,TEXT,true));if(!pn.isEmpty())ct.addView(txt(pn,11,ACCENT,true),lp(ViewGroup.LayoutParams.MATCH_PARENT,ViewGroup.LayoutParams.WRAP_CONTENT,0,3,0,0));ct.addView(txt((wp.isEmpty()?"Solana Wallet":wp)+"  •  "+shortWallet(wk),10,MUTED,false),lp(ViewGroup.LayoutParams.MATCH_PARENT,ViewGroup.LayoutParams.WRAP_CONTENT,0,3,0,0));cr.addView(ct,new LinearLayout.LayoutParams(0,ViewGroup.LayoutParams.WRAP_CONTENT,1));Button change=miniButton("Log out");cr.addView(change,lp(dp(86),dp(42),8,0,0,0));account.addView(cr);body.addView(account);change.setOnClickListener(new View.OnClickListener(){public void onClick(View v){confirmWalletLogout();}});
        final int linkedNow=PremiumManager.linkedAccountCount(this), accountLimit=PremiumManager.accountLimit(this);
        account.addView(txt("Encrypted profiles: "+WalletAccountStore.count(this)+"  •  Premium linked: "+linkedNow+" / "+accountLimit,10,PURPLE,false),lp(ViewGroup.LayoutParams.MATCH_PARENT,ViewGroup.LayoutParams.WRAP_CONTENT,0,8,0,0));
        if(isPremium()&&linkedNow<accountLimit){Button addAccount=outlineButton("CONNECT ANOTHER ACCOUNT",PURPLE);account.addView(addAccount,lp(ViewGroup.LayoutParams.MATCH_PARENT,dp(44),0,8,0,0));addAccount.setOnClickListener(new View.OnClickListener(){public void onClick(View v){startWalletLogin(WalletAuthManager.PHANTOM);}});}
        LinearLayout premiumCard=card();premiumCard.setBackground(outlineBg(CARD,16,isPremium()?ACCENT:BORDER));LinearLayout ph=new LinearLayout(this);ph.setGravity(Gravity.CENTER_VERTICAL);LinearLayout pt=new LinearLayout(this);pt.setOrientation(LinearLayout.VERTICAL);pt.addView(txt("Premium",15,isPremium()?ACCENT:TEXT,true));pt.addView(txt(PremiumManager.statusLabel(this),11,isPremium()?ACCENT:MUTED,false),lp(ViewGroup.LayoutParams.MATCH_PARENT,ViewGroup.LayoutParams.WRAP_CONTENT,0,3,0,0));pt.addView(txt("Full Market Trends",10,MUTED,false),lp(ViewGroup.LayoutParams.MATCH_PARENT,ViewGroup.LayoutParams.WRAP_CONTENT,0,3,0,0));ph.addView(pt,new LinearLayout.LayoutParams(0,ViewGroup.LayoutParams.WRAP_CONTENT,1));Button premiumBtn=miniButton(isPremium()?"Renew":"Unlock");ph.addView(premiumBtn,lp(dp(88),dp(42),8,0,0,0));premiumCard.addView(ph);body.addView(premiumCard);premiumBtn.setOnClickListener(new View.OnClickListener(){public void onClick(View v){showPremiumPaywall(isPremium()?"Add another 30 days of full Market Trends access.":"Unlock full Market Trends.");}});
        LinearLayout gameCard=card();gameCard.setBackground(outlineBg(isPremium()?Color.BLACK:CARD,16,isPremium()?ACCENT:BORDER));LinearLayout gameHead=new LinearLayout(this);gameHead.setGravity(Gravity.CENTER_VERTICAL);ImageView gameIcon=new ImageView(this);gameIcon.setImageResource(drawableId("app_icon_v172"));gameIcon.setScaleType(ImageView.ScaleType.CENTER_INSIDE);gameHead.addView(gameIcon,lp(dp(48),dp(48),0,0,11,0));LinearLayout gameCopy=new LinearLayout(this);gameCopy.setOrientation(LinearLayout.VERTICAL);gameCopy.addView(txt("KINTARA GAME",15,TEXT,true));gameCopy.addView(txt(isPremium()?"Hold the Settings tab to launch the online game.":"Premium access is required to launch the game.",10,MUTED,false),lp(ViewGroup.LayoutParams.MATCH_PARENT,ViewGroup.LayoutParams.WRAP_CONTENT,0,4,0,0));gameHead.addView(gameCopy,new LinearLayout.LayoutParams(0,ViewGroup.LayoutParams.WRAP_CONTENT,1));gameCard.addView(gameHead);body.addView(gameCard);
        LinearLayout tracking=card();tracking.addView(txt("Market Tracking",15,TEXT,true));long last=HistoryStore.latestTime(this);tracking.addView(txt(last<=0?"Waiting for market activity":"Updated "+age(System.currentTimeMillis()-last)+" ago",10,MUTED,false),lp(ViewGroup.LayoutParams.MATCH_PARENT,ViewGroup.LayoutParams.WRAP_CONTENT,0,4,0,0));body.addView(tracking);
        LinearLayout privacy=card();privacy.addView(txt("Secure & Private",15,TEXT,true));privacy.addView(txt("Your wallet stays in your control. The app never stores your recovery phrase or private key.",11,MUTED,false),lp(ViewGroup.LayoutParams.MATCH_PARENT,ViewGroup.LayoutParams.WRAP_CONTENT,0,4,0,0));body.addView(privacy);
        LinearLayout about=card();about.setGravity(Gravity.CENTER);TextView a=txt("KINTARA MARKET",12,MUTED,true);a.setGravity(Gravity.CENTER);about.addView(a);TextView by=txt("By JavadTM",11,ACCENT,false);by.setGravity(Gravity.CENTER);about.addView(by,lp(ViewGroup.LayoutParams.MATCH_PARENT,ViewGroup.LayoutParams.WRAP_CONTENT,0,5,0,1));body.addView(about);about.setOnClickListener(new View.OnClickListener(){public void onClick(View v){recordSilentTap();}});
    }

    private void recordSilentTap(){
        long now=System.currentTimeMillis();if(now-silentTapAtMs<=480L)silentTapCount++;else silentTapCount=1;silentTapAtMs=now;
        if(silentTapCount>=2){silentTapCount=0;silentTapAtMs=0L;showAdminCodeEntry();}
    }

    private void showAdminCodeEntry(){
        final Dialog d=new Dialog(this);d.requestWindowFeature(Window.FEATURE_NO_TITLE);d.setCancelable(true);d.setCanceledOnTouchOutside(true);
        LinearLayout shell=new LinearLayout(this);shell.setPadding(dp(18),dp(18),dp(18),dp(18));shell.setBackground(outlineBg(CARD,16,BORDER));
        final EditText code=input("");code.setGravity(Gravity.CENTER);code.setInputType(InputType.TYPE_CLASS_NUMBER|InputType.TYPE_NUMBER_VARIATION_PASSWORD);code.setFilters(new InputFilter[]{new InputFilter.LengthFilter(8)});shell.addView(code,new LinearLayout.LayoutParams(ViewGroup.LayoutParams.MATCH_PARENT,dp(54)));d.setContentView(shell);
        code.addTextChangedListener(new TextWatcher(){
            private boolean checking=false;
            public void beforeTextChanged(CharSequence s,int st,int c,int a){}
            public void onTextChanged(CharSequence s,int st,int before,int count){}
            public void afterTextChanged(Editable e){
                if(checking||e==null||e.length()!=8)return;
                checking=true;code.setEnabled(false);final String entered=e.toString();
                new Thread(new Runnable(){public void run(){
                    final PremiumManager.AdminUnlockResult result=PremiumManager.unlockWithAdminCode(getApplicationContext(),entered);
                    handler.post(new Runnable(){public void run(){
                        if(result.ok){d.dismiss();if("settings".equals(currentPage))showSettings();else refreshPremiumUi();}
                        else{checking=false;code.setEnabled(true);code.setText("");code.setBackground(outlineBg(CARD2,12,RED));code.requestFocus();}
                    }});
                }},"AdminCodeCheck").start();
            }
        });
        d.show();Window w=d.getWindow();if(w!=null){w.setBackgroundDrawable(new android.graphics.drawable.ColorDrawable(Color.TRANSPARENT));w.setDimAmount(.72f);w.addFlags(android.view.WindowManager.LayoutParams.FLAG_DIM_BEHIND);w.setSoftInputMode(android.view.WindowManager.LayoutParams.SOFT_INPUT_STATE_ALWAYS_VISIBLE);w.setLayout((int)(getResources().getDisplayMetrics().widthPixels*.78f),ViewGroup.LayoutParams.WRAP_CONTENT);}code.requestFocus();
    }

    private void setTheme(boolean amoled){if(UiPrefs.isAmoled(this)==amoled)return;UiPrefs.setAmoled(this,amoled);stopForegroundCollector();stopListingPoll();stopInventoryLive();stopHistoryHoldTick();applyThemePalette();getWindow().setStatusBarColor(BG);getWindow().setNavigationBarColor(BG);buildShell();showSettings();startForegroundCollector();startListingPoll();}

    private void startListingPoll(){if(SecurePrefs.getCookie(this).isEmpty()||root==null)return;stopListingPoll();syncActiveListings();listingPoll=new Runnable(){public void run(){syncActiveListings();handler.postDelayed(this,8000);}};handler.postDelayed(listingPoll,8000);}
    private void stopListingPoll(){if(listingPoll!=null)handler.removeCallbacks(listingPoll);listingPoll=null;listingSyncing=false;}
    private void syncActiveListings(){if(listingSyncing||root==null||SecurePrefs.getCookie(this).isEmpty())return;final String walletAtStart=SecurePrefs.getWalletPublicKey(this);listingSyncing=true;new Thread(new Runnable(){public void run(){List<KintaraApi.Listing> rows=null;try{rows=KintaraApi.getMyListings(getApplicationContext());if(walletAtStart.equals(SecurePrefs.getWalletPublicKey(getApplicationContext())))SaleHistoryStore.reconcileActive(getApplicationContext(),rows);}catch(Exception ignored){}final List<KintaraApi.Listing> result=rows;handler.post(new Runnable(){public void run(){listingSyncing=false;if(result!=null&&walletAtStart.equals(SecurePrefs.getWalletPublicKey(MainActivity.this)))applyActiveListingsState(result,true);}});}},"ListingSync").start();}
    private void applyActiveListingsState(List<KintaraApi.Listing> rows,boolean updateHistory){latestActiveListings.clear();if(rows!=null){LinkedHashMap<String,KintaraApi.Listing> unique=new LinkedHashMap<String,KintaraApi.Listing>();for(KintaraApi.Listing x:rows){if(x==null||x.id==null||x.id.trim().isEmpty())continue;unique.put(x.id.trim(),x);}latestActiveListings.addAll(unique.values());}refreshBottomNav();styleHistoryTabs();if(updateHistory&&"history".equals(currentPage)&&"active".equals(currentHistoryMode)&&historyContent!=null)renderHistoryList(historyContent,"active",new ArrayList<KintaraApi.Listing>(latestActiveListings));}
    private String checkoutRemaining(long until){long ms=Math.max(0,until-System.currentTimeMillis());long sec=(ms+999)/1000;return String.format(Locale.US,"%d:%02d",sec/60,sec%60);}
    private void cancelListing(final KintaraApi.Listing x){async("Cancelling listing",new Work<KintaraApi.CancelResult>(){public KintaraApi.CancelResult run(){KintaraApi.CancelResult r=KintaraApi.cancelListing(getApplicationContext(),x.id);if(r!=null&&r.ok)SaleHistoryStore.markCancelled(getApplicationContext(),x.id);return r;}},new Done<KintaraApi.CancelResult>(){public void done(KintaraApi.CancelResult r,Exception e){if(e!=null||r==null||!r.ok){toast("Could not cancel listing");return;}toast("Cancelled");syncActiveListings();}});}

    private String shortWallet(String key){if(key==null||key.isEmpty())return "—";if(key.length()<=12)return key;return key.substring(0,5)+"…"+key.substring(key.length()-5);}
    private void confirmWalletLogout(){
        showBrandedConfirm("Log out wallet account","This removes the active Kintara session from this device. Your encrypted Premium entitlement and saved account profiles remain available.","LOG OUT","CANCEL",new View.OnClickListener(){public void onClick(View v){MarketJobService.cancel(getApplicationContext());stopForegroundCollector();stopListingPoll();stopInventoryLive();if(gameSession!=null){gameSession.destroy();gameSession=null;}WalletAccountStore.saveActive(getApplicationContext());SecurePrefs.clearActiveWalletAuth(getApplicationContext());navHistory.clear();latestActiveListings.clear();showLogin();}});
    }

    private void startForegroundCollector(){if(SecurePrefs.getCookie(this).isEmpty()||root==null)return;stopForegroundCollector();foregroundCollector=new Runnable(){public void run(){if(!SecurePrefs.getCookie(getApplicationContext()).isEmpty()&&System.currentTimeMillis()-HistoryStore.lastSnapshotTime(getApplicationContext())>=55000){new Thread(new Runnable(){public void run(){HistoryStore.collectSnapshot(getApplicationContext());handler.post(new Runnable(){public void run(){updateCollectorStatus();}});}},"ForegroundMarketCollector").start();}handler.postDelayed(this,60000);}};handler.postDelayed(foregroundCollector,60000);}
    private void stopForegroundCollector(){if(foregroundCollector!=null)handler.removeCallbacks(foregroundCollector);foregroundCollector=null;}
}
