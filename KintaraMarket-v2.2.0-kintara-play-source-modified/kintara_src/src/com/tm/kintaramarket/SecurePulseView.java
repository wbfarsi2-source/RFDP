package com.tm.kintaramarket;

import android.animation.ValueAnimator;
import android.content.Context;
import android.graphics.Canvas;
import android.graphics.Color;
import android.graphics.LinearGradient;
import android.graphics.Paint;
import android.graphics.Path;
import android.graphics.RectF;
import android.graphics.Shader;
import android.view.View;
import android.view.animation.LinearInterpolator;

/** A lightweight animated shield-and-lock illustration for secure actions. */
public final class SecurePulseView extends View {
    private final Paint paint = new Paint(Paint.ANTI_ALIAS_FLAG);
    private final Paint stroke = new Paint(Paint.ANTI_ALIAS_FLAG);
    private final Path shield = new Path();
    private final RectF arc = new RectF();
    private ValueAnimator animator;
    private float phase;

    public SecurePulseView(Context context) {
        super(context);
        setLayerType(View.LAYER_TYPE_SOFTWARE, null);
        stroke.setStyle(Paint.Style.STROKE);
        stroke.setStrokeCap(Paint.Cap.ROUND);
        stroke.setStrokeJoin(Paint.Join.ROUND);
        setContentDescription("Secure purchase");
    }

    private float dp(float value) {
        return value * getResources().getDisplayMetrics().density;
    }

    private void startMotion() {
        if (animator != null && animator.isRunning()) return;
        animator = ValueAnimator.ofFloat(0f, 1f);
        animator.setDuration(2200L);
        animator.setRepeatCount(ValueAnimator.INFINITE);
        animator.setInterpolator(new LinearInterpolator());
        animator.addUpdateListener(new ValueAnimator.AnimatorUpdateListener() {
            @Override public void onAnimationUpdate(ValueAnimator valueAnimator) {
                phase = (Float) valueAnimator.getAnimatedValue();
                invalidate();
            }
        });
        animator.start();
    }

    @Override protected void onAttachedToWindow() {
        super.onAttachedToWindow();
        startMotion();
    }

    @Override protected void onDetachedFromWindow() {
        if (animator != null) animator.cancel();
        animator = null;
        super.onDetachedFromWindow();
    }

    @Override protected void onDraw(Canvas canvas) {
        super.onDraw(canvas);
        float w = getWidth(), h = getHeight();
        if (w <= 0 || h <= 0) return;
        float cx = w * .5f, cy = h * .49f, size = Math.min(w, h);

        float pulse = phase < .5f ? phase * 2f : (1f - phase) * 2f;
        stroke.setStrokeWidth(dp(1.4f));
        stroke.setColor(Color.argb((int) (70 * (1f - pulse)), 72, 205, 141));
        canvas.drawCircle(cx, cy, size * (.31f + .15f * pulse), stroke);

        canvas.save();
        canvas.rotate(phase * 360f, cx, cy);
        arc.set(cx - size * .43f, cy - size * .43f, cx + size * .43f, cy + size * .43f);
        stroke.setStrokeWidth(dp(2.2f));
        stroke.setColor(Color.argb(185, 92, 238, 173));
        canvas.drawArc(arc, -82f, 72f, false, stroke);
        stroke.setColor(Color.argb(80, 87, 183, 255));
        canvas.drawArc(arc, 98f, 42f, false, stroke);
        canvas.restore();

        float top = cy - size * .31f, bottom = cy + size * .32f;
        shield.reset();
        shield.moveTo(cx, top);
        shield.cubicTo(cx - size * .11f, top + size * .06f, cx - size * .24f, top + size * .08f, cx - size * .27f, top + size * .12f);
        shield.lineTo(cx - size * .24f, cy + size * .08f);
        shield.cubicTo(cx - size * .21f, bottom - size * .12f, cx - size * .08f, bottom - size * .02f, cx, bottom);
        shield.cubicTo(cx + size * .08f, bottom - size * .02f, cx + size * .21f, bottom - size * .12f, cx + size * .24f, cy + size * .08f);
        shield.lineTo(cx + size * .27f, top + size * .12f);
        shield.cubicTo(cx + size * .24f, top + size * .08f, cx + size * .11f, top + size * .06f, cx, top);
        shield.close();

        paint.setStyle(Paint.Style.FILL);
        paint.setShader(new LinearGradient(cx - size * .2f, top, cx + size * .2f, bottom,
                new int[]{Color.rgb(23, 151, 112), Color.rgb(28, 92, 103), Color.rgb(34, 50, 72)},
                null, Shader.TileMode.CLAMP));
        paint.setShadowLayer(dp(14), 0, dp(4), Color.argb(95, 35, 220, 157));
        canvas.drawPath(shield, paint);
        paint.clearShadowLayer();
        paint.setShader(null);
        stroke.setStrokeWidth(dp(1.6f));
        stroke.setColor(Color.argb(220, 119, 244, 193));
        canvas.drawPath(shield, stroke);

        float lockW = size * .25f, bodyTop = cy - size * .015f;
        arc.set(cx - lockW * .38f, cy - size * .17f, cx + lockW * .38f, cy + size * .08f);
        stroke.setStrokeWidth(dp(4f));
        stroke.setColor(Color.rgb(224, 255, 244));
        canvas.drawArc(arc, 198f, 144f, false, stroke);
        paint.setColor(Color.rgb(225, 255, 244));
        paint.setStyle(Paint.Style.FILL);
        RectF body = new RectF(cx - lockW * .55f, bodyTop, cx + lockW * .55f, bodyTop + size * .2f);
        canvas.drawRoundRect(body, dp(7), dp(7), paint);
        paint.setColor(Color.rgb(22, 91, 78));
        canvas.drawCircle(cx, bodyTop + size * .075f, dp(3.2f), paint);
        canvas.drawRoundRect(new RectF(cx - dp(1.5f), bodyTop + size * .075f, cx + dp(1.5f), bodyTop + size * .14f), dp(2), dp(2), paint);
    }
}
