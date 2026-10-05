"""Lazy engine registry: capability type -> engine module, imported on first use (WP1).

Each engine module defines a module-level ``ENGINE`` instance satisfying ``engines.base.Engine``.
A type whose module does not exist yet raises ``EngineUnavailable``; the runtime turns that into a
"not available yet" reply. An ImportError raised *inside* an existing engine module is a bug and
propagates.
"""

import importlib
from collections.abc import Iterator
from contextlib import contextmanager

from app.runtime.engines.base import Engine

ENGINE_MODULES: dict[str, str] = {
    "info": "app.runtime.engines.info",
    "catalog": "app.runtime.engines.catalog",
    "booking": "app.runtime.engines.booking",
    "request": "app.runtime.engines.request",
    "orders": "app.runtime.engines.orders",  # Wave 0 stub; W1-ORD replaces the module
}

_loaded: dict[str, Engine] = {}
_overrides: dict[str, Engine] = {}


class EngineUnavailable(LookupError):
    """No engine is installed for this capability type (module missing or type unknown)."""


def get_engine(capability_type: str) -> Engine:
    if capability_type in _overrides:
        return _overrides[capability_type]
    if capability_type in _loaded:
        return _loaded[capability_type]
    module_name = ENGINE_MODULES.get(capability_type)
    if module_name is None:
        raise EngineUnavailable(capability_type)
    try:
        module = importlib.import_module(module_name)
    except ModuleNotFoundError as exc:
        if exc.name == module_name:
            raise EngineUnavailable(capability_type) from exc
        raise
    engine: Engine = module.ENGINE
    _loaded[capability_type] = engine
    return engine


@contextmanager
def override_engine(capability_type: str, engine: Engine) -> Iterator[Engine]:
    """Test helper: use ``engine`` for ``capability_type`` inside the ``with`` block."""
    previous = _overrides.get(capability_type)
    _overrides[capability_type] = engine
    try:
        yield engine
    finally:
        if previous is None:
            _overrides.pop(capability_type, None)
        else:
            _overrides[capability_type] = previous
