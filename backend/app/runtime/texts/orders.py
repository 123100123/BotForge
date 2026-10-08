"""Default Persian texts for the ``orders`` capability (Business OS: commerce, W1-ORD).

``TEXTS`` holds exactly ``TEXT_KEYS["orders"]`` (overridable per capability via ``cap.texts``).
The engine pre-renders ``{price}``/``{total}`` (formatted amounts), ``{lines}`` (cart or order item
lines) and ``{details}`` (item detail lines or checkout answers). The module-level constants
below are fixed UI strings with no registered text key (button labels, line formats); they are
not overridable. Constants with ``{...}`` are filled with ``botspec.text_keys.fill_text``.
"""

from app.runtime.texts.common import FORM_TEXTS

TEXTS: dict[str, str] = {
    "list_header": "محصول موردنظر را انتخاب کنید.",
    "empty": "در حال حاضر کالایی در «{title}» موجود نیست.",
    "item_line": "{title} · {price}",
    "item_detail": "قیمت: {price}\n{details}",
    "added_to_cart": "{qty} عدد {title} به سبد اضافه شد.",
    "cart_summary": "{lines}\n\nجمع کل: {total}",
    "cart_empty": "سبد خرید شما خالی است.",
    "checkout_prompt": "جمع کل سفارش: {total}\nبرای ثبت سفارش، اطلاعات زیر را وارد کنید.",
    "placed": "سفارش شما با کد {id} ثبت شد.\nجمع کل: {total}",
    "cancelled": "سفارش شمارهٔ {id} لغو شد.",
    "not_cancellable": "این سفارش دیگر قابل لغو نیست.",
    "status_changed": "وضعیت سفارش شما در «{title}» (شمارهٔ {id}) تغییر کرد.\nوضعیت جدید: {status}",
    "out_of_stock": "متأسفانه موجودی «{title}» کافی نیست.",
    "mine_header": "آخرین سفارش‌های شما:",
    "mine_empty": "شما هنوز سفارشی ثبت نکرده‌اید.",
    "owner_placed": "سفارش جدید در «{title}» (شمارهٔ {id}) از {user}:\n{lines}\nجمع کل: {total}\n{details}",
    "owner_cancelled": "سفارش شمارهٔ {id} در «{title}» توسط {user} لغو شد.",
    "action_done": "وضعیت سفارش {id} به «{status}» تغییر کرد.",
    "not_allowed": "این اقدام برای این سفارش مجاز نیست.",
    **FORM_TEXTS,
}

# --- fixed strings (no text key) -------------------------------------------------------------

CART_BUTTON = "🛒 سبد خرید"
CART_BUTTON_COUNT = "🛒 سبد خرید ({count})"
CHECKOUT_BUTTON = "ثبت سفارش"
ADD_BUTTON = "افزودن به سبد"
DEC_BUTTON = "کم کردن"
MINE_BUTTON = "📦 سفارش‌های من"
SHOP_BUTTON = "🛍 فروشگاه"
BACK_TO_SHOP = "‹ فروشگاه"
CANCEL_BUTTON = "لغو سفارش"
CONTINUE_BUTTON = "ادامهٔ خرید"
QTY_MINUS = "➖"
QTY_PLUS = "➕"
CHECKOUT_CRUMB = "ثبت سفارش"
IN_CART_NOTE = "در سبد شما: {qty} عدد"
SOLD_OUT = "این محصول تمام شده است."
CART_LINE = "• {title} × {qty} — {total}"
MINE_LINE = "• سفارش {id} — {status} — {total} ({when})"
STOCK_LINE = "موجودی: {stock}"

PRICE = "{amount} تومان"
OUT_OF_STOCK_MARK = "ناموجود"
MARKED_LINE = "{line} ({mark})"
DEC_LINE_BUTTON = "➖ {title}"
ORDER_BUTTON = "سفارش {id}"
CANCEL_ORDER_BUTTON = "لغو سفارش {id}"
STATUS_LINE = "وضعیت: {status}"
ORDER_DETAIL = "{heading}\n{lines}\nجمع کل: {total}\nوضعیت: {status}"
ORDER_CRUMB = "سفارش {id}"
GROUP_PRIVATE = "برای خرید و ثبت سفارش، لطفاً در گفتگوی خصوصی با ربات ادامه دهید."
ITEM_UNAVAILABLE = "این کالا دیگر در دسترس نیست."
CART_ITEMS_REMOVED = (
    "برخی از کالاهای سبد شما دیگر در دسترس نیستند و از سبد حذف شدند. لطفاً سبد را دوباره بررسی کنید."
)
CART_LIMIT = "سقف تعداد این کالا یا تعداد اقلام سبد خرید پر شده است."
ORDER_NOT_FOUND = "این سفارش پیدا نشد."
NOT_ALLOWED_FROM = "این اقدام برای سفارشی که در وضعیت «{status}» است مجاز نیست."
