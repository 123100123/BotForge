"""``catalog`` engine: browse resource records (WP1).

open / ``list:<page>``: paginated list (8 per page, 0-based page arg), one button per record
labelled with its ``title_field`` (callback ``item:<record id>``), honoring
``upcoming_only_field`` (records whose datetime is before ``event.now`` are hidden),
``sort_field`` and ``sort_desc``.
``item:<id>``: the record's ``detail_fields`` as "label: value" lines (text key ``item_detail``),
with "back" (to the page the item is on) and "home". A missing or hidden record is stale.
"""

from typing import ClassVar

from app.botspec.models import CatalogCapability, Resource
from app.runtime import listing
from app.runtime.callbacks import ACT_ITEM, ACT_LIST
from app.runtime.contracts import Button
from app.runtime.ctx import Ctx, parse_int
from app.runtime.engines.base import EngineBase
from app.runtime.store import Record


class CatalogEngine(EngineBase):
    type: ClassVar[str] = "catalog"

    async def open(self, ctx: Ctx, cap: CatalogCapability, view: str) -> None:
        await self._list(ctx, cap, 0)

    async def on_callback(self, ctx: Ctx, cap: CatalogCapability, action: str, arg: str) -> None:
        if action == ACT_LIST:
            await self._list(ctx, cap, parse_int(arg) or 0)
        elif action == ACT_ITEM:
            await self._item(ctx, cap, parse_int(arg))
        else:
            ctx.stale()

    async def _items(self, ctx: Ctx, cap: CatalogCapability) -> tuple[Resource, list[Record]] | None:
        resource = ctx.spec.resource(cap.resource)
        if resource is None:
            return None
        items = await listing.load_items(
            ctx,
            resource,
            upcoming_only_field=cap.upcoming_only_field,
            sort_field=cap.sort_field,
            sort_desc=cap.sort_desc,
        )
        return resource, items

    async def _list(self, ctx: Ctx, cap: CatalogCapability, page: int) -> None:
        loaded = await self._items(ctx, cap)
        if loaded is None:
            ctx.stale()
            return
        resource, items = loaded
        if not items:
            ctx.reply(ctx.t(cap, "empty", title=cap.title), [ctx.home_row()])
            return
        shown, page, pages = listing.paginate(items, page)
        rows: list[list[Button]] = [
            [ctx.button(listing.truncate(listing.record_title(ctx, resource, r)), cap, ACT_ITEM, r.id)]
            for r in shown
        ]
        nav = listing.nav_row(cap, page, pages)
        if nav:
            rows.append(nav)
        rows.append(ctx.home_row())
        text = ctx.t(cap, "list_header", title=cap.title)
        if pages > 1:
            text += "\n" + listing.page_indicator(page, pages)
        ctx.reply(text, rows)

    async def _item(self, ctx: Ctx, cap: CatalogCapability, record_id: int | None) -> None:
        loaded = await self._items(ctx, cap)
        if loaded is None or record_id is None:
            ctx.stale()
            return
        resource, items = loaded
        record = next((r for r in items if r.id == record_id), None)
        if record is None:
            ctx.stale()
            return
        text = ctx.t(
            cap,
            "item_detail",
            title=listing.record_title(ctx, resource, record),
            details=listing.detail_lines(ctx, resource, record, cap.detail_fields),
        )
        ctx.reply(text, [ctx.back_home_row(cap, ACT_LIST, listing.page_of(items, record.id))])


ENGINE = CatalogEngine()
