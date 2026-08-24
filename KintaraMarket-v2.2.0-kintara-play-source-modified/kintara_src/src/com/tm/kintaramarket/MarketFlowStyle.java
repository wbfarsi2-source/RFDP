package com.tm.kintaramarket;

import android.graphics.Color;

import java.util.Locale;

/** Shared labels and palette for the Premium Market Flow dashboard. */
public final class MarketFlowStyle {
    private static final int GOLD = Color.rgb(244, 194, 65);
    private static final int MOLTEN = Color.rgb(235, 112, 47);
    private static final int BRUTE = Color.rgb(202, 133, 82);
    private static final int WATER = Color.rgb(71, 186, 218);
    private static final int ORE = Color.rgb(166, 177, 190);
    private static final int WOOD = Color.rgb(169, 126, 77);
    private static final int TOOL = Color.rgb(128, 190, 171);
    private static final int COSMETIC = Color.rgb(224, 135, 179);
    private static final int PET = Color.rgb(134, 191, 126);
    private static final int DEFAULT = Color.rgb(111, 169, 199);

    private MarketFlowStyle() {}

    /** Returns a short, stable label that fits under a six-column chart. */
    public static String shortLabel(String itemType, String fallback) {
        String t = KintaraApi.normalizeItemType(itemType);
        if ("gold".equals(t)) return "Gold";
        if ("molten_rock".equals(t)) return "Molten";
        if ("brute_horn".equals(t)) return "Brute";
        if ("iron_ore".equals(t)) return "Iron";
        if ("silver_ore".equals(t)) return "Silver";
        if ("copper_ore".equals(t)) return "Copper";
        if ("stone".equals(t)) return "Stone";
        if ("wood".equals(t)) return "Wood";
        if ("coal".equals(t)) return "Coal";
        if (t.startsWith("cooked_")) return compactWord(t.substring(7), "Cooked");
        if (t.startsWith("burnt_")) return compactWord(t.substring(6), "Burnt");
        if (t.startsWith("fish_")) return compactWord(t.substring(5), "Fish");
        if (t.startsWith("bait_")) return compactWord(t.substring(5), "Bait");
        if (t.startsWith("tool_")) return compactWord(t.substring(5), "Tool");
        if (t.startsWith("pet_")) return compactWord(t.substring(4), "Pet");
        if (t.startsWith("mount_")) return compactWord(t.substring(6), "Mount");
        if (t.startsWith("cosmetic_")) return compactWord(t.substring(9), "Style");
        String raw = fallback == null || fallback.trim().isEmpty() ? KintaraApi.humanizeType(t) : fallback.trim();
        raw = raw.replace('-', ' ').replace('_', ' ').replaceAll("\\s+", " ").trim();
        if (raw.length() <= 10) return raw;
        String[] words = raw.split(" ");
        if (words.length > 1) {
            StringBuilder initials = new StringBuilder();
            for (String word : words) if (!word.isEmpty()) initials.append(Character.toUpperCase(word.charAt(0)));
            if (initials.length() >= 2 && initials.length() <= 6) return initials.toString();
        }
        return raw.substring(0, 9) + "…";
    }

    private static String compactWord(String raw, String prefix) {
        String word = raw == null ? "" : raw.replace('_', ' ').replace('-', ' ').trim();
        if (word.isEmpty()) return prefix;
        String[] parts = word.split("\\s+");
        String candidate = parts[0];
        if (candidate.length() > 8) candidate = candidate.substring(0, 7) + "…";
        // Keep the category visible for ambiguous one-word payloads while
        // staying below the width of the chart label lane.
        if (parts.length > 1 && candidate.length() <= 5) candidate += " " + parts[1].substring(0, Math.min(3, parts[1].length()));
        if (candidate.length() > 10) candidate = candidate.substring(0, 9) + "…";
        return titleCase(candidate);
    }

    private static String titleCase(String value) {
        String[] parts = value.toLowerCase(Locale.US).split("\\s+");
        StringBuilder out = new StringBuilder();
        for (String p : parts) {
            if (p.isEmpty()) continue;
            if (out.length() > 0) out.append(' ');
            out.append(Character.toUpperCase(p.charAt(0)));
            if (p.length() > 1) out.append(p.substring(1));
        }
        return out.toString();
    }

    /** Item/category colors; deliberately contains no purple tones. */
    public static int itemColor(String itemType) {
        String t = KintaraApi.normalizeItemType(itemType);
        if ("gold".equals(t)) return GOLD;
        if ("molten_rock".equals(t)) return MOLTEN;
        if ("brute_horn".equals(t)) return BRUTE;
        if (t.startsWith("fish_") || t.startsWith("bait_") || "fish".equals(t)) return WATER;
        if (t.contains("ore") || t.contains("ingot") || "metal".equals(t)) return ORE;
        if ("wood".equals(t) || "stone".equals(t) || "coal".equals(t)) return WOOD;
        if (t.startsWith("tool_") || t.contains("sword") || t.contains("axe") || t.contains("pickaxe")) return TOOL;
        if (t.startsWith("cosmetic_") || t.startsWith("furniture_")) return COSMETIC;
        if (t.startsWith("pet_") || t.startsWith("mount_")) return PET;
        return DEFAULT;
    }

    public static int metricColor(int metric) {
        if (metric == MarketFlowChartView.METRIC_UNITS) return Color.rgb(64, 194, 221);
        if (metric == MarketFlowChartView.METRIC_PROFIT) return Color.rgb(91, 211, 139);
        return Color.rgb(235, 178, 65);
    }

    public static String currencyShort(String currency) {
        return "token".equalsIgnoreCase(currency) ? "$" : "G";
    }
}
