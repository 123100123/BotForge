"""Owner-readable spec diff (frozen contract, WP0).

``diff_specs(old, new)`` compares two specs structurally, matching keyed-list elements by key:
  added / removed  a keyed-list element (path ends at its key; old/new is the whole element)
  changed          a scalar, scalar list, or nullable value (path ends at the field), a capability
                   whose type differs (whole element), or the order of a keyed list
                   (path ends at the list; old/new are the key orders)
Fields that go from null to a value are "changed", not "added".

``label_fa`` is a short Persian line, e.g. "ظرفیت: ۱۰ ← ۱۲". Specific labels exist for the rule
parameters; other paths get a generic label built from Persian field names.
"""

from typing import Any, Literal

from pydantic import BaseModel

from app.botspec.models import BotSpec
from app.botspec.patch import ROOT, Shape, pick_model, shape_of


class SpecChange(BaseModel):
    path: list[str]
    kind: Literal["added", "removed", "changed"]
    old: Any = None
    new: Any = None
    label_fa: str


_FA_DIGITS = str.maketrans("0123456789", "۰۱۲۳۴۵۶۷۸۹")

FIELD_LABELS_FA: dict[str, str] = {
    "name": "نام ربات",
    "welcome_text": "متن خوش‌آمد",
    "timezone": "منطقهٔ زمانی",
    "language": "زبان",
    "title": "عنوان",
    "label": "برچسب",
    "label_plural": "نام جمع",
    "title_field": "فیلد عنوان",
    "type": "نوع",
    "required": "اجباری",
    "choices": "گزینه‌ها",
    "default": "مقدار پیش‌فرض",
    "body": "متن",
    "value": "مقدار",
    "resource": "منبع داده",
    "detail_fields": "فیلدهای نمایش جزئیات",
    "upcoming_only_field": "نمایش فقط موارد آینده بر اساس",
    "sort_field": "مرتب‌سازی بر اساس",
    "sort_desc": "مرتب‌سازی نزولی",
    "start_field": "فیلد زمان شروع",
    "one_active_per_user_per_item": "جلوگیری از ثبت‌نام تکراری",
    "max_active_per_user": "حداکثر ثبت‌نام فعال هر کاربر",
    "closes_hours_before_start": "بسته شدن ثبت‌نام",
    "notify_owner_on": "اعلان به مدیر",
    "notify_user_on": "اعلان به کاربر",
    "item_resource": "انتخاب مورد از",
    "initial_status": "وضعیت اولیه",
    "from_statuses": "از وضعیت‌های",
    "to_status": "به وضعیت",
    "capability": "قابلیت",
    "view": "نما",
    "enabled": "فعال",
    "auto_promote": "جایگزینی خودکار",
    "mode": "نوع ظرفیت",
    "field": "فیلد ظرفیت",
    "deadline_hours": "مهلت لغو ثبت‌نام",
    "spec_version": "نسخهٔ قالب",
}

LIST_KIND_FA: dict[str, str] = {
    "resources": "منبع داده",
    "fields": "فیلد",
    "capabilities": "قابلیت",
    "pages": "صفحه",
    "form_fields": "فیلد فرم",
    "texts": "متن",
    "statuses": "وضعیت",
    "owner_actions": "عملیات مدیر",
    "menu": "گزینهٔ منو",
}

_VALUE_FA: dict[str, str] = {
    "fixed": "ثابت",
    "per_item": "جداگانه برای هر مورد",
    "main": "اصلی",
    "mine": "موارد من",
    "booked": "ثبت‌نام",
    "waitlisted": "ورود به لیست انتظار",
    "cancelled": "لغو",
    "promoted": "جایگزینی از لیست انتظار",
    "submitted": "ثبت درخواست",
    "status_changed": "تغییر وضعیت",
}


def fa_digits(text: str) -> str:
    return text.translate(_FA_DIGITS)


def _fmt(v: Any) -> str:
    if v is None:
        return "ندارد"
    if isinstance(v, bool):
        return "بله" if v else "خیر"
    if isinstance(v, int | float):
        return fa_digits(str(v))
    if isinstance(v, str):
        if v in _VALUE_FA:
            return _VALUE_FA[v]
        short = v if len(v) <= 40 else v[:39] + "…"
        return f"«{short}»"
    if isinstance(v, list):
        return "، ".join(_fmt(x) for x in v) if v else "هیچ"
    if isinstance(v, dict):
        return _name_of(v)
    return str(v)


def _hours_until_start(v: Any) -> str:
    return "بدون محدودیت" if v is None else f"تا {fa_digits(str(v))} ساعت قبل از شروع"


def _closes(v: Any) -> str:
    return "تا زمان شروع" if v is None else f"{fa_digits(str(v))} ساعت قبل از شروع"


def _unlimited(v: Any) -> str:
    return "نامحدود" if v is None else _fmt(v)


# (schema path pattern with "*" for keys) -> (label, formatter)
_SPECIFIC: dict[tuple[str, ...], tuple[str, Any]] = {
    ("capabilities", "*", "capacity", "value"): ("ظرفیت", _fmt),
    ("capabilities", "*", "capacity", "mode"): ("نوع ظرفیت", _fmt),
    ("capabilities", "*", "capacity", "field"): ("فیلد ظرفیت", _fmt),
    ("capabilities", "*", "cancellation", "enabled"): ("امکان لغو ثبت‌نام", _fmt),
    ("capabilities", "*", "cancellation", "deadline_hours"): ("مهلت لغو ثبت‌نام", _hours_until_start),
    ("capabilities", "*", "waitlist", "enabled"): ("لیست انتظار", _fmt),
    ("capabilities", "*", "waitlist", "auto_promote"): ("جایگزینی خودکار از لیست انتظار", _fmt),
    ("capabilities", "*", "closes_hours_before_start"): ("بسته شدن ثبت‌نام", _closes),
    ("capabilities", "*", "max_active_per_user"): ("حداکثر ثبت‌نام فعال هر کاربر", _unlimited),
}


def _name_of(elem: Any) -> str:
    if isinstance(elem, dict):
        for k in ("title", "label", "key"):
            if isinstance(elem.get(k), str):
                return f"«{elem[k]}»"
    return "؟"


class _Differ:
    def __init__(self, old: dict[str, Any], new: dict[str, Any]) -> None:
        self.old_root = old
        self.new_root = new
        self.out: list[SpecChange] = []

    # schema path: keys of keyed-list elements replaced by "*"; ctx: nested element descriptors
    def run(self) -> list[SpecChange]:
        self._walk(self.old_root, self.new_root, ROOT, [], (), [])
        return self.out

    def _walk(
        self, old: Any, new: Any, shape: Shape, path: list[str], pattern: tuple[str, ...], ctx: list[str]
    ) -> None:
        if shape.kind == "model" and isinstance(old, dict) and isinstance(new, dict):
            cls_old = pick_model(shape.models, old)
            cls_new = pick_model(shape.models, new)
            if cls_old is None or cls_old is not cls_new:
                self._changed(path, old, new, pattern, ctx)
                return
            for name, info in cls_old.model_fields.items():
                self._walk(
                    old.get(name),
                    new.get(name),
                    shape_of(info.annotation),
                    [*path, name],
                    (*pattern, name),
                    ctx,
                )
        elif shape.kind == "keyed_list" and isinstance(old, list) and isinstance(new, list):
            self._keyed(old, new, shape, path, pattern, ctx)
        elif old != new:
            self._changed(path, old, new, pattern, ctx)

    def _keyed(
        self,
        old: list[Any],
        new: list[Any],
        shape: Shape,
        path: list[str],
        pattern: tuple[str, ...],
        ctx: list[str],
    ) -> None:
        list_name = path[-1] if path else ""
        kind_fa = LIST_KIND_FA.get(list_name, list_name)
        old_by = {e["key"]: e for e in old if isinstance(e, dict) and "key" in e}
        new_by = {e["key"]: e for e in new if isinstance(e, dict) and "key" in e}
        prefix = self._prefix(ctx)
        for key, elem in old_by.items():
            if key not in new_by:
                self.out.append(
                    SpecChange(
                        path=[*path, key],
                        kind="removed",
                        old=elem,
                        label_fa=f"{prefix}حذف شد: {kind_fa} {_name_of(elem)}",
                    )
                )
        for key, elem in new_by.items():
            if key not in old_by:
                self.out.append(
                    SpecChange(
                        path=[*path, key],
                        kind="added",
                        new=elem,
                        label_fa=f"{prefix}افزوده شد: {kind_fa} {_name_of(elem)}",
                    )
                )
        for key, elem in new_by.items():
            if key in old_by:
                # Elements nested below a top-level element get a context descriptor.
                sub_ctx = [*ctx, f"{kind_fa} {_name_of(elem)}"] if len(path) > 1 else ctx
                self._walk(
                    old_by[key], elem, Shape("model", shape.models), [*path, key], (*pattern, "*"), sub_ctx
                )
        common_old = [k for k in old_by if k in new_by]
        common_new = [k for k in new_by if k in old_by]
        if common_old != common_new:
            self.out.append(
                SpecChange(
                    path=path,
                    kind="changed",
                    old=common_old,
                    new=common_new,
                    label_fa=f"{prefix}ترتیب {kind_fa}‌ها تغییر کرد",
                )
            )

    @staticmethod
    def _prefix(ctx: list[str]) -> str:
        return f"{' › '.join(ctx)} — " if ctx else ""

    def _changed(self, path: list[str], old: Any, new: Any, pattern: tuple[str, ...], ctx: list[str]) -> None:
        spec = _SPECIFIC.get(pattern)
        if pattern and pattern[-1] == "*":  # a whole keyed element replaced (capability type change)
            kind_fa = LIST_KIND_FA.get(path[-2], path[-2]) if len(path) >= 2 else ""
            label, fmt = f"{kind_fa} «{path[-1]}» جایگزین شد", _name_of
        elif spec is not None:
            label, fmt = spec
        else:
            name = path[-1] if path else ""
            label, fmt = FIELD_LABELS_FA.get(name, name), _fmt
        line = f"{self._prefix(ctx)}{label}: {fmt(old)} ← {fmt(new)}"
        self.out.append(SpecChange(path=path, kind="changed", old=old, new=new, label_fa=line))


def diff_specs(old: BotSpec, new: BotSpec) -> list[SpecChange]:
    return _Differ(old.model_dump(mode="json"), new.model_dump(mode="json")).run()


def affected_capabilities(changes: list[SpecChange]) -> list[str]:
    """Capability keys touched by the changes, in first-seen order."""
    seen: list[str] = []
    for ch in changes:
        if len(ch.path) >= 2 and ch.path[0] == "capabilities" and ch.path[1] not in seen:
            seen.append(ch.path[1])
    return seen
