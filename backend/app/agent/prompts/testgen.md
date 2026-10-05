# Task: testgen (acceptance scenarios)

Write 2 to 6 acceptance scenarios that check the bot does what the owner asked. You see the
requirements and an outline of the bot (keys, titles, resource fields, form fields). You do not see
the rule values on purpose: derive every expectation from the requirements, never from the bot.
Return JSON: `{"scenarios": [Scenario, ...]}`.

Scenario: `{"id", "title", "source": "acceptance", "requirement_ids", "capability_keys",
"capacity_override", "seed", "steps"}`.
- `id`: short snake_case, unique, starting with "acc_".
- `title`: one Persian sentence telling the story (e.g. «ظرفیت ۲: علی و سارا تأیید، رضا در لیست انتظار»).
- `requirement_ids`: the requirement ids (from the list below) this scenario checks. At least one.
- `capability_keys`: capability keys the steps use.
- `capacity_override`: for mechanism scenarios (waitlist, promotion, cancellation, duplicates) use 2
  so they stay short; leave null in the one scenario that checks the configured capacity number
  itself, and then use enough actors to reach that number (u1, u2, ... and one more).
- `seed`: items to create first: `{"ref": "w1", "collection": "<resource key>", "values":
  [{"key": "<field key>", "value": "<string>"}]}`. Fill every required field. Datetimes are relative:
  "+48h" (48 hours from the scenario start), "-1h", "+30m", "+2d". Numbers as plain digits.
- `steps`: semantic actions, executed in order:

| do | required fields | expect |
|---|---|---|
| book | actor, capability, item | confirmed / waitlisted / rejected (+ reason) |
| cancel | actor, capability, item | cancelled / rejected (+ reason) |
| expect_booking | actor, capability, item, expect | confirmed / waitlisted / cancelled / none (actor's latest booking on the item) |
| expect_counts | capability, item, confirmed and/or waitlisted | (no expect) |
| submit_request | actor, capability [item, form] | submitted / rejected |
| owner_action | capability, action, target_actor [item] | ok / rejected; on a booking: action "cancel" and item (owner cancels target_actor's booking) |
| expect_request | actor, capability, expect = a status key | |
| expect_notified | actor, event | (no expect) - event is one of booked, waitlisted, cancelled, promoted, submitted, status_changed, ordered, order_status_changed |
| open | actor, capability [item, view, contains] | (no expect) - contains may only check a value you seeded, e.g. an item title |
| advance_time | hours (> 0) | (no expect) - moves the clock forward |

`reason` (only with expect "rejected"): capacity_full, duplicate, user_limit, booking_closed,
cancel_deadline_passed, cancellation_disabled, not_found, invalid_input, not_allowed, out_of_stock.
`form`: `[{"key", "value"}]` answers for the capability's form fields (book and submit_request only).
Actors: any id like "ali", "sara", "reza", "u1"; "owner" is the bot owner. Owner notifications go
to "owner" (check them with expect_notified actor "owner").
Notifications are always matched with `event`, never `contains`.
Leave out fields a step does not use.

Steps per capability type (a step the type's driver lacks fails the test; never invent others):
- booking, including preset "events" (an event is a booking: RSVP = book, cancel RSVP = cancel; use
  the same steps and the same coverage): book, cancel, expect_booking, expect_counts, owner_action
  (action "cancel" + item), open, expect_notified, advance_time. Reminders, category filters and
  subscriptions have no steps: do not test them.
- request: submit_request, owner_action, expect_request, open, expect_notified, advance_time.
- orders, exactly these (cart and checkout are mapped onto the existing steps):
  - `book` (actor, capability, item): add one unit of the item to the actor's cart; expect
    confirmed (added) or rejected with reason out_of_stock.
  - `submit_request` (actor, capability, item, form): add the item and check out; `form` answers the
    checkout_fields by key; expect submitted or rejected.
  - `cancel` (actor, capability, item): the actor cancels their latest order containing the item;
    expect cancelled or rejected.
  - `owner_action` (capability, action = an owner action key, target_actor [actor "owner"]): moves
    the target's latest order; expect ok or rejected (not_allowed).
  - `expect_request` (actor, capability, expect = a status key, or "none" when no order): the
    actor's latest order status.
  - `open`, `expect_notified` (event ordered for the owner after checkout, order_status_changed for
    the customer after an owner action), `advance_time`.
  Never use expect_booking, expect_counts, totals, payment or quantities >1. Seed the catalog
  resource: fill its price_field (and stock_field, e.g. 1 to test out_of_stock) as plain digits.
Only test capabilities that are enabled; users cannot reach disabled ones, and capabilities with a
staff or managers audience are driven as the owner, so do not write multi-customer scenarios for them.

Good coverage, one scenario per behavior: the basic booking flow; reaching capacity (waitlisted
or rejected, as the requirements say); promotion from the waitlist after a cancellation (with
expect_notified "promoted"); cancellation freeing a seat; duplicates; the configured capacity
number; deadlines with advance_time; for orders: checkout then the owner action and the status,
out of stock, customer cancellation. Only test what a requirement states or assumes.

Example:
```
{"id": "acc_waitlist_promotion", "title": "ظرفیت ۲: با انصراف علی، رضا از لیست انتظار جایگزین می‌شود",
 "source": "acceptance", "requirement_ids": ["R3", "R4"], "capability_keys": ["book_workshop"],
 "capacity_override": 2,
 "seed": [{"ref": "w1", "collection": "workshop", "values": [{"key": "title", "value": "کارگاه سفال"},
           {"key": "starts_at", "value": "+48h"}]}],
 "steps": [{"do": "book", "actor": "ali", "capability": "book_workshop", "item": "w1", "expect": "confirmed"},
           {"do": "book", "actor": "sara", "capability": "book_workshop", "item": "w1", "expect": "confirmed"},
           {"do": "book", "actor": "reza", "capability": "book_workshop", "item": "w1", "expect": "waitlisted"},
           {"do": "cancel", "actor": "ali", "capability": "book_workshop", "item": "w1", "expect": "cancelled"},
           {"do": "expect_booking", "actor": "reza", "capability": "book_workshop", "item": "w1", "expect": "confirmed"},
           {"do": "expect_notified", "actor": "reza", "event": "promoted"},
           {"do": "expect_counts", "capability": "book_workshop", "item": "w1", "confirmed": 2, "waitlisted": 0}]}
```
