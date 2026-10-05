"""``orders`` engine: Wave 0 stub (Business OS commerce).

Every entry point answers politely that the section is not available yet, with the main menu,
and records nothing. Wave 1 (W1-ORD) replaces this module with the real cart / checkout / order
status engine (record layout: ``botspec/models.py`` module docstring).
"""

from typing import ClassVar

from app.botspec.models import OrdersCapability
from app.runtime.ctx import Ctx
from app.runtime.texts import orders as texts


class OrdersEngine:
    type: ClassVar[str] = "orders"

    @staticmethod
    def _not_ready(ctx: Ctx) -> None:
        ctx.reply(texts.NOT_READY, ctx.menu_buttons())

    async def open(self, ctx: Ctx, cap: OrdersCapability, view: str) -> None:
        self._not_ready(ctx)

    async def on_callback(self, ctx: Ctx, cap: OrdersCapability, action: str, arg: str) -> None:
        self._not_ready(ctx)

    async def on_text(self, ctx: Ctx, cap: OrdersCapability, text: str) -> None:
        await ctx.clear_session()
        self._not_ready(ctx)

    async def owner_action(self, ctx: Ctx, cap: OrdersCapability, record_id: int, action: str) -> None:
        self._not_ready(ctx)


ENGINE = OrdersEngine()
