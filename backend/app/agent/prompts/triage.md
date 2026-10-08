# Task: triage

The owner of a bot that is already live sent the message below. Classify it and return JSON:
`{"intent": "change" | "question" | "data_request" | "unsupported", "reply": "<Persian text>"}`.

- `change`: the owner wants the bot to behave differently: a rule, a number, a limit, a
  deadline, a notification, a text, a button name or entry, a form field, a new or removed feature that the
  catalog supports. Example: «ظرفیت هر کارگاه را ۱۲ نفر کن.» `reply`: one short sentence saying
  you will prepare the change.
- `question`: the owner asks how the bot works today, without asking to change it. `reply`: a
  short, plain Persian answer from the requirements and the bot outline below (two sentences at
  most). If the answer is not there, say so briefly.
- `data_request`: the owner wants to add, edit or remove business items (for example a new
  workshop on Friday, a new price, a deleted product). Items are managed by the owner, never by
  you. `reply`: one sentence telling the owner to do it in the «داده‌ها» (Data) tab.
- `unsupported`: a change the catalog cannot build (online payment, chat with customers, AI
  answers, integrations with other services, anything outside the catalog's types: info, catalog, booking with events, request, orders).
  `reply`: a plain Persian explanation and the closest supported alternative.

Turning an existing feature on or off, or restricting it to staff or managers, is a `change`. Asking
for reports, Excel analysis, daily staff reports, scheduled reports, announcements or the copilot is
not a spec change: choose `question` and tell the owner to enable these modules in the Capability
Center (مرکز قابلیت‌ها).

When the message mixes a change with something else, choose `change`. When unsure between
`change` and `question`, choose `change` only if the owner asks for something to be different.
