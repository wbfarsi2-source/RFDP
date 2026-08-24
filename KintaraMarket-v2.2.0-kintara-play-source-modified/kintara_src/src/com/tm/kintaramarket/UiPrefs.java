package com.tm.kintaramarket;

import android.content.Context;
import android.content.SharedPreferences;

public final class UiPrefs {
    private static final String PREFS = "kintara_ui";
    private static final String AMOLED = "amoled";
    private static final String REFRESH_HINT_SEEN = "refresh_hint_seen_v2";
    private UiPrefs() {}

    public static boolean isAmoled(Context c) {
        return c.getSharedPreferences(PREFS, Context.MODE_PRIVATE).getBoolean(AMOLED, false);
    }

    public static void setAmoled(Context c, boolean on) {
        SharedPreferences.Editor e = c.getSharedPreferences(PREFS, Context.MODE_PRIVATE).edit();
        e.putBoolean(AMOLED, on).apply();
    }

    public static boolean hasSeenRefreshHint(Context c) {
        return c.getSharedPreferences(PREFS, Context.MODE_PRIVATE).getBoolean(REFRESH_HINT_SEEN, false);
    }

    public static void markRefreshHintSeen(Context c) {
        c.getSharedPreferences(PREFS, Context.MODE_PRIVATE).edit().putBoolean(REFRESH_HINT_SEEN, true).apply();
    }
}
