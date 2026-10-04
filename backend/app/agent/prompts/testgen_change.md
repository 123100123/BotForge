# Task: testgen (acceptance scenarios for a change to a live bot)

The bot is live and the owner changed some requirements. The acceptance scenarios of the live bot
are carried forward unchanged and run again; you write NEW scenarios only for the requirements
listed in `changed_requirements` (added or changed). Write 1 to 4 scenarios. Each one must list at
least one of those requirement ids in `requirement_ids`. Do not re-test unchanged requirements.

For a new or changed deadline or cutoff, check both sides of it with `advance_time`: for example,
seed an item starting at "+3h", book, `advance_time` 2 hours (one hour before the start), then
expect the action to be rejected with the matching reason; and a second case where it is still
allowed. For a changed configured number (such as the capacity), write the one scenario that
reaches exactly that number with `capacity_override` null and actors u1, u2, ... plus one more.

The scenario format and the step table follow.
