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
    ScriptedR1Scaffold,
    run_r1_live,
)
from completion_verifier.experiments.r1.scenarios import get_r1_scenario
from completion_verifier.remote import RemoteObservation, RemoteOutcome


TARGET = R1LiveTarget("safe-owner/output-gate", 66221)
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
        return R1ControllerReceipt("create_pull_request", True, 1, private_pull_number=41)

    def close_pull_request(self, pull_number):
        self.calls.append("close_pull_request")
        return R1ControllerReceipt("close_pull_request", True, 1, private_pull_number=pull_number)


class Verifier:
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


class OutputGateTests(unittest.TestCase):
    def test_nonempty_actual_output_directory_is_rejected_before_any_live_action(self) -> None:
        config = R1ExperimentConfig(
            experiment_id="PRIVATE_OUTPUT_GATE",
            seed=5,
            repetitions=1,
            scenarios=("S0",),
            treatment="baseline",
            scaffold_id="output-review",
            scaffold_version="1",
            max_live_actions=4,
            live=True,
        )
        attempt = R1PreparedAttempt(
            target=TARGET,
            task=R1BoundedTask(
                scenario_id="S0",
                base_oid=BASE,
                branch_name="r1-output-gate",
                fixture_path="r1-fixtures/output/gate.txt",
                fixture_content="private-output-gate",
                base_ref="main",
            ),
            expectation=R1ContractExpectation(expected_state="open"),
        )
        controller = Controller()
        with tempfile.TemporaryDirectory() as tmp:
            output = Path(tmp) / "out"
            output.mkdir()
            (output / "already-here.txt").write_text("occupied", encoding="utf-8")
            with self.assertRaises(Exception):
                run_r1_live(
                    config,
                    _permit(),
                    controller,
                    Verifier(),
                    output,
                    attempts=(attempt,),
                    scaffold=ScriptedR1Scaffold(),
                    forbidden_literals=("PRIVATE_EXTERNAL_SECRET",),
                )
        self.assertEqual(controller.calls, [])


if __name__ == "__main__":
    unittest.main()
