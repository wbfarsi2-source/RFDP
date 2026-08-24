package com.tm.kintaramarket;

import android.content.Context;
import android.graphics.Canvas;
import android.graphics.Paint;
import android.graphics.RectF;
import android.view.View;

/** Lightweight animated wallet/login halo; no external animation dependency. */
public final class WalletPulseView extends View {
    private final Paint paint = new Paint(Paint.ANTI_ALIAS_FLAG);
    private final RectF oval = new RectF();
    private boolean running = true;

    public WalletPulseView(Context c) { super(c); paint.setStyle(Paint.Style.STROKE); }

    @Override protected void onAttachedToWindow() { super.onAttachedToWindow(); running = true; postInvalidateOnAnimation(); }
    @Override protected void onDetachedFromWindow() { running = false; super.onDetachedFromWindow(); }

    @Override protected void onDraw(Canvas c) {
        super.onDraw(c);
        float w=getWidth(), h=getHeight(), cx=w/2f, cy=h/2f, min=Math.min(w,h);
        long now=System.currentTimeMillis();
        float t=(now%2600L)/2600f;
        for(int i=0;i<3;i++){
            float p=(t+i/3f)%1f;
            float radius=min*(0.22f+0.27f*p);
            int alpha=(int)(155*(1f-p));
            paint.setColor((alpha<<24)|(72<<16)|(205<<8)|141);
            paint.setStrokeWidth(Math.max(1f,min*0.008f));
            c.drawCircle(cx,cy,radius,paint);
        }
        float angle=(now%5200L)/5200f*360f;
        paint.setStrokeWidth(Math.max(2f,min*0.012f));
        paint.setColor(0xD948CD8D);
        float r=min*0.39f; oval.set(cx-r,cy-r,cx+r,cy+r);
        c.drawArc(oval,angle,72f,false,paint);
        paint.setColor(0x995BE0A1);
        c.drawArc(oval,angle+180f,42f,false,paint);
        if(running) postInvalidateDelayed(16L);
    }
}
