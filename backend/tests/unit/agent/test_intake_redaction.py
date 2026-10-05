"""Owner text entering an agent run: a Telegram bot token is redacted before it is stored, emitted or
sent to a model, also when it is written with spaces around the colon."""

import pytest

from app.agent.orchestrator import TOKEN_NOTICE, Orchestrator
from app.agent.state import RunState
from app.security.redact import REDACTED

SECRET = "AAHdqTcvCH1vGWJxfSeofSAs0K5PALDsawQ"  # 35 characters, like a real token's secret part


@pytest.mark.parametrize(
    "token",
    [
        f"123456789:{SECRET}",
        f"123456789 : {SECRET}",
        f"123456789: {SECRET}",
        f"123456789\u200f : \u200e{SECRET}",  # bidi marks around the colon, as in mixed Persian text
    ],
)
def test_intake_redacts_compact_and_spaced_tokens(token: str) -> None:
    state = RunState(kind="create", phase="understand")
    events = Orchestrator._intake(state, f"توکن ربات من {token} است")
    assert SECRET not in state.model_dump_json() + repr(events)
    assert events == [
        ("owner_message", {"text": f"توکن ربات من {REDACTED} است"}),
        ("agent_message", {"text": TOKEN_NOTICE}),
    ]


def test_intake_keeps_times_and_phone_numbers() -> None:
    state = RunState(kind="create", phase="understand")
    message = "کلاس‌ها ساعت 10 : 30 شروع می‌شوند. شماره تماس 09121234567 : فقط پیامک."
    assert Orchestrator._intake(state, message) == [("owner_message", {"text": message})]
