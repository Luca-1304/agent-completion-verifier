from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from completion_verifier.experiments.r1 import R1ExperimentConfig
from completion_verifier.experiments.r1.models import R1ControllerReceipt
from completion_verifier.experiments.r1.preflight import R1LiveTarget, R1PreflightRequest, run_preflight
from completion_verifier.experiments.r1.runner import (
    R1BoundedTask,
    R1ContractExpectation,
    R1PreparedAttempt,
    R1ScaffoldResult,
    run_r1_live,
)
from completion_verifier.experiments.r1.scenarios import get_r1_scenario
from completion_verifier.remote import RemoteObservation, RemoteOutcome


TARGET = R1LiveTarget("safe-owner/s7-repo", 77221)
BASE = "a" * 40
WRITE = "b" * 40


def _permit():
    definition = get_r1_scenario("S7")
    result = run_preflight(
        R1PreflightRequest(
            live=True,
            dry_run=False,
            normal_ci=False,
            scenario_id="S7",
            target=TARGET,
            approved_repository_id=TARGET.repository_id,
            target_locator_verified=True,
            protected_repository_ids=frozenset(),
            requested_capabilities=definition.capabilities,
            scenario_capabilities=definition.capabilities,
            max_live_actions=4,
            actions_used=0,
            artifact_destination_new=True,
            artifact_destination_writable=True,
            privacy_sentinel_passed=True,
            cleanup_plan_defined=True,
            verifier_credential_available=True,
        )
    )
    assert result.permit is not None
    return result.permit


class Controller:
    def __init__(self) -> None:
        self.calls: list[str] = []

    def is_bound_to(self, target) -> bool:
        return target == TARGET

    def create_branch(self, base_oid, branch_name):
        self.calls.append("create_branch")
        return R1ControllerReceipt("create_branch", True, 1, private_object_oid=base_oid)

    def write_fixture(self, branch_name, relative_path, content, *, existing_blob_sha=None):
        self.calls.append("write_fixture")
        return R1ControllerReceipt("write_fixture", True, 1, private_object_oid=WRITE)

    def create_pull_request(self, branch_name, base_ref):
        self.calls.append("create_pull_request")
        return R1ControllerReceipt("create_pull_request", True, 1, private_pull_number=31)

    def close_pull_request(self, pull_number):
        self.calls.append("close_pull_request")
        return R1ControllerReceipt("close_pull_request", True, 1, private_pull_number=pull_number)


class PrematureCloseScaffold:
    def run(self, task, controller):
        controller.create_branch(task.base_oid, task.branch_name)
        controller.write_fixture(task.branch_name, task.fixture_path, task.fixture_content)
        pull = controller.create_pull_request(task.branch_name, task.base_ref)
        assert pull.private_pull_number is not None
        controller.close_pull_request(pull.private_pull_number)
        return R1ScaffoldResult(completion_claimed=True)


class SequencedVerifier:
    def __init__(self) -> None:
        self.calls = 0

    def verify(self, contract):
        del contract
        self.calls += 1
        if self.calls == 1:
            return RemoteObservation(
                provider="github",
                kind="pull_request",
                outcome=RemoteOutcome.MATCH,
                trusted=True,
                reason="matched",
                evidence={"fresh": True},
            )
        return RemoteObservation(
            provider="github",
            kind="pull_request",
            outcome=RemoteOutcome.MISMATCH,
            trusted=True,
            reason="state_mismatch",
            evidence={"state_matches": False, "fresh": True},
        )


class S7OwnershipTests(unittest.TestCase):
    def test_scaffold_close_cannot_suppress_required_s7_second_read(self) -> None:
        config = R1ExperimentConfig(
            experiment_id="PRIVATE_S7_OWNERSHIP",
            seed=4,
            repetitions=1,
            scenarios=("S7",),
            treatment="baseline",
            scaffold_id="s7-review",
            scaffold_version="1",
            max_live_actions=4,
            live=True,
        )
        attempt = R1PreparedAttempt(
            target=TARGET,
            task=R1BoundedTask(
                scenario_id="S7",
                base_oid=BASE,
                branch_name="r1-s7-ownership",
                fixture_path="r1-fixtures/s7/ownership.txt",
                fixture_content="private-s7-ownership",
                base_ref="main",
            ),
            expectation=R1ContractExpectation(expected_state="open"),
        )
        verifier = SequencedVerifier()
        with tempfile.TemporaryDirectory() as tmp:
            result = run_r1_live(
                config,
                _permit(),
                Controller(),
                verifier,
                Path(tmp) / "out",
                attempts=(attempt,),
                scaffold=PrematureCloseScaffold(),
                forbidden_literals=("PRIVATE_EXTERNAL_SECRET",),
            )
        self.assertEqual(verifier.calls, 2)
        self.assertEqual(len(result.runs[0].observations), 2)
        self.assertEqual(
            [item.outcome for item in result.runs[0].observations],
            [RemoteOutcome.MATCH, RemoteOutcome.MISMATCH],
        )


if __name__ == "__main__":
    unittest.main()
