from __future__ import annotations

from collections.abc import Sequence
from typing import Any

from ..models import Requirement
from .base import (
    AdaptedEvent,
    TraceAdapterError,
    TraceEnvelope,
    TraceSource,
    _required_text,
    canonical_json_sha256,
    validate_requirements,
)


class GenericJsonTraceAdapter:
    """Convert the documented generic JSON trace shape into a TraceEnvelope."""

    name = "generic-json"
    version = "1"

    def adapt(
        self,
        raw: object,
        *,
        requirements: Sequence[Requirement],
        source_ref: str,
    ) -> TraceEnvelope:
        if not isinstance(raw, dict):
            raise TraceAdapterError("Generic trace must be a JSON object.")

        trace_id = _required_text(raw.get("trace_id"), "trace_id")
        task = _required_text(raw.get("task"), "task")
        claimed = raw.get("completion_claimed")
        if not isinstance(claimed, bool):
            raise TraceAdapterError("'completion_claimed' must be boolean.")

        events_raw = raw.get("events")
        if not isinstance(events_raw, list):
            raise TraceAdapterError("'events' must be a list.")

        seen_ids: set[str] = set()
        events: list[AdaptedEvent] = []
        for sequence, value in enumerate(events_raw):
            events.append(self._adapt_event(value, sequence, seen_ids))

        source = TraceSource(
            adapter=f"{self.name}@{self.version}",
            source_type=self.name,
            source_ref=source_ref,
            raw_sha256=canonical_json_sha256(raw),
        )
        return TraceEnvelope(
            trace_id=trace_id,
            task=task,
            completion_claimed=claimed,
            requirements=validate_requirements(requirements),
            events=tuple(events),
            source=source,
        )

    @staticmethod
    def _adapt_event(
        raw: object,
        sequence: int,
        seen_ids: set[str],
    ) -> AdaptedEvent:
        if not isinstance(raw, dict):
            raise TraceAdapterError(f"events[{sequence}] must be an object.")

        action = _required_text(raw.get("action"), f"events[{sequence}].action")
        success = raw.get("success")
        if not isinstance(success, bool):
            raise TraceAdapterError(f"events[{sequence}].success must be boolean.")
        evidence = raw.get("evidence", {})
        if not isinstance(evidence, dict):
            raise TraceAdapterError(f"events[{sequence}].evidence must be an object.")

        source_event_id_raw: Any = raw.get("source_event_id")
        source_event_id: str | None = None
        if source_event_id_raw is not None:
            source_event_id = _required_text(
                source_event_id_raw, f"events[{sequence}].source_event_id"
            )
            if source_event_id in seen_ids:
                raise TraceAdapterError(
                    f"events[{sequence}] has duplicate source_event_id "
                    f"'{source_event_id}'."
                )
            seen_ids.add(source_event_id)

        return AdaptedEvent(
            action=action,
            success=success,
            evidence=dict(evidence),
            sequence=sequence,
            source_event_id=source_event_id,
        )
