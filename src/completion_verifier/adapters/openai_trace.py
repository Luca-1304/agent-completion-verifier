from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
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


@dataclass(frozen=True)
class _ToolCall:
    call_id: str
    name: str
    arguments: dict[str, Any]
    order: int


@dataclass(frozen=True)
class _ToolResult:
    call_id: str
    success: bool
    evidence: dict[str, Any]


class OpenAIToolTraceAdapter:
    """Adapt a strict, dependency-free OpenAI-style tool call/result trace."""

    name = "openai-tool-trace"
    version = "1"

    def adapt(
        self,
        raw: object,
        *,
        requirements: Sequence[Requirement],
        source_ref: str,
    ) -> TraceEnvelope:
        if not isinstance(raw, dict):
            raise TraceAdapterError("OpenAI-style trace must be a JSON object.")

        trace_id = _required_text(raw.get("trace_id"), "trace_id")
        task = _required_text(raw.get("task"), "task")
        claimed = raw.get("completion_claimed")
        if not isinstance(claimed, bool):
            raise TraceAdapterError("'completion_claimed' must be boolean.")
        records = raw.get("records")
        if not isinstance(records, list):
            raise TraceAdapterError("'records' must be a list.")

        calls: dict[str, _ToolCall] = {}
        results: dict[str, _ToolResult] = {}
        call_order = 0

        for index, record in enumerate(records):
            if not isinstance(record, dict):
                raise TraceAdapterError(f"records[{index}] must be an object.")
            record_type = _required_text(record.get("type"), f"records[{index}].type")
            if record_type == "tool_call":
                call = self._parse_call(record, index, call_order)
                if call.call_id in calls:
                    raise TraceAdapterError(
                        f"records[{index}] has duplicate tool_call id '{call.call_id}'."
                    )
                calls[call.call_id] = call
                call_order += 1
            elif record_type == "tool_result":
                result = self._parse_result(record, index)
                if result.call_id in results:
                    raise TraceAdapterError(
                        f"records[{index}] has duplicate tool_result id "
                        f"'{result.call_id}'."
                    )
                results[result.call_id] = result
            else:
                raise TraceAdapterError(
                    f"records[{index}] has unsupported record type '{record_type}'."
                )

        unmatched_calls = sorted(set(calls) - set(results))
        if unmatched_calls:
            raise TraceAdapterError(
                "Tool call has no result: " + ", ".join(unmatched_calls) + "."
            )
        unmatched_results = sorted(set(results) - set(calls))
        if unmatched_results:
            raise TraceAdapterError(
                "Tool result has no call: " + ", ".join(unmatched_results) + "."
            )

        ordered_calls = sorted(calls.values(), key=lambda value: value.order)
        events = tuple(
            AdaptedEvent(
                action=call.name,
                success=results[call.call_id].success,
                evidence=dict(results[call.call_id].evidence),
                sequence=sequence,
                source_event_id=call.call_id,
            )
            for sequence, call in enumerate(ordered_calls)
        )

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
            events=events,
            source=source,
        )

    @staticmethod
    def _parse_call(raw: dict[str, Any], index: int, order: int) -> _ToolCall:
        call_id = _required_text(
            raw.get("tool_call_id"), f"records[{index}].tool_call_id"
        )
        name = _required_text(raw.get("name"), f"records[{index}].name")
        arguments = raw.get("arguments", {})
        if not isinstance(arguments, dict):
            raise TraceAdapterError(f"records[{index}].arguments must be an object.")
        return _ToolCall(call_id, name, dict(arguments), order)

    @staticmethod
    def _parse_result(raw: dict[str, Any], index: int) -> _ToolResult:
        call_id = _required_text(
            raw.get("tool_call_id"), f"records[{index}].tool_call_id"
        )
        success = raw.get("success")
        if not isinstance(success, bool):
            raise TraceAdapterError(f"records[{index}].success must be boolean.")
        evidence = raw.get("evidence", {})
        if not isinstance(evidence, dict):
            raise TraceAdapterError(f"records[{index}].evidence must be an object.")
        return _ToolResult(call_id, success, dict(evidence))
