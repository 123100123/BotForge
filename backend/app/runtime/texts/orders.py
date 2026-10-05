"""Default Persian texts for the ``orders`` capability (Business OS: commerce, W1-ORD).

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

CART_BUTTON = "سبد خرید"
CHECKOUT_BUTTON = "ثبت سفارش"
ADD_BUTTON = "افزودن به سبد"
DEC_BUTTON = "کم کردن"
MINE_BUTTON = "سفارش‌های من"
CANCEL_BUTTON = "لغو سفارش"
CONTINUE_BUTTON = "ادامه خرید"
CART_LINE = "• {title} × {qty} — {total}"
MINE_LINE = "• سفارش {id} — {status} — {total} ({when})"
STOCK_LINE = "موجودی: {stock}"

PRICE = "{amount} تومان"
OUT_OF_STOCK_MARK = "ناموجود"
MARKED_LINE = "{line} ({mark})"
DEC_LINE_BUTTON = "− {title}"
ORDER_BUTTON = "سفارش {id}"
CANCEL_ORDER_BUTTON = "لغو سفارش {id}"
STATUS_LINE = "وضعیت: {status}"
ORDER_DETAIL = "سفارش {id}\n{lines}\nجمع کل: {total}\nوضعیت: {status}"
GROUP_PRIVATE = "برای خرید و ثبت سفارش، لطفاً در گفتگوی خصوصی با ربات ادامه دهید."
ITEM_UNAVAILABLE = "این کالا دیگر در دسترس نیست."
CART_ITEMS_REMOVED = (
    "برخی از کالاهای سبد شما دیگر در دسترس نیستند و از سبد حذف شدند. لطفاً سبد را دوباره بررسی کنید."
)
CART_LIMIT = "سقف تعداد این کالا یا تعداد اقلام سبد خرید پر شده است."
ORDER_NOT_FOUND = "این سفارش پیدا نشد."
NOT_ALLOWED_FROM = "این اقدام برای سفارشی که در وضعیت «{status}» است مجاز نیست."
