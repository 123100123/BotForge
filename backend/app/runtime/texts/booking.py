"""Default Persian texts for the ``booking`` capability (WP2).

``TEXTS`` holds exactly ``TEXT_KEYS["booking"]`` (overridable per capability via ``cap.texts``).
The module-level constants below are fixed UI strings with no registered text key (button labels,
status labels, extra detail lines); they are not overridable. Constants with ``{...}`` are filled
with ``botspec.text_keys.fill_text``.

Preset wording: ``words(cap)`` returns the fixed strings for the capability's preset (``Words``);
the events preset uses ``EVENTS_WORDS`` plus the ``events_*`` keys of ``TEXTS``.
"""

from typing import NamedTuple

from app.runtime.texts.common import FORM_TEXTS

TEXTS: dict[str, str] = {
    "list_header": "یکی از موارد زیر را انتخاب کنید.",
    "empty": "در حال حاضر موردی برای ثبت‌نام وجود ندارد.",
    "item_detail": "{details}\n\nظرفیت باقی‌مانده: {remaining}",
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
    # events preset (see ``Words`` below for its fixed strings)
    "events_list_header": "رویدادهای پیش‌رو",
    "events_empty": "در حال حاضر رویداد پیش‌رویی ثبت نشده است.",
    "events_item_detail": "{details}\n\nظرفیت باقی‌مانده: {remaining}",
    "events_confirmed": "شرکت شما در «{title}» ثبت شد.",
    "events_waitlisted": "ظرفیت «{title}» تکمیل است؛ شما در فهرست انتظار قرار گرفتید (نفر {position}).",
    "events_full": "متأسفانه ظرفیت «{title}» تکمیل است.",
    "events_duplicate": "شما قبلاً در «{title}» ثبت‌نام کرده‌اید.",
    "events_closed": "مهلت ثبت‌نام در «{title}» به پایان رسیده است.",
    "events_cancelled": "شرکت شما در «{title}» لغو شد.",
    "events_promoted": "خبر خوب! از فهرست انتظار خارج شدید و شرکت شما در «{title}» قطعی شد.",
    "events_mine_header": "ثبت‌نام‌های شما در رویدادها:",
    "events_mine_empty": "شما هنوز در هیچ رویدادی ثبت‌نام نکرده‌اید.",
    "events_subs_header": "دسته‌هایی که می‌خواهید از رویدادهای آن‌ها باخبر شوید را انتخاب کنید (✓ یعنی فعال):",
    "events_owner_booked": "{user} در رویداد «{title}» ثبت‌نام کرد.",
    "events_owner_waitlisted": "{user} در فهرست انتظار «{title}» قرار گرفت.",
    "events_owner_cancelled": "{user} شرکت خود در «{title}» را لغو کرد.",
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
STARTED_STATUS = "برگزار شده"
CLOSED_LINE = "ثبت‌نام این مورد بسته شده است."
FORM_INTRO = "ثبت‌نام در «{title}»"
LIST_LINE = "• {title}{when}"
MINE_LINE = "• {title}{when} — {status}"
MINE_WHEN = " ({when})"

ITEM_NOT_FOUND = "این مورد دیگر برای ثبت‌نام در دسترس نیست."
BOOKING_NOT_FOUND = "این ثبت‌نام پیدا نشد یا قبلاً لغو شده است."
CANCEL_AFTER_START = "«{title}» شروع شده است و دیگر نمی‌توان ثبت‌نام آن را لغو کرد."
OWNER_CANCEL_DONE = "ثبت‌نام کاربر {user} در «{title}» لغو شد."
OWNER_ACTION_UNKNOWN = "این عملیات برای ثبت‌نام‌ها تعریف نشده است."


# --- preset wording --------------------------------------------------------------------------


class Words(NamedTuple):
    """Fixed (non-overridable) strings that differ between the booking and events presets."""

    book_button: str
    cancel_button: str
    cancel_button_for: str
    mine_button: str
    list_button: str
    status_labels: dict[str, str]
    waitlist_count_line: str
    my_waitlist_status: str
    closed_line: str
    form_intro: str
    item_not_found: str
    started_status: str
    cancel_after_start: str


BOOKING_WORDS = Words(
    book_button=BOOK_BUTTON,
    cancel_button=CANCEL_BUTTON,
    cancel_button_for=CANCEL_BUTTON_FOR,
    mine_button=MINE_BUTTON,
    list_button=LIST_BUTTON,
    status_labels=STATUS_LABELS,
    waitlist_count_line=WAITLIST_COUNT_LINE,
    my_waitlist_status=MY_WAITLIST_STATUS,
    closed_line=CLOSED_LINE,
    form_intro=FORM_INTRO,
    item_not_found=ITEM_NOT_FOUND,
    started_status=STARTED_STATUS,
    cancel_after_start=CANCEL_AFTER_START,
)

EVENTS_WORDS = Words(
    book_button="شرکت می‌کنم",
    cancel_button="لغو شرکت",
    cancel_button_for="لغو شرکت: {title}",
    mine_button=MINE_BUTTON,
    list_button="رویدادها",
    status_labels={
        "confirmed": "شرکت می‌کنید",
        "waitlisted": "در فهرست انتظار",
        "cancelled": "لغو شده",
    },
    waitlist_count_line="تعداد در فهرست انتظار: {count}",
    my_waitlist_status="در فهرست انتظار (نفر {position})",
    closed_line="ثبت‌نام این رویداد بسته شده است.",
    form_intro="ثبت‌نام در رویداد «{title}»",
    item_not_found="این رویداد دیگر در دسترس نیست.",
    started_status="برگزار شده",
    cancel_after_start="رویداد «{title}» شروع شده است و دیگر نمی‌توان شرکت در آن را لغو کرد.",
)


def words(preset: str) -> Words:
    """Fixed strings for a ``BookingCapability.preset``."""
    return EVENTS_WORDS if preset == "events" else BOOKING_WORDS


# --- events-only fixed strings -----------------------------------------------------------------

EVENTS_ALL_CATEGORIES = "همه"
EVENTS_SUBS_BUTTON = "اشتراک دسته‌ها"
EVENTS_SUB_ON = "✓"
EVENTS_SUB_OFF = "○"
EVENTS_CATEGORY_LINE = "دسته: {category}"
EVENTS_GOING_LINE = "{going} نفر شرکت می‌کنند"
EVENTS_GOING_OF_LINE = "{going} / {capacity}"
EVENTS_GROUP_PRIVATE = "برای ثبت‌نام به چت خصوصی ربات پیام دهید"
EVENTS_CARD_CLOSED = "ثبت‌نام این رویداد بسته شده است."
