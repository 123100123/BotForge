"""Central Persian copy for Telegram navigation (``runtime/nav.py``): entry labels, headings,
breadcrumbs, Back/Home, the stale and error notices.

These strings are fixed product copy, not bot texts: they are not overridable through ``cap.texts``
and no capability type is called ``nav``, so ``texts.default_texts`` never reads this module as a
type module (``TEXTS`` stays empty for that reason). Business nouns (a resource's
``label_plural``, a capability's ``title``, the bot's name) are filled in by the compiler; templates
with ``{...}`` are filled with ``botspec.text_keys.fill_text``.

Emojis are anchors on entries only, one per kind of entry, used the same way in every bot.
"""

TEXTS: dict[str, str] = {}  # not a capability type module (see the docstring)

# --- shared chrome ---------------------------------------------------------------------------------

HOME = "🏠 خانه"
BACK = "‹ بازگشت"
CRUMB_SEPARATOR = " › "

# --- customer (user) home ------------------------------------------------------------------------

HOME_HEADING = "🏠 {business}"
HOME_HINT = "یکی از گزینه‌های زیر را انتخاب کنید."
HOME_EMPTY = "فعلاً بخشی برای شما فعال نیست."

SHOP = "🛍 فروشگاه"
SHOP_NAMED = "🛍 {title}"  # several orders capabilities: each shop by its own title
BROWSE = "🗂 {label}"  # a catalog (browse only), by its resource's plural label
CART = "🛒 سبد خرید"
MY_ORDERS = "📦 سفارش‌های من"
MY_ORDERS_NAMED = "📦 سفارش‌های من · {title}"
EVENTS = "📅 {label}"  # events booking, by its resource's plural label («📅 کارگاه‌ها»)
MY_EVENTS = "🗓 ثبت‌نام‌های من"
MY_EVENTS_NAMED = "🗓 ثبت‌نام‌های من · {label}"
BOOKING = "📅 {label}"  # plain booking, by its resource's plural label
MY_BOOKINGS = "🗓 رزروهای من"
MY_BOOKINGS_NAMED = "🗓 رزروهای من · {label}"
SUPPORT = "📝 پشتیبانی"  # a request capability keyed "support"
REQUEST = "📝 {title}"  # any other request capability, by its title
MY_REQUESTS = "درخواست‌های من"
INFO = "ℹ️ {title}"
PRODUCT = "محصول"
STAFF_QUEUE = "📋 صف درخواست‌ها"

# --- manager home --------------------------------------------------------------------------------

MANAGER_HEADING = "🧭 مدیریت {business}"
MANAGER_SHORT = "🧭 مدیریت"
MANAGER_HINT = "یکی از بخش‌های زیر را انتخاب کنید."
ATTENTION_HEADING = "نیازمند توجه:"
MANAGE_ORDERS = "📦 سفارش‌ها"
MANAGE_EVENTS = "📅 مدیریت رویدادها"
NEW_EVENT = "➕ رویداد جدید"
MANAGE_REQUESTS = "📝 درخواست‌ها"
REPORTS = "📊 گزارش‌ها"
TEAM = "👥 کارکنان"
CUSTOMER_VIEW = "👁 نمای مشتری"
CUSTOMER_VIEW_NOTE = "👁 نمای مشتری: مشتری‌ها ربات را این‌طور می‌بینند."
COMING_SOON = "این بخش هنوز در تلگرام آماده نیست. فعلاً از پنل وب استفاده کنید."

# --- stale and error -----------------------------------------------------------------------------

STALE = "این منو قدیمی شده است."
STALE_BUTTON = "نمایش منوی فعلی"
ERROR = "نتوانستم این کار را انجام دهم. لطفاً دوباره امتحان کنید."
RETRY = "تلاش دوباره"
