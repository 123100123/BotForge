"""Persian texts owned by the Telegram integration (not by any capability engine)."""

NOT_READY = "این ربات هنوز آماده نیست. لطفاً کمی بعد دوباره تلاش کنید."
OWNER_LINKED = "حساب شما به‌عنوان مدیر این ربات ثبت شد. از این پس اعلان‌های ربات را اینجا دریافت می‌کنید."
OWNER_LINK_INVALID = "این لینک نامعتبر است یا قبلاً استفاده شده است. لینک جدید را از بخش تنظیمات ربات بگیرید."

# Onboarding / API errors shown to the owner in the web app.
INVALID_TOKEN = "توکن ربات نامعتبر است. توکن را دقیقاً از BotFather کپی کنید."
TOKEN_IN_USE = (
    "ربات تلگرام @{username} قبلاً به کسب‌وکار دیگری در این سامانه وصل شده است. اول آن را از آنجا جدا کنید."
)
TOKEN_IN_USE_ELSEWHERE = (
    "این ربات تلگرام همین حالا به سرور دیگری وصل است (یک نسخهٔ دیگر BotForge یا برنامهٔ دیگری). "
    "اول آن را از آنجا جدا کنید، بعد دوباره امتحان کنید."
)
# Stored in bots.tg_last_error when the poller parks a bot; the prefix is a stable marker the web app
# matches on (do not translate or change it).
POLLING_CONFLICT_PREFIX = "POLLING_CONFLICT:"
POLLING_CONFLICT = (
    f"{POLLING_CONFLICT_PREFIX} این ربات تلگرام هم‌زمان در سرور دیگری فعال است؛ این سرور دریافت پیام‌ها را "
    "متوقف کرد تا تداخل پیش نیاید. اگر سرور دیگر را خاموش کرده‌اید، «تلاش دوباره» را بزنید."
)
TELEGRAM_UNREACHABLE = "ارتباط با تلگرام برقرار نشد. کمی بعد دوباره تلاش کنید."
TELEGRAM_REJECTED = "تلگرام درخواست را نپذیرفت: {description}"
PUBLIC_URL_MISSING = "آدرس عمومی سرور (PUBLIC_BASE_URL) تنظیم نشده است؛ اتصال به تلگرام ممکن نیست."
SERVER_MISCONFIGURED = "تنظیمات رمزنگاری سرور کامل نیست؛ اتصال به تلگرام ممکن نیست."
