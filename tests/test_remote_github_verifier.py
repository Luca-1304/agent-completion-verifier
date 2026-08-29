from __future__ import annotations

import unittest

from completion_verifier.models import Status
from completion_verifier.remote import RemoteOutcome
from completion_verifier.remote.github import (
    GitHubPullRequestContract,
    GitHubPullRequestSnapshot,
    GitHubReadResult,
    evaluate_github_pull_request,
    verify_github_pull_request,
)


HEAD = "a" * 40
MERGE = "b" * 40
NOW = 1_000.0


def contract(**overrides: object) -> GitHubPullRequestContract:
    values: dict[str, object] = {
        "repository": "PRIVATE_OWNER/PRIVATE_REPO",
        "repository_id": 101,
        "pull_number": 22,
        "expected_head_oid": HEAD,
        "expected_base_ref": "PRIVATE_BASE",
        "expected_state": "open",
    }
    values.update(overrides)
    return GitHubPullRequestContract(**values)  # type: ignore[arg-type]


def snapshot(**overrides: object) -> GitHubPullRequestSnapshot:
    values: dict[str, object] = {
        "repository_id": 101,
        "pull_number": 22,
        "state": "open",
        "merged": False,
        "head_oid": HEAD,
        "head_repository_id": 101,
        "base_ref": "PRIVATE_BASE",
        "merge_oid": None,
        "request_started_at": NOW - 2,
        "request_finished_at": NOW - 1,
        "provider_date": NOW - 1,
    }
    values.update(overrides)
    return GitHubPullRequestSnapshot(**values)  # type: ignore[arg-type]


class FakeReader:
    def __init__(self, result: GitHubReadResult) -> None:
        self.result = result
        self.calls = 0

    def read_pull_request(self, requested: GitHubPullRequestContract) -> GitHubReadResult:
        self.calls += 1
        return self.result


class GitHubSnapshotVerifierTests(unittest.TestCase):
    def verify(
        self,
        expected: GitHubPullRequestContract | None = None,
        observed: GitHubPullRequestSnapshot | None = None,
    ):
        reader = FakeReader(GitHubReadResult(snapshot=observed or snapshot()))
        result = verify_github_pull_request(
            expected or contract(),
            reader,
            now=lambda: NOW,
        )
        self.assertEqual(reader.calls, 1)
        return result

    def test_exact_match_is_authenticated_match(self) -> None:
        result = self.verify()
        self.assertEqual(result.outcome, RemoteOutcome.MATCH)
        self.assertTrue(result.trusted)
        self.assertEqual(result.reason, "matched")
        self.assertTrue(all(result.evidence.values()))

    def test_repository_identity_mismatch_is_decisive(self) -> None:
        result = self.verify(observed=snapshot(repository_id=999))
        self.assertEqual(result.outcome, RemoteOutcome.MISMATCH)
        self.assertEqual(result.reason, "repository_identity_mismatch")
        self.assertFalse(result.evidence["repository_identity_matches"])

    def test_head_mismatch_is_decisive(self) -> None:
        result = self.verify(observed=snapshot(head_oid="c" * 40))
        self.assertEqual(result.reason, "head_mismatch")
        self.assertFalse(result.evidence["head_matches"])

    def test_declared_head_repository_must_match(self) -> None:
        expected = contract(expected_head_repository_id=202)
        result = self.verify(expected=expected, observed=snapshot(head_repository_id=None))
        self.assertEqual(result.reason, "head_repository_mismatch")
        self.assertFalse(result.evidence["head_repository_matches"])

    def test_base_mismatch_is_decisive(self) -> None:
        result = self.verify(observed=snapshot(base_ref="OTHER_BASE"))
        self.assertEqual(result.reason, "base_mismatch")
        self.assertFalse(result.evidence["base_matches"])

    def test_open_closed_and_merged_states_are_distinct(self) -> None:
        closed_expected = contract(expected_state="closed")
        closed_result = self.verify(
            expected=closed_expected,
            observed=snapshot(state="closed", merged=False),
        )
        self.assertEqual(closed_result.outcome, RemoteOutcome.MATCH)

        merged_expected = contract(
            expected_state="merged",
            expected_merge_oid=MERGE,
        )
        merged_result = self.verify(
            expected=merged_expected,
            observed=snapshot(state="closed", merged=True, merge_oid=MERGE),
        )
        self.assertEqual(merged_result.outcome, RemoteOutcome.MATCH)

        wrong_state = self.verify(
            expected=merged_expected,
            observed=snapshot(state="closed", merged=False, merge_oid=MERGE),
        )
        self.assertEqual(wrong_state.reason, "state_mismatch")

    def test_wrong_merge_oid_is_decisive_after_merged_state(self) -> None:
        expected = contract(expected_state="merged", expected_merge_oid=MERGE)
        result = self.verify(
            expected=expected,
            observed=snapshot(state="closed", merged=True, merge_oid="c" * 40),
        )
        self.assertEqual(result.reason, "merge_mismatch")
        self.assertFalse(result.evidence["merge_matches"])

    def test_premerge_merge_oid_never_proves_merged_completion(self) -> None:
        expected = contract(expected_state="merged", expected_merge_oid=MERGE)
        result = self.verify(
            expected=expected,
            observed=snapshot(state="open", merged=False, merge_oid=MERGE),
        )
        self.assertEqual(result.outcome, RemoteOutcome.MISMATCH)
        self.assertEqual(result.reason, "state_mismatch")

    def test_reader_indeterminate_result_stays_unverified(self) -> None:
        reader = FakeReader(GitHubReadResult(snapshot=None, reason="provider_unavailable"))
        observation = verify_github_pull_request(contract(), reader, now=lambda: NOW)
        self.assertEqual(observation.outcome, RemoteOutcome.INDETERMINATE)
        self.assertFalse(observation.trusted)
        self.assertEqual(observation.reason, "provider_unavailable")
        evaluation = evaluate_github_pull_request(
            contract(),
            reader,
            now=lambda: NOW,
        )
        self.assertEqual(evaluation.status, Status.UNVERIFIED)

    def test_decisive_mismatch_and_match_use_existing_evaluator(self) -> None:
        matched = evaluate_github_pull_request(
            contract(),
            FakeReader(GitHubReadResult(snapshot=snapshot())),
            now=lambda: NOW,
        )
        failed = evaluate_github_pull_request(
            contract(),
            FakeReader(GitHubReadResult(snapshot=snapshot(head_oid="d" * 40))),
            now=lambda: NOW,
        )
        self.assertEqual(matched.status, Status.VERIFIED_COMPLETE)
        self.assertEqual(failed.status, Status.FAILED)


class GitHubFreshnessTests(unittest.TestCase):
    def verify_snapshot(self, observed: GitHubPullRequestSnapshot):
        return verify_github_pull_request(
            contract(),
            FakeReader(GitHubReadResult(snapshot=observed)),
            now=lambda: NOW,
        )

    def test_request_time_order_must_be_coherent(self) -> None:
        result = self.verify_snapshot(
            snapshot(request_started_at=NOW - 1, request_finished_at=NOW - 2)
        )
        self.assertEqual(result.outcome, RemoteOutcome.INDETERMINATE)
        self.assertEqual(result.reason, "observation_not_fresh")

    def test_request_finish_cannot_be_more_than_five_seconds_in_future(self) -> None:
        result = self.verify_snapshot(
            snapshot(request_started_at=NOW + 5, request_finished_at=NOW + 6)
        )
        self.assertEqual(result.reason, "observation_not_fresh")

    def test_local_observation_age_must_not_exceed_sixty_seconds(self) -> None:
        result = self.verify_snapshot(
            snapshot(request_started_at=NOW - 62, request_finished_at=NOW - 61)
        )
        self.assertEqual(result.reason, "observation_not_fresh")

    def test_provider_date_must_be_within_five_minutes_of_finish(self) -> None:
        result = self.verify_snapshot(
            snapshot(provider_date=(NOW - 1) - 301)
        )
        self.assertEqual(result.reason, "observation_not_fresh")

    def test_missing_provider_date_is_allowed_with_fresh_local_timing(self) -> None:
        result = self.verify_snapshot(snapshot(provider_date=None))
        self.assertEqual(result.outcome, RemoteOutcome.MATCH)
        self.assertTrue(result.evidence["fresh"])


if __name__ == "__main__":
    unittest.main()
