# Task: repair

Some scenarios fail against the current draft. Find out why and fix it.

Procedure:
1. Read the failure list below. Call `get_failure` for a failing scenario when the message alone
   does not tell you the cause.
2. Decide, for each failure, which side is wrong:
   - The spec does not do what a requirement says (the usual case): fix the spec with one
     `apply_spec_patch` call containing all needed ops.
   - An acceptance scenario written in this run misstates the requirement (wrong expectation, a
     seed missing a required field, a step that does not match the requirement's wording): correct
     it with `fix_scenario` and a one-sentence Persian reason. Only scenarios marked fixable can be
     fixed. Never change a correct expectation to match a wrong spec.
   - A derived scenario fails: derived scenarios come from the spec itself; fix the spec.
3. Call `run_tests` to confirm, then call `finish`. If a failure cannot be fixed with the catalog,
   call `finish` anyway and say why in the summary.
