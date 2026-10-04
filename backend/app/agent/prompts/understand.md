# Task: understand

Turn the conversation with the owner into a requirements model. Return JSON:
`{"requirements": Requirements, "message": "<short Persian message to the owner>"}`.

Requirements:
- `business_summary`: one Persian sentence describing the business and what the bot is for.
- `items`: requirements, each `{"id", "kind", "statement", "status"}`.
  - `id`: "R1", "R2", ... If previous requirements are given, keep every id whose meaning is
    unchanged, reuse no id for a different meaning, and number new items after the highest id.
  - `kind`: capability (something users can do), rule (a constraint or number), data (what an
    item records), text (wording), notification (who is told what).
  - `statement`: one Persian, owner-readable sentence. State numbers exactly as the owner said.
  - `status`: confirmed when the owner said it; assumed when you chose a sensible default.
  Cover each distinct thing the owner asked for with its own item: each capability, each number,
  each rule (waitlist, automatic promotion, cancellation, deadlines, limits), each notification.
  Add assumed items for the defaults you will build (for example "one active booking per person
  per item", "the owner is told about each booking and cancellation").
- `unsupported`: things the owner asked for that the catalog cannot build, each with a Persian
  `statement`, a Persian `reason`, and the closest supported `alternative` (or null). Do not also
  list them as items.
- `open_questions`: questions, each `{"id": "Q1", "text" (Persian), "why" (short English), "severity",
  "options" (2-4 short Persian answers, or null)}`.
  - blocking: the answer changes which capability or which rule mode is built and no sensible
    default exists. Ask at most three.
  - important: a sensible default exists. Do NOT put it here: record the default as an assumed
    item instead.
  Ask nothing that the owner already answered in the conversation. Prefer zero questions.

The message: one to three short, plain Persian sentences. Say what you understood in one line. If
something is unsupported, say so plainly and name the alternative. If you ask questions, say you
need a short answer before building (the questions themselves are shown separately).

If the request contains no buildable workflow at all, return no items and explain in the message
what kinds of bots you can build (show items and book them, take requests the owner approves,
show information pages, show a list of services or products).
