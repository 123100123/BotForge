"""``info`` engine: static pages (WP1).

open: one page -> shown directly; several -> list of page buttons (``show``, arg = page key).
show: the page title and body, with "back" (re-opens the list via the menu item) and "home".
"""

from typing import ClassVar

from app.botspec.models import InfoCapability, InfoPage
from app.runtime.callbacks import ACT_SHOW
from app.runtime.contracts import Button
from app.runtime.ctx import Ctx
from app.runtime.engines.base import EngineBase


class InfoEngine(EngineBase):
    type: ClassVar[str] = "info"

    async def open(self, ctx: Ctx, cap: InfoCapability, view: str) -> None:
        if len(cap.pages) == 1:
            self._show_page(ctx, cap, cap.pages[0], with_back=False)
            return
        rows = [[ctx.button(p.title, cap, ACT_SHOW, p.key)] for p in cap.pages]
        rows.append(ctx.home_row())
        ctx.reply(ctx.t(cap, "list_header", title=cap.title), rows)

    async def on_callback(self, ctx: Ctx, cap: InfoCapability, action: str, arg: str) -> None:
        page = next((p for p in cap.pages if p.key == arg), None) if action == ACT_SHOW else None
        if page is None:
            ctx.stale()
            return
        self._show_page(ctx, cap, page, with_back=len(cap.pages) > 1)

    def _show_page(self, ctx: Ctx, cap: InfoCapability, page: InfoPage, *, with_back: bool) -> None:
        row: list[Button] = []
        back = ctx.menu_button_for(cap) if with_back else None
        if back is not None:
            row.append(back)
        row.append(ctx.home_button())
        ctx.reply(f"{page.title}\n\n{page.body}", [row])


ENGINE = InfoEngine()
