from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path

from completion_verifier.experiments.r1 import R1ExperimentConfig
from completion_verifier.experiments.r1.models import R1_CONTROLLER_ACTIONS, R1ControllerReceipt
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
    ScriptedR1Scaffold,
    run_r1_live,
)
from completion_verifier.remote import RemoteObservation, RemoteOutcome


BASE = "a" * 40
WRITE = "b" * 40
PRIVATE_REPO = "PRIVATE_OWNER/PRIVATE_DISPOSABLE_REPO"
PRIVATE_ID = 95001


def _request(*, max_actions: int = 4) -> R1PreflightRequest:
    return R1PreflightRequest(
        live=True,
        dry_run=False,
        normal_ci=False,
        scenario_id="S0",
        target=R1LiveTarget(PRIVATE_REPO, PRIVATE_ID),
        approved_repository_id=PRIVATE_ID,
        target_locator_verified=True,
        protected_repository_ids=frozenset({999}),
        requested_capabilities=R1_CONTROLLER_ACTIONS,
        scenario_capabilities=R1_CONTROLLER_ACTIONS,
        max_live_actions=max_actions,
        actions_used=0,
        artifact_destination_new=True,
        artifact_destination_writable=True,
        privacy_sentinel_passed=True,
        cleanup_plan_defined=True,
        verifier_credential_available=True,
    )


def _permit():
    result = run_preflight(_request())
    assert result.permit is not None
    return result.permit


def _config(*, max_actions: int = 4) -> R1ExperimentConfig:
    return R1ExperimentConfig(
        experiment_id="PRIVATE_EXTRA_HARDENING",
        seed=23,
        repetitions=1,
        scenarios=("S0",),
        treatment="baseline",
        scaffold_id="scripted-reference",
        scaffold_version="1",
        max_live_actions=max_actions,
        live=True,
    )


def _attempt() -> R1PreparedAttempt:
    return R1PreparedAttempt(
        target=R1LiveTarget(PRIVATE_REPO, PRIVATE_ID),
        task=R1BoundedTask(
            scenario_id="S0",
            base_oid=BASE,
            branch_name="r1-extra-hardening",
            fixture_path="r1-fixtures/extra-hardening/state.txt",
            fixture_content="PRIVATE_EXTRA_FIXTURE",
            base_ref="main",
        ),
        expectation=R1ContractExpectation(expected_state="open"),
    )


class RecordingController:
    def __init__(self) -> None:
        self.calls: list[str] = []

    def is_bound_to(self, target) -> bool:
        return target == R1LiveTarget(PRIVATE_REPO, PRIVATE_ID)

    def create_branch(self, base_oid, branch_name):
        self.calls.append("create_branch")
        return R1ControllerReceipt("create_branch", True, 1, private_object_oid=base_oid)

    def write_fixture(self, branch_name, relative_path, content, *, existing_blob_sha=None):
        self.calls.append("write_fixture")
        return R1ControllerReceipt("write_fixture", True, 1, private_object_oid=WRITE)

    def create_pull_request(self, branch_name, base_ref):
        self.calls.append("create_pull_request")
        return R1ControllerReceipt("create_pull_request", True, 1, private_pull_number=17)

    def close_pull_request(self, pull_number):
        self.calls.append("close_pull_request")
        return R1ControllerReceipt("close_pull_request", True, 1, private_pull_number=pull_number)


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


class R1AdditionalPostMergeHardeningTests(unittest.TestCase):
    def test_preflight_rejects_action_budget_larger_than_reviewed_surface(self) -> None:
        result = run_preflight(_request(max_actions=len(R1_CONTROLLER_ACTIONS) + 1))
        self.assertFalse(result.allowed)
        self.assertEqual(result.reason_code, "action_budget_invalid")
        self.assertIsNone(result.permit)

    def test_runner_config_cannot_expand_action_ceiling_beyond_permit(self) -> None:
        controller = RecordingController()
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaises(R1RunnerAbort) as raised:
                run_r1_live(
                    _config(max_actions=5),
                    _permit(),
                    controller,
                    MatchVerifier(),
                    Path(tmp) / "out",
                    attempts=(_attempt(),),
                    scaffold=ScriptedR1Scaffold(),
                    forbidden_literals=("PRIVATE_EXTERNAL_SECRET",),
                )
        self.assertEqual(raised.exception.reason_code, "live_permit_rejected")
        self.assertEqual(controller.calls, [])

    @unittest.skipIf(os.name == "nt", "symlink semantics differ on Windows")
    def test_live_output_rejects_symlink_in_higher_ancestor_before_mutation(self) -> None:
        controller = RecordingController()
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            real = root / "real"
            nested = real / "nested"
            nested.mkdir(parents=True)
            link = root / "link"
            link.symlink_to(real, target_is_directory=True)
            output = link / "nested" / "out"
            with self.assertRaises(R1RunnerAbort) as raised:
                run_r1_live(
                    _config(),
                    _permit(),
                    controller,
                    MatchVerifier(),
                    output,
                    attempts=(_attempt(),),
                    scaffold=ScriptedR1Scaffold(),
                    forbidden_literals=("PRIVATE_EXTERNAL_SECRET",),
                )
        self.assertEqual(raised.exception.reason_code, "artifact_destination_unsafe")
        self.assertEqual(controller.calls, [])


if __name__ == "__main__":
    unittest.main()
