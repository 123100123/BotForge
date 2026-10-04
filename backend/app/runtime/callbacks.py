"""Telegram callback data format and action vocabulary (frozen contract, WP0).

Format: ``"<capability_key>:<action>:<arg>"``, at most 64 bytes UTF-8 (Telegram's limit).
``menu`` is a reserved pseudo-capability. Parsing splits on the first two ':' only, so an arg may
contain ':' or '.'; the arg may be empty (the data then ends with ':').

Engines and drivers build and parse callback data only through ``make_callback`` /
``parse_callback`` and only with the actions below. The Telegram adapter treats data as opaque.

Vocabulary (capability type -> action -> arg):
  menu (pseudo)  home  -> ""                       open -> menu item key
  info           show  -> page key
  catalog        list  -> page number               item -> record id
  booking        list  -> page number               item -> record id
                 book  -> item record id            mine -> ""
                 cancel-> booking record id
  request        new   -> ""                        pick -> item record id
                 mine  -> ""                        own  -> "<record_id>.<owner_action_key>"
  form (any)     ans   -> choice index              skip -> ""        stop -> ""
"""

import re

MAX_CALLBACK_BYTES = 64
MENU = "menu"

ACT_HOME = "home"
ACT_OPEN = "open"
ACT_SHOW = "show"
ACT_LIST = "list"
ACT_ITEM = "item"
ACT_BOOK = "book"
ACT_MINE = "mine"
ACT_CANCEL = "cancel"
ACT_NEW = "new"
ACT_PICK = "pick"
ACT_OWN = "own"
ACT_ANS = "ans"
ACT_SKIP = "skip"
ACT_STOP = "stop"

FORM_ACTIONS = frozenset({ACT_ANS, ACT_SKIP, ACT_STOP})
ACTIONS_BY_TYPE: dict[str, frozenset[str]] = {
    MENU: frozenset({ACT_HOME, ACT_OPEN}),
    "info": frozenset({ACT_SHOW}),
    "catalog": frozenset({ACT_LIST, ACT_ITEM}),
    "booking": frozenset({ACT_LIST, ACT_ITEM, ACT_BOOK, ACT_MINE, ACT_CANCEL}) | FORM_ACTIONS,
    "request": frozenset({ACT_NEW, ACT_PICK, ACT_MINE, ACT_OWN}) | FORM_ACTIONS,
}
ALL_ACTIONS: frozenset[str] = frozenset().union(*ACTIONS_BY_TYPE.values())

_CAP_RE = re.compile(r"^[a-z][a-z0-9_]{0,23}$")  # same as botspec Key; "menu" also matches


class CallbackError(ValueError):
    pass


def make_callback(capability_key: str, action: str, arg: str = "") -> str:
    if not _CAP_RE.fullmatch(capability_key):
        raise CallbackError(f"invalid capability key {capability_key!r}")
    if action not in ALL_ACTIONS:
        raise CallbackError(f"unknown callback action {action!r}")
    data = f"{capability_key}:{action}:{arg}"
    if len(data.encode("utf-8")) > MAX_CALLBACK_BYTES:
        raise CallbackError(f"callback data exceeds {MAX_CALLBACK_BYTES} bytes: {data!r}")
    return data


def parse_callback(data: str) -> tuple[str, str, str]:
    """Return ``(capability_key, action, arg)``; raise CallbackError on malformed data."""
    if len(data.encode("utf-8")) > MAX_CALLBACK_BYTES:
        raise CallbackError("callback data too long")
    parts = data.split(":", 2)
    if len(parts) != 3:
        raise CallbackError(f"malformed callback data {data!r}")
    cap, action, arg = parts
    if not _CAP_RE.fullmatch(cap) or action not in ALL_ACTIONS:
        raise CallbackError(f"malformed callback data {data!r}")
    return cap, action, arg
