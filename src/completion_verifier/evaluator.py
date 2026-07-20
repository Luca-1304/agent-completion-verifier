from __future__ import annotations

from collections.abc import Iterable
from typing import Any

from .models import Case, Evaluation, Event, Requirement, Status


def _latest_event_for_action(case: Case, action: str) -> Event | None:
    matching = (event for event in case.events if event.action == action)
    return max(matching, key=lambda event: event.sequence, default=None)


def _has_evidence_value(value: Any) -> bool:
    if value is None:
        return False
    if isinstance(value, str):
        return bool(value.strip())
    if isinstance(value, (list, tuple, dict, set)):
        return bool(value)
    return True


def _requirement_is_proven(
    case: Case, requirement: Requirement
) -> tuple[bool, str]:
    event = _latest_event_for_action(case, requirement.action)
    if event is None:
        return False, f"No event recorded for required action '{requirement.action}'."
    if not event.success:
        return False, f"Latest event for '{requirement.action}' reports failure."

    missing_fields = [
        field
        for field in requirement.evidence_fields
        if field not in event.evidence or not _has_evidence_value(event.evidence[field])
    ]
    if missing_fields:
        return False, (
            f"Action '{requirement.action}' succeeded but lacks required evidence: "
            + ", ".join(missing_fields)
            + "."
        )
    return True, f"Action '{requirement.action}' has successful, sufficient evidence."


def evaluate_case(case: Case) -> Evaluation:
    proven: list[str] = []
    missing: list[str] = []
    failed: list[str] = []
    reasons: list[str] = []

    for requirement in case.requirements:
        event = _latest_event_for_action(case, requirement.action)
        is_proven, reason = _requirement_is_proven(case, requirement)
        reasons.append(reason)
        if is_proven:
            proven.append(requirement.action)
        elif event is not None and not event.success:
            failed.append(requirement.action)
        else:
            missing.append(requirement.action)

    if len(proven) == len(case.requirements):
        status = Status.VERIFIED_COMPLETE
    elif failed:
        status = Status.FAILED
    elif proven:
        status = Status.PARTIAL
    else:
        status = Status.UNVERIFIED

    if case.completion_claimed and status is not Status.VERIFIED_COMPLETE:
        reasons.append("The agent claimed completion without proving every requirement.")
    elif not case.completion_claimed and status is Status.VERIFIED_COMPLETE:
        reasons.append(
            "The task is evidenced as complete even though no completion claim was made."
        )

    return Evaluation(
        case_id=case.case_id,
        status=status,
        proven_actions=tuple(proven),
        missing_actions=tuple(missing),
        failed_actions=tuple(failed),
        reasons=tuple(reasons),
    )


def evaluate_cases(cases: Iterable[Case]) -> list[Evaluation]:
    return [evaluate_case(case) for case in cases]
