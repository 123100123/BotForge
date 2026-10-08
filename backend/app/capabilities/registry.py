"""The capability registry: the single declarative description of what a bot can do (W1-REG).

A capability is a switchable unit of business behavior. ``kind="spec"`` capabilities are realised by
BotSpec capabilities (matched by type, booking preset or key); ``kind="module"`` capabilities live
outside the spec in ``bot_modules`` (no row = the registry default, ``default_enabled``).

The enabled set is derived, never stored twice: a spec capability is enabled when any spec key it
matches has ``enabled: true``; a module is enabled when its ``bot_modules`` row says so.

Ids are a contract (frontend, agent, reports use them): see ``REGISTRY_IDS``.

``default_ops(spec)`` returns deterministic ``PatchOp``s that add the capability with sensible
defaults, or ``None`` when the owner's judgment is needed (the caller then hands
``handoff_prompt`` to the agent). Every default op list must apply cleanly to a valid spec (unit
tested against ``examples/workshop.botspec.json``). The ops never touch ``spec.menu``: Telegram
navigation is compiled from the enabled capabilities (``runtime/nav.py``), so a new capability
appears in the role homes by itself and a "full menu" can no longer block a toggle.

Matching rules worth knowing:
  forms    any ``request`` capability EXCEPT the keys owned by the more specific entries
           (``support``, ``feedback``), so turning off "forms" never silently turns off support.
  support / feedback   a ``request`` capability with exactly that key; if the key is taken by
           another type, ``default_ops`` returns None (a suffixed key would never match).
  events   the resource is keyed ``event`` (a resource key may not equal a capability key, and
           the capability is keyed ``events``); both get a numeric suffix when taken.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any, Literal

from app.botspec.models import (
    AnyCapability,
    BookingCapability,
    BotSpec,
    CatalogCapability,
    FieldType,
    InfoCapability,
    RequestCapability,
)
from app.botspec.patch import PatchOp

Category = Literal["commerce", "operations", "team", "intelligence", "customer"]
Kind = Literal["spec", "module"]

CATEGORY_ORDER: tuple[Category, ...] = ("commerce", "operations", "team", "intelligence", "customer")
CATEGORY_NAMES: dict[Category, str] = {
    "commerce": "تجارت",
    "operations": "عملیات",
    "team": "تیم",
    "intelligence": "هوش کسب‌وکار",
    "customer": "مشتریان",
}

Matcher = Callable[[BotSpec], list[str]]
DefaultOps = Callable[[BotSpec], list[PatchOp] | None]


def _no_match(_: BotSpec) -> list[str]:
    return []


def _no_ops(_: BotSpec) -> list[PatchOp] | None:
    return None


@dataclass(frozen=True)
class CapabilityDef:
    """One registry entry. ``matcher``/``ops_builder`` are only meaningful for ``kind="spec"``."""

    id: str
    name: str  # Persian
    description: str  # Persian, 1-2 sentences for owners
    category: Category
    kind: Kind
    features: tuple[str, ...] = ()  # Persian bullet list
    metrics: tuple[str, ...] = ()  # metric ids served by the reporting engine
    requires: tuple[str, ...] = ()
    requires_any: tuple[str, ...] = ()
    conflicts: tuple[str, ...] = ()
    audience: str | None = None  # default audience shown when no spec key carries one
    configurable: bool = False
    available: bool = True  # False: listed but cannot be enabled (capability_unavailable)
    default_enabled: bool = False  # module kind: state when no bot_modules row exists
    handoff_prompt: str | None = None  # Persian request text for the agent
    realised_by: str = ""  # English, for the agent catalog prompt
    module_default_config: dict[str, Any] = field(default_factory=dict)
    matcher: Matcher = _no_match
    ops_builder: DefaultOps = _no_ops

    def matches(self, spec: BotSpec | None) -> list[str]:
        """Spec capability keys that realise this capability (always [] for modules)."""
        if spec is None or self.kind != "spec":
            return []
        return self.matcher(spec)

    def default_ops(self, spec: BotSpec) -> list[PatchOp] | None:
        """Ops that add this capability with defaults; None means the agent is needed."""
        if self.kind != "spec" or not self.available:
            return None
        return self.ops_builder(spec)


# --------------------------------------------------------------------------- matching helpers


def _match(pred: Callable[[AnyCapability], bool]) -> Matcher:
    def matcher(spec: BotSpec) -> list[str]:
        return [c.key for c in spec.capabilities if pred(c)]

    return matcher


SPECIFIC_REQUEST_KEYS = frozenset({"support", "feedback"})


def _is_booking(preset: str) -> Callable[[AnyCapability], bool]:
    return lambda c: isinstance(c, BookingCapability) and c.preset == preset


# --------------------------------------------------------------------------- default-op helpers


def unique_key(base: str, taken: set[str]) -> str:
    """``base``, else ``base_2``, ``base_3``... (kept within the 24-char key limit)."""
    if base not in taken:
        return base
    n = 2
    while True:
        suffix = f"_{n}"
        candidate = base[: 24 - len(suffix)] + suffix
        if candidate not in taken:
            return candidate
        n += 1


def _entity_keys(spec: BotSpec) -> set[str]:
    """Capability and resource keys share one namespace (``key_collision``)."""
    return {c.key for c in spec.capabilities} | {r.key for r in spec.resources}


def _field(
    key: str, label: str, type_: str, *, required: bool = True, choices: list[str] | None = None
) -> dict:
    return {
        "key": key,
        "label": label,
        "type": type_,
        "required": required,
        "choices": choices,
        "default": None,
    }


def _add_capability(value: dict[str, Any]) -> PatchOp:
    return PatchOp(op="add", path=["capabilities"], value=value)


# --------------------------------------------------------------------------- default ops


ORDER_STATUSES = [
    {"key": "new", "label": "جدید"},
    {"key": "confirmed", "label": "تأییدشده"},
    {"key": "delivered", "label": "تحویل‌شده"},
    {"key": "cancelled", "label": "لغوشده"},
]
ORDER_ACTIONS = [
    {"key": "confirm", "label": "تأیید سفارش", "from_statuses": ["new"], "to_status": "confirmed"},
    {"key": "deliver", "label": "تحویل شد", "from_statuses": ["confirmed"], "to_status": "delivered"},
    {"key": "cancel", "label": "لغو سفارش", "from_statuses": ["new", "confirmed"], "to_status": "cancelled"},
]


def _price_field(spec: BotSpec, resource_key: str) -> str | None:
    resource = spec.resource(resource_key)
    if resource is None:
        return None
    ints = [f for f in resource.fields if f.type == FieldType.integer]
    priced = [f for f in ints if "price" in f.key or "قیمت" in f.label or "هزینه" in f.label]
    if len(priced) == 1:
        return priced[0].key
    if len(ints) == 1:
        return ints[0].key
    return None


def _orders_ops(spec: BotSpec) -> list[PatchOp] | None:
    """Only when exactly one catalog resource has an integer field (an unambiguous price)."""
    catalog_resources = list(
        dict.fromkeys(c.resource for c in spec.capabilities if isinstance(c, CatalogCapability))
    )
    candidates = [
        r
        for r in catalog_resources
        if (res := spec.resource(r)) is not None and any(f.type == FieldType.integer for f in res.fields)
    ]
    if len(candidates) != 1:
        return None
    resource = candidates[0]
    price = _price_field(spec, resource)
    if price is None:
        return None
    key = unique_key("orders", _entity_keys(spec))
    cap = {
        "type": "orders",
        "key": key,
        "title": "سفارش‌ها",
        "resource": resource,
        "price_field": price,
        "stock_field": None,
        "checkout_fields": [],
        "statuses": ORDER_STATUSES,
        "initial_status": "new",
        "owner_actions": ORDER_ACTIONS,
        "cancellable_statuses": ["new"],
        "notify_owner_on": ["placed", "cancelled"],
        "notify_user_on": ["status_changed"],
    }
    return [_add_capability(cap)]


EVENT_CATEGORIES = ["آموزشی", "سازمانی", "اجتماعی"]  # training / company / social


def _events_ops(spec: BotSpec) -> list[PatchOp] | None:
    taken = _entity_keys(spec)
    resource_key = unique_key("event", taken)
    taken.add(resource_key)
    cap_key = unique_key("events", taken)
    resource = {
        "key": resource_key,
        "label": "رویداد",
        "label_plural": "رویدادها",
        "title_field": "title",
        "fields": [
            _field("title", "عنوان", "text"),
            _field("description", "توضیحات", "long_text", required=False),
            _field("category", "دسته‌بندی", "choice", required=False, choices=list(EVENT_CATEGORIES)),
            _field("starts_at", "زمان شروع", "datetime"),
            _field("location", "مکان", "text", required=False),
            _field("capacity", "ظرفیت", "integer"),  # per_item capacity needs a required integer
        ],
    }
    cap = {
        "type": "booking",
        "key": cap_key,
        "title": "رویدادها",
        "resource": resource_key,
        "capacity": {"mode": "per_item", "value": None, "field": "capacity"},
        "start_field": "starts_at",
        "detail_fields": ["description", "category", "starts_at", "location"],
        "form_fields": [],
        "waitlist": {"enabled": True, "auto_promote": True},
        "cancellation": {"enabled": True, "deadline_hours": None},
        "notify_owner_on": ["booked", "cancelled"],
        "notify_user_on": ["promoted"],
        "preset": "events",
        "reminder_hours_before": 24,
        "category_field": "category",
    }
    return [PatchOp(op="add", path=["resources"], value=resource), _add_capability(cap)]


def _info_ops(spec: BotSpec) -> list[PatchOp] | None:
    key = unique_key("info", _entity_keys(spec))
    cap = {
        "type": "info",
        "key": key,
        "title": "دربارهٔ ما",
        "pages": [{"key": "about", "title": "دربارهٔ ما", "body": spec.bot.welcome_text}],
    }
    return [_add_capability(cap)]


def _fixed_key_request(key: str, build: Callable[[], dict[str, Any]]) -> DefaultOps:
    def ops(spec: BotSpec) -> list[PatchOp] | None:
        if key in _entity_keys(spec):
            return None  # the fixed key is taken by something else; a suffixed key would never match
        return [_add_capability({"type": "request", "key": key, **build()})]

    return ops


def _support() -> dict[str, Any]:
    return {
        "title": "پشتیبانی",
        "form_fields": [_field("subject", "موضوع", "text"), _field("text", "شرح درخواست", "long_text")],
        "item_resource": None,
        "statuses": [
            {"key": "open", "label": "باز"},
            {"key": "answered", "label": "پاسخ داده شد"},
            {"key": "closed", "label": "بسته شد"},
        ],
        "initial_status": "open",
        "owner_actions": [
            {"key": "answer", "label": "پاسخ داده شد", "from_statuses": ["open"], "to_status": "answered"},
            {"key": "close", "label": "بستن", "from_statuses": ["open", "answered"], "to_status": "closed"},
        ],
        "notify_owner_on": ["submitted"],
        "notify_user_on": ["status_changed"],
    }


def _feedback() -> dict[str, Any]:
    return {
        "title": "ثبت نظر",
        "form_fields": [
            _field("rating", "امتیاز", "choice", choices=["۱", "۲", "۳", "۴", "۵"]),
            _field("comment", "نظر شما", "long_text", required=False),
        ],
        "item_resource": None,
        "statuses": [{"key": "new", "label": "جدید"}, {"key": "seen", "label": "دیده شد"}],
        "initial_status": "new",
        "owner_actions": [{"key": "seen", "label": "دیده شد", "from_statuses": ["new"], "to_status": "seen"}],
        "notify_owner_on": ["submitted"],
        "notify_user_on": [],
    }


# --------------------------------------------------------------------------- the registry


REGISTRY: tuple[CapabilityDef, ...] = (
    # --- commerce
    CapabilityDef(
        id="catalog",
        name="فهرست محصولات و خدمات",
        description="محصولات یا خدمات شما را با جزئیات در ربات نمایش می‌دهد تا مشتری راحت انتخاب کند.",
        category="commerce",
        kind="spec",
        features=(
            "نمایش فهرست و جزئیات هر مورد",
            "مرتب‌سازی و پنهان کردن موارد گذشته",
            "مدیریت موارد از پنل وب",
        ),
        audience="everyone",
        configurable=True,
        handoff_prompt=(
            "یک فهرست محصولات یا خدمات به ربات اضافه کن تا مشتری‌ها بتوانند موارد را با جزئیات ببینند."
        ),
        realised_by="spec capability type=catalog",
        matcher=_match(lambda c: c.type == "catalog"),
    ),
    CapabilityDef(
        id="orders",
        name="فروشگاه و سفارش‌ها",
        description=(
            "مشتری از ربات کالا انتخاب می‌کند، سبد خرید می‌سازد و سفارش "
            "ثبت می‌کند؛ شما وضعیت سفارش را پیگیری می‌کنید."
        ),
        category="commerce",
        kind="spec",
        features=(
            "سبد خرید و ثبت سفارش",
            "وضعیت سفارش و اطلاع‌رسانی به مشتری",
            "لغو سفارش توسط مشتری",
            "گزارش فروش",
        ),
        metrics=(
            "order_count",
            "revenue",
            "average_order_value",
            "orders_by_day",
            "top_products",
            "orders_by_status",
        ),
        requires=("catalog",),
        audience="everyone",
        configurable=True,
        handoff_prompt="فروشگاه آنلاین با فهرست محصولات، سبد خرید و ثبت سفارش اضافه کن",
        realised_by="spec capability type=orders (resource = the catalog items, integer price_field)",
        matcher=_match(lambda c: c.type == "orders"),
        ops_builder=_orders_ops,
    ),
    CapabilityDef(
        id="inventory",
        name="موجودی انبار",
        description=(
            "موجودی هر کالا را نگه می‌دارد، با هر سفارش کم می‌کند و وقتی موجودی کم شد به شما هشدار می‌دهد."
        ),
        category="commerce",
        kind="module",
        features=("کسر خودکار موجودی با هر سفارش", "هشدار کمبود موجودی", "ویرایش موجودی از پنل وب"),
        metrics=("low_stock_items",),
        requires=("orders",),
        configurable=True,
        realised_by="module inventory (uses OrdersCapability.stock_field); config low_stock_threshold",
        module_default_config={"low_stock_threshold": 5},
    ),
    CapabilityDef(
        id="payments",
        name="پرداخت آنلاین",
        description=(
            "پرداخت آنلاین در نسخه‌های بعدی اضافه می‌شود؛ فعلاً سفارش‌ها با وضعیت «پرداخت‌نشده» ثبت می‌شوند."
        ),
        category="commerce",
        kind="module",
        features=("پرداخت از درگاه بانکی (به‌زودی)",),
        requires=("orders",),
        configurable=False,
        available=False,
        realised_by="deferred: not available in this version; record requests under Requirements.unsupported",
    ),
    # --- operations
    CapabilityDef(
        id="booking",
        name="رزرو و نوبت‌دهی",
        description=(
            "مشتری از ربات وقت یا جای خالی رزرو می‌کند؛ ظرفیت، لیست انتظار و انصراف خودکار مدیریت می‌شود."
        ),
        category="operations",
        kind="spec",
        features=(
            "ظرفیت ثابت یا جداگانه برای هر مورد",
            "لیست انتظار و جایگزینی خودکار",
            "انصراف با مهلت",
            "اطلاع‌رسانی به شما",
        ),
        metrics=("booking_count", "cancel_rate", "capacity_use", "bookings_by_day"),
        audience="everyone",
        configurable=True,
        handoff_prompt="امکان رزرو و نوبت‌دهی با ظرفیت و لیست انتظار به ربات اضافه کن",
        realised_by="spec capability type=booking, preset='booking'",
        matcher=_match(_is_booking("booking")),
    ),
    CapabilityDef(
        id="forms",
        name="فرم‌ها و درخواست‌ها",
        description=(
            "فرم‌هایی مثل درخواست مرخصی، شکایت یا ثبت درخواست می‌سازد و هر درخواست را با وضعیت پیگیری می‌کند."
        ),
        category="operations",
        kind="spec",
        features=("فرم با فیلدهای دلخواه", "وضعیت و اقدام‌های مدیر", "اطلاع‌رسانی تغییر وضعیت به کاربر"),
        metrics=("open_count", "resolved_count", "average_resolution_time", "requests_by_status"),
        audience="everyone",
        configurable=True,
        handoff_prompt="یک فرم درخواست به ربات اضافه کن که کاربران پر کنند و من وضعیتش را پیگیری کنم",
        realised_by="spec capability type=request (any key except support/feedback)",
        matcher=_match(lambda c: isinstance(c, RequestCapability) and c.key not in SPECIFIC_REQUEST_KEYS),
    ),
    CapabilityDef(
        id="approvals",
        name="تأیید و گردش کار",
        description="درخواست‌هایی که کارکنان ثبت می‌کنند در صف تأیید مدیر قرار می‌گیرند تا تأیید یا رد شوند.",
        category="operations",
        kind="module",
        features=("صف درخواست‌های در انتظار تأیید", "تأیید یا رد با یک دکمه", "نمایش در نمای کلی"),
        metrics=("pending_approvals",),
        requires=("forms",),
        realised_by="module approvals: request capabilities whose owner actions include approve/reject",
    ),
    # --- team
    CapabilityDef(
        id="events",
        name="رویدادها",
        description=("رویدادهای سازمان را با دسته‌بندی، ظرفیت و یادآوری اعلام می‌کند و ثبت‌نام اعضا را می‌گیرد."),
        category="team",
        kind="spec",
        features=("ثبت‌نام و انصراف", "دسته‌بندی رویدادها", "یادآوری پیش از شروع", "ظرفیت و لیست انتظار"),
        metrics=(
            "booking_count",
            "cancel_rate",
            "capacity_use",
            "rsvp_breakdown",
            "bookings_by_category",
            "bookings_by_day",
        ),
        audience="everyone",
        configurable=True,
        handoff_prompt="بخش رویدادها با دسته‌بندی، ظرفیت، ثبت‌نام و یادآوری به ربات اضافه کن",
        realised_by="spec capability type=booking, preset='events' (category_field, reminder_hours_before)",
        matcher=_match(_is_booking("events")),
        ops_builder=_events_ops,
    ),
    CapabilityDef(
        id="announcements",
        name="اطلاعیه‌ها",
        description="پیام یا اطلاعیه را برای همهٔ کاربران ربات یا گروه‌ها می‌فرستد.",
        category="team",
        kind="module",
        features=("ارسال پیام همگانی", "ارسال به گروه‌های متصل", "تاریخچهٔ اطلاعیه‌ها"),
        metrics=("announcements_sent",),
        realised_by="module announcements (outbox broadcasts)",
    ),
    CapabilityDef(
        id="staff",
        name="نقش‌ها و کارکنان",
        description=(
            "با یک لینک دعوت، کارکنان را به ربات اضافه می‌کند تا به بخش‌های مخصوص کارکنان دسترسی داشته باشند."
        ),
        category="team",
        kind="module",
        features=("لینک دعوت کارکنان", "بخش‌های مخصوص کارکنان و مدیران", "فهرست اعضا"),
        metrics=("staff_count",),
        realised_by="module staff: enables the staff link (bots.staff_link_code) and audience='staff'",
    ),
    CapabilityDef(
        id="staff_reporting",
        name="گزارش روزانهٔ کارکنان",
        description=(
            "کارکنان گزارش روزانه را به‌صورت فایل اکسل می‌فرستند و شما "
            "خلاصه و افرادی که گزارش نداده‌اند را می‌بینید."
        ),
        category="team",
        kind="module",
        features=("دریافت فایل گزارش از کارکنان", "فهرست کسانی که گزارش نداده‌اند", "خلاصهٔ خودکار"),
        requires=("staff", "spreadsheet_intelligence"),
        realised_by="module staff_reporting (an analysis profile flagged daily_report)",
    ),
    # --- intelligence
    CapabilityDef(
        id="reporting",
        name="گزارش‌ها و داشبورد",
        description=(
            "آمار کسب‌وکار شما را از داده‌های ربات محاسبه می‌کند و در نمای کلی و صفحهٔ گزارش‌ها نشان می‌دهد."
        ),
        category="intelligence",
        kind="module",
        features=("شاخص‌های کلیدی", "نمودار روزانه", "گزارش هر قابلیت"),
        default_enabled=True,
        realised_by="module reporting (enabled by default)",
    ),
    CapabilityDef(
        id="spreadsheet_intelligence",
        name="تحلیل فایل اکسل",
        description="فایل اکسل یا CSV را بارگذاری کنید تا ستون‌ها، آمار و موارد غیرعادی آن تحلیل شود.",
        category="intelligence",
        kind="module",
        features=("بارگذاری اکسل و CSV", "تشخیص ستون‌ها و آمار", "اجرای دوباره روی فایل‌های بعدی"),
        metrics=("analysis_runs", "anomalies"),
        realised_by="module spreadsheet_intelligence (uploads + analysis profiles)",
    ),
    CapabilityDef(
        id="scheduled_reports",
        name="گزارش‌های زمان‌بندی‌شده",
        description="خلاصهٔ گزارش‌ها را در زمان مشخص (روزانه یا هفتگی) در تلگرام برای شما می‌فرستد.",
        category="intelligence",
        kind="module",
        features=("ارسال روزانه یا هفتگی", "خلاصهٔ شاخص‌ها در تلگرام"),
        requires=("reporting",),
        realised_by="module scheduled_reports (report schedules)",
    ),
    CapabilityDef(
        id="copilot",
        name="دستیار مدیر",
        description="دربارهٔ کسب‌وکارتان سؤال بپرسید تا دستیار با داده‌های ربات پاسخ دهد.",
        category="intelligence",
        kind="module",
        features=("پرسش به زبان ساده", "پاسخ بر اساس داده‌های واقعی", "پیشنهاد اقدام"),
        requires=("reporting",),
        realised_by="module copilot (manager Q&A over reports)",
    ),
    # --- customer
    CapabilityDef(
        id="info",
        name="اطلاعات و معرفی",
        description="صفحه‌های اطلاعاتی مثل دربارهٔ ما، نشانی و ساعت کاری را در ربات نمایش می‌دهد.",
        category="customer",
        kind="spec",
        features=("صفحه‌های متنی", "نشانی و راه‌های تماس"),
        audience="everyone",
        configurable=True,
        handoff_prompt="یک بخش اطلاعات (دربارهٔ ما، نشانی و تماس) به ربات اضافه کن",
        realised_by="spec capability type=info",
        matcher=_match(lambda c: isinstance(c, InfoCapability)),
        ops_builder=_info_ops,
    ),
    CapabilityDef(
        id="support",
        name="پشتیبانی",
        description="مشتری درخواست پشتیبانی ثبت می‌کند و شما پاسخ می‌دهید و درخواست را می‌بندید.",
        category="customer",
        kind="spec",
        features=("ثبت درخواست پشتیبانی", "پاسخ و بستن درخواست", "اطلاع‌رسانی به مشتری"),
        metrics=("open_count", "resolved_count", "average_resolution_time", "requests_by_status"),
        audience="everyone",
        configurable=True,
        handoff_prompt="بخش پشتیبانی به ربات اضافه کن تا مشتری‌ها درخواست ثبت کنند و من پاسخ بدهم",
        realised_by="spec capability type=request with key 'support'",
        matcher=_match(lambda c: isinstance(c, RequestCapability) and c.key == "support"),
        ops_builder=_fixed_key_request("support", _support),
    ),
    CapabilityDef(
        id="feedback",
        name="نظرسنجی و بازخورد",
        description="مشتری به خدمات شما امتیاز می‌دهد و نظرش را می‌نویسد.",
        category="customer",
        kind="spec",
        features=("امتیاز ۱ تا ۵", "ثبت نظر", "گزارش رضایت"),
        metrics=("open_count", "requests_by_status"),
        audience="everyone",
        configurable=True,
        handoff_prompt="بخش ثبت نظر و امتیازدهی مشتری به ربات اضافه کن",
        realised_by="spec capability type=request with key 'feedback'",
        matcher=_match(lambda c: isinstance(c, RequestCapability) and c.key == "feedback"),
        ops_builder=_fixed_key_request("feedback", _feedback),
    ),
)

REGISTRY_BY_ID: dict[str, CapabilityDef] = {c.id: c for c in REGISTRY}
REGISTRY_IDS: tuple[str, ...] = tuple(c.id for c in REGISTRY)


def get_capability(cap_id: str) -> CapabilityDef | None:
    return REGISTRY_BY_ID.get(cap_id)
