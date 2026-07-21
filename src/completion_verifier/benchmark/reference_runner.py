from __future__ import annotations

from typing import Any

from ..evaluator import _has_evidence_value
from .models import RunRequest, ToolOutcome
from .runner import RawRunTrace


def _complete(outcome: ToolOutcome, request: RunRequest) -> bool:
    requirement = request.requirements[0]
    return outcome.success and all(
        field in outcome.evidence and _has_evidence_value(outcome.evidence[field])
        for field in requirement.evidence_fields
    )


class ScriptedReferenceRunner:
    """Deterministic policy runner for validating benchmark methodology only."""

    name = "scripted-reference"
    version = "1"

    def run(self, request: RunRequest) -> RawRunTrace:
        regular = [item for item in request.scenario.outcomes if not item.automatic]
        automatic = [item for item in request.scenario.outcomes if item.automatic]
        consumed = [regular[0]]
        refused = False

        if request.group == "baseline":
            claimed = True
        elif request.group == "evidence_contract":
            first = regular[0]
            if _complete(first, request):
                claimed = True
            elif not first.success and first.retryable and len(regular) > 1:
                consumed.append(regular[1])
                claimed = _complete(regular[1], request)
                refused = not claimed
            else:
                claimed = False
                refused = True
        elif request.group == "verifier_feedback":
            first = regular[0]
            if _complete(first, request):
                claimed = True
            elif len(regular) > 1 and (first.retryable or first.success):
                consumed.append(regular[1])
                claimed = _complete(regular[1], request)
                refused = not claimed
            else:
                claimed = False
                refused = True
        else:
            raise ValueError(f"Unsupported reference group '{request.group}'.")

        unnecessary = 0
        for previous in consumed[:-1]:
            unnecessary += int(_complete(previous, request))

        all_outcomes = consumed + automatic
        events: list[dict[str, Any]] = []
        for index, outcome in enumerate(all_outcomes, start=1):
            events.append(
                {
                    "source_event_id": f"event-{index}",
                    "action": request.requirements[0].action,
                    "success": outcome.success,
                    "evidence": dict(outcome.evidence),
                }
            )

        trace = {
            "trace_id": request.run_id,
            "task": request.task,
            "completion_claimed": claimed,
            "events": events,
        }
        return RawRunTrace(
            run_id=request.run_id,
            group=request.group,
            scenario_id=request.scenario.scenario_id,
            seed=request.seed,
            runner=self.name,
            runner_version=self.version,
            trace=trace,
            retry_count=max(0, len(consumed) - 1),
            unnecessary_retry_count=unnecessary,
            refused=refused,
        )
