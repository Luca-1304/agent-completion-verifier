from __future__ import annotations

import hashlib
import json
import string
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any, Protocol

from ..models import Case, Event, Requirement


class TraceAdapterError(ValueError):
    """Raised when a source trace cannot be converted without ambiguity."""


def _required_text(value: object, field_name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise TraceAdapterError(f"'{field_name}' must be a non-empty string.")
    return value.strip()


def canonical_json_sha256(raw: object) -> str:
    """Hash the canonical JSON representation of a parsed trace object."""

    try:
        encoded = json.dumps(
            raw,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
            allow_nan=False,
        ).encode("utf-8")
    except (TypeError, ValueError) as exc:
        raise TraceAdapterError(f"Trace is not canonical JSON: {exc}") from exc
    return hashlib.sha256(encoded).hexdigest()


def validate_requirements(
    requirements: Sequence[Requirement],
) -> tuple[Requirement, ...]:
    if not isinstance(requirements, Sequence) or isinstance(
        requirements, (str, bytes, bytearray)
    ):
        raise TraceAdapterError("Requirements must be a sequence of Requirement objects.")
    values = tuple(requirements)
    if not values:
        raise TraceAdapterError("At least one requirement is required.")
    if not all(isinstance(value, Requirement) for value in values):
        raise TraceAdapterError("Requirements must contain only Requirement objects.")
    return values


@dataclass(frozen=True)
class TraceSource:
    adapter: str
    source_type: str
    source_ref: str
    raw_sha256: str

    def __post_init__(self) -> None:
        object.__setattr__(self, "adapter", _required_text(self.adapter, "adapter"))
        object.__setattr__(
            self, "source_type", _required_text(self.source_type, "source_type")
        )
        object.__setattr__(
            self, "source_ref", _required_text(self.source_ref, "source_ref")
        )
        digest = _required_text(self.raw_sha256, "raw_sha256").lower()
        if len(digest) != 64 or any(ch not in string.hexdigits for ch in digest):
            raise TraceAdapterError(
                "Trace source requires a 64-character SHA-256 digest."
            )
        object.__setattr__(self, "raw_sha256", digest)

    def to_dict(self) -> dict[str, str]:
        return {
            "adapter": self.adapter,
            "source_type": self.source_type,
            "source_ref": self.source_ref,
            "raw_sha256": self.raw_sha256,
        }


@dataclass(frozen=True)
class AdaptedEvent:
    action: str
    success: bool
    evidence: dict[str, Any]
    sequence: int
    source_event_id: str | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "action", _required_text(self.action, "action"))
        if not isinstance(self.success, bool):
            raise TraceAdapterError("Adapted event 'success' must be boolean.")
        if not isinstance(self.evidence, dict):
            raise TraceAdapterError("Adapted event 'evidence' must be an object.")
        object.__setattr__(self, "evidence", dict(self.evidence))
        if isinstance(self.sequence, bool) or not isinstance(self.sequence, int):
            raise TraceAdapterError("Adapted event 'sequence' must be an integer.")
        if self.sequence < 0:
            raise TraceAdapterError("Adapted event 'sequence' must be non-negative.")
        if self.source_event_id is not None:
            object.__setattr__(
                self,
                "source_event_id",
                _required_text(self.source_event_id, "source_event_id"),
            )

    def to_event(self) -> Event:
        return Event(self.action, self.success, dict(self.evidence), self.sequence)

    def to_dict(self) -> dict[str, Any]:
        return {
            "action": self.action,
            "success": self.success,
            "evidence": dict(self.evidence),
            "sequence": self.sequence,
            "source_event_id": self.source_event_id,
        }


@dataclass(frozen=True)
class TraceEnvelope:
    trace_id: str
    task: str
    completion_claimed: bool
    requirements: tuple[Requirement, ...]
    events: tuple[AdaptedEvent, ...]
    source: TraceSource

    def __post_init__(self) -> None:
        object.__setattr__(self, "trace_id", _required_text(self.trace_id, "trace_id"))
        object.__setattr__(self, "task", _required_text(self.task, "task"))
        if not isinstance(self.completion_claimed, bool):
            raise TraceAdapterError("'completion_claimed' must be boolean.")
        object.__setattr__(
            self, "requirements", validate_requirements(self.requirements)
        )
        if not isinstance(self.events, tuple) or not all(
            isinstance(value, AdaptedEvent) for value in self.events
        ):
            raise TraceAdapterError("Events must be a tuple of AdaptedEvent objects.")
        sequences = [event.sequence for event in self.events]
        if sequences != list(range(len(self.events))):
            raise TraceAdapterError(
                "Adapted event sequences must be contiguous and ordered from zero."
            )
        source_ids = [
            event.source_event_id
            for event in self.events
            if event.source_event_id is not None
        ]
        if len(source_ids) != len(set(source_ids)):
            raise TraceAdapterError("Adapted event source IDs must be unique.")
        if not isinstance(self.source, TraceSource):
            raise TraceAdapterError("'source' must be a TraceSource object.")

    def to_case(self) -> Case:
        return Case(
            case_id=self.trace_id,
            task=self.task,
            completion_claimed=self.completion_claimed,
            requirements=self.requirements,
            events=tuple(event.to_event() for event in self.events),
        )

    def case_dict(self) -> dict[str, Any]:
        return {
            "case_id": self.trace_id,
            "task": self.task,
            "completion_claimed": self.completion_claimed,
            "requirements": [
                {
                    "action": requirement.action,
                    "evidence_fields": list(requirement.evidence_fields),
                }
                for requirement in self.requirements
            ],
            "events": [
                {
                    "action": event.action,
                    "success": event.success,
                    "evidence": dict(event.evidence),
                }
                for event in self.events
            ],
        }

    def to_dict(self) -> dict[str, Any]:
        return {
            "trace_id": self.trace_id,
            "task": self.task,
            "completion_claimed": self.completion_claimed,
            "requirements": [
                {
                    "action": requirement.action,
                    "evidence_fields": list(requirement.evidence_fields),
                }
                for requirement in self.requirements
            ],
            "events": [event.to_dict() for event in self.events],
            "source": self.source.to_dict(),
        }


class TraceAdapter(Protocol):
    name: str
    version: str

    def adapt(
        self,
        raw: object,
        *,
        requirements: Sequence[Requirement],
        source_ref: str,
    ) -> TraceEnvelope:
        ...
