from __future__ import annotations

import unittest

from completion_verifier.experiments.r1.models import R1ControllerReceipt, R1SourceClaim
from completion_verifier.experiments.r1.orchestrator import (
    append_explicit_second_observation,
    evaluate_attempt,
)
from completion_verifier.remote import RemoteObservation, RemoteOutcome
from completion_verifier.remote.github import GitHubPullRequestContract


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


class R1CodexReviewLatencyTests(unittest.TestCase):
    def _contract(self) -> GitHubPullRequestContract:
        return GitHubPullRequestContract(
            repository="owner/repo",
            repository_id=44,
            pull_number=7,
            expected_head_oid="a" * 40,
            expected_head_repository_id=44,
            expected_base_ref="main",
            expected_state="open",
        )

    def _claim(self) -> R1SourceClaim:
        return R1SourceClaim(
            completion_claimed=True,
            retry_count=0,
            refusal=False,
            action_count=3,
        )

    def test_first_verifier_read_records_nonnegative_latency(self) -> None:
        run = evaluate_attempt(
            scenario_id="S0",
            contract=self._contract(),
            source_claim=self._claim(),
            controller_receipts=(),
            verifier=MatchVerifier(),
        )
        self.assertEqual(len(run.verification_latency_ms), 1)
        self.assertIsNotNone(run.verification_latency_ms[0])
        self.assertGreaterEqual(run.verification_latency_ms[0], 0.0)

    def test_s7_second_read_appends_second_measured_latency(self) -> None:
        run = evaluate_attempt(
            scenario_id="S7",
            contract=self._contract(),
            source_claim=self._claim(),
            controller_receipts=(),
            verifier=MatchVerifier(),
        )
        rollback = R1ControllerReceipt(
            action="close_pull_request",
            success=True,
            action_cost=1,
            private_pull_number=7,
        )
        updated = append_explicit_second_observation(
            run,
            contract=self._contract(),
            verifier=MatchVerifier(),
            rollback_receipt=rollback,
        )
        self.assertEqual(len(updated.verification_latency_ms), 2)
        self.assertTrue(all(value is not None and value >= 0 for value in updated.verification_latency_ms))


if __name__ == "__main__":
    unittest.main()
