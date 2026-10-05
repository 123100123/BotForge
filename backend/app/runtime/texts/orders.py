"""Default Persian texts for the ``orders`` capability (Business OS: commerce).

``TEXTS`` holds exactly ``TEXT_KEYS["orders"]`` (overridable per capability via ``cap.texts``).
The engine pre-renders ``{price}``/``{total}`` (formatted amounts), ``{lines}`` (cart or order item
lines) and ``{details}`` (item detail lines or checkout answers). The module-level constants
below are fixed UI strings with no registered text key (button labels, line formats); they are
not overridable. Constants with ``{...}`` are filled with ``botspec.text_keys.fill_text``.
"""

from app.runtime.texts.common import FORM_TEXTS

TEXTS: dict[str, str] = {
    "list_header": "{title}\nیکی از کالاهای زیر را انتخاب کنید:",
    "empty": "در حال حاضر کالایی در «{title}» موجود نیست.",
    "item_line": "{title} — {price}",
    "item_detail": "{title}\n{details}\nقیمت: {price}",
    "added_to_cart": "«{title}» به سبد خرید اضافه شد (تعداد: {qty}).",
    "cart_summary": "سبد خرید شما:\n{lines}\nجمع کل: {total}",
    "cart_empty": "سبد خرید شما خالی است.",
    "checkout_prompt": "جمع کل سفارش: {total}\nبرای ثبت سفارش، اطلاعات زیر را وارد کنید.",
    "placed": "سفارش شما در «{title}» ثبت شد.\nشمارهٔ سفارش: {id}\nمبلغ قابل پرداخت: {total}",
    "cancelled": "سفارش شمارهٔ {id} لغو شد.",
    "not_cancellable": "سفارش شمارهٔ {id} در وضعیت «{status}» قابل لغو نیست.",
    "status_changed": "وضعیت سفارش شما در «{title}» (شمارهٔ {id}) تغییر کرد.\nوضعیت جدید: {status}",
    "out_of_stock": "متأسفانه موجودی «{title}» کافی نیست.",
    "mine_header": "سفارش‌های شما:",
    "mine_empty": "شما هنوز سفارشی ثبت نکرده‌اید.",
    "owner_placed": "سفارش جدید در «{title}» (شمارهٔ {id}) از {user}:\n{lines}\nجمع کل: {total}\n{details}",
    "owner_cancelled": "سفارش شمارهٔ {id} در «{title}» توسط {user} لغو شد.",
    "action_done": "وضعیت سفارش {id} به «{status}» تغییر کرد.",
    "not_allowed": "این اقدام برای این سفارش مجاز نیست.",
    **FORM_TEXTS,
}

# --- fixed strings (no text key) -------------------------------------------------------------

NOT_READY = "بخش سفارش‌ها هنوز در دسترس نیست. لطفاً بعداً دوباره امتحان کنید."
CART_BUTTON = "سبد خرید"
CHECKOUT_BUTTON = "ثبت سفارش"
ADD_BUTTON = "افزودن به سبد"
DEC_BUTTON = "کم کردن"
MINE_BUTTON = "سفارش‌های من"
CANCEL_BUTTON = "لغو سفارش"
CART_LINE = "• {title} × {qty} — {total}"
MINE_LINE = "• سفارش {id} — {status} — {total} ({when})"
STOCK_LINE = "موجودی: {stock}"
