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


TARGET = R1LiveTarget("safe-owner/controller-failure", 55221)
BASE = "a" * 40


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


class WriteFailingController:
    def __init__(self) -> None:
        self.calls: list[str] = []

    def is_bound_to(self, target) -> bool:
        return target == TARGET

    def create_branch(self, base_oid, branch_name):
        self.calls.append("create_branch")
        return R1ControllerReceipt("create_branch", True, 1, private_object_oid=base_oid)

    def write_fixture(self, branch_name, relative_path, content, *, existing_blob_sha=None):
        self.calls.append("write_fixture")
        return R1ControllerReceipt(
            "write_fixture", False, 1, error_code="provider_unavailable"
        )

    def create_pull_request(self, branch_name, base_ref):
        raise AssertionError("PR creation must not follow failed fixture write")

    def close_pull_request(self, pull_number):
        raise AssertionError("No PR exists to close")


class VerifierMustNotRun:
    def verify(self, contract):
        raise AssertionError("Unaddressable controller failure must not fabricate a remote read")


class ControllerFailureRecordingTests(unittest.TestCase):
    def test_normal_controller_failure_is_retained_as_unobserved_aborted_run(self) -> None:
        config = R1ExperimentConfig(
            experiment_id="PRIVATE_CONTROLLER_FAILURE",
            seed=6,
            repetitions=1,
            scenarios=("S0",),
            treatment="baseline",
            scaffold_id="controller-failure",
            scaffold_version="1",
            max_live_actions=4,
            live=True,
        )
        attempt = R1PreparedAttempt(
            target=TARGET,
            task=R1BoundedTask(
                scenario_id="S0",
                base_oid=BASE,
                branch_name="r1-controller-failure",
                fixture_path="r1-fixtures/controller/failure.txt",
                fixture_content="private-controller-failure",
                base_ref="main",
            ),
            expectation=R1ContractExpectation(expected_state="open"),
        )
        with tempfile.TemporaryDirectory() as tmp:
            result = run_r1_live(
                config,
                _permit(),
                WriteFailingController(),
                VerifierMustNotRun(),
                Path(tmp) / "out",
                attempts=(attempt,),
                scaffold=ScriptedR1Scaffold(),
                forbidden_literals=("PRIVATE_EXTERNAL_SECRET",),
            )
        self.assertEqual(len(result.runs), 1)
        run = result.runs[0]
        self.assertEqual(run.abort_reason, "controller_failed_before_verification")
        self.assertEqual(run.observations, ())
        self.assertEqual(run.evaluations, ())
        self.assertFalse(run.source_claim.completion_claimed)
        self.assertEqual([r.action for r in run.controller_receipts], ["create_branch", "write_fixture"])
        self.assertEqual(result.metrics["unobserved_run_count"], 1)
        self.assertTrue(result.manifest_verified)


if __name__ == "__main__":
    unittest.main()
