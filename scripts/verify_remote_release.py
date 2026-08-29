"""Verify the privacy and status boundary for the v0.8 remote verifier."""

from __future__ import annotations

import json

import completion_verifier
from completion_verifier.models import Status
from completion_verifier.remote import RemoteOutcome
from completion_verifier.remote.github import (
    GitHubPullRequestContract,
    GitHubPullRequestSnapshot,
    GitHubReadResult,
    verify_github_pull_request,
)


NOW = 2_000.0
REPOSITORY = "PRIVATE_RELEASE_OWNER/PRIVATE_RELEASE_REPO"
REPOSITORY_ID = 987654321
PULL_NUMBER = 54321
BASE = "PRIVATE_RELEASE_BASE"
HEAD = "a" * 40
WRONG_HEAD = "b" * 40
HEAD_REPOSITORY_ID = 123456789


class FakeReader:
    def __init__(self, result: GitHubReadResult) -> None:
        self._result = result

    def read_pull_request(self, contract: GitHubPullRequestContract) -> GitHubReadResult:
        return self._result


def _contract() -> GitHubPullRequestContract:
    return GitHubPullRequestContract(
        repository=REPOSITORY,
        repository_id=REPOSITORY_ID,
        pull_number=PULL_NUMBER,
        expected_head_oid=HEAD,
        expected_base_ref=BASE,
        expected_state="open",
        expected_head_repository_id=HEAD_REPOSITORY_ID,
    )


def _snapshot(head_oid: str = HEAD) -> GitHubPullRequestSnapshot:
    return GitHubPullRequestSnapshot(
        repository_id=REPOSITORY_ID,
        pull_number=PULL_NUMBER,
        state="open",
        merged=False,
        head_oid=head_oid,
        head_repository_id=HEAD_REPOSITORY_ID,
        base_ref=BASE,
        merge_oid=None,
        request_started_at=NOW - 2,
        request_finished_at=NOW - 1,
        provider_date=NOW - 1,
    )


def main() -> int:
    if completion_verifier.__version__ != "0.8.0":
        raise AssertionError("Remote verifier release identity must be 0.8.0.")

    expected = _contract()
    match = verify_github_pull_request(
        expected,
        FakeReader(GitHubReadResult(snapshot=_snapshot())),
        now=lambda: NOW,
    )
    mismatch = verify_github_pull_request(
        expected,
        FakeReader(GitHubReadResult(snapshot=_snapshot(WRONG_HEAD))),
        now=lambda: NOW,
    )
    indeterminate = verify_github_pull_request(
        expected,
        FakeReader(GitHubReadResult(snapshot=None, reason="provider_unavailable")),
        now=lambda: NOW,
    )

    if [match.outcome, mismatch.outcome, indeterminate.outcome] != [
        RemoteOutcome.MATCH,
        RemoteOutcome.MISMATCH,
        RemoteOutcome.INDETERMINATE,
    ]:
        raise AssertionError("Unexpected remote outcome sequence.")

    evaluations = [
        completion_verifier.evaluate_remote_observation(item)
        for item in (match, mismatch, indeterminate)
    ]
    if [item.status for item in evaluations] != [
        Status.VERIFIED_COMPLETE,
        Status.FAILED,
        Status.UNVERIFIED,
    ]:
        raise AssertionError("Remote outcomes do not map through the existing evaluator.")

    public = json.dumps(
        [item.to_dict() for item in (match, mismatch, indeterminate)],
        sort_keys=True,
    )
    private_values = (
        REPOSITORY,
        "PRIVATE_RELEASE_OWNER",
        "PRIVATE_RELEASE_REPO",
        BASE,
        HEAD,
        WRONG_HEAD,
        str(REPOSITORY_ID),
        str(PULL_NUMBER),
        str(HEAD_REPOSITORY_ID),
        str(NOW),
        "PRIVATE_TOKEN_SENTINEL",
        "PRIVATE_PROVIDER_BODY_SENTINEL",
        "PRIVATE_PROVIDER_ERROR_SENTINEL",
    )
    for value in private_values:
        if value in public:
            raise AssertionError("Private remote value leaked into public evidence.")

    print("Remote release verification passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
