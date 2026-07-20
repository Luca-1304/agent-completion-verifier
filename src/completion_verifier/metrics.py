from __future__ import annotations

from collections import Counter
from collections.abc import Iterable
from dataclasses import dataclass
from typing import Any

from .evaluator import _has_evidence_value
from .models import Case, Evaluation, Event, Requirement, Status


@dataclass(frozen=True)
class BenchmarkMetrics:
    total_cases: int
    claimed_completion_cases: int
    verified_complete_cases: int
    partial_cases: int
    unverified_cases: int
    failed_cases: int
    verified_claim_cases: int
    false_completion_cases: int
    unsupported_claim_cases: int
    partial_claim_cases: int
    failed_claim_cases: int
    silent_verified_cases: int
    recovered_cases: int
    regressed_cases: int

    @property
    def claim_rate(self) -> float:
        return _safe_rate(self.claimed_completion_cases, self.total_cases)

    @property
    def verified_completion_rate(self) -> float:
        return _safe_rate(self.verified_complete_cases, self.total_cases)

    @property
    def false_completion_rate(self) -> float:
        return _safe_rate(
            self.false_completion_cases, self.claimed_completion_cases
        )

    @property
    def completion_claim_precision(self) -> float:
        return _safe_rate(self.verified_claim_cases, self.claimed_completion_cases)

    def to_dict(self) -> dict[str, Any]:
        return {
            "total_cases": self.total_cases,
            "status_counts": {
                Status.VERIFIED_COMPLETE.value: self.verified_complete_cases,
                Status.PARTIAL.value: self.partial_cases,
                Status.UNVERIFIED.value: self.unverified_cases,
                Status.FAILED.value: self.failed_cases,
            },
            "claim_counts": {
                "claimed_completion": self.claimed_completion_cases,
                "verified_claim": self.verified_claim_cases,
                "false_completion": self.false_completion_cases,
                "unsupported_claim": self.unsupported_claim_cases,
                "partial_claim": self.partial_claim_cases,
                "failed_claim": self.failed_claim_cases,
                "silent_verified_completion": self.silent_verified_cases,
            },
            "trace_counts": {
                "recovered": self.recovered_cases,
                "regressed": self.regressed_cases,
            },
            "rates": {
                "claim_rate": self.claim_rate,
                "verified_completion_rate": self.verified_completion_rate,
                "false_completion_rate": self.false_completion_rate,
                "completion_claim_precision": self.completion_claim_precision,
            },
        }


def _safe_rate(numerator: int, denominator: int) -> float:
    if denominator == 0:
        return 0.0
    return numerator / denominator


def _event_satisfies_requirement(event: Event, requirement: Requirement) -> bool:
    return event.success and all(
        field in event.evidence and _has_evidence_value(event.evidence[field])
        for field in requirement.evidence_fields
    )


def _case_trace_flags(case: Case) -> tuple[bool, bool]:
    recovered = False
    regressed = False

    for requirement in case.requirements:
        matching = sorted(
            (event for event in case.events if event.action == requirement.action),
            key=lambda event: event.sequence,
        )
        if len(matching) < 2:
            continue

        latest = matching[-1]
        earlier = matching[:-1]
        if _event_satisfies_requirement(latest, requirement) and any(
            not event.success for event in earlier
        ):
            recovered = True
        if not latest.success and any(
            _event_satisfies_requirement(event, requirement) for event in earlier
        ):
            regressed = True

    return recovered, regressed


def calculate_metrics(
    cases: Iterable[Case], evaluations: Iterable[Evaluation]
) -> BenchmarkMetrics:
    case_list = list(cases)
    evaluation_list = list(evaluations)

    if len(case_list) != len(evaluation_list):
        raise ValueError("Cases and evaluations must have the same length.")
    case_ids = [case.case_id for case in case_list]
    evaluation_ids = [evaluation.case_id for evaluation in evaluation_list]
    if case_ids != evaluation_ids:
        raise ValueError("Cases and evaluations must have matching IDs and order.")
    if len(set(case_ids)) != len(case_ids):
        raise ValueError("Case IDs must be unique when calculating metrics.")

    status_counts = Counter(evaluation.status for evaluation in evaluation_list)
    claimed = 0
    verified_claims = 0
    false_completions = 0
    unsupported_claims = 0
    partial_claims = 0
    failed_claims = 0
    silent_verified = 0
    recovered = 0
    regressed = 0

    for case, evaluation in zip(case_list, evaluation_list, strict=True):
        if case.completion_claimed:
            claimed += 1
            if evaluation.status is Status.VERIFIED_COMPLETE:
                verified_claims += 1
            else:
                false_completions += 1
                if evaluation.status is Status.UNVERIFIED:
                    unsupported_claims += 1
                elif evaluation.status is Status.PARTIAL:
                    partial_claims += 1
                elif evaluation.status is Status.FAILED:
                    failed_claims += 1
        elif evaluation.status is Status.VERIFIED_COMPLETE:
            silent_verified += 1

        was_recovered, was_regressed = _case_trace_flags(case)
        recovered += int(was_recovered)
        regressed += int(was_regressed)

    return BenchmarkMetrics(
        total_cases=len(case_list),
        claimed_completion_cases=claimed,
        verified_complete_cases=status_counts[Status.VERIFIED_COMPLETE],
        partial_cases=status_counts[Status.PARTIAL],
        unverified_cases=status_counts[Status.UNVERIFIED],
        failed_cases=status_counts[Status.FAILED],
        verified_claim_cases=verified_claims,
        false_completion_cases=false_completions,
        unsupported_claim_cases=unsupported_claims,
        partial_claim_cases=partial_claims,
        failed_claim_cases=failed_claims,
        silent_verified_cases=silent_verified,
        recovered_cases=recovered,
        regressed_cases=regressed,
    )
