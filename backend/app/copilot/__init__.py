"""Manager Copilot: Persian Q&A for the bot owner over bounded, read-only tools (roadmap: Manager Copilot).

``tools`` wraps the Reporting Engine, analysis runs and the team list; ``service.ask`` runs the fast-tier
tool loop and enforces the module toggle and the daily cap; ``prompts`` holds the system prompt. The
numbers always come from the tools, never from the model.
"""
