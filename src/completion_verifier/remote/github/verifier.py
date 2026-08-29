from __future__ import annotations

import math
import time
from dataclasses import dataclass
from typing import Callable, Protocol

from ...models import Evaluation
from ..evaluation import evaluate_remote_observation
from ..models import RemoteObservation, RemoteOutcome
from .contracts import GitHubPullRequestContract, GitHubPullRequestSnapshot


_INDETERMINATE_REASONS = frozenset(
    {
        "authentication_failed",
        "permission_unverified",
        "resource_unobservable",
        "rate_limited",
        "redirect_rejected",
        "provider_unavailable",
        "invalid_provider_response",
        "observation_not_fresh",
    }
)
_MAX_LOCAL_AGE_SECONDS = 60.0
_MAX_PROVIDER_DATE_SKEW_SECONDS = 300.0
_MAX_FUTURE_FINISH_SECONDS = 5.0


@dataclass(frozen=True, repr=False)
class GitHubReadResult:
    snapshot: GitHubPullRequestSnapshot | None
    reason: str | None = None

    def __post_init__(self) -> None:
        if (self.snapshot is None) == (self.reason is None):
            raise ValueError("GitHub read result requires exactly one of snapshot or reason.")
        if self.snapshot is not None and not isinstance(self.snapshot, GitHubPullRequestSnapshot):
            raise ValueError("GitHub read result snapshot has wrong type.")
        if self.reason is not None and self.reason not in _INDETERMINATE_REASONS:
            raise ValueError("Unknown GitHub read reason code.")

    def __repr__(self) -> str:
        return "GitHubReadResult()"


class GitHubStateReader(Protocol):
    def read_pull_request(self, contract: GitHubPullRequestContract) -> GitHubReadResult:
        ...


def _fresh(snapshot: GitHubPullRequestSnapshot, now: float) -> bool:
    if snapshot.request_started_at > snapshot.request_finished_at:
        return False
    if snapshot.request_finished_at > now + _MAX_FUTURE_FINISH_SECONDS:
        return False
    if now - snapshot.request_finished_at > _MAX_LOCAL_AGE_SECONDS:
        return False
    if snapshot.provider_date is not None:
        if abs(snapshot.provider_date - snapshot.request_finished_at) > _MAX_PROVIDER_DATE_SKEW_SECONDS:
            return False
    return True


def _state_matches(contract: GitHubPullRequestContract, snapshot: GitHubPullRequestSnapshot) -> bool:
    if contract.expected_state == "open":
        return snapshot.state == "open" and not snapshot.merged
    if contract.expected_state == "closed":
        return snapshot.state == "closed" and not snapshot.merged
    return snapshot.merged


def verify_github_pull_request(
    contract: GitHubPullRequestContract,
    reader: GitHubStateReader,
    *,
    now: Callable[[], float] = time.time,
) -> RemoteObservation:
    result = reader.read_pull_request(contract)
    if not isinstance(result, GitHubReadResult):
        return RemoteObservation(
            provider="github",
            kind="pull_request",
            outcome=RemoteOutcome.INDETERMINATE,
            trusted=False,
            reason="invalid_provider_response",
            evidence={"fresh": False},
        )

    if result.snapshot is None:
        return RemoteObservation(
            provider="github",
            kind="pull_request",
            outcome=RemoteOutcome.INDETERMINATE,
            trusted=False,
            reason=result.reason or "invalid_provider_response",
            evidence={"fresh": False},
        )

    snapshot = result.snapshot
    current_time = now()
    if isinstance(current_time, bool) or not isinstance(current_time, (int, float)):
        raise ValueError("Verification clock must return a finite numeric timestamp.")
    current_timestamp = float(current_time)
    if not math.isfinite(current_timestamp):
        raise ValueError("Verification clock must return a finite numeric timestamp.")
    fresh = _fresh(snapshot, current_timestamp)
    if not fresh:
        return RemoteObservation(
            provider="github",
            kind="pull_request",
            outcome=RemoteOutcome.INDETERMINATE,
            trusted=False,
            reason="observation_not_fresh",
            evidence={"fresh": False},
        )

    evidence = {
        "repository_identity_matches": snapshot.repository_id == contract.repository_id,
        "head_matches": snapshot.head_oid == contract.expected_head_oid,
        "head_repository_matches": (
            True
            if contract.expected_head_repository_id is None
            else snapshot.head_repository_id == contract.expected_head_repository_id
        ),
        "base_matches": snapshot.base_ref == contract.expected_base_ref,
        "state_matches": _state_matches(contract, snapshot),
        "merge_matches": (
            True
            if contract.expected_merge_oid is None
            else snapshot.merge_oid == contract.expected_merge_oid
        ),
        "fresh": True,
    }

    ordered_mismatches = (
        ("repository_identity_matches", "repository_identity_mismatch"),
        ("state_matches", "state_mismatch"),
        ("head_matches", "head_mismatch"),
        ("head_repository_matches", "head_repository_mismatch"),
        ("base_matches", "base_mismatch"),
        ("merge_matches", "merge_mismatch"),
    )
    for field, reason in ordered_mismatches:
        if not evidence[field]:
            return RemoteObservation(
                provider="github",
                kind="pull_request",
                outcome=RemoteOutcome.MISMATCH,
                trusted=True,
                reason=reason,
                evidence=evidence,
            )

    return RemoteObservation(
        provider="github",
        kind="pull_request",
        outcome=RemoteOutcome.MATCH,
        trusted=True,
        reason="matched",
        evidence=evidence,
    )


def evaluate_github_pull_request(
    contract: GitHubPullRequestContract,
    reader: GitHubStateReader,
    *,
    completion_claimed: bool = True,
    now: Callable[[], float] = time.time,
) -> Evaluation:
    observation = verify_github_pull_request(contract, reader, now=now)
    return evaluate_remote_observation(
        observation,
        completion_claimed=completion_claimed,
    )
