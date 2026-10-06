# Task: build

Write the BotSpec that implements every requirement below, using only the catalog.

Procedure:
1. Call `set_spec` once with the complete spec (or, if a current draft is given and only part of
   it must change, call `apply_spec_patch` with all needed ops in one call).
2. If the result has errors, fix all of them in one `apply_spec_patch` call (or call `set_spec`
   again with the corrected full spec). Warnings are allowed but read them.
3. When validation reports no errors, call `finish` with a one-sentence summary.

Rules:
- Map each requirement to a parameter or capability. Numbers stated by the owner go into the spec
  exactly (a uniform capacity means `capacity.mode = "fixed"` with that value).
- Use `null`/defaults for parameters no requirement mentions.
- Bot texts, labels, titles and the welcome text are Persian and short. The bot name comes from the
  business (Persian).
- Prefer composing existing types and presets (orders, booking preset events, request templates for
  forms, support and feedback) over custom behaviour. Use `audience` for internal features and
  `enabled: false` only to switch something off. Modules (reports, copilot, staff, ...) are never
  in the spec.
- Keep the menu at 8 items or fewer, counting only items of enabled capabilities.
- Give each booking, request or orders capability a "main" menu item, and a "mine" menu item when users
  must see or cancel what they booked or requested. Add an info capability only if the owner gave
  information to show or the bot would otherwise have a single button.
- Resource fields: what the owner must enter for each item, with Persian labels; a required text
  title; a datetime start field when items happen at a time; capacity field only for per_item mode;
  an integer price (and an integer stock when orders track stock) for orders; a `choice` category
  field for the events preset.
- You have a small tool budget. Do not call `get_spec` or `validate_spec` unless you need them:
  `set_spec` and `apply_spec_patch` already return the validation issues.
