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

/** Animated, resolution-independent status art for in-app notices. */
public final class NoticeIconView extends View {
    public static final int SUCCESS = 1;
    public static final int ERROR = 2;
    public static final int WARNING = 3;
    public static final int INFO = 4;

    private final Paint fill = new Paint(Paint.ANTI_ALIAS_FLAG);
    private final Paint stroke = new Paint(Paint.ANTI_ALIAS_FLAG);
    private final Path symbol = new Path();
    private final RectF rect = new RectF();
    private final int kind;
    private final int accent;
    private ValueAnimator animator;
    private float phase;

    public NoticeIconView(Context context, int noticeKind, int noticeAccent) {
        super(context);
        kind = noticeKind;
        accent = noticeAccent;
        setLayerType(View.LAYER_TYPE_SOFTWARE, null);
        stroke.setStyle(Paint.Style.STROKE);
        stroke.setStrokeCap(Paint.Cap.ROUND);
        stroke.setStrokeJoin(Paint.Join.ROUND);
        setImportantForAccessibility(View.IMPORTANT_FOR_ACCESSIBILITY_NO);
    }

    private float dp(float value) {
        return value * getResources().getDisplayMetrics().density;
    }

    private void startMotion() {
        if (animator != null && animator.isRunning()) return;
        animator = ValueAnimator.ofFloat(0f, 1f);
        animator.setDuration(2400L);
        animator.setRepeatCount(ValueAnimator.INFINITE);
        animator.setInterpolator(new LinearInterpolator());
        animator.addUpdateListener(new ValueAnimator.AnimatorUpdateListener() {
            @Override public void onAnimationUpdate(ValueAnimator animation) {
                phase = (Float) animation.getAnimatedValue();
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
        float size = Math.min(w, h), cx = w * .5f, cy = h * .5f;
        float pulse = (float) ((Math.sin(phase * Math.PI * 2.0) + 1.0) * .5);

        // Soft breathing halo behind the icon tile.
        fill.setShader(null);
        fill.setStyle(Paint.Style.FILL);
        fill.setColor(Color.argb((int) (26 + 22 * pulse), Color.red(accent), Color.green(accent), Color.blue(accent)));
        fill.setShadowLayer(dp(9 + 3 * pulse), 0, dp(2), Color.argb(100, Color.red(accent), Color.green(accent), Color.blue(accent)));
        canvas.drawCircle(cx, cy, size * (.43f + .025f * pulse), fill);
        fill.clearShadowLayer();

        // Layered rounded tile with a diagonal, glassy gradient.
        float inset = size * .12f;
        rect.set(inset, inset, w - inset, h - inset);
        int dark = Color.rgb(
                Math.max(10, (int) (Color.red(accent) * .18f)),
                Math.max(13, (int) (Color.green(accent) * .18f)),
                Math.max(18, (int) (Color.blue(accent) * .18f)));
        fill.setShader(new LinearGradient(rect.left, rect.top, rect.right, rect.bottom,
                new int[]{Color.argb(245, Color.red(accent), Color.green(accent), Color.blue(accent)), dark},
                new float[]{0f, 1f}, Shader.TileMode.CLAMP));
        canvas.drawRoundRect(rect, size * .23f, size * .23f, fill);
        fill.setShader(null);

        stroke.setStrokeWidth(dp(1.25f));
        stroke.setColor(Color.argb(185, 255, 255, 255));
        canvas.drawRoundRect(rect, size * .23f, size * .23f, stroke);

        // Orbiting highlights make the badge feel alive without distracting.
        canvas.save();
        canvas.rotate(phase * 360f, cx, cy);
        rect.set(size * .055f, size * .055f, w - size * .055f, h - size * .055f);
        stroke.setStrokeWidth(dp(1.5f));
        stroke.setColor(Color.argb(150, Color.red(accent), Color.green(accent), Color.blue(accent)));
        canvas.drawArc(rect, -62f, 82f, false, stroke);
        stroke.setColor(Color.argb(55, 255, 255, 255));
        canvas.drawArc(rect, 128f, 38f, false, stroke);
        canvas.restore();

        drawSymbol(canvas, cx, cy, size);
        drawSpark(canvas, size * .77f, size * .22f, size * (.035f + .012f * pulse));
    }

    private void drawSymbol(Canvas canvas, float cx, float cy, float size) {
        stroke.setShader(null);
        stroke.setColor(Color.WHITE);
        stroke.setStrokeWidth(dp(kind == WARNING ? 3.4f : 3.1f));
        symbol.reset();
        if (kind == SUCCESS) {
            symbol.moveTo(cx - size * .18f, cy + size * .01f);
            symbol.lineTo(cx - size * .045f, cy + size * .15f);
            symbol.lineTo(cx + size * .21f, cy - size * .15f);
            canvas.drawPath(symbol, stroke);
        } else if (kind == ERROR) {
            symbol.moveTo(cx - size * .145f, cy - size * .145f);
            symbol.lineTo(cx + size * .145f, cy + size * .145f);
            symbol.moveTo(cx + size * .145f, cy - size * .145f);
            symbol.lineTo(cx - size * .145f, cy + size * .145f);
            canvas.drawPath(symbol, stroke);
        } else if (kind == WARNING) {
            canvas.drawLine(cx, cy - size * .18f, cx, cy + size * .045f, stroke);
            fill.setColor(Color.WHITE);
            fill.setStyle(Paint.Style.FILL);
            canvas.drawCircle(cx, cy + size * .16f, dp(2.1f), fill);
        } else {
            fill.setColor(Color.WHITE);
            fill.setStyle(Paint.Style.FILL);
            canvas.drawCircle(cx, cy - size * .15f, dp(2.2f), fill);
            canvas.drawRoundRect(new RectF(cx - dp(1.8f), cy - size * .035f, cx + dp(1.8f), cy + size * .18f), dp(2), dp(2), fill);
        }
    }

    private void drawSpark(Canvas canvas, float x, float y, float radius) {
        stroke.setStrokeWidth(dp(1.2f));
        stroke.setColor(Color.argb(215, 255, 255, 255));
        canvas.drawLine(x - radius, y, x + radius, y, stroke);
        canvas.drawLine(x, y - radius, x, y + radius, stroke);
    }
}
