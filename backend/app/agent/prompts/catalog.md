# Capability catalog

A BotSpec has five parts (capability types: info, catalog, booking, request, orders):

```
{"spec_version": 1,
 "bot": {"name": "<Persian>", "welcome_text": "<Persian>", "timezone": "Asia/Tehran", "language": "fa"},
 "resources": [ ...owner-managed item types... ],
 "capabilities": [ ...what bot users can do... ],
 "menu": [ ...main-menu buttons, 1 to 8... ]}
```

Every list is a list of objects with a unique `key`. Resource keys and capability keys share one
namespace (they must differ), and `menu` is reserved. All objects reject unknown properties.

## Resources (owner-managed items)

A resource is a kind of item the owner adds in the web admin (workshops, services, products,
appliance types). Bot users never create resources; they browse and book or request them.

```
{"key": "workshop", "label": "کارگاه", "label_plural": "کارگاه‌ها", "title_field": "title",
 "fields": [FieldDef, ...]}
```

FieldDef: `{"key", "label" (Persian), "type", "required" (default true), "choices" (only for
choice: 2+ unique strings, else null), "default" (string form or null)}`.
Field types: `text`, `long_text`, `integer`, `decimal`, `datetime`, `boolean`, `choice`, `phone`.
`title_field` must be one of the resource's fields (usually a required text field).
Datetimes exist only on resources (entered by the owner); bot users never type dates.
Typical item fields: title (text), description (long_text, required: false is fine), a start time
(datetime) when items happen at a time, a price (integer, toman, often required: false), a teacher
or provider (text).

## info - static pages

What: buttons that show fixed Persian text (about us, address and hours, rules, FAQ).
Parameters: `type: "info"`, `key`, `title` (Persian), `pages: [{"key", "title", "body"}]` (body is
Persian plain text; newlines allowed).
When: the owner mentions information to show; also a sensible default "about" page with
placeholder text the owner can edit later is fine when a bot has nothing else to say about itself.
Example:
```
{"type": "info", "key": "info", "title": "دربارهٔ ما",
 "pages": [{"key": "about", "title": "دربارهٔ ما", "body": "..."},
           {"key": "address", "title": "نشانی و تماس", "body": "..."}]}
```

## catalog - browse a list of items

What: list -> detail browsing of a resource, no reservation.
Parameters: `type: "catalog"`, `key`, `title`, `resource` (resource key), `detail_fields` (field
keys shown on the detail view), `upcoming_only_field` (a datetime field; hides past items; default
null), `sort_field` (default null = insertion order), `sort_desc` (default false), `texts` (default []).
When: the owner wants customers to see a menu, a price list, or services, but not reserve them.
Example: `{"type": "catalog", "key": "services", "title": "خدمات", "resource": "service",
"detail_fields": ["description", "price"]}`

## booking - reserve seats on items

What: users browse bookable items, reserve, see "my reservations", and cancel. Capacity,
duplicates, per-user limits, a booking cutoff, a waitlist with automatic promotion, and a
cancellation deadline are typed parameters.
Parameters (defaults in brackets):
- `type: "booking"`, `key`, `title`, `resource` (the bookable items), `detail_fields`.
- `capacity`: `{"mode": "fixed", "value": N, "field": null}` - the same N seats for every item, set
  in the spec; or `{"mode": "per_item", "value": null, "field": "<integer field>"}` - each item
  stores its own capacity in a required integer field of the resource.
  Choosing the mode: if the owner states one uniform number ("ظرفیت هر کارگاه ۱۰ نفر است"), use
  fixed with that number. Use per_item only when the owner says capacity differs per item. If the
  owner says nothing, ask (blocking) or assume per_item with a required capacity field.
  Appointment slots (one person per slot) are fixed with value 1.
- `start_field` [null]: datetime field when the item happens. Needed by the deadline and cutoff.
- `form_fields` [[]]: FieldDefs asked from the user when booking (e.g. phone number); no datetime.
- `one_active_per_user_per_item` [true]: a user cannot hold two active bookings on one item.
- `max_active_per_user` [null]: max active bookings per user across items.
- `closes_hours_before_start` [null]: booking closes this many hours before start (needs start_field).
- `waitlist` [`{"enabled": false, "auto_promote": true}`]: when full, new bookings are waitlisted
  instead of rejected; with auto_promote, when a confirmed booking is cancelled the oldest
  waitlisted booking is confirmed and that user is notified.
- `cancellation` [`{"enabled": true, "deadline_hours": null}`]: users may cancel; with
  deadline_hours, cancelling is refused less than that many hours before start (needs start_field).
- `notify_owner_on` [[]]: any of "booked", "waitlisted", "cancelled" - owner alerts in Telegram.
- `notify_user_on` [["promoted"]]: the user is told when promoted from the waitlist.
- `texts` [[]]: Persian text overrides (see below); usually leave empty.
Menu: give a booking a "main" menu item (browse and book) and, when cancellation is enabled, a
"mine" menu item (my reservations) - otherwise users cannot reach their bookings to cancel.
Sensible defaults: owner notified on "booked" and "cancelled"; duplicates blocked.
Events preset (registry id events): `preset: "events"` (default "booking") is the same booking
capability shaped for the events of a team, club or company: RSVP = booking, "mine" = my RSVPs.
Extras: `category_field` [null] (a `choice` field of the resource, e.g. آموزشی / سازمانی / اجتماعی;
users filter the list by it and can subscribe to a category), `reminder_hours_before` [null] (1 to
720, needs `start_field`; attendees are reminded automatically). Use per_item capacity with a
required integer capacity field, a `start_field`, a waitlist and cancellation. Publishing an event
card to a Telegram group is done by the owner in the web admin after the bot is built, not in the
spec.
Example:
```
{"type": "booking", "key": "book_workshop", "title": "ثبت‌نام در کارگاه", "resource": "workshop",
 "capacity": {"mode": "fixed", "value": 10, "field": null}, "start_field": "starts_at",
 "detail_fields": ["description", "teacher", "starts_at", "price"], "form_fields": [],
 "one_active_per_user_per_item": true, "max_active_per_user": null,
 "closes_hours_before_start": null, "waitlist": {"enabled": true, "auto_promote": true},
 "cancellation": {"enabled": true, "deadline_hours": null},
 "notify_owner_on": ["booked", "cancelled"], "notify_user_on": ["promoted"], "texts": []}
```

## request - submit a form, owner moves its status

What: a user fills a short form (and optionally picks one item of a resource); the request gets a
status; the owner approves, rejects or advances it (in Telegram or the web admin) and the user is
notified of status changes. Users can see "my requests".
Parameters: `type: "request"`, `key`, `title`, `form_fields` (FieldDefs, no datetime),
`item_resource` [null] (resource to pick one item from), `statuses` (`[{"key", "label"}]`),
`initial_status` (a status key), `owner_actions` (`[{"key", "label", "from_statuses": [...],
"to_status"}]`), `notify_owner_on` [["submitted"]], `notify_user_on` [["status_changed"]], `texts` [[]].
Capability key + owner action key must stay short (callback data limit): keep both under ~12 chars.
When: repair or service requests, applications, forms, simple single-item orders that the owner
confirms (several items or a cart: use `orders`).
Templates (registry ids forms, approvals, support and feedback are all `request` capabilities):
- forms / approvals: any key (e.g. `leave` for a leave request: statuses pending, approved,
  rejected; actions approve and reject from pending). Staff submit and managers decide, so for
  internal forms use `audience: "staff"`.
- support: key exactly `support`; fields subject (text) + text (long_text); statuses open, answered,
  closed; actions answer (open -> answered), close (open, answered -> closed).
- feedback: key exactly `feedback`; fields rating (choice ۱ to ۵) + comment (long_text, optional);
  statuses new, seen; action seen (new -> seen); `notify_user_on: []`.
Example:
```
{"type": "request", "key": "repair", "title": "درخواست تعمیر",
 "form_fields": [{"key": "device", "label": "نوع دستگاه", "type": "text", "required": true, "choices": null, "default": null},
                 {"key": "phone", "label": "شماره تماس", "type": "phone", "required": true, "choices": null, "default": null}],
 "item_resource": null,
 "statuses": [{"key": "pending", "label": "در انتظار بررسی"}, {"key": "approved", "label": "تأیید شد"},
              {"key": "rejected", "label": "رد شد"}, {"key": "done", "label": "انجام شد"}],
 "initial_status": "pending",
 "owner_actions": [{"key": "approve", "label": "تأیید", "from_statuses": ["pending"], "to_status": "approved"},
                   {"key": "reject", "label": "رد", "from_statuses": ["pending"], "to_status": "rejected"},
                   {"key": "done", "label": "انجام شد", "from_statuses": ["approved"], "to_status": "done"}],
 "notify_owner_on": ["submitted"], "notify_user_on": ["status_changed"], "texts": []}
```

## orders - catalog items, cart, checkout, order statuses

What: customers browse the items of a catalog resource, add them to a cart, check out and follow
"my orders"; the owner moves each order along its statuses (in Telegram or the web admin). There is
NO payment yet: every order is recorded with payment_status "unpaid" and the owner settles payment
outside the bot.
Parameters: `type: "orders"`, `key`, `title`, `resource` (the catalog items; also give that resource
a `catalog` capability so items can be browsed), `price_field` (an INTEGER field of the resource,
toman), `stock_field` [null] (an INTEGER field of the resource; each order decrements it and a
cancellation restocks it; null = unlimited), `checkout_fields` [[]] (FieldDefs asked at checkout,
at most 5, no datetime: e.g. address, phone), `statuses`, `initial_status`, `owner_actions` (like
request), `cancellable_statuses` [[]] (statuses in which the customer may cancel),
`notify_owner_on` [["placed"]] (any of "placed", "cancelled"), `notify_user_on`
[["status_changed"]], `texts` [[]].
Records (you never write them): orders are records of collection `<key>` (items, total,
payment_status), carts of `<key>.cart`, order lines of `<key>.lines`. Price and stock are integer
fields on the resource's items, so the owner edits them in the Data tab.
Menu: a "main" item (shop and cart) and a "mine" item (my orders, cancel).
When: the owner sells several products or wants carts and stock. Online payment is NOT available.
Default shape (use it unless the owner says otherwise):
```
{"type": "orders", "key": "shop", "title": "فروشگاه", "resource": "product", "price_field": "price",
 "stock_field": "stock", "checkout_fields": [{"key": "address", "label": "نشانی", "type": "long_text", "required": true, "choices": null, "default": null}],
 "statuses": [{"key": "new", "label": "جدید"}, {"key": "confirmed", "label": "تأییدشده"},
              {"key": "delivered", "label": "تحویل‌شده"}, {"key": "cancelled", "label": "لغوشده"}],
 "initial_status": "new",
 "owner_actions": [{"key": "confirm", "label": "تأیید سفارش", "from_statuses": ["new"], "to_status": "confirmed"},
                   {"key": "deliver", "label": "تحویل شد", "from_statuses": ["confirmed"], "to_status": "delivered"},
                   {"key": "cancel", "label": "لغو سفارش", "from_statuses": ["new", "confirmed"], "to_status": "cancelled"}],
 "cancellable_statuses": ["new"], "notify_owner_on": ["placed", "cancelled"], "notify_user_on": ["status_changed"], "texts": []}
```

## Menu

`{"key", "label" (Persian button text), "capability" (capability key), "view": "main" | "mine"}`.
1 to 8 items reaching ENABLED capabilities (items of disabled capabilities do not count). "mine"
is only for booking, request and orders capabilities. Every enabled capability should be reachable
from the menu.

## enabled and audience (booking, request and orders capabilities)

- `enabled` [true]: false hides the capability from users (menu, buttons) but keeps its
  configuration and records. To turn a feature off, set `enabled` to false instead of removing it,
  and set it back to true to turn it on again. Remove only when the owner wants it gone for good.
- `audience` ["everyone"]: who may use it: "everyone", "staff" (staff and managers: internal forms
  such as leave requests) or "managers" (managers only: approvals and internal tools). The bot
  owner always counts as a manager. A staff audience is only useful once the owner has enabled the
  `staff` module and invited staff.
Examples: `{"op": "set", "path": ["capabilities", "leave", "audience"], "value": "staff"}`,
`{"op": "set", "path": ["capabilities", "shop", "enabled"], "value": false}`.

## Modules you cannot configure

The registry at the end lists modules (kind module): inventory, approvals, announcements, staff,
staff_reporting, reporting, spreadsheet_intelligence, scheduled_reports, copilot. They are not
part of the spec. The owner switches them on in the Capability Center (مرکز قابلیت‌ها) of the web
app, which is deterministic. When a requirement needs one, record it as an assumed requirement,
name it in the owner message and tell the owner to enable it there. Never write spec JSON for a
module and never claim it is already running. Payments is listed but not available.

## Text overrides

`texts: [{"key", "value"}]` replaces a default Persian bot text. Keys and their allowed
`{placeholders}` are fixed per capability type (listed at the end of this catalog). Defaults are
good; override only when the owner asks for specific wording.

## Patch ops (apply_spec_patch)

`{"op": "set" | "add" | "remove", "path": [segments], "value": ..., "before": null}`.
Segments name fields; inside a keyed list the next segment is an element's key (never an index).
- set: a scalar, a scalar list (replaced whole), a whole sub-object, or a whole keyed-list element.
- add: path ends at a keyed list; value is the new object with its own new key; optional before.
- remove: a keyed-list element, or a nullable field (becomes null).
Changing a key or a capability's type is refused (remove and add instead). A keyed list cannot be
set whole. The whole op list is atomic and the result must validate.
Examples:
```
{"op": "set", "path": ["capabilities", "book_workshop", "capacity", "value"], "value": 12}
{"op": "set", "path": ["capabilities", "book_workshop", "waitlist"], "value": {"enabled": true, "auto_promote": true}}
{"op": "set", "path": ["capabilities", "book_workshop", "cancellation", "deadline_hours"], "value": 2}
{"op": "add", "path": ["capabilities", "book_workshop", "form_fields"],
 "value": {"key": "phone", "label": "شماره تماس", "type": "phone", "required": true, "choices": null, "default": null}}
{"op": "add", "path": ["menu"], "value": {"key": "my_bookings", "label": "ثبت‌نام‌های من", "capability": "book_workshop", "view": "mine"}}
{"op": "remove", "path": ["menu", "about"]}
```

## Unsupported (record with a reason and the closest alternative)

Online payment or a payment gateway (alternative: `orders`, which stay unpaid, or a request the
owner confirms); external calendars (Google Calendar and the like), accounting, delivery or any
other integration or external API; arbitrary code, scripts or rules beyond the typed parameters;
file or photo uploads by bot users; free-text or AI chat inside the bot (bot users use buttons and
short form answers; the manager Q&A is the owner-side copilot module); automatic recurring
schedules (the owner adds each item); languages other than Persian; platforms other than Telegram.
Supported, so never list them as unsupported: carts and stock (orders), reminders before an item
starts (`reminder_hours_before`), broadcasts, staff roles, reports and Excel analysis (modules).
