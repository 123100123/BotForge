"""deploy: activate the approved draft revision through the revisions service (deterministic)."""

from app.agent import events as ev
from app.agent.context import Next, RunContext
from app.agent.phases import say

DEPLOYED_TEXT = (
    "نسخهٔ جدید فعال شد. حالا در بخش «داده‌ها» موارد واقعی را اضافه کنید و در «تنظیمات» "
    "توکن ربات تلگرام را وصل کنید."
)


async def run(ctx: RunContext) -> Next:
    """Raises ActivationRefused (from the repository) when the revisions service refuses."""
    state = ctx.state
    assert state.revision_id is not None
    number = await ctx.repo.activate(state.revision_id)
    await ctx.emit(ev.deployed(state.revision_id, number))
    await say(ctx, DEPLOYED_TEXT)
    return Next("deploy", "done")
