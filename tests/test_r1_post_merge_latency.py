from __future__ import annotations

import unittest

from completion_verifier.experiments.r1.models import R1ControllerReceipt, R1SourceClaim
from completion_verifier.experiments.r1.orchestrator import (
    append_explicit_second_observation,
    evaluate_attempt,
)
from completion_verifier.remote import GitHubPullRequestContract, RemoteObservation, RemoteOutcome


class MatchVerifier:
    def verify(self, contract):
        del contract
        return RemoteObservation(
            provider="github",
            kind="pull_request",
            outcome=RemoteOutcome.MATCH,
            trusted=True,
            reason="matched",
            evidence={"fresh": True},
        )


def _contract() -> GitHubPullRequestContract:
    return GitHubPullRequestContract(
        repository="safe-owner/safe-repo",
        repository_id=1001,
        pull_number=7,
        expected_head_oid="a" * 40,
        expected_head_repository_id=1001,
        expected_base_ref="main",
        expected_state="open",
    )


class PostMergeLatencyReviewTests(unittest.TestCase):
    def test_runner_generated_first_observation_has_measured_latency(self) -> None:
        run = evaluate_attempt(
            scenario_id="S0",
            contract=_contract(),
            source_claim=R1SourceClaim(True, 0, False, 0),
            controller_receipts=(),
            verifier=MatchVerifier(),
        )
        self.assertEqual(len(run.verification_latency_ms), 1)
        self.assertIsInstance(run.verification_latency_ms[0], float)
        self.assertGreaterEqual(run.verification_latency_ms[0], 0.0)

    def test_s7_second_read_appends_its_own_measured_latency(self) -> None:
        run = evaluate_attempt(
            scenario_id="S7",
            contract=_contract(),
            source_claim=R1SourceClaim(True, 0, False, 0),
            controller_receipts=(),
            verifier=MatchVerifier(),
        )
        updated = append_explicit_second_observation(
            run,
            contract=_contract(),
            verifier=MatchVerifier(),
            rollback_receipt=R1ControllerReceipt(
                "close_pull_request", True, 1, private_pull_number=7
            ),
        )
        self.assertEqual(len(updated.verification_latency_ms), 2)
        self.assertTrue(all(isinstance(value, float) for value in updated.verification_latency_ms))
        self.assertTrue(all(value >= 0.0 for value in updated.verification_latency_ms))


if __name__ == "__main__":
    unittest.main()
