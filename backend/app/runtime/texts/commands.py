"""Central Persian copy for the slash commands ``/menu``, ``/panel`` and ``/help`` (``runtime.py``).

Fixed product copy, not bot texts (not overridable; no capability type is called ``commands``, so
``TEXTS`` stays empty as in ``texts/nav.py``).
"""

TEXTS: dict[str, str] = {}  # not a capability type module (see the docstring)

HELP_HEADING = "❓ راهنمای {business}"
HELP_ENTRIES = "از اینجا می‌توانید:"
HELP_ENTRIES_MANAGER = "از پنل مدیریت می‌توانید:"
HELP_EMPTY = "فعلاً بخشی برای شما فعال نیست."
HELP_COMMANDS = "دستورها:"
HELP_START = "/start ← شروع از ابتدا"
HELP_MENU = "/menu ← منوی اصلی"
HELP_PANEL = "/panel ← پنل مدیریت"
HELP_HELP = "/help ← همین راهنما"
