"""Derived scenarios for the events preset of the booking capability (W1-EVT).

Importing this module wraps the ``booking`` entry of ``derive.TEMPLATES`` so that a booking
capability with ``preset == "events"`` gets, on top of every plain booking template (an event is a
booking, capacity and waitlist included), these scenarios:

  ``events_list``             opening the events list shows the seeded event: its title, and its
                              category when the capability has a ``category_field``
  ``events_category_filter``  a category the seeded event is NOT in is offered (as a filter
                              button) in the list reply; needs a category field with 2+ choices
  ``events_rsvp_mine``        RSVP (book) confirms and the event then shows in "ثبت‌نام‌های من"
  ``events_cancel_rsvp``      cancelling the RSVP frees the seat (needs ``cancellation.enabled``)

Scenario steps are a frozen vocabulary without a way to press ``list:sub.<idx>``, so the
subscription toggle is covered by ``tests/unit/runtime/test_events_preset.py`` instead. Like all
derived tests, these only check values the scenario seeded, never engine wording.

Registration happens on import and is idempotent. ``app.testing.derive`` does not import this
module (it would be circular), so something must: the integrator adds
``from app.testing import events_derive  # noqa: F401`` at the end of ``app/testing/derive.py``
(or in ``app/testing/__init__.py``).
"""

from app.botspec.models import BookingCapability, BotSpec, FieldType
from app.testing import derive
from app.testing.derive import _Booking, _has_menu, _rendered_title
from app.testing.scenario import Scenario, Step


def _category_values(spec: BotSpec, cap: BookingCapability) -> list[str]:
    resource = spec.resource(cap.resource)
    if resource is None or cap.category_field is None:
        return []
    field = next((f for f in resource.fields if f.key == cap.category_field), None)
    if field is None or field.type != FieldType.choice:
        return []
    return list(field.choices or [])


def events_templates(spec: BotSpec, cap: BookingCapability) -> list[Scenario]:
    """The events-only scenarios of ``cap`` (empty unless it is an events preset users can reach)."""
    resource = spec.resource(cap.resource)
    if cap.preset != "events" or resource is None or not _has_menu(spec, cap.key, "main"):
        return []
    b = _Booking(spec, cap, resource)
    seed = b.seeds()
    title = _rendered_title(spec, resource, seed[0])
    categories = _category_values(spec, cap)

    list_contains = [title]
    if categories:
        list_contains.append(categories[0])  # the seeded choice (see derive._field_value)
    steps = [Step(do="open", actor="ali", capability=cap.key, contains=text) for text in list_contains]
    b.add("events_list", "فهرست رویدادهای پیش‌رو، رویداد ثبت‌شده دیده می‌شود", steps, seed)

    if len(categories) >= 2:
        other = categories[-1]  # never the seeded first choice, so only a filter button shows it
        filter_steps = [Step(do="open", actor="ali", capability=cap.key, contains=other)]
        b.add("events_category_filter", "فیلتر دسته‌بندی در فهرست رویدادها", filter_steps, b.seeds())

    rsvp = [b.book("ali", "i1", "confirmed"), b.booking("ali", "i1", "confirmed"), b.counts("i1", 1, 0)]
    if _has_menu(spec, cap.key, "mine"):
        rsvp.append(Step(do="open", actor="ali", capability=cap.key, view="mine", contains=title))
    b.add("events_rsvp_mine", "ثبت‌نام در رویداد و نمایش آن در «ثبت‌نام‌های من»", rsvp, b.seeds())

    if cap.cancellation.enabled:
        cancel = [
            b.book("ali", "i1", "confirmed"),
            b.cancel("ali", "i1", "cancelled"),
            b.booking("ali", "i1", "cancelled"),
            b.counts("i1", 0, 0),
        ]
        b.add("events_cancel_rsvp", "لغو شرکت در رویداد", cancel, b.seeds())
    return b.out


def _install() -> None:
    base = derive.TEMPLATES["booking"]
    if getattr(base, "events_aware", False):
        return

    def booking_with_events(spec: BotSpec, cap: BookingCapability) -> list[Scenario]:
        return [*base(spec, cap), *events_templates(spec, cap)]

    booking_with_events.events_aware = True  # type: ignore[attr-defined]
    derive.register_templates("booking", booking_with_events)


_install()
