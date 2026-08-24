package com.tm.kintaramarket;

import android.content.Context;
import android.graphics.BlurMaskFilter;
import android.graphics.Canvas;
import android.graphics.Color;
import android.graphics.LinearGradient;
import android.graphics.Paint;
import android.graphics.Path;
import android.graphics.PathMeasure;
import android.graphics.RectF;
import android.graphics.Shader;
import android.view.MotionEvent;
import android.view.View;

import java.text.SimpleDateFormat;
import java.util.ArrayList;
import java.util.Date;
import java.util.HashMap;
import java.util.List;
import java.util.Locale;
import java.util.Map;
import java.util.TimeZone;

/** Animated native 30-day market chart with touch inspection. */
public final class MarketChartView extends View {
    private static final long DAY_MS = 86400000L;
    private static final int DAYS = 30;
    private static final class P { long dayMs; double unit; int sales; boolean traded; }

    private final Paint grid = new Paint(Paint.ANTI_ALIAS_FLAG);
    private final Paint line = new Paint(Paint.ANTI_ALIAS_FLAG);
    private final Paint glow = new Paint(Paint.ANTI_ALIAS_FLAG);
    private final Paint fill = new Paint(Paint.ANTI_ALIAS_FLAG);
    private final Paint text = new Paint(Paint.ANTI_ALIAS_FLAG);
    private final Paint dot = new Paint(Paint.ANTI_ALIAS_FLAG);
    private final Paint sweep = new Paint(Paint.ANTI_ALIAS_FLAG);
    private final List<P> points = new ArrayList<>();
    private final SimpleDateFormat dateFmt = new SimpleDateFormat("MMM d", Locale.US);
    private boolean token;
    private int selected = -1, firstIdx = -1, tradedDays = 0;
    private double lo = 0, hi = 1, changePct = 0;
    private long animationStartedMs = System.currentTimeMillis();

    public MarketChartView(Context context) {
        super(context);
        dateFmt.setTimeZone(TimeZone.getTimeZone("UTC"));
        setMinimumHeight(dp(196));
        setLayerType(View.LAYER_TYPE_SOFTWARE, null);
        setContentDescription("Interactive price history chart");
    }

    public void setData(List<KintaraApi.HistoryPoint> source, boolean isToken) {
        token = isToken;
        selected = -1;
        points.clear();
        tradedDays = 0;
        firstIdx = -1;
        long today = Math.floorDiv(System.currentTimeMillis(), DAY_MS);
        long start = today - (DAYS - 1);
        Map<Long,KintaraApi.HistoryPoint> byDay = new HashMap<>();
        if (source != null) for (KintaraApi.HistoryPoint p : source) {
            if (p == null || p.unit <= 0) continue;
            long day = Math.floorDiv(p.dayMs, DAY_MS);
            if (day >= start && day <= today) byDay.put(day, p);
        }
        Double carry = null;
        for (int i = 0; i < DAYS; i++) {
            long day = start + i;
            KintaraApi.HistoryPoint hp = byDay.get(day);
            P p = new P();
            p.dayMs = day * DAY_MS;
            if (hp != null) {
                p.unit = hp.unit;
                p.sales = Math.max(0, hp.sales);
                p.traded = true;
                carry = hp.unit;
                tradedDays++;
                if (firstIdx < 0) firstIdx = i;
            } else if (carry != null) p.unit = carry;
            else p.unit = Double.NaN;
            points.add(p);
        }
        lo = Double.POSITIVE_INFINITY;
        hi = Double.NEGATIVE_INFINITY;
        if (firstIdx >= 0) for (int i = firstIdx; i < points.size(); i++) {
            double unit = points.get(i).unit;
            if (Double.isFinite(unit) && unit > 0) { lo = Math.min(lo, unit); hi = Math.max(hi, unit); }
        }
        if (!Double.isFinite(lo)) { lo = 0; hi = 1; }
        else if (Math.abs(hi - lo) < 1e-9) {
            double base = lo;
            lo = base * .9;
            hi = base * 1.1;
            if (hi <= lo) hi = lo + 1;
        }
        if (firstIdx >= 0 && tradedDays >= 2) {
            double first = points.get(firstIdx).unit;
            double last = points.get(points.size() - 1).unit;
            changePct = first > 0 ? (last - first) / first * 100.0 : 0;
        } else changePct = 0;
        animationStartedMs = System.currentTimeMillis();
        invalidate();
    }

    private int dp(int n) { return (int) (n * getResources().getDisplayMetrics().density + .5f); }
    private float dp(float n) { return n * getResources().getDisplayMetrics().density; }
    private float sp(float n) { return n * getResources().getDisplayMetrics().scaledDensity; }
    private String price(double value) { return token ? String.format(Locale.US,"$%.4f",value).replaceAll("0+$","").replaceAll("\\.$","") : String.format(Locale.US,"%,.0f g",value); }
    private float xFor(int index,float left,float plotWidth) { return left + plotWidth * index / (DAYS - 1f); }
    private float yFor(double unit,float bottom,float plotHeight) { return bottom - (float) ((unit - lo) / (hi - lo)) * plotHeight; }

    private Path makeCurve(float left,float bottom,float plotWidth,float plotHeight) {
        Path path = new Path();
        boolean first = true;
        float previousX = 0, previousY = 0;
        for (int i = firstIdx; i < points.size(); i++) {
            P p = points.get(i);
            if (!Double.isFinite(p.unit)) continue;
            float x = xFor(i,left,plotWidth), y = yFor(p.unit,bottom,plotHeight);
            if (first) { path.moveTo(x,y); first = false; }
            else {
                float mid = (previousX + x) * .5f;
                path.cubicTo(mid,previousY,mid,y,x,y);
            }
            previousX = x; previousY = y;
        }
        return path;
    }

    @Override protected void onDraw(Canvas canvas) {
        super.onDraw(canvas);
        int width = getWidth(), height = getHeight();
        if (width <= 0 || height <= 0) return;
        int accent = token ? Color.rgb(91, 234, 181) : Color.rgb(255, 194, 83);
        float left = dp(12), right = width - dp(12), top = dp(40), bottom = height - dp(31);
        float plotHeight = Math.max(1,bottom-top), plotWidth = Math.max(1,right-left);

        Paint panel = new Paint(Paint.ANTI_ALIAS_FLAG);
        panel.setShader(new LinearGradient(0,top,0,bottom,Color.argb(65,27,45,57),Color.argb(12,15,22,30),Shader.TileMode.CLAMP));
        canvas.drawRoundRect(new RectF(dp(2),dp(29),width-dp(2),height-dp(21)),dp(14),dp(14),panel);

        grid.setStrokeWidth(dp(1));
        grid.setColor(Color.argb(48,133,150,166));
        for (int i=0;i<=4;i++) {
            float y=top+plotHeight*i/4f;
            canvas.drawLine(left,y,right,y,grid);
        }
        grid.setColor(Color.argb(24,133,150,166));
        for (int i=0;i<=5;i++) {
            float x=left+plotWidth*i/5f;
            canvas.drawLine(x,top,x,bottom,grid);
        }

        String change=(Math.abs(changePct)<.5?"= ":(changePct>0?"▲ ":"▼ "))+(Math.abs(changePct)>=10?String.format(Locale.US,"%.0f%%",Math.abs(changePct)):String.format(Locale.US,"%.1f%%",Math.abs(changePct)));
        text.setTextSize(sp(12));text.setColor(accent);text.setFakeBoldText(true);
        canvas.drawText("30 days",left,dp(20),text);
        canvas.drawText(change,right-text.measureText(change),dp(20),text);
        text.setFakeBoldText(false);

        if (tradedDays < 2) {
            text.setTextSize(sp(11));text.setColor(Color.rgb(154,164,178));
            String message=tradedDays==0?"No sales yet":"More sales are needed for a trend";
            canvas.drawText(message,left,top+plotHeight/2,text);
            drawFooter(canvas,left,right,height,plotWidth);
            return;
        }

        long now=System.currentTimeMillis();
        float reveal=Math.min(1f,(now-animationStartedMs)/850f);
        float phase=(now%2600L)/2600f;
        Path fullPath=makeCurve(left,bottom,plotWidth,plotHeight);
        PathMeasure measure=new PathMeasure(fullPath,false);
        Path visiblePath=new Path();
        measure.getSegment(0,measure.getLength()*reveal,visiblePath,true);

        Path area=new Path(fullPath);
        area.lineTo(right,bottom);
        area.lineTo(xFor(firstIdx,left,plotWidth),bottom);
        area.close();
        fill.setStyle(Paint.Style.FILL);
        fill.setShader(new LinearGradient(0,top,0,bottom,Color.argb(118,Color.red(accent),Color.green(accent),Color.blue(accent)),Color.argb(2,Color.red(accent),Color.green(accent),Color.blue(accent)),Shader.TileMode.CLAMP));
        canvas.save();
        canvas.clipRect(left-dp(2),top-dp(10),left+plotWidth*reveal+dp(8),bottom+dp(4));
        canvas.drawPath(area,fill);
        canvas.restore();
        fill.setShader(null);

        glow.setStyle(Paint.Style.STROKE);glow.setStrokeCap(Paint.Cap.ROUND);glow.setStrokeJoin(Paint.Join.ROUND);glow.setStrokeWidth(dp(7));glow.setColor(Color.argb(115,Color.red(accent),Color.green(accent),Color.blue(accent)));glow.setMaskFilter(new BlurMaskFilter(dp(7),BlurMaskFilter.Blur.NORMAL));canvas.drawPath(visiblePath,glow);glow.setMaskFilter(null);
        line.setStyle(Paint.Style.STROKE);line.setStrokeCap(Paint.Cap.ROUND);line.setStrokeJoin(Paint.Join.ROUND);line.setStrokeWidth(dp(2));line.setColor(accent);canvas.drawPath(visiblePath,line);

        float sweepX=left+(plotWidth+dp(90))*phase-dp(45);
        sweep.setShader(new LinearGradient(sweepX-dp(34),0,sweepX+dp(34),0,new int[]{Color.TRANSPARENT,Color.argb(42,Color.red(accent),Color.green(accent),Color.blue(accent)),Color.TRANSPARENT},null,Shader.TileMode.CLAMP));
        canvas.save();canvas.clipRect(left,top,right,bottom);canvas.drawRect(sweepX-dp(34),top,sweepX+dp(34),bottom,sweep);canvas.restore();sweep.setShader(null);

        int index=selected>=firstIdx?selected:points.size()-1;
        P pick=points.get(index);
        float sx=xFor(index,left,plotWidth),sy=yFor(pick.unit,bottom,plotHeight);
        float pulse=(float)((Math.sin(phase*Math.PI*2)+1)*.5);
        dot.setStyle(Paint.Style.FILL);dot.setColor(Color.argb((int)(70*(1-pulse)),Color.red(accent),Color.green(accent),Color.blue(accent)));canvas.drawCircle(sx,sy,dp(6)+(dp(5)*pulse),dot);
        dot.setColor(accent);canvas.drawCircle(sx,sy,dp(selected>=0?5:4),dot);
        dot.setColor(Color.WHITE);canvas.drawCircle(sx,sy,dp(1.5f),dot);

        if (selected>=firstIdx) {
            Paint cross=new Paint(grid);cross.setColor(Color.argb(125,205,218,229));canvas.drawLine(sx,top,sx,bottom,cross);
            text.setTextSize(sp(10));text.setColor(Color.rgb(238,242,247));
            String activity=pick.traded?(pick.sales+(pick.sales==1?" sale":" sales")):"no sales";
            String read=dateFmt.format(new Date(pick.dayMs))+"  •  "+price(pick.unit)+"  •  "+activity;
            canvas.drawText(read,left,dp(36),text);
        }
        drawFooter(canvas,left,right,height,plotWidth);
        if (isAttachedToWindow()) postInvalidateOnAnimation();
    }

    private void drawFooter(Canvas canvas,float left,float right,int height,float plotWidth) {
        text.setTextSize(sp(9));text.setColor(Color.rgb(154,164,178));
        String low="low "+price(lo), high="high "+price(hi), traded=tradedDays+" active days";
        canvas.drawText(low,left,height-dp(8),text);
        canvas.drawText(high,left+(plotWidth-text.measureText(high))/2,height-dp(8),text);
        canvas.drawText(traded,right-text.measureText(traded),height-dp(8),text);
    }

    @Override public boolean onTouchEvent(MotionEvent event) {
        if (tradedDays<2) return true;
        float left=dp(12),right=getWidth()-dp(12);
        if (event.getAction()==MotionEvent.ACTION_DOWN||event.getAction()==MotionEvent.ACTION_MOVE) {
            float fraction=Math.max(0,Math.min(1,(event.getX()-left)/Math.max(1,right-left)));
            selected=Math.max(firstIdx,Math.round(fraction*(DAYS-1)));
            invalidate();return true;
        }
        if (event.getAction()==MotionEvent.ACTION_UP||event.getAction()==MotionEvent.ACTION_CANCEL) {
            postDelayed(new Runnable(){@Override public void run(){selected=-1;invalidate();}},900L);
            return true;
        }
        return true;
    }
}
