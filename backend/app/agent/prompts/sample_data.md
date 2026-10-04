# Task: sample_data

Write realistic Persian sample items for the bot's sandbox so the owner can try the bot in the
simulator right away. Return JSON: `{"records": [SeedRecord, ...]}` with two or three records per
resource below.

SeedRecord: `{"ref": "s1", "collection": "<resource key>", "values": [{"key": "<field key>",
"value": "<string>"}]}`.
- Fill every required field; use only the listed field keys.
- Datetime fields must be relative to now and in the future: "+48h", "+3d", "+7d".
- integer and decimal: plain ASCII digits (prices in toman, e.g. "1500000"). boolean: "true"/"false".
  choice: exactly one of the listed choices. phone: "09121234567".
- Titles and descriptions are short, plausible Persian for this business.
