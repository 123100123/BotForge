# Task: repair (change to a live bot)

Some scenarios fail against the changed draft. Find out why and fix it. Each failure is marked
with its `kind`:

- `derived`: generated from the spec itself. The spec is wrong: fix it with `apply_spec_patch`.
- `new`: an acceptance scenario written for this change. If the spec does not do what the changed
  requirement says, fix the spec. If the scenario misstates the requirement, correct it with
  `fix_scenario` and a one-sentence Persian reason.
- `carried`: an acceptance scenario of the live bot, carried forward unchanged. You cannot edit it.
  - If `supersedable` is true, it checks a requirement this change modifies or removes, so its old
    expectation may no longer hold (for example it checks the old capacity number). Retire it with
    `supersede_scenario` and a one-sentence Persian reason naming the change; the new scenarios
    cover the new behavior.
  - If `supersedable` is false, its requirement did not change: the failure is a regression. Fix
    the spec so it passes again. Never try to retire it.

Procedure: read the failures; call `get_failure` only when the message alone does not tell you the
cause; make the fixes (one `apply_spec_patch` call with all ops); call `run_tests` to confirm; then
call `finish`. If a failure cannot be fixed with the catalog, call `finish` and say why.
