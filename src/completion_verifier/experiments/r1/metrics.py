from __future__ import annotations

from collections import Counter
from typing import Any

from ...remote.models import RemoteOutcome
from .models import R1RunRecord


def _latency_summary(runs: tuple[R1RunRecord, ...]) -> dict[str, float | int | None]:
    values = [
        float(value)
        for run in runs
        for value in run.verification_latency_ms
        if value is not None
    ]
    if not values:
        return {"count": 0, "mean": None, "min": None, "max": None}
    return {
        "count": len(values),
        "mean": sum(values) / len(values),
        "min": min(values),
        "max": max(values),
    }


def calculate_r1_metrics(runs: tuple[R1RunRecord, ...]) -> dict[str, Any]:
    if not isinstance(runs, tuple) or not runs or not all(
        isinstance(run, R1RunRecord) for run in runs
    ):
        raise ValueError("R1 metrics require a non-empty tuple of R1RunRecord objects.")

    observed_runs = tuple(run for run in runs if run.observations)
    latest_pairs = tuple((run, run.observations[-1].outcome) for run in observed_runs)
    latest = [outcome for _, outcome in latest_pairs]
    counts = Counter(outcome.value for outcome in latest)
    total = len(runs)
    observed_total = len(observed_runs)
    aborted_count = sum(run.abort_reason is not None for run in runs)

    divergence_count = sum(
        run.scenario_id == "S7"
        and len(run.observations) > 1
        and run.observations[0].outcome is RemoteOutcome.MATCH
        and any(
            observation.outcome is not RemoteOutcome.MATCH
            for observation in run.observations[1:]
        )
        for run in observed_runs
    )

    controller_total = sum(len(run.controller_receipts) for run in runs)
    cleanup_failure_count = sum(
        receipt.action == "close_pull_request" and not receipt.success
        for run in runs
        for receipt in run.controller_receipts
    )
    cleanup_unresolved_count = sum(
        any(
            receipt.action == "create_pull_request"
            and receipt.error_code == "accepted_unaddressable"
            for receipt in run.controller_receipts
        )
        and not any(
            receipt.action == "close_pull_request" and receipt.success
            for receipt in run.controller_receipts
        )
        for run in runs
    )
    retry_total = sum(run.source_claim.retry_count for run in runs)
    retry_runs = sum(run.source_claim.retry_count > 0 for run in runs)
    refusals = sum(run.source_claim.refusal for run in runs)

    agreement = 0
    false_positive = 0
    false_negative = 0
    indeterminate = 0
    for run, outcome in latest_pairs:
        claimed = run.source_claim.completion_claimed
        if outcome is RemoteOutcome.INDETERMINATE:
            indeterminate += 1
        elif claimed and outcome is RemoteOutcome.MATCH:
            agreement += 1
        elif not claimed and outcome is RemoteOutcome.MISMATCH:
            agreement += 1
        elif claimed and outcome is RemoteOutcome.MISMATCH:
            false_positive += 1
        elif not claimed and outcome is RemoteOutcome.MATCH:
            false_negative += 1

    def rate(outcome: RemoteOutcome) -> float | None:
        if observed_total == 0:
            return None
        return counts[outcome.value] / observed_total

    return {
        "schema_version": "1",
        "total_runs": total,
        "observed_run_count": observed_total,
        "harness_aborted_count": aborted_count,
        "latest_outcome_counts": {
            outcome.value: counts[outcome.value]
            for outcome in (
                RemoteOutcome.MATCH,
                RemoteOutcome.MISMATCH,
                RemoteOutcome.INDETERMINATE,
            )
        },
        "remote_match_rate": rate(RemoteOutcome.MATCH),
        "remote_mismatch_rate": rate(RemoteOutcome.MISMATCH),
        "remote_indeterminate_rate": rate(RemoteOutcome.INDETERMINATE),
        "post_verification_divergence_count": divergence_count,
        "controller_action_count_total": controller_total,
        "controller_action_count_mean": controller_total / total,
        "cleanup_failure_count": cleanup_failure_count,
        "cleanup_unresolved_count": cleanup_unresolved_count,
        "retry_count_total": retry_total,
        "retry_run_count": retry_runs,
        "refusal_run_count": refusals,
        "refusal_rate": refusals / total,
        "verification_latency_ms": _latency_summary(runs),
        "source_external_agreement_count": agreement,
        "source_false_positive_count": false_positive,
        "source_false_negative_count": false_negative,
        "source_indeterminate_count": indeterminate,
        "limitations": {
            "retry_necessity_independently_labeled": False,
            "intent_quality_inferred": False,
            "latest_remote_outcome_used_for_headline_rates": True,
            "harness_aborts_excluded_from_remote_rates": True,
        },
    }
