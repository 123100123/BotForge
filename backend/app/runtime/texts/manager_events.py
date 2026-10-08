"""Persian copy of the manager's event management in Telegram (``runtime/manager_events.py``).

Fixed product copy like ``texts/nav.py``: not overridable through ``cap.texts`` and not a capability
type module (``TEXTS`` stays empty). Templates with ``{...}`` are filled with
``botspec.text_keys.fill_text``. ``{label}`` is the event resource's singular noun («رویداد»,
«کارگاه»), ``{plural}`` its plural («رویدادها»). Numbers and dates are filled in Persian digits.
"""

TEXTS: dict[str, str] = {}  # not a capability type module (see the docstring)

# --- list ----------------------------------------------------------------------------------------

LIST_HEADING = "📅 {plural}"  # breadcrumb title after «🧭 مدیریت»
NEW_BUTTON = "➕ {label} جدید"
UPCOMING_TITLE = "پیش رو"
PAST_TITLE = "گذشته"
PAST_BUTTON = "🕘 گذشته"
UPCOMING_BUTTON = "📅 پیش رو"
UPCOMING_COUNT = "{count} {label} پیش رو. برای مدیریت روی هر کدام بزنید."
PAST_COUNT = "{count} {label} برگزار شده."
UPCOMING_EMPTY = "{label} پیش رویی ندارید. با «➕ {label} جدید» اولین را بسازید."
PAST_EMPTY = "هنوز {label} برگزارشده‌ای ندارید."
MANAGER_BUTTON = "🧭 مدیریت"
GOING_OF = "{going}/{capacity}"
GOING = "{going} نفر"
NO_DATE = "بی‌تاریخ"

# --- creation form -------------------------------------------------------------------------------

NEW_TITLE = "➕ {label} جدید"  # breadcrumb title of the form
STEP_LINE = "مرحلهٔ {n} از {total}: {name}"
DATE_STEP = "تاریخ"
TIME_STEP = "ساعت"
ASK_TITLE = "عنوان {label} را بنویسید."
ASK_DESCRIPTION = "توضیح کوتاهی دربارهٔ {label} بنویسید."
ASK_DATE = "تاریخ «{name}» را انتخاب کنید."
ASK_DATE_START = "تاریخ برگزاری را انتخاب کنید."
ASK_DATE_TYPED = (
    "تاریخ را به شمسی بنویسید، مثلاً «۱۴۰۵/۷/۲۰» یا «1405-07-20».\n"
    "اگر سال را ننویسید («۷/۲۰»)، سال جاری در نظر گرفته می‌شود."
)
ASK_TIME = "ساعت «{name}» را انتخاب کنید یا بنویسید (مثلاً «۱۸:۳۰»)."
ASK_TIME_START = "ساعت شروع را انتخاب کنید یا بنویسید (مثلاً «۱۸:۳۰»)."
ASK_TIME_NONE_LEFT = "برای امروز ساعتی باقی نمانده است. ساعت را بنویسید یا تاریخ را عوض کنید."
ASK_CHOICE = "«{name}» را انتخاب کنید."
ASK_LOCATION = "محل برگزاری را بنویسید."
ASK_CAPACITY = "ظرفیت را بنویسید یا یکی از گزینه‌ها را بزنید."
ASK_BOOLEAN = "«{name}»؟"
ASK_TEXT = "«{name}» را بنویسید."
ASK_NUMBER = "«{name}» را به عدد بنویسید."
OPTIONAL = "(اختیاری)"
CURRENT_VALUE = "مقدار فعلی: {value}"
USE_BUTTONS = "لطفاً یکی از دکمه‌ها را بزنید."
STEP_STALE = "این دکمه مربوط به مرحلهٔ دیگری است. مرحلهٔ فعلی:"

INVALID_DATE = "«{text}» تاریخ معتبری نیست. تاریخ را مثل «۱۴۰۵/۷/۲۰» بنویسید."
PAST_DATE = "این تاریخ گذشته است. تاریخی از امروز به بعد انتخاب کنید."
INVALID_TIME = "«{text}» ساعت معتبری نیست. ساعت را مثل «۱۸:۳۰» بنویسید."
PAST_TIME = "این زمان گذشته است. ساعت یا تاریخ دیگری انتخاب کنید."
INVALID_CAPACITY = "ظرفیت باید عددی از ۱ به بالا باشد."
INVALID_ANSWER = "این پاسخ پذیرفته نشد: {error}"

TYPE_DATE = "✍️ تاریخ دیگر را بنویسید"
KEEP = "✔ بدون تغییر"
SKIP = "رد کردن"
UNLIMITED = "بدون محدودیت"
BACK = "‹ بازگشت"
CANCEL = "✖ لغو"
YES = "بله"
NO = "خیر"

PREVIEW_HEADING = "پیش‌نمایش {label}:"
PREVIEW_HINT = "اگر درست است «انتشار» را بزنید."
PUBLISH = "✅ انتشار"
EDIT = "✏️ ویرایش"
CANCELLED = "ساخت {label} لغو شد."
CREATED = "{label} ثبت شد و برای مشتریان نمایش داده می‌شود."
CREATE_FAILED = "{label} ثبت نشد: {error}\nلطفاً این مرحله را درست کنید."
PUBLISH_IN_GROUP = "📣 انتشار در گروه"
VIEW_EVENT = "مشاهدهٔ {label}"
EVENTS_BUTTON = "📅 {plural}"

# --- detail --------------------------------------------------------------------------------------

DETAIL_WHEN = "🗓 {when}"
DETAIL_PLACE = "📍 {place}"
DETAIL_CATEGORY = "🏷 {category}"
DETAIL_CAPACITY = "👥 ظرفیت: {capacity}"
UNLIMITED_CAPACITY = "بدون محدودیت"
DETAIL_COUNTS = "✅ قطعی: {confirmed} · ⏳ در انتظار: {waitlisted}"
DETAIL_COUNTS_NO_WAITLIST = "✅ ثبت‌نام: {confirmed}"
DETAIL_PAST = "این {label} برگزار شده است."
ATTENDEES_BUTTON = "👥 شرکت‌کنندگان ({count})"
ANNOUNCE_BUTTON = "📣 اعلان به ثبت‌نام‌شدگان"
BACK_TO_LIST = "🧭 بازگشت به {plural}"
NOT_FOUND = "این {label} دیگر وجود ندارد."

# --- attendees -----------------------------------------------------------------------------------

ATTENDEES_TITLE = "شرکت‌کنندگان"
ATTENDEES_EMPTY = "هنوز کسی ثبت‌نام نکرده است."
ATTENDEE_LINE = "{n}. {name} — {status}"
STATUS_CONFIRMED = "قطعی"
STATUS_WAITLISTED = "در انتظار (نوبت {position})"
CANCEL_ATTENDEE = "✖ لغو ثبت‌نام {name}"
CONFIRM_CANCEL = "ثبت‌نام «{name}» در «{title}» لغو شود؟ به او خبر داده می‌شود."
CONFIRM_CANCEL_YES = "بله، لغو شود"
BOOKING_GONE = "این ثبت‌نام دیگر فعال نیست."
BACK_TO_ATTENDEES = "‹ شرکت‌کنندگان"
BACK_TO_EVENT = "‹ بازگشت به {label}"
UNKNOWN_PERSON = "کاربر {id}"

# --- announce ------------------------------------------------------------------------------------

ANNOUNCE_TITLE = "📣 اعلان"
ANNOUNCE_ASK = "متن اعلان را بنویسید. برای {count} نفر ثبت‌نام‌شدهٔ قطعی فرستاده می‌شود."
ANNOUNCE_NOBODY = "هنوز کسی ثبت‌نام قطعی ندارد؛ اعلان گیرنده‌ای ندارد."
ANNOUNCE_PREVIEW = "پیش‌نمایش اعلان برای {count} نفر:\n\n{message}"
ANNOUNCE_SEND = "📣 ارسال برای {count} نفر"
ANNOUNCE_REWRITE = "✏️ نوشتن دوباره"
ANNOUNCE_TOO_LONG = "متن اعلان حداکثر {max} نویسه است. کوتاه‌ترش کنید."
ANNOUNCE_EMPTY = "متن اعلان خالی است. لطفاً متن را بنویسید."
ANNOUNCE_MESSAGE = "📣 {title}\n\n{message}"
ANNOUNCE_SENT = "اعلان برای {count} نفر در صف ارسال قرار گرفت."
ANNOUNCE_CANCELLED = "ارسال اعلان لغو شد."

# --- group publish -------------------------------------------------------------------------------

GROUPS_ASK = "کارت «{title}» در کدام گروه منتشر شود؟"
GROUP_QUEUED = "کارت «{title}» در صف انتشار در «{group}» قرار گرفت."
GROUP_GONE = "ربات دیگر عضو این گروه نیست یا گروه پیدا نشد."
NO_GROUPS = "ربات هنوز عضو هیچ گروهی نیست. اول ربات را به گروه اضافه کنید."
ATTENDEE_CANCELLED = "ثبت‌نام «{name}» لغو شد و به او خبر داده شد."
