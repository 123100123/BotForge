"""The ``Engine`` protocol (roadmap: Capability Catalog) and an optional convenience base (WP1).

How the runtime calls an engine:
- ``open(ctx, cap, view)``           menu button ``menu:open:<item>``; view is "main" or "mine".
- ``on_callback(ctx, cap, action, arg)`` any other callback for ``cap``; ``action`` is already
  checked against ``callbacks.ACTIONS_BY_TYPE[cap.type]``. Form actions (ans/skip/stop) arrive
  here too: delegate them with ``forms.handle_callback``. The ``own`` action never arrives here:
  the runtime routes it (owner-checked) to ``owner_action``.
- ``on_text(ctx, cap, text)``        free text while the actor's session belongs to ``cap``.
- ``owner_action(ctx, cap, record_id, action)`` web-admin ``cancel``/``own`` or Telegram ``own``;
  the runtime has already checked ``actor.is_owner``.

Engines must not raise for bad user input or stale args; reply (``ctx.stale()`` or a Persian
explanation) and, for business actions, record an ``Outcome``.
"""

from typing import TYPE_CHECKING, Any, ClassVar, Protocol

if TYPE_CHECKING:
    from app.runtime.ctx import Ctx


class Engine(Protocol):
    type: ClassVar[str]

    async def open(self, ctx: "Ctx", cap: Any, view: str) -> None: ...

    async def on_callback(self, ctx: "Ctx", cap: Any, action: str, arg: str) -> None: ...

    async def on_text(self, ctx: "Ctx", cap: Any, text: str) -> None: ...

    async def owner_action(self, ctx: "Ctx", cap: Any, record_id: int, action: str) -> None: ...


class EngineBase:
    """Optional base with sensible defaults for engines that have no sessions or owner actions."""

    type: ClassVar[str] = ""

    async def open(self, ctx: "Ctx", cap: Any, view: str) -> None:  # pragma: no cover - abstract
        raise NotImplementedError

    async def on_callback(self, ctx: "Ctx", cap: Any, action: str, arg: str) -> None:
        ctx.stale()

    async def on_text(self, ctx: "Ctx", cap: Any, text: str) -> None:
        """No session of ours should exist: drop it and show the menu."""
        await ctx.clear_session()
        ctx.show_menu()

    async def owner_action(self, ctx: "Ctx", cap: Any, record_id: int, action: str) -> None:
        ctx.stale()
