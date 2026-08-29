from __future__ import annotations

import json
import unittest

from completion_verifier.remote import RemoteObservation, RemoteOutcome
from completion_verifier.remote.github import (
    GitHubPullRequestContract,
    GitHubPullRequestSnapshot,
)


OID40 = "A" * 40
OID64 = "B" * 64


class GitHubPullRequestContractTests(unittest.TestCase):
    def test_valid_contract_canonicalizes_object_ids(self) -> None:
        contract = GitHubPullRequestContract(
            repository="PRIVATE_OWNER/PRIVATE_REPO",
            repository_id=123,
            pull_number=7,
            expected_head_oid=OID40,
            expected_base_ref="PRIVATE_BASE",
            expected_state="merged",
            expected_merge_oid=OID64,
            expected_head_repository_id=456,
        )
        self.assertEqual(contract.expected_head_oid, OID40.lower())
        self.assertEqual(contract.expected_merge_oid, OID64.lower())

    def test_contract_rejects_boolean_numeric_identifiers(self) -> None:
        for field, value in (
            ("repository_id", True),
            ("pull_number", True),
            ("expected_head_repository_id", True),
        ):
            kwargs = {
                "repository": "owner/repo",
                "repository_id": 1,
                "pull_number": 2,
                "expected_head_oid": "a" * 40,
                "expected_base_ref": "main",
                "expected_state": "open",
            }
            kwargs[field] = value
            with self.subTest(field=field), self.assertRaises(ValueError):
                GitHubPullRequestContract(**kwargs)  # type: ignore[arg-type]

    def test_contract_rejects_invalid_repository_locator(self) -> None:
        for value in ("repo", "/repo", "owner/", "owner/repo/extra", "owner\n/repo"):
            with self.subTest(value=value), self.assertRaises(ValueError):
                GitHubPullRequestContract(
                    repository=value,
                    repository_id=1,
                    pull_number=2,
                    expected_head_oid="a" * 40,
                    expected_base_ref="main",
                    expected_state="open",
                )

    def test_contract_rejects_invalid_object_ids(self) -> None:
        for value in ("a" * 39, "a" * 41, "g" * 40, "a" * 63, "a" * 65):
            with self.subTest(value=value), self.assertRaises(ValueError):
                GitHubPullRequestContract(
                    repository="owner/repo",
                    repository_id=1,
                    pull_number=2,
                    expected_head_oid=value,
                    expected_base_ref="main",
                    expected_state="open",
                )

    def test_contract_rejects_invalid_state_or_merge_combination(self) -> None:
        with self.assertRaises(ValueError):
            GitHubPullRequestContract(
                repository="owner/repo",
                repository_id=1,
                pull_number=2,
                expected_head_oid="a" * 40,
                expected_base_ref="main",
                expected_state="unknown",
            )
        with self.assertRaises(ValueError):
            GitHubPullRequestContract(
                repository="owner/repo",
                repository_id=1,
                pull_number=2,
                expected_head_oid="a" * 40,
                expected_base_ref="main",
                expected_state="open",
                expected_merge_oid="b" * 40,
            )

    def test_contract_rejects_control_characters_and_oversized_ref(self) -> None:
        for ref in ("", "bad\nref", "x" * 256):
            with self.subTest(ref=ref), self.assertRaises(ValueError):
                GitHubPullRequestContract(
                    repository="owner/repo",
                    repository_id=1,
                    pull_number=2,
                    expected_head_oid="a" * 40,
                    expected_base_ref=ref,
                    expected_state="open",
                )

    def test_contract_repr_does_not_expose_caller_values(self) -> None:
        contract = GitHubPullRequestContract(
            repository="PRIVATE_OWNER/PRIVATE_REPO",
            repository_id=987654,
            pull_number=7654,
            expected_head_oid="c" * 40,
            expected_base_ref="PRIVATE_BRANCH",
            expected_state="merged",
            expected_merge_oid="d" * 40,
        )
        rendered = repr(contract)
        self.assertEqual(rendered, "GitHubPullRequestContract()")
        for secret in (
            "PRIVATE_OWNER",
            "PRIVATE_REPO",
            "987654",
            "7654",
            "PRIVATE_BRANCH",
            "c" * 40,
            "d" * 40,
        ):
            self.assertNotIn(secret, rendered)

    def test_snapshot_repr_is_private_and_fixed(self) -> None:
        snapshot = GitHubPullRequestSnapshot(
            repository_id=111,
            pull_number=222,
            state="open",
            merged=False,
            head_oid="a" * 40,
            head_repository_id=None,
            base_ref="PRIVATE_BASE",
            merge_oid=None,
            request_started_at=1000.0,
            request_finished_at=1001.0,
            provider_date=1001.0,
        )
        self.assertEqual(repr(snapshot), "GitHubPullRequestSnapshot()")
        self.assertNotIn("PRIVATE_BASE", repr(snapshot))


class RemoteObservationPrivacyTests(unittest.TestCase):
    def test_public_observation_contains_only_fixed_labels_and_booleans(self) -> None:
        observation = RemoteObservation(
            provider="github",
            kind="pull_request",
            outcome=RemoteOutcome.MATCH,
            trusted=True,
            reason="matched",
            evidence={
                "repository_identity_matches": True,
                "head_matches": True,
                "base_matches": True,
                "state_matches": True,
                "merge_matches": True,
                "head_repository_matches": True,
                "fresh": True,
            },
        )
        payload = json.dumps(observation.to_dict(), sort_keys=True)
        self.assertIn("authenticated_remote_state", payload)
        self.assertIn("MATCH", payload)
        for secret in (
            "PRIVATE_OWNER",
            "PRIVATE_REPO",
            "PRIVATE_BRANCH",
            "PRIVATE_TOKEN",
            "a" * 40,
        ):
            self.assertNotIn(secret, payload)

    def test_observation_rejects_unknown_evidence_or_reason(self) -> None:
        with self.assertRaises(ValueError):
            RemoteObservation(
                provider="github",
                kind="pull_request",
                outcome=RemoteOutcome.MATCH,
                trusted=True,
                reason="made_up_reason",
                evidence={"fresh": True},
            )
        with self.assertRaises(ValueError):
            RemoteObservation(
                provider="github",
                kind="pull_request",
                outcome=RemoteOutcome.MATCH,
                trusted=True,
                reason="matched",
                evidence={"PRIVATE_FIELD": True},
            )

    def test_outcome_and_trust_must_be_consistent(self) -> None:
        with self.assertRaises(ValueError):
            RemoteObservation(
                provider="github",
                kind="pull_request",
                outcome=RemoteOutcome.MATCH,
                trusted=False,
                reason="matched",
                evidence={"fresh": True},
            )
        with self.assertRaises(ValueError):
            RemoteObservation(
                provider="github",
                kind="pull_request",
                outcome=RemoteOutcome.INDETERMINATE,
                trusted=True,
                reason="provider_unavailable",
                evidence={"fresh": False},
            )


if __name__ == "__main__":
    unittest.main()
