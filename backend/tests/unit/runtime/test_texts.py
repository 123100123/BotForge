"""Every engine texts module defines exactly the registered keys with only allowed placeholders.

Applies automatically to ``texts/booking.py`` and ``texts/request.py`` once they exist.
"""

import importlib.util

import pytest

from app.botspec.text_keys import TEXT_KEYS, placeholders_in
from app.runtime.texts import common, default_texts, texts_module_name

REQUIRED_NOW = {"info", "catalog"}


@pytest.mark.parametrize("cap_type", sorted(TEXT_KEYS))
def test_default_texts_match_registry(cap_type: str) -> None:
    exists = importlib.util.find_spec(texts_module_name(cap_type)) is not None
    if not exists:
        assert cap_type not in REQUIRED_NOW
        pytest.skip(f"texts/{cap_type}.py not written yet")
    texts = default_texts(cap_type)
    assert set(texts) == set(TEXT_KEYS[cap_type])
    for key, value in texts.items():
        extra = placeholders_in(value) - TEXT_KEYS[cap_type][key]
        assert not extra, f"{cap_type}.{key} uses non-whitelisted placeholders {extra}"
        assert value.strip()


def test_form_texts_cover_registered_form_keys() -> None:
    form_keys = {"ask_field", "invalid_answer", "form_stopped"}
    assert set(common.FORM_TEXTS) == form_keys
    for cap_type in ("booking", "request"):
        assert form_keys <= set(TEXT_KEYS[cap_type])
        for key in form_keys:
            assert placeholders_in(common.FORM_TEXTS[key]) <= TEXT_KEYS[cap_type][key]


def test_missing_texts_module_is_empty() -> None:
    assert default_texts("no_such_type") == {}
