from __future__ import annotations

from time import perf_counter_ns
from typing import Protocol

from ...remote.evaluation import evaluate_remote_observation
from ...remote.github import GitHubPullRequestContract
from ...remote.models import RemoteObservation
from .models import (
    R1_SCENARIOS,
    R1ControllerReceipt,
    R1RunRecord,
    R1SourceClaim,
)


class R1Verifier(Protocol):
    def verify(self, contract: GitHubPullRequestContract) -> RemoteObservation: ...


def seal_source_claim(
    *,
    completion_claimed: bool,
    retry_count: int,
    refusal: bool,
    action_count: int,
    private_trace_ref: str | None = None,
) -> R1SourceClaim:
    return R1SourceClaim(
        completion_claimed=completion_claimed,
        retry_count=retry_count,
        refusal=refusal,
        action_count=action_count,
        private_trace_ref=private_trace_ref,
    )


def _timed_verify(
    verifier: R1Verifier, contract: GitHubPullRequestContract
) -> tuple[RemoteObservation, float]:
    started = perf_counter_ns()
    observation = verifier.verify(contract)
    elapsed_ms = (perf_counter_ns() - started) / 1_000_000.0
    if not isinstance(observation, RemoteObservation):
        raise ValueError("R1 verifier returned an invalid observation.")
    return observation, elapsed_ms


def evaluate_attempt(
    *,
    scenario_id: str,
    contract: GitHubPullRequestContract,
    source_claim: R1SourceClaim,
    controller_receipts: tuple[R1ControllerReceipt, ...],
    verifier: R1Verifier,
) -> R1RunRecord:
    if scenario_id not in R1_SCENARIOS:
        raise ValueError("Unknown R1 scenario.")
    if not isinstance(contract, GitHubPullRequestContract):
        raise ValueError("R1 attempt requires a GitHub pull-request contract.")
    if not isinstance(source_claim, R1SourceClaim):
        raise ValueError("R1 attempt requires a sealed source claim.")
    if not isinstance(controller_receipts, tuple) or not all(
        isinstance(item, R1ControllerReceipt) for item in controller_receipts
    ):
        raise ValueError("R1 attempt controller receipts are invalid.")

    observation, elapsed_ms = _timed_verify(verifier, contract)
    evaluation = evaluate_remote_observation(
        observation,
        completion_claimed=source_claim.completion_claimed,
    )
    return R1RunRecord(
        scenario_id=scenario_id,
        source_claim=source_claim,
        controller_receipts=controller_receipts,
        observations=(observation,),
        evaluations=(evaluation,),
        verification_latency_ms=(elapsed_ms,),
    )


def append_explicit_second_observation(
    run_record: R1RunRecord,
    *,
    contract: GitHubPullRequestContract,
    verifier: R1Verifier,
    rollback_receipt: R1ControllerReceipt,
) -> R1RunRecord:
    """Append R1's explicit post-rollback read without polling or rewriting history."""

    if not isinstance(run_record, R1RunRecord):
        raise ValueError("R1 second observation requires an R1RunRecord.")
    if run_record.scenario_id != "S7":
        raise ValueError("Explicit second observation is reserved for R1 scenario S7.")
    if not isinstance(contract, GitHubPullRequestContract):
        raise ValueError("R1 second observation requires a GitHub pull-request contract.")
    if not isinstance(rollback_receipt, R1ControllerReceipt):
        raise ValueError("R1 rollback receipt is invalid.")
    if rollback_receipt.action != "close_pull_request":
        raise ValueError("R1 S7 rollback receipt must be a close_pull_request action.")

    observation, elapsed_ms = _timed_verify(verifier, contract)
    evaluation = evaluate_remote_observation(
        observation,
        completion_claimed=run_record.source_claim.completion_claimed,
    )
    return R1RunRecord(
        scenario_id=run_record.scenario_id,
        source_claim=run_record.source_claim,
        controller_receipts=run_record.controller_receipts + (rollback_receipt,),
        observations=run_record.observations + (observation,),
        evaluations=run_record.evaluations + (evaluation,),
        verification_latency_ms=run_record.verification_latency_ms + (elapsed_ms,),
        run_status=run_record.run_status,
        abort_reason_code=run_record.abort_reason_code,
    )
