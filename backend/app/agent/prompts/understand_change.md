# Task: understand (change to a live bot)

The bot is live. The owner asks for a change. Work out how the requirements change and return JSON:
`{"delta": RequirementsDelta, "message": "<short Persian message to the owner>"}`.

RequirementsDelta: `{"added": [Requirement], "changed": [Requirement], "removed": ["R<n>"],
"unsupported": [Unsupported], "open_questions": [Question]}`, always relative to the BASE
requirements below (the live bot), even when a previous delta or a current draft is shown.

- `changed`: a base requirement whose meaning changes. Keep its `id` and `kind`, write the new
  Persian `statement` (state numbers exactly as the owner said), `status` "confirmed".
  Example: base R2 «ظرفیت هر کارگاه ۱۰ نفر است.» + owner «ظرفیت را ۱۲ نفر کن» -> changed
  `{"id": "R2", "kind": "rule", "statement": "ظرفیت هر کارگاه ۱۲ نفر است.", "status": "confirmed"}`.
- `added`: a new requirement with no base counterpart (for example a cancellation deadline when
  the base says nothing about deadlines). Use any id; ids are renumbered after the highest base id.
- `removed`: ids of base requirements the owner no longer wants.
- Touch nothing the owner did not ask about. A requirement that only gets more specific (a
  deadline added to "customers can cancel") is an addition, unless the base statement itself
  contradicts the new rule, in which case it is a change.
- `unsupported`, `open_questions`: as in the creation task. Ask a blocking question only when the
  answer changes what gets built and no sensible default exists; record important open points as
  assumed `added` items instead. Prefer zero questions.

If a previous delta is given, the owner has replied or asked for more: return the complete delta
against the base, including what still applies from the previous one.

The message: one or two short, plain Persian sentences saying what will change.
