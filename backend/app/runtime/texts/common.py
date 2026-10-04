"""Non-overridable Persian strings shared by the runtime and all engines (WP1).

``FORM_TEXTS`` holds the defaults for the overridable form keys (``ask_field``, ``invalid_answer``,
``form_stopped``) that ``botspec/text_keys.py`` registers for every type with ``form_fields``.
Engine text modules include them with ``**FORM_TEXTS``.
"""

HOME = "منوی اصلی"
BACK = "بازگشت"
NEXT = "بعدی ›"
PREVIOUS = "‹ قبلی"

MENU_HEADER = "منوی اصلی\nیکی از گزینه‌های زیر را انتخاب کنید."
STALE = "این گزینه دیگر در دسترس نیست."
NOT_AVAILABLE = "این بخش هنوز در دسترس نیست. لطفاً بعداً دوباره امتحان کنید."
NOT_ALLOWED = "این کار فقط برای مدیر ربات مجاز است."
PAGE_INDICATOR = "صفحهٔ {page} از {pages}"

# Form collector (runtime/forms.py)
SKIP = "رد کردن"
STOP = "انصراف"
YES = "بله"
NO = "خیر"
CHOOSE_HINT = "یکی از گزینه‌های زیر را انتخاب کنید."
OPTIONAL_HINT = "(اختیاری؛ برای ادامه بدون پاسخ «رد کردن» را بزنید.)"

FORM_TEXTS: dict[str, str] = {
    "ask_field": "لطفاً «{label}» را وارد کنید:",
    "invalid_answer": "پاسخ «{label}» پذیرفته نشد: {error}\nلطفاً دوباره وارد کنید.",
    "form_stopped": "فرم لغو شد.",
}
