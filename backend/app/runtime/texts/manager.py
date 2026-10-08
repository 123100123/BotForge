"""Central Persian copy for the Telegram manager screens (``runtime/manager.py``,
``runtime/manager_orders.py``, ``runtime/manager_team.py``): the manager home's summary and
attention lines, the orders queue, the team screen and the reports list.

Fixed product copy, like ``texts/nav.py``: not overridable through ``cap.texts`` and not a capability
type module (no capability type is called ``manager``), so ``TEXTS`` stays empty. Business nouns (a
capability's title, a status label, a resource's titles) are filled in by the screens; templates
with ``{...}`` are filled with ``botspec.text_keys.fill_text``. Numbers arrive already in Persian
digits. Emojis are anchors only: 🧭 manager, 📦 orders, 📅 events, 📝 requests, 📊 reports,
👥 team.
"""

TEXTS: dict[str, str] = {}  # not a capability type module (see the docstring)

MANAGER = "🧭 مدیریت"  # the manager-home button and the first breadcrumb of every manager screen

# --- manager home: summary and attention -----------------------------------------------------------

TODAY = "امروز: {parts}"
TODAY_PART_SEPARATOR = " · "
TODAY_NOTHING = "امروز: هنوز موردی ثبت نشده."
TODAY_ORDERS = "{count} سفارش"
TODAY_REGISTRATIONS = "{count} ثبت‌نام"
TODAY_BOOKINGS = "{count} رزرو"
TODAY_REQUESTS = "{count} درخواست"
NOTHING_WAITING = "فعلاً موردی منتظر شما نیست."

ATTENTION_ORDERS = "{count} سفارش «{status}» منتظر رسیدگی"
ATTENTION_ORDERS_NAMED = "{count} سفارش «{status}» در «{title}» منتظر رسیدگی"
ATTENTION_ORDERS_BUTTON = "📦 سفارش‌های {status} ({count})"
ATTENTION_REQUESTS = "{count} درخواست باز در «{title}»"
ATTENTION_REQUESTS_BUTTON = "📝 درخواست‌های باز ({count})"
ATTENTION_EVENT = "رویداد «{title}» · {when} · {going}"
ATTENTION_EVENT_MORE = "و {count} رویداد دیگر در ۲۴ ساعت آینده"
ATTENTION_EVENTS_BUTTON = "📅 رویدادهای ۲۴ ساعت آینده ({count})"
GOING_OF = "{going}/{capacity} نفر"
GOING = "{going} نفر"

# --- orders ----------------------------------------------------------------------------------------

ORDERS_ALL = "همه"
FILTER_BUTTON = "{status} ({count})"
FILTER_ACTIVE = "• {label}"  # the filter being shown
FILTER_LINE = "نمایش: {status} · {count} سفارش"
ORDERS_EMPTY = "سفارشی در این وضعیت نیست."
ORDER_LINE = "#{id} · {customer} · {total} تومان"
ORDER_LINE_WITH_STATUS = "#{id} · {customer} · {total} تومان · {status}"
ORDER_CRUMB = "سفارش #{id}"
ORDER_CUSTOMER = "مشتری: {name}"
ORDER_STATUS = "وضعیت: {status}"
ORDER_WHEN = "ثبت: {when}"
ORDER_ITEMS = "اقلام:"
ORDER_ITEM = "• {title} × {qty} — {total} تومان"
ORDER_TOTAL = "جمع کل: {total} تومان"
ORDER_NO_ACTIONS = "برای این وضعیت کاری تعریف نشده است."
CUSTOMER_UNKNOWN = "مشتری"
BACK_TO_ORDERS = "‹ سفارش‌ها"
VIEW_ORDER = "مشاهدهٔ سفارش"
ACTION_STALE = "این سفارش دیگر قابل این تغییر نیست."
ORDER_GONE = "این سفارش پیدا نشد."
DONE_MARK = "✅ {text}"

# --- requests --------------------------------------------------------------------------------------
# (the queue itself is the request engine's; the manager screen only adds the heading)

# --- team ------------------------------------------------------------------------------------------

ROLE_WORDS: dict[str, str] = {"manager": "مدیر", "staff": "همکار", "customer": "مشتری"}
OWNER_MARK = "مالک"
TEAM_COUNTS = "مدیر: {managers} · همکار: {staff} · مشتری: {customers}"
TEAM_MEMBERS = "اعضای تیم:"
TEAM_MEMBER = "• {name} — {role}"
TEAM_MEMBER_OWNER = "• {name} — {role} ({owner})"
TEAM_MORE = "و {count} نفر دیگر"
TEAM_EMPTY = "هنوز همکاری به ربات نپیوسته است."
TEAM_LINK = "لینک دعوت همکاران (هر کس آن را باز کند همکار ربات می‌شود):\n{link}"
TEAM_NO_LINK = "ربات هنوز لینک دعوت ندارد؛ آن را از بخش تیم در کنترل‌سنتر وب بسازید."
TEAM_LINK_OWNER_ONLY = "لینک دعوت همکاران را مالک ربات از کنترل‌سنتر وب می‌گیرد."
TEAM_WEB_NOTE = "تغییر نقش‌ها و ساختن لینک تازه در کنترل‌سنتر وب انجام می‌شود."
TEAM_UNAVAILABLE = "فهرست کارکنان اینجا در دسترس نیست؛ آن را در کنترل‌سنتر وب ببینید."

# --- reports ---------------------------------------------------------------------------------------

OVERVIEW = "خلاصه کسب‌وکار"
REPORTS_HINT = "یک گزارش را انتخاب کنید."
BACK_TO_REPORTS = "‹ گزارش‌ها"
