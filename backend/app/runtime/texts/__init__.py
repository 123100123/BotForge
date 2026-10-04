"""Default Persian texts per capability type (WP1 registry; one module per type).

Convention: ``app/runtime/texts/<type>.py`` defines ``TEXTS: dict[str, str]`` with a default for
exactly the keys ``botspec.text_keys.TEXT_KEYS[<type>]`` declares, using only the whitelisted
placeholders. Types with ``form_fields`` include ``**common.FORM_TEXTS``. Modules are imported on
first use, so adding a type means adding its module; nothing here is edited.
"""

import importlib
from functools import cache

TEXTS_PACKAGE = "app.runtime.texts"


def texts_module_name(capability_type: str) -> str:
    return f"{TEXTS_PACKAGE}.{capability_type}"


@cache
def default_texts(capability_type: str) -> dict[str, str]:
    """The type's default texts, or ``{}`` if its module does not exist yet."""
    name = texts_module_name(capability_type)
    try:
        module = importlib.import_module(name)
    except ModuleNotFoundError as exc:
        if exc.name == name:
            return {}
        raise
    return dict(module.TEXTS)


def default_text(capability_type: str, key: str) -> str | None:
    return default_texts(capability_type).get(key)
