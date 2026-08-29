from __future__ import annotations

import unittest

from completion_verifier.remote.github import (
    GitHubPullRequestContract,
    GitHubPullRequestSnapshot,
    GitHubReadResult,
    verify_github_pull_request,
)


HEAD = "a" * 40
NOW = 1_000.0


def contract() -> GitHubPullRequestContract:
    return GitHubPullRequestContract(
        repository="owner/repo",
        repository_id=101,
        pull_number=22,
        expected_head_oid=HEAD,
        expected_base_ref="main",
        expected_state="open",
    )


def snapshot(**overrides: object) -> GitHubPullRequestSnapshot:
    values: dict[str, object] = {
        "repository_id": 101,
        "pull_number": 22,
        "state": "open",
        "merged": False,
        "head_oid": HEAD,
        "head_repository_id": 101,
        "base_ref": "main",
        "merge_oid": None,
        "request_started_at": NOW - 2,
        "request_finished_at": NOW - 1,
        "provider_date": NOW - 1,
    }
    values.update(overrides)
    return GitHubPullRequestSnapshot(**values)  # type: ignore[arg-type]


class FakeReader:
    def __init__(self, observed: GitHubPullRequestSnapshot) -> None:
        self._observed = observed

    def read_pull_request(self, requested: GitHubPullRequestContract) -> GitHubReadResult:
        return GitHubReadResult(snapshot=self._observed)


class ReviewRegressionTests(unittest.TestCase):
    def test_snapshot_rejects_open_merged_contradiction(self) -> None:
        with self.assertRaises(ValueError):
            snapshot(state="open", merged=True)

    def test_verification_clock_must_be_finite(self) -> None:
        observed = snapshot()
        for current_time in (float("nan"), float("inf"), float("-inf")):
            with self.subTest(current_time=current_time), self.assertRaises(ValueError):
                verify_github_pull_request(
                    contract(),
                    FakeReader(observed),
                    now=lambda current_time=current_time: current_time,
                )


if __name__ == "__main__":
    unittest.main()
