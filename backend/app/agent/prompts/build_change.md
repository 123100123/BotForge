# Task: build (change to a live bot)

The current draft below is a copy of the live bot's spec. Change it so it implements the
requirement change, and nothing else.

Procedure:
1. Call `apply_spec_patch` once with every op the change needs (key-addressed paths, e.g.
   `{"op": "set", "path": ["capabilities", "book_workshop", "capacity", "value"], "value": 12}`).
   `set_spec` is not available: the live bot is changed only through patches.
2. If the result reports `issues` with severity error or `compat_errors`, fix them all in one more
   `apply_spec_patch` call.
3. When there are no errors, call `finish` with a one-sentence summary.

Rules:
- Change only what the delta requires. Do not rename keys, reorder lists, reword texts, or touch
  capabilities the delta does not mention.
- Live records exist for the collections listed in `live_record_counts`. Never change a field's
  type; never add a required field without a default to a resource that has records; prefer
  keeping existing fields and capabilities over removing them.
- Requests about the menu ("rename the menu button", "add a button for X", "remove the Y
  button") are not menu edits: the bot's menus are generated and `menu` stays `[]`. Renaming a
  button means changing the capability `title` or the resource `label` / `label_plural`; adding or
  removing a button means turning the capability on (`enabled: true`) or off (`enabled: false`),
  or adding the capability the owner asks for. If nothing in the spec can express the request,
  change nothing and say so in the `finish` summary.
- Turning a feature on or off is `set` on its capability's `enabled` (true or false), never remove
  and add: that keeps its configuration and records.
- A uniform capacity stays `capacity.mode = "fixed"` with the owner's number.
- You have a small tool budget: do not call `get_spec` or `validate_spec` unless you need them.
