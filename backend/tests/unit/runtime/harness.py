"""Event-level test harness for runtime tests (reusable by engine packages).

h = Harness(spec)                       # MemoryStore with owner "owner", clock at T0
r = await h.start("ali")                # /start
r = await h.tap("ali", "menu:open:about")
r = await h.send("ali", "متن")
r = await h.admin("repair:own:17.approve")   # as the owner
h.advance(hours=2)
"""

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from app.botspec.models import BotSpec
from app.runtime.contracts import Actor, Button, RuntimeEvent, RuntimeResponse
from app.runtime.memory_store import MemoryStore
from app.runtime.runtime import BotRuntime

EXAMPLES = Path(__file__).resolve().parents[4] / "examples"
T0 = datetime(2026, 10, 4, 8, 0, tzinfo=UTC)  # 12 Mehr 1405, 11:30 Tehran


def load_example(name: str) -> BotSpec:
    return BotSpec.model_validate(json.loads((EXAMPLES / name).read_text(encoding="utf-8")))


class Harness:
    def __init__(self, spec: BotSpec, store: MemoryStore | None = None, now: datetime = T0) -> None:
        self.spec = spec
        self.store = store or MemoryStore()
        self.now = now
        self.runtime = BotRuntime()
        self.last: RuntimeResponse | None = None

    def advance(self, hours: float) -> None:
        self.now += timedelta(hours=hours)

    @staticmethod
    def actor(actor_id: str) -> Actor:
        return Actor(id=actor_id, display_name=actor_id, is_owner=actor_id == "owner")

    async def event(
        self, actor: str | Actor, kind: str, *, text: str | None = None, data: str | None = None
    ) -> RuntimeResponse:
        a = actor if isinstance(actor, Actor) else self.actor(actor)
        ev = RuntimeEvent(
            bot_id="b1",
            env="sandbox",
            actor=a,
            kind=kind,
            text=text,
            data=data,
            now=self.now,  # type: ignore[arg-type]
        )
        self.last = await self.runtime.handle(ev, self.spec, self.store)
        return self.last

    async def start(self, actor: str | Actor = "ali") -> RuntimeResponse:
        return await self.event(actor, "start")

    async def tap(self, actor: str | Actor, data: str) -> RuntimeResponse:
        return await self.event(actor, "callback", data=data)

    async def send(self, actor: str | Actor, text: str) -> RuntimeResponse:
        return await self.event(actor, "text", text=text)

    async def admin(self, data: str, actor: str | Actor = "owner") -> RuntimeResponse:
        return await self.event(actor, "admin", data=data)

    async def seed(self, collection: str, data: dict[str, Any], **kw: Any) -> int:
        rec = await self.store.create_record(collection, data, now=self.now, **kw)
        return rec.id


def buttons(resp: RuntimeResponse, msg: int = -1) -> list[Button]:
    """Flattened buttons of message ``msg`` (default: last)."""
    return [b for row in resp.messages[msg].buttons for b in row]


def button_data(resp: RuntimeResponse, msg: int = -1) -> list[str]:
    return [b.data for b in buttons(resp, msg)]


def find_button(resp: RuntimeResponse, label: str, msg: int = -1) -> Button:
    for b in buttons(resp, msg):
        if label in b.label:
            return b
    raise AssertionError(f"no button containing {label!r}; have {[b.label for b in buttons(resp, msg)]}")


def text(resp: RuntimeResponse, msg: int = -1) -> str:
    return resp.messages[msg].text
