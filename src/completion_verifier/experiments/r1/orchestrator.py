from __future__ import annotations

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

    observation = verifier.verify(contract)
    if not isinstance(observation, RemoteObservation):
        raise ValueError("R1 verifier returned an invalid observation.")
    evaluation = evaluate_remote_observation(
        observation,
        completion_claimed=source_claim.completion_claimed,
    )
    return R1RunRecord(
        scenario_id=scenario_id,
        source_claim=source_claim,
        controller_receipts=controller_receipts,
        observations=(observation,),
        evaluation=evaluation,
    )
