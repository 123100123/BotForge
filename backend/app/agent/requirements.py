"""Requirements model between the owner's conversation and the spec (frozen contract, WP0).

Requirement ids ("R1", "R2", ...) are stable across revisions and join requirements, scenarios
(``Scenario.requirement_ids``) and the modify-time supersede guard.
"""

from typing import Literal

from app.botspec.models import StrictModel


class Requirement(StrictModel):
    id: str  # "R1", "R2", ... stable across revisions
    kind: Literal["capability", "rule", "data", "text", "notification"]
    statement: str  # Persian, owner-readable, one sentence
    status: Literal["confirmed", "assumed"]


class Unsupported(StrictModel):
    statement: str
    reason: str
    alternative: str | None


class Question(StrictModel):
    id: str
    text: str  # Persian
    why: str
    severity: Literal["blocking", "important"]
    options: list[str] | None = None


class Requirements(StrictModel):
    business_summary: str
    items: list[Requirement]
    unsupported: list[Unsupported]
    open_questions: list[Question]


class RequirementsDelta(StrictModel):  # MODIFY only
    added: list[Requirement]
    changed: list[Requirement]  # same id, new statement
    removed: list[str]  # ids
    unsupported: list[Unsupported]
    open_questions: list[Question]
