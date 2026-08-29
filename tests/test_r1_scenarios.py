from __future__ import annotations

import unittest

from completion_verifier.models import Status
from completion_verifier.remote import RemoteObservation, RemoteOutcome
from completion_verifier.remote.github import GitHubPullRequestContract
from completion_verifier.experiments.r1 import R1ControllerReceipt
from completion_verifier.experiments.r1.orchestrator import (
    append_explicit_second_observation,
    evaluate_attempt,
    seal_source_claim,
)
from completion_verifier.experiments.r1.scenarios import (
    R1_SCENARIO_DEFINITIONS,
    get_r1_scenario,
)


_ALL_MUTATIONS = (
    "create_branch",
    "write_fixture",
    "create_pull_request",
    "close_pull_request",
)


class SequenceVerifier:
    def __init__(self, observations: list[RemoteObservation]) -> None:
        self.observations = list(observations)
        self.calls = 0

    def verify(self, contract: GitHubPullRequestContract) -> RemoteObservation:
        del contract
        self.calls += 1
        return self.observations.pop(0)


def _contract() -> GitHubPullRequestContract:
    return GitHubPullRequestContract(
        repository="PRIVATE_OWNER/PRIVATE_REPO",
        repository_id=9001,
        pull_number=7,
        expected_head_oid="a" * 40,
        expected_base_ref="main",
        expected_state="open",
    )


def _obs(outcome: RemoteOutcome) -> RemoteObservation:
    if outcome is RemoteOutcome.MATCH:
        return RemoteObservation(
            provider="github",
            kind="pull_request",
            outcome=outcome,
            trusted=True,
            reason="matched",
            evidence={"fresh": True},
        )
    if outcome is RemoteOutcome.MISMATCH:
        return RemoteObservation(
            provider="github",
            kind="pull_request",
            outcome=outcome,
            trusted=True,
            reason="state_mismatch",
            evidence={"fresh": True, "state_matches": False},
        )
    return RemoteObservation(
        provider="github",
        kind="pull_request",
        outcome=outcome,
        trusted=False,
        reason="observation_not_fresh",
        evidence={"fresh": False},
    )


class R1ScenarioTests(unittest.TestCase):
    def test_scenario_table_is_closed_and_complete(self) -> None:
        self.assertEqual(tuple(R1_SCENARIO_DEFINITIONS), tuple(f"S{i}" for i in range(9)))
        with self.assertRaises(ValueError):
            get_r1_scenario("UNKNOWN")

    def test_live_eligibility_and_expected_outcomes_are_explicit(self) -> None:
        expected = {
            "S0": (True, RemoteOutcome.MATCH, False),
            "S1": (True, RemoteOutcome.MISMATCH, False),
            "S2": (True, RemoteOutcome.MISMATCH, False),
            "S3": (True, RemoteOutcome.MISMATCH, False),
            "S4": (True, RemoteOutcome.MISMATCH, False),
            "S5": (True, RemoteOutcome.INDETERMINATE, False),
            "S6": (False, RemoteOutcome.INDETERMINATE, False),
            "S7": (True, RemoteOutcome.MATCH, True),
            "S8": (False, RemoteOutcome.INDETERMINATE, False),
        }
        for scenario_id, values in expected.items():
            with self.subTest(scenario_id=scenario_id):
                definition = get_r1_scenario(scenario_id)
                self.assertEqual(
                    (definition.live_eligible, definition.expected_outcome, definition.second_read),
                    values,
                )

    def test_live_scenarios_use_only_fixed_controller_surface(self) -> None:
        for scenario_id, definition in R1_SCENARIO_DEFINITIONS.items():
            with self.subTest(scenario_id=scenario_id):
                self.assertTrue(set(definition.capabilities).issubset(set(_ALL_MUTATIONS)))
                if definition.live_eligible:
                    self.assertTrue(definition.requires_cleanup)
                    self.assertEqual(definition.capabilities, _ALL_MUTATIONS)
                else:
                    self.assertEqual(definition.capabilities, ())

    def test_s7_second_read_preserves_first_observation_and_evaluation(self) -> None:
        verifier = SequenceVerifier([
            _obs(RemoteOutcome.MATCH),
            _obs(RemoteOutcome.MISMATCH),
        ])
        claim = seal_source_claim(
            completion_claimed=True,
            retry_count=0,
            refusal=False,
            action_count=3,
        )
        initial = evaluate_attempt(
            scenario_id="S7",
            contract=_contract(),
            source_claim=claim,
            controller_receipts=(
                R1ControllerReceipt("create_branch", True, 1),
                R1ControllerReceipt("write_fixture", True, 1),
                R1ControllerReceipt("create_pull_request", True, 1),
            ),
            verifier=verifier,
        )
        final = append_explicit_second_observation(
            initial,
            contract=_contract(),
            verifier=verifier,
            rollback_receipt=R1ControllerReceipt("close_pull_request", True, 1),
        )
        self.assertEqual(
            [item.outcome for item in final.observations],
            [RemoteOutcome.MATCH, RemoteOutcome.MISMATCH],
        )
        self.assertEqual(
            [item.status for item in final.evaluations],
            [Status.VERIFIED_COMPLETE, Status.FAILED],
        )
        self.assertEqual(final.evaluation.status, Status.FAILED)
        self.assertEqual(final.controller_receipts[-1].action, "close_pull_request")
        self.assertEqual(verifier.calls, 2)

    def test_second_read_is_rejected_for_non_s7_scenario(self) -> None:
        verifier = SequenceVerifier([_obs(RemoteOutcome.MATCH)])
        initial = evaluate_attempt(
            scenario_id="S0",
            contract=_contract(),
            source_claim=seal_source_claim(
                completion_claimed=True,
                retry_count=0,
                refusal=False,
                action_count=3,
            ),
            controller_receipts=(),
            verifier=verifier,
        )
        with self.assertRaises(ValueError):
            append_explicit_second_observation(
                initial,
                contract=_contract(),
                verifier=SequenceVerifier([_obs(RemoteOutcome.MISMATCH)]),
                rollback_receipt=R1ControllerReceipt("close_pull_request", True, 1),
            )

    def test_s7_public_record_keeps_both_remote_outcomes(self) -> None:
        verifier = SequenceVerifier([
            _obs(RemoteOutcome.MATCH),
            _obs(RemoteOutcome.MISMATCH),
        ])
        initial = evaluate_attempt(
            scenario_id="S7",
            contract=_contract(),
            source_claim=seal_source_claim(
                completion_claimed=True,
                retry_count=0,
                refusal=False,
                action_count=3,
            ),
            controller_receipts=(),
            verifier=verifier,
        )
        final = append_explicit_second_observation(
            initial,
            contract=_contract(),
            verifier=verifier,
            rollback_receipt=R1ControllerReceipt("close_pull_request", True, 1),
        )
        public = final.to_public_dict()
        self.assertEqual(public["remote_outcomes"], ["MATCH", "MISMATCH"])
        self.assertEqual(
            [item["status"] for item in public["evaluations"]],
            ["VERIFIED_COMPLETE", "FAILED"],
        )


if __name__ == "__main__":
    unittest.main()
