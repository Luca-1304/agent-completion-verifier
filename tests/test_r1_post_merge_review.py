from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from completion_verifier.experiments.r1 import R1ExperimentConfig
from completion_verifier.experiments.r1.models import R1ControllerReceipt
from completion_verifier.experiments.r1.preflight import (
    R1LiveTarget,
    R1PreflightRequest,
    run_preflight,
)
from completion_verifier.experiments.r1.runner import (
    R1BoundedTask,
    R1ContractExpectation,
    R1PreparedAttempt,
    R1RunnerAbort,
    R1ScaffoldResult,
    run_r1_live,
)
from completion_verifier.experiments.r1.scenarios import get_r1_scenario
from completion_verifier.remote import RemoteObservation, RemoteOutcome


REPOSITORY_ID = 99123
APPROVED = R1LiveTarget("safe-owner/approved-repo", REPOSITORY_ID)
SUBSTITUTED = R1LiveTarget("other-owner/other-repo", REPOSITORY_ID)
BASE = "a" * 40
WRITE = "b" * 40


def _permit():
    definition = get_r1_scenario("S0")
    result = run_preflight(
        R1PreflightRequest(
            live=True,
            dry_run=False,
            normal_ci=False,
            scenario_id="S0",
            target=APPROVED,
            approved_repository_id=REPOSITORY_ID,
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


class BoundController:
    def __init__(self, target: R1LiveTarget) -> None:
        self.target = target
        self.calls: list[str] = []

    def is_bound_to(self, target: R1LiveTarget) -> bool:
        return target == self.target

    def create_branch(self, base_oid, branch_name):
        self.calls.append("create_branch")
        return R1ControllerReceipt("create_branch", True, 1, private_object_oid=base_oid)

    def write_fixture(self, branch_name, relative_path, content, *, existing_blob_sha=None):
        self.calls.append("write_fixture")
        return R1ControllerReceipt("write_fixture", True, 1, private_object_oid=WRITE)

    def create_pull_request(self, branch_name, base_ref):
        self.calls.append("create_pull_request")
        return R1ControllerReceipt("create_pull_request", True, 1, private_pull_number=11)

    def close_pull_request(self, pull_number):
        self.calls.append("close_pull_request")
        return R1ControllerReceipt("close_pull_request", True, 1, private_pull_number=pull_number)


class Scaffold:
    def run(self, task, controller):
        controller.create_branch(task.base_oid, task.branch_name)
        controller.write_fixture(task.branch_name, task.fixture_path, task.fixture_content)
        controller.create_pull_request(task.branch_name, task.base_ref)
        return R1ScaffoldResult(completion_claimed=True)


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


class PostMergeReviewTests(unittest.TestCase):
    def test_same_repository_id_cannot_substitute_a_different_locator(self) -> None:
        config = R1ExperimentConfig(
            experiment_id="PRIVATE_TARGET_BINDING",
            seed=1,
            repetitions=1,
            scenarios=("S0",),
            treatment="baseline",
            scaffold_id="test",
            scaffold_version="1",
            max_live_actions=4,
            live=True,
        )
        attempt = R1PreparedAttempt(
            target=SUBSTITUTED,
            task=R1BoundedTask(
                scenario_id="S0",
                base_oid=BASE,
                branch_name="r1-target-binding",
                fixture_path="r1-fixtures/target-binding/state.txt",
                fixture_content="private-target-binding",
                base_ref="main",
            ),
            expectation=R1ContractExpectation(expected_state="open"),
        )
        controller = BoundController(SUBSTITUTED)
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaises(R1RunnerAbort) as raised:
                run_r1_live(
                    config,
                    _permit(),
                    controller,
                    MatchVerifier(),
                    Path(tmp) / "out",
                    attempts=(attempt,),
                    scaffold=Scaffold(),
                    forbidden_literals=("PRIVATE_TARGET_BINDING_SENTINEL",),
                )
        self.assertEqual(raised.exception.reason_code, "live_permit_rejected")
        self.assertEqual(controller.calls, [])


if __name__ == "__main__":
    unittest.main()
