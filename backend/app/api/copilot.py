"""Manager Copilot API: one stateless endpoint (the client sends the last turns of the conversation).

The model is the one the agent runs use (``make_llm``); without a configured provider the endpoint
answers 503 ``llm_unavailable``. Tests override ``get_copilot_llm`` with a ``FakeLLM``.
"""

from datetime import UTC, datetime

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from app.agent.llm import LLMClient, make_llm
from app.api.deps import get_owned_bot
from app.config import get_settings
from app.copilot import service
from app.db.models import Bot
from app.db.session import get_session
from app.schemas.business import CopilotMessageIn, CopilotMessageOut

router = APIRouter(tags=["copilot"])

LLM_UNAVAILABLE = "دستیار هوشمند در این سرور تنظیم نشده است. لطفاً با مدیر سیستم تماس بگیرید."


def get_copilot_llm() -> LLMClient:
    settings = get_settings()
    if settings.LLM_PROVIDER == "anthropic" and not settings.ANTHROPIC_API_KEY:
        raise HTTPException(status_code=503, detail={"code": "llm_unavailable", "message": LLM_UNAVAILABLE})
    return make_llm()


@router.post("/bots/{bot_id}/copilot/messages", response_model=CopilotMessageOut)
async def post_message(
    body: CopilotMessageIn,
    bot: Bot = Depends(get_owned_bot),
    session: AsyncSession = Depends(get_session),
    llm: LLMClient = Depends(get_copilot_llm),
) -> CopilotMessageOut:
    try:
        return await service.ask(session, bot, llm, body.messages, now=datetime.now(UTC))
    except service.CopilotError as exc:
        raise HTTPException(
            status_code=exc.status, detail={"code": exc.code, "message": exc.message}
        ) from None
