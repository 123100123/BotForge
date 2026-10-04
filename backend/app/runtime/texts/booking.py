"""Default Persian texts for the ``booking`` capability (WP2).

``TEXTS`` holds exactly ``TEXT_KEYS["booking"]`` (overridable per capability via ``cap.texts``).
The module-level constants below are fixed UI strings with no registered text key (button labels,
status labels, extra detail lines); they are not overridable. Constants with ``{...}`` are filled
with ``botspec.text_keys.fill_text``.
"""

from app.runtime.texts.common import FORM_TEXTS

TEXTS: dict[str, str] = {
    "list_header": "{title}\nیکی از موارد زیر را انتخاب کنید:",
    "empty": "{title}\nدر حال حاضر موردی برای ثبت‌نام وجود ندارد.",
    "item_detail": "{title}\n\n{details}\n\nظرفیت باقی‌مانده: {remaining}",
    "confirmed": "ثبت‌نام شما در «{title}» قطعی شد.",
    "waitlisted": "ظرفیت «{title}» تکمیل است؛ شما در لیست انتظار قرار گرفتید (نفر {position}).",
    "full": "متأسفانه ظرفیت «{title}» تکمیل است.",
    "duplicate": "شما قبلاً در «{title}» ثبت‌نام کرده‌اید.",
    "user_limit": "شما به سقف {limit} ثبت‌نام فعال رسیده‌اید و ثبت‌نام جدید ممکن نیست.",
    "closed": "مهلت ثبت‌نام در «{title}» به پایان رسیده است.",
    "cancelled": "ثبت‌نام شما در «{title}» لغو شد.",
    "cancel_deadline_passed": (
        "لغو ثبت‌نام «{title}» فقط تا {hours} ساعت پیش از شروع ممکن است و این مهلت گذشته است."
    ),
    "cancellation_disabled": "امکان لغو ثبت‌نام «{title}» وجود ندارد.",
    "promoted": "خبر خوب! از لیست انتظار خارج شدید و ثبت‌نام شما در «{title}» قطعی شد.",
    "mine_header": "ثبت‌نام‌های فعال شما:",
    "mine_empty": "شما در حال حاضر ثبت‌نام فعالی ندارید.",
    "owner_booked": "ثبت‌نام جدید: {user} در «{title}» ثبت‌نام کرد.",
    "owner_waitlisted": "{user} در لیست انتظار «{title}» قرار گرفت.",
    "owner_cancelled": "{user} ثبت‌نام خود در «{title}» را لغو کرد.",
    **FORM_TEXTS,
}

# --- fixed strings (no text key) -------------------------------------------------------------

BOOK_BUTTON = "ثبت‌نام"
CANCEL_BUTTON = "لغو ثبت‌نام"
CANCEL_BUTTON_FOR = "لغو: {title}"
MINE_BUTTON = "ثبت‌نام‌های من"
LIST_BUTTON = "فهرست"

STATUS_LABELS: dict[str, str] = {
    "confirmed": "قطعی",
    "waitlisted": "در لیست انتظار",
    "cancelled": "لغو شده",
}

WAITLIST_COUNT_LINE = "تعداد در لیست انتظار: {count}"
MY_STATUS_LINE = "وضعیت شما: {status}"
MY_WAITLIST_STATUS = "در لیست انتظار (نفر {position})"
CLOSED_LINE = "ثبت‌نام این مورد بسته شده است."
FORM_INTRO = "ثبت‌نام در «{title}»"
LIST_LINE = "• {title}{when}"
MINE_LINE = "• {title}{when} — {status}"
MINE_WHEN = " ({when})"

ITEM_NOT_FOUND = "این مورد دیگر برای ثبت‌نام در دسترس نیست."
BOOKING_NOT_FOUND = "این ثبت‌نام پیدا نشد یا قبلاً لغو شده است."
OWNER_CANCEL_DONE = "ثبت‌نام کاربر {user} در «{title}» لغو شد."
OWNER_ACTION_UNKNOWN = "این عملیات برای ثبت‌نام‌ها تعریف نشده است."
