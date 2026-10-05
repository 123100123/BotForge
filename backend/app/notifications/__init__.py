"""Notifications (roadmap: Business OS Expansion -> Notifications & scheduler).

``outbox``: the ``outbound_messages`` queue (enqueue with dedupe, claim, record results).
``ticker``: the in-process task that runs the generators and delivers due rows, throttled.
``generators``: auto-discovered producers of outbox rows (event reminders, announcements).
``targets``: announcement audiences -> chat ids.
"""
