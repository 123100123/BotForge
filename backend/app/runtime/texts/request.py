"""Default Persian texts for the ``request`` capability (WP8).

``TEXTS`` holds exactly ``TEXT_KEYS["request"]`` (overridable per capability via ``cap.texts``).
The module-level constants below are fixed UI strings with no registered text key (button labels,
extra lines, the rejection explanations); they are not overridable. Constants with ``{...}`` are
filled with ``botspec.text_keys.fill_text``.
"""

from app.runtime.texts.common import FORM_TEXTS

TEXTS: dict[str, str] = {
    "form_intro": "لطفاً اطلاعات زیر را وارد کنید.",
    "pick_item": "یکی از موارد زیر را انتخاب کنید.",
    "submitted": "درخواست شما در «{title}» ثبت شد.\nکد پیگیری: {id}",
    "mine_header": "درخواست‌های شما:",
    "mine_empty": "شما هنوز درخواستی ثبت نکرده‌اید.",
    "status_changed": "وضعیت درخواست شما در «{title}» (کد پیگیری {id}) تغییر کرد.\nوضعیت جدید: {status}",
    "owner_submitted": "درخواست جدید در «{title}» (کد {id}) از {user}:\n{details}",
    "action_done": "وضعیت درخواست {id} به «{status}» تغییر کرد.",
    "not_allowed": "این اقدام برای درخواست‌ها تعریف نشده است.",
    **FORM_TEXTS,
}

# --- fixed strings (no text key) -------------------------------------------------------------

MAIN_INTRO = "یک گزینه را انتخاب کنید."
NEW_BUTTON = "درخواست جدید"
NEW_CRUMB = "درخواست جدید"
MINE_BUTTON = "درخواست‌های من"

STATUS_LINE = "وضعیت: {status}"
PICKED_LINE = "مورد انتخاب‌شده: {item}"
NO_ITEMS = "در حال حاضر موردی برای انتخاب وجود ندارد."
ITEM_NOT_FOUND = "این مورد دیگر در دسترس نیست."
PICK_LINE = "• {title}"
MINE_LINE = "• کد {id}{item} — {status} ({when})"
MINE_ITEM = " — {item}"
ITEM_DETAIL_LINE = "مورد: {item}"
REQUEST_NOT_FOUND = "این درخواست پیدا نشد."
NOT_ALLOWED_FROM = "این اقدام برای درخواستی که در وضعیت «{status}» است مجاز نیست."
