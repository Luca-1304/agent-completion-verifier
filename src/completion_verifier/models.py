from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any


class Status(str, Enum):
    VERIFIED_COMPLETE = "VERIFIED_COMPLETE"
    PARTIAL = "PARTIAL"
    UNVERIFIED = "UNVERIFIED"
    FAILED = "FAILED"


@dataclass(frozen=True)
class Event:
    action: str
    success: bool
    evidence: dict[str, Any] = field(default_factory=dict)
    sequence: int = 0

    @classmethod
    def from_dict(cls, raw: dict[str, Any], sequence: int) -> "Event":
        if not isinstance(raw, dict):
            raise ValueError("Each event must be an object.")
        action = str(raw.get("action", "")).strip()
        if not action:
            raise ValueError("Each event requires a non-empty 'action'.")
        if not isinstance(raw.get("success"), bool):
            raise ValueError("Each event requires boolean 'success'.")
        evidence = raw.get("evidence", {})
        if not isinstance(evidence, dict):
            raise ValueError("'evidence' must be an object.")
        return cls(action, raw["success"], evidence, sequence)


@dataclass(frozen=True)
class Requirement:
    action: str
    evidence_fields: tuple[str, ...] = ()

    @classmethod
    def from_dict(cls, raw: dict[str, Any]) -> "Requirement":
        if not isinstance(raw, dict):
            raise ValueError("Each requirement must be an object.")
        action = str(raw.get("action", "")).strip()
        if not action:
            raise ValueError("Each requirement requires a non-empty 'action'.")
        fields = raw.get("evidence_fields", [])
        if not isinstance(fields, list) or not all(
            isinstance(value, str) and value.strip() for value in fields
        ):
            raise ValueError("'evidence_fields' must be a list of non-empty strings.")
        return cls(action, tuple(value.strip() for value in fields))


@dataclass(frozen=True)
class Case:
    case_id: str
    task: str
    completion_claimed: bool
    requirements: tuple[Requirement, ...]
    events: tuple[Event, ...]

    @classmethod
    def from_dict(cls, raw: dict[str, Any]) -> "Case":
        if not isinstance(raw, dict):
            raise ValueError("Each case must be an object.")
        case_id = str(raw.get("case_id", "")).strip()
        task = str(raw.get("task", "")).strip()
        if not case_id or not task:
            raise ValueError("A case requires non-empty 'case_id' and 'task'.")
        if not isinstance(raw.get("completion_claimed"), bool):
            raise ValueError("'completion_claimed' must be boolean.")

        requirements_raw = raw.get("requirements", [])
        events_raw = raw.get("events", [])
        if not isinstance(requirements_raw, list) or not requirements_raw:
            raise ValueError("'requirements' must be a non-empty list.")
        if not isinstance(events_raw, list):
            raise ValueError("'events' must be a list.")

        return cls(
            case_id=case_id,
            task=task,
            completion_claimed=raw["completion_claimed"],
            requirements=tuple(
                Requirement.from_dict(value) for value in requirements_raw
            ),
            events=tuple(
                Event.from_dict(value, sequence)
                for sequence, value in enumerate(events_raw)
            ),
        )


@dataclass(frozen=True)
class Evaluation:
    case_id: str
    status: Status
    proven_actions: tuple[str, ...]
    missing_actions: tuple[str, ...]
    failed_actions: tuple[str, ...]
    reasons: tuple[str, ...]

    def to_dict(self) -> dict[str, Any]:
        return {
            "case_id": self.case_id,
            "status": self.status.value,
            "proven_actions": list(self.proven_actions),
            "missing_actions": list(self.missing_actions),
            "failed_actions": list(self.failed_actions),
            "reasons": list(self.reasons),
        }
