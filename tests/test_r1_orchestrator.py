from __future__ import annotations

import unittest

from completion_verifier.models import Status
from completion_verifier.remote import RemoteObservation, RemoteOutcome
from completion_verifier.remote.github import GitHubPullRequestContract
from completion_verifier.experiments.r1 import R1ControllerReceipt
from completion_verifier.experiments.r1.orchestrator import (
    evaluate_attempt,
    seal_source_claim,
)


class FakeVerifier:
    def __init__(self, observation: RemoteObservation) -> None:
        self.observation = observation
        self.calls: list[GitHubPullRequestContract] = []

    def verify(self, contract: GitHubPullRequestContract) -> RemoteObservation:
        self.calls.append(contract)
        return self.observation


def _contract() -> GitHubPullRequestContract:
    return GitHubPullRequestContract(
        repository="PRIVATE_OWNER/PRIVATE_REPO",
        repository_id=9001,
        pull_number=7,
        expected_head_oid="a" * 40,
        expected_base_ref="main",
        expected_state="open",
    )


def _observation(outcome: RemoteOutcome) -> RemoteObservation:
    if outcome is RemoteOutcome.MATCH:
        return RemoteObservation(
            provider="github",
            kind="pull_request",
            outcome=outcome,
            trusted=True,
            reason="matched",
            evidence={"fresh": True, "head_matches": True},
        )
    if outcome is RemoteOutcome.MISMATCH:
        return RemoteObservation(
            provider="github",
            kind="pull_request",
            outcome=outcome,
            trusted=True,
            reason="head_mismatch",
            evidence={"fresh": True, "head_matches": False},
        )
    return RemoteObservation(
        provider="github",
        kind="pull_request",
        outcome=outcome,
        trusted=False,
        reason="provider_unavailable",
        evidence={"fresh": False},
    )


class R1OrchestratorTests(unittest.TestCase):
    def _claim(self, completion_claimed: bool = True):
        return seal_source_claim(
            completion_claimed=completion_claimed,
            retry_count=0,
            refusal=False,
            action_count=3,
            private_trace_ref="PRIVATE_TRACE_SENTINEL",
        )

    def _receipts(self) -> tuple[R1ControllerReceipt, ...]:
        return (
            R1ControllerReceipt("create_branch", True, 1, private_target_ref="PRIVATE_A"),
            R1ControllerReceipt("write_fixture", True, 1, private_target_ref="PRIVATE_B"),
            R1ControllerReceipt("create_pull_request", True, 1, private_target_ref="PRIVATE_C"),
        )

    def test_mismatch_beats_successful_controller_receipts(self) -> None:
        verifier = FakeVerifier(_observation(RemoteOutcome.MISMATCH))
        result = evaluate_attempt(
            scenario_id="S2",
            contract=_contract(),
            source_claim=self._claim(True),
            controller_receipts=self._receipts(),
            verifier=verifier,
        )
        self.assertEqual(result.observations[0].outcome, RemoteOutcome.MISMATCH)
        self.assertEqual(result.evaluation.status, Status.FAILED)
        self.assertEqual(len(verifier.calls), 1)

    def test_indeterminate_stays_unverified_even_with_success_receipts(self) -> None:
        result = evaluate_attempt(
            scenario_id="S5",
            contract=_contract(),
            source_claim=self._claim(True),
            controller_receipts=self._receipts(),
            verifier=FakeVerifier(_observation(RemoteOutcome.INDETERMINATE)),
        )
        self.assertEqual(result.evaluation.status, Status.UNVERIFIED)

    def test_match_uses_existing_evaluator_and_source_claim_flag(self) -> None:
        claimed = evaluate_attempt(
            scenario_id="S0",
            contract=_contract(),
            source_claim=self._claim(True),
            controller_receipts=self._receipts(),
            verifier=FakeVerifier(_observation(RemoteOutcome.MATCH)),
        )
        silent = evaluate_attempt(
            scenario_id="S0",
            contract=_contract(),
            source_claim=self._claim(False),
            controller_receipts=self._receipts(),
            verifier=FakeVerifier(_observation(RemoteOutcome.MATCH)),
        )
        self.assertEqual(claimed.evaluation.status, Status.VERIFIED_COMPLETE)
        self.assertEqual(silent.evaluation.status, Status.VERIFIED_COMPLETE)

    def test_source_claim_must_be_sealed_model_before_verification(self) -> None:
        verifier = FakeVerifier(_observation(RemoteOutcome.MATCH))
        with self.assertRaises(ValueError):
            evaluate_attempt(
                scenario_id="S0",
                contract=_contract(),
                source_claim={"completion_claimed": True},  # type: ignore[arg-type]
                controller_receipts=self._receipts(),
                verifier=verifier,
            )
        self.assertEqual(verifier.calls, [])

    def test_receipts_must_be_controller_receipts_before_verification(self) -> None:
        verifier = FakeVerifier(_observation(RemoteOutcome.MATCH))
        with self.assertRaises(ValueError):
            evaluate_attempt(
                scenario_id="S0",
                contract=_contract(),
                source_claim=self._claim(),
                controller_receipts=({"success": True},),  # type: ignore[arg-type]
                verifier=verifier,
            )
        self.assertEqual(verifier.calls, [])

    def test_verifier_never_receives_controller_or_receipts(self) -> None:
        verifier = FakeVerifier(_observation(RemoteOutcome.MATCH))
        result = evaluate_attempt(
            scenario_id="S0",
            contract=_contract(),
            source_claim=self._claim(),
            controller_receipts=self._receipts(),
            verifier=verifier,
        )
        self.assertEqual(verifier.calls, [_contract()])
        self.assertEqual(len(result.controller_receipts), 3)

    def test_public_run_record_excludes_private_source_controller_and_contract_values(self) -> None:
        result = evaluate_attempt(
            scenario_id="S0",
            contract=_contract(),
            source_claim=self._claim(),
            controller_receipts=self._receipts(),
            verifier=FakeVerifier(_observation(RemoteOutcome.MATCH)),
        )
        public = result.to_public_dict()
        rendered = str(public)
        for forbidden in (
            "PRIVATE_OWNER",
            "PRIVATE_REPO",
            "PRIVATE_TRACE_SENTINEL",
            "PRIVATE_A",
            "PRIVATE_B",
            "PRIVATE_C",
            "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
        ):
            self.assertNotIn(forbidden, rendered)
        self.assertEqual(public["scenario_id"], "S0")
        self.assertEqual(public["remote_outcomes"], ["MATCH"])
        self.assertEqual(public["evaluation"]["status"], "VERIFIED_COMPLETE")

    def test_invalid_scenario_is_rejected_before_verifier(self) -> None:
        verifier = FakeVerifier(_observation(RemoteOutcome.MATCH))
        with self.assertRaises(ValueError):
            evaluate_attempt(
                scenario_id="UNKNOWN",
                contract=_contract(),
                source_claim=self._claim(),
                controller_receipts=self._receipts(),
                verifier=verifier,
            )
        self.assertEqual(verifier.calls, [])


if __name__ == "__main__":
    unittest.main()
