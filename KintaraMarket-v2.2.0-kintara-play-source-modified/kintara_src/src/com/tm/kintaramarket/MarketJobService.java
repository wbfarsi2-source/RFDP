package com.tm.kintaramarket;

import android.app.job.JobInfo;
import android.app.job.JobParameters;
import android.app.job.JobScheduler;
import android.app.job.JobService;
import android.content.ComponentName;
import android.content.Context;

public class MarketJobService extends JobService {
    public static final int JOB_ID = 503405;
    public static void schedule(Context c) {
        if (SecurePrefs.getCookie(c).isEmpty()) return;
        JobScheduler js=(JobScheduler)c.getSystemService(Context.JOB_SCHEDULER_SERVICE);
        if(js==null)return;
        JobInfo job=new JobInfo.Builder(JOB_ID,new ComponentName(c,MarketJobService.class))
                .setRequiredNetworkType(JobInfo.NETWORK_TYPE_ANY)
                .setPeriodic(15L*60L*1000L)
                .setPersisted(true)
                .build();
        js.schedule(job);
    }
    public static void cancel(Context c) { JobScheduler js=(JobScheduler)c.getSystemService(Context.JOB_SCHEDULER_SERVICE);if(js!=null)js.cancel(JOB_ID); }
    @Override public boolean onStartJob(final JobParameters params) {
        new Thread(new Runnable(){@Override public void run(){Context c=getApplicationContext();final String walletAtStart=SecurePrefs.getWalletPublicKey(c);if(walletAtStart.isEmpty()){jobFinished(params,false);return;}HistoryStore.collectSnapshot(c);for(String item:HistoryStore.TRACKED){KintaraApi.loadStatsTask(c,item,"token");if(!"gold".equals(item))KintaraApi.loadStatsTask(c,item,"gold");if(!walletAtStart.equals(SecurePrefs.getWalletPublicKey(c))){jobFinished(params,false);return;}}try{ListGuard.saveInventory(c,walletAtStart);}catch(Exception ignored){}try{if(walletAtStart.equals(SecurePrefs.getWalletPublicKey(c)))MarketCacheStore.saveLatest(c,"all","",KintaraApi.getLatestListings(c,"all","",60));}catch(Exception ignored){}jobFinished(params,false);}},"KintaraMarketCollector").start();return true;
    }

    /** Keeps a background inventory response tied to the wallet that requested it. */
    private static final class ListGuard {
        static void saveInventory(Context c,String wallet) throws Exception {
            if(!wallet.equals(SecurePrefs.getWalletPublicKey(c)))return;
            InventoryCacheStore.save(c,KintaraApi.getInventory(c));
        }
    }
    @Override public boolean onStopJob(JobParameters params) { return true; }
}
