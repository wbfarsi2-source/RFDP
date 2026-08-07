# نقشه سریع فایل‌ها

این فایل برای پیدا‌کردن سریع بخش موردنظر در بروزرسانی‌های بعدی است.

## تنظیمات

```text
.env.example                         قالب تمام متغیرهای محیطی
core/configuration/environment.py    تعریف تنظیمات فایل env
core/configuration/runtime.py        تنظیمات قابل تغییر از پنل ادمین
```

## دیتابیس و کاربران

```text
core/models.py                       جدول‌های دیتابیس
core/repositories.py                 عملیات خواندن و نوشتن دیتابیس
core/database.py                     اتصال و ساخت دیتابیس
core/crypto.py                       رمزگذاری اطلاعات اتصال
```

## پرداخت و اشتراک

```text
core/services/payments/              بررسی عمومی پرداخت‌ها
games/kintara/purchases/service.py   روند خرید و فعال‌سازی Kintara
games/kintara/purchases/messages.py  پیام‌ها و راهنمای اتصال حساب
telegram/routers/admin.py            تأیید و رد نهایی سفارش توسط ادمین
```

## رابط تلگرام

```text
telegram/routers/start.py            شروع، زبان و منوی اصلی
telegram/routers/accounts.py         حساب‌های کاربر
telegram/routers/admin.py            پنل مدیریت عمومی
telegram/keyboards.py                دکمه‌های عمومی
games/kintara/telegram/router.py     تمام منوها و مراحل کاربر در Kintara
locales/fa_literals.json             تمام متن‌های فارسی
```

## Kintara

```text
games/kintara/plugin.py              پلن‌ها، قیمت‌ها و قابلیت‌ها
games/kintara/features.json          فعال یا مخفی‌بودن قابلیت‌ها
games/kintara/api/client.py          ارتباط HTTP با Kintara
games/kintara/engine/account_engine.py اجرای مدیریت‌شده موتور حساب
games/kintara/engine/legacy_engine.py منطق اصلی ماهیگیری و پخت
games/kintara/services/paid/runner.py مدیریت موتور هر حساب
games/kintara/services/paid/spinner.py مرز مستقل گردونه
games/kintara/shared_credentials.py  Cookie مشترک پروژه
```

## موقعیت مولتن و کانال

```text
games/kintara/molten/access.py       سیاست رایگان یا پولی و Entitlement
games/kintara/molten/view.py         متن کوتاه نتیجه
games/kintara/molten/channel.py      پیام کانال، لینک شخصی و حذف دسترسی
games/kintara/services/ember/monitor.py مانیتور دقیق سرورها
games/kintara/services/ember/runner.py Process مشترک مولتن
```

## CMD و Supervisor

```text
core/runtime/account_instances/store.py    ساخت پوشه و BAT هر حساب
core/runtime/account_instances/manager.py  اجرا، توقف و Restart حساب‌ها
core/runtime/account_instances/runner.py   Process اصلی هر حساب
core/runtime/shared_services/store.py      فایل‌های Runtime مشترک
core/runtime/shared_services/manager.py    اجرای CMD مشترک مولتن
```

## Proxy و راه‌اندازی

```text
START_GAMEBOT.bat                    لانچر ویندوز
scripts/bootstrap_dependencies.py   نصب وابستگی فقط در صورت نیاز
scripts/detect_system_proxy.ps1     تشخیص Proxy ویندوز
core/system_proxy.py                اعمال Proxy در Python و Workerها
scripts/validate_setup.py           بررسی تنظیمات پیش از اجرا
```
