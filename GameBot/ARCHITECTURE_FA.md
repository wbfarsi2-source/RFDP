# معماری GameBot Platform v0.7.0

## اصل طراحی

هسته پلتفرم از منطق بازی‌ها جداست. هر بازی مالک API، رابط تلگرام، سرویس‌ها و Runtimeهای خودش است. افزودن یا اصلاح یک بازی نباید فایل‌های بازی دیگر را درگیر کند.

```text
Start/
├── app.py
├── START_GAMEBOT.bat
├── .env.example
├── core/
│   ├── configuration/
│   │   ├── environment.py
│   │   └── runtime.py
│   ├── runtime/
│   │   ├── account_instances/
│   │   │   ├── manager.py
│   │   │   ├── runner.py
│   │   │   └── store.py
│   │   └── shared_services/
│   │       ├── manager.py
│   │       └── store.py
│   ├── services/
│   │   ├── payments/
│   │   ├── notifications/
│   │   └── backups/
│   ├── models.py
│   ├── repositories.py
│   ├── crypto.py
│   └── registry.py
├── telegram/
│   ├── bot.py
│   ├── keyboards.py
│   └── routers/
│       ├── start.py
│       ├── accounts.py
│       ├── payments.py
│       └── admin.py
├── games/
│   ├── base.py
│   └── kintara/
│       ├── manifest.json
│       ├── features.json
│       ├── plugin.py
│       ├── api/
│       │   └── client.py
│       ├── telegram/
│       │   └── router.py
│       ├── purchases/
│       │   ├── service.py
│       │   └── messages.py
│       ├── molten/
│       │   ├── access.py
│       │   ├── channel.py
│       │   └── view.py
│       ├── engine/
│       │   ├── account_engine.py
│       │   └── legacy_engine.py
│       ├── services/
│       │   ├── paid/
│       │   │   ├── runner.py
│       │   │   └── spinner.py
│       │   └── ember/
│       │       ├── monitor.py
│       │       └── runner.py
│       └── runtime/
│           ├── users/
│           └── shared/ember/
├── locales/
│   └── fa_literals.json
├── scripts/
└── data/
    └── gamebot.db
```

## هسته ثابت

هسته فقط مسئول این موارد است:

- کاربران و زبان
- دیتابیس و مهاجرت سازگار
- رمزگذاری اطلاعات اتصال
- سفارش و بررسی پرداخت
- اشتراک و انقضا
- مدیریت Process و Heartbeat
- Restart کنترل‌شده
- تنظیمات ادمین
- اعلان، بکاپ و Proxy
- کش نصب وابستگی‌ها
- کشف خودکار افزونه‌های بازی

هسته نباید Endpoint یا منطق بازی خاصی داشته باشد.

## قرارداد بازی

هر بازی یک Plugin دارد که این موارد را تعریف می‌کند:

- شناسه و نام بازی
- پلن‌ها و امکانات
- اعتبارسنجی اطلاعات اتصال
- ساخت تنظیمات Worker
- اجرای Runtime حساب
- سرویس‌های مشترک بازی

بازی جدید در پوشه مستقل زیر اضافه می‌شود:

```text
games\<game_id>
```

## Kintara

### خرید و فعال‌سازی

منطق خرید Kintara در `purchases/` است. رابط کاربر در `telegram/router.py` قرار دارد. موتور اجرای حساب در `services/paid/` و `engine/` نگهداری می‌شود.

اطلاعات اتصال قبل از پرداخت دریافت نمی‌شود. پس از تأیید نهایی ادمین، Cookie دریافت، از چت حذف، اعتبارسنجی و رمزگذاری می‌شود.

### Runtime حساب کاربر

```text
games\kintara\runtime\users\account_<id>\
├── instance.json
├── owner.json
├── worker.log
├── engine.env
├── engine_errors.log
├── location_settings.json
├── START_ACCOUNT.bat
├── STOP_ACCOUNT.bat
└── stop.request
```

`instance.json` شامل Snapshot اجرایی، پلن، قابلیت‌ها، زمان اشتراک، وضعیت Process، PID و Credential رمزگذاری‌شده است. دیتابیس همچنان منبع اصلی حقیقت است.

### سرویس مشترک مولتن

```text
games\kintara\runtime\shared\ember\
├── service.json
├── snapshot.json
├── service.log
├── START_MOLTEN.bat
├── STOP_MOLTEN.bat
└── refresh.request
```

فقط یک Process مشترک همه سرورها را مانیتور می‌کند. کاربران مجاز از Snapshot مشترک استفاده می‌کنند و برای هر نفر CMD جدا ساخته نمی‌شود.

اولویت Cookie سرویس مشترک:

1. `KINTARA_EMBER_COOKIE`
2. `KINTARA_COOKIE`
3. Admin Override رمزگذاری‌شده، فقط در صورت انتخاب صریح در پنل

Cookie حساب‌های پولی از مسیر بالا خوانده نمی‌شود.

## کنترل دسترسی مولتن و کانال

دسترسی مولتن با `ServiceEntitlement` مدیریت می‌شود.

- حالت رایگان: هنگام ورود کاربر Entitlement بدون تاریخ انقضا ساخته می‌شود
- حالت پولی: Entitlement بعد از پرداخت و تأیید ادمین تا پایان اشتراک معتبر است
- تغییر رایگان به پولی: Entitlementهای رایگان لغو و اعضای مربوط از کانال خارج می‌شوند
- پایان اشتراک: دسترسی ربات و کانال قطع می‌شود
- تمدید: Entitlement فعال و لینک اختصاصی جدید ساخته می‌شود

برای خروج کاربر از کانال، بات ابتدا Ban و بلافاصله Unban می‌کند. این روش عضویت فعلی را قطع می‌کند اما امکان بازگشت قانونی بعد از تمدید را از بین نمی‌برد.

## مدیریت Process

`desired_state` دو مقدار دارد:

```text
running
stopped
```

- بسته‌شدن CMD در حالت `running`: Restart
- Crash در حالت `running`: Restart با محدودیت
- توقف از ربات: تغییر به `stopped`
- پایان اشتراک: تغییر به `stopped`
- غیرفعال‌شدن بازی: توقف Runtimeهای آن بازی

## مهاجرت نسخه‌های قبلی

مسیرهای قدیمی هنگام اولین اجرا به مسیرهای جدید منتقل می‌شوند:

```text
data\instances\kintara\account_*
→ games\kintara\runtime\users\account_*
```

```text
data\shared_services\Ember
→ games\kintara\runtime\shared\ember
```

فایل `.env` و دیتابیس موجود حذف یا بازسازی نمی‌شوند.
