"""Registry of overridable bot text keys and their whitelisted placeholders (frozen contract).

``TEXT_KEYS[capability_type][text_key]`` is the set of placeholder names a text for that key may
use. Engines (``runtime/texts_fa.py``) must provide a default Persian string for exactly these keys,
using only these placeholders; ``validate_spec`` checks ``texts`` overrides against this registry.
Adding a key is an additive contract change: add it here and in ``texts_fa.py`` together.

Placeholder syntax is ``{name}``. Substitution is literal string replacement (``fill_text``); there
is no ``str.format``, no expressions and no escaping language. Unknown ``{...}`` sequences are left
as is. Values are plain text (the Telegram adapter HTML-escapes the final message).

Placeholder meanings:
  title    - item title (booking/catalog item) or capability title (headers, request texts)
  details  - pre-rendered detail lines of an item
  remaining- free seats left on an item (booking)
  position - 1-based waitlist position (booking)
  hours    - a configured hour count (deadline, cutoff)
  limit    - max_active_per_user (booking)
  user     - display name of the acting bot user (owner notices)
  label    - FieldDef.label of the form field being asked
  error    - Persian validation message for a rejected form answer
  id       - request record id
  status   - Persian status label (request)
"""

import re

P = frozenset

_FORM_KEYS: dict[str, frozenset[str]] = {
    "ask_field": P({"label"}),
    "invalid_answer": P({"label", "error"}),
    "form_stopped": P(),
}

TEXT_KEYS: dict[str, dict[str, frozenset[str]]] = {
    "info": {
        "list_header": P({"title"}),
    },
    "catalog": {
        "list_header": P({"title"}),
        "empty": P({"title"}),
        "item_detail": P({"title", "details"}),
    },
    "booking": {
        "list_header": P({"title"}),
        "empty": P({"title"}),
        "item_detail": P({"title", "details", "remaining"}),
        "confirmed": P({"title"}),
        "waitlisted": P({"title", "position"}),
        "full": P({"title"}),
        "duplicate": P({"title"}),
        "user_limit": P({"limit"}),
        "closed": P({"title"}),
        "cancelled": P({"title"}),
        "cancel_deadline_passed": P({"title", "hours"}),
        "cancellation_disabled": P({"title"}),
        "promoted": P({"title"}),
        "mine_header": P(),
        "mine_empty": P(),
        "owner_booked": P({"title", "user"}),
        "owner_waitlisted": P({"title", "user"}),
        "owner_cancelled": P({"title", "user"}),
        **_FORM_KEYS,
    },
    "request": {
        "form_intro": P({"title"}),
        "pick_item": P({"title"}),
        "submitted": P({"title", "id"}),
        "mine_header": P(),
        "mine_empty": P(),
        "status_changed": P({"title", "id", "status"}),
        "owner_submitted": P({"title", "id", "user", "details"}),
        "action_done": P({"id", "status"}),
        "not_allowed": P(),
        **_FORM_KEYS,
    },
}

PLACEHOLDER_RE = re.compile(r"\{([A-Za-z_][A-Za-z0-9_]*)\}")


def allowed_placeholders(capability_type: str, text_key: str) -> frozenset[str] | None:
    """Placeholders allowed for a text key, or None if the key is not declared."""
    return TEXT_KEYS.get(capability_type, {}).get(text_key)


def placeholders_in(text: str) -> set[str]:
    return set(PLACEHOLDER_RE.findall(text))


def fill_text(template: str, values: dict[str, str]) -> str:
    """Literal, single-pass placeholder substitution.

    Each ``{name}`` with a provided value is replaced; substituted values are never re-scanned,
    so a value containing ``{other}`` stays literal.
    """
    return PLACEHOLDER_RE.sub(lambda m: values.get(m.group(1), m.group(0)), template)
