package com.tm.kintaramarket;

import android.content.Context;
import android.graphics.Canvas;
import android.graphics.Color;
import android.graphics.Paint;
import android.graphics.RectF;
import android.view.View;

import java.util.ArrayList;
import java.util.Collections;
import java.util.Comparator;
import java.util.List;
import java.util.Locale;

/** Compact item-colour bar chart used by the Premium Market Flow view. */
public final class MarketFlowChartView extends View {
    public static final int METRIC_SPENT = 0, METRIC_UNITS = 1, METRIC_PROFIT = 2;
    private final Paint paint = new Paint(Paint.ANTI_ALIAS_FLAG);
    private final Paint text = new Paint(Paint.ANTI_ALIAS_FLAG);
    private final List<MarketFlowAnalyzer.FlowRow> rows = new ArrayList<MarketFlowAnalyzer.FlowRow>();
    private int metric = METRIC_SPENT, accent = MarketFlowStyle.metricColor(METRIC_SPENT);

    public MarketFlowChartView(Context c) { super(c); setMinimumHeight(dp(230)); setContentDescription("Market flow bar chart"); }
    public void setData(List<MarketFlowAnalyzer.FlowRow> source, int metric, int accent) {
        rows.clear(); if(source!=null) rows.addAll(source); this.metric=metric; this.accent=accent;
        Collections.sort(rows,new Comparator<MarketFlowAnalyzer.FlowRow>(){public int compare(MarketFlowAnalyzer.FlowRow a,MarketFlowAnalyzer.FlowRow b){double av=value(a),bv=value(b);int c=Double.compare(bv,av);if(c!=0)return c;return b.sales-a.sales;}});
        invalidate();
    }
    private int dp(int n) { return (int)(n*getResources().getDisplayMetrics().density+.5f); }
    private float value(MarketFlowAnalyzer.FlowRow r) { return (float)(metric==METRIC_UNITS?r.units:metric==METRIC_PROFIT?r.profit:r.spent); }
    private String valueText(double v, MarketFlowAnalyzer.FlowRow r) { if(metric==METRIC_UNITS)return String.format(Locale.US,"%,d",(int)Math.round(v))+" units"; return ("token".equals(r.currency)?String.format(Locale.US,"$%.2f",v):String.format(Locale.US,"%,.0f g",v)); }
    @Override protected void onDraw(Canvas c) {
        super.onDraw(c);
        int w=getWidth(),h=getHeight();
        if(w<=0||h<=0)return;
        float left=dp(12),right=w-dp(12),top=dp(34),bottom=h-dp(36);
        paint.setColor(Color.argb(62,58,70,78));
        c.drawRoundRect(new RectF(dp(2),dp(8),w-dp(2),h-dp(10)),dp(16),dp(16),paint);
        text.setTextSize(dp(11));
        text.setColor(MarketFlowStyle.metricColor(metric));
        c.drawText(metric==METRIC_UNITS?"UNITS SOLD":metric==METRIC_PROFIT?"SELLER PROFIT":"BUYER SPEND",left,dp(25),text);
        if(rows.isEmpty()){
            text.setTextSize(dp(11));
            text.setColor(Color.rgb(180,188,205));
            c.drawText("Collecting completed-sale signals…",left,top+(bottom-top)/2,text);
            return;
        }
        int n=Math.min(6,rows.size());
        double max=0;
        for(int i=0;i<n;i++)max=Math.max(max,value(rows.get(i)));
        if(max<=0)max=1;
        float gap=dp(7),barW=(right-left-gap*(n-1))/n;
        for(int i=0;i<n;i++){
            MarketFlowAnalyzer.FlowRow r=rows.get(i);
            float x=left+i*(barW+gap),barH=(float)(value(r)/max*(bottom-top));
            int col=MarketFlowStyle.itemColor(r.itemType);
            paint.setColor(Color.argb(55,Color.red(col),Color.green(col),Color.blue(col)));
            c.drawRoundRect(new RectF(x,bottom-barH,x+barW,bottom),dp(8),dp(8),paint);
            paint.setColor(col);
            c.drawRoundRect(new RectF(x,bottom-barH+dp(3),x+barW,bottom),dp(8),dp(8),paint);
            text.setColor(Color.rgb(238,242,247));
            text.setTextSize(dp(9));
            String val=valueText(value(r),r);
            float tw=text.measureText(val);
            c.drawText(val,x+Math.max(0,(barW-tw)/2),Math.max(top+dp(12),bottom-barH-dp(5)),text);
            String label=MarketFlowStyle.shortLabel(r.itemType,r.label);
            float lw=text.measureText(label);
            c.drawText(label,x+Math.max(0,(barW-lw)/2),h-dp(20),text);
            String currency=MarketFlowStyle.currencyShort(r.currency);
            text.setTextSize(dp(8));
            text.setColor(Color.argb(210,210,220,228));
            float cw=text.measureText(currency);
            c.drawText(currency,x+Math.max(0,(barW-cw)/2),h-dp(8),text);
        }
    }
}
