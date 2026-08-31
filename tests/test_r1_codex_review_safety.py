from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from completion_verifier.experiments.r1 import R1ExperimentConfig
from completion_verifier.experiments.r1.models import R1ControllerReceipt
from completion_verifier.experiments.r1.preflight import R1LiveTarget, R1PreflightRequest, run_preflight
from completion_verifier.experiments.r1.runner import (
    R1BoundedTask, R1ContractExpectation, R1PreparedAttempt, R1RunnerAbort,
    ScriptedR1Scaffold, run_r1_live,
)
from completion_verifier.experiments.r1.scenarios import get_r1_scenario
from completion_verifier.remote import RemoteObservation, RemoteOutcome

BASE = "a" * 40
WRITE = "b" * 40
APPROVED_REPO = "approved-owner/disposable_repo"
SUBSTITUTED_REPO = "other-owner/disposable_repo"
REPO_ID = 92001


def _config() -> R1ExperimentConfig:
    return R1ExperimentConfig(
        experiment_id="PRIVATE_CODEX_SAFETY", seed=17, repetitions=1,
        scenarios=("S0",), treatment="baseline", scaffold_id="trusted-scripted",
        scaffold_version="1", max_live_actions=4, live=True,
    )


def _attempt(locator: str = APPROVED_REPO) -> R1PreparedAttempt:
    return R1PreparedAttempt(
        target=R1LiveTarget(locator, REPO_ID),
        task=R1BoundedTask(
            scenario_id="S0", base_oid=BASE, branch_name="r1-codex-safety",
            fixture_path="r1-fixtures/codex/safety.txt",
            fixture_content="PRIVATE_CODEX_FIXTURE", base_ref="main",
        ),
        expectation=R1ContractExpectation(expected_state="open"),
    )


def _permit():
    definition = get_r1_scenario("S0")
    result = run_preflight(R1PreflightRequest(
        live=True, dry_run=False, normal_ci=False, scenario_id="S0",
        target=R1LiveTarget(APPROVED_REPO, REPO_ID), approved_repository_id=REPO_ID,
        target_locator_verified=True, protected_repository_ids=frozenset({999}),
        requested_capabilities=definition.capabilities,
        scenario_capabilities=definition.capabilities, max_live_actions=4, actions_used=0,
        artifact_destination_new=True, artifact_destination_writable=True,
        privacy_sentinel_passed=True, cleanup_plan_defined=True,
        verifier_credential_available=True,
    ))
    assert result.permit is not None
    return result.permit


class RecordingController:
    def __init__(self, locator: str = APPROVED_REPO) -> None:
        self.locator = locator
        self.calls: list[tuple] = []
    def is_bound_to(self, target) -> bool:
        return target == R1LiveTarget(self.locator, REPO_ID)
    def create_branch(self, base_oid, branch_name):
        self.calls.append(("create_branch", base_oid, branch_name))
        return R1ControllerReceipt("create_branch", True, 1, private_object_oid=base_oid)
    def write_fixture(self, branch_name, relative_path, content, *, existing_blob_sha=None):
        self.calls.append(("write_fixture", branch_name, relative_path))
        return R1ControllerReceipt("write_fixture", True, 1, private_object_oid=WRITE)
    def create_pull_request(self, branch_name, base_ref):
        self.calls.append(("create_pull_request", branch_name, base_ref))
        return R1ControllerReceipt("create_pull_request", True, 1, private_pull_number=71)
    def close_pull_request(self, pull_number):
        self.calls.append(("close_pull_request", pull_number))
        return R1ControllerReceipt("close_pull_request", True, 1, private_pull_number=pull_number)


class MatchVerifier:
    def verify(self, contract):
        del contract
        return RemoteObservation(
            provider="github", kind="pull_request", outcome=RemoteOutcome.MATCH,
            trusted=True, reason="matched", evidence={"fresh": True},
        )


class R1CodexReviewSafetyTests(unittest.TestCase):
    def test_permit_rejects_same_numeric_id_with_different_locator(self) -> None:
        controller = RecordingController(SUBSTITUTED_REPO)
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaises(R1RunnerAbort) as raised:
                run_r1_live(
                    _config(), _permit(), controller, MatchVerifier(), Path(tmp) / "out",
                    attempts=(_attempt(SUBSTITUTED_REPO),), scaffold=ScriptedR1Scaffold(),
                    forbidden_literals=("PRIVATE_SENTINEL",),
                )
        self.assertEqual(raised.exception.reason_code, "live_permit_rejected")
        self.assertEqual(controller.calls, [])

    def test_live_permit_is_single_use_across_sequential_invocations(self) -> None:
        permit = _permit()
        controller = RecordingController()
        with tempfile.TemporaryDirectory() as tmp:
            first = run_r1_live(
                _config(), permit, controller, MatchVerifier(), Path(tmp) / "first",
                attempts=(_attempt(),), scaffold=ScriptedR1Scaffold(),
                forbidden_literals=("PRIVATE_SENTINEL",),
            )
            self.assertTrue(first.manifest_verified)
            with self.assertRaises(R1RunnerAbort) as raised:
                run_r1_live(
                    _config(), permit, RecordingController(), MatchVerifier(), Path(tmp) / "second",
                    attempts=(_attempt(),), scaffold=ScriptedR1Scaffold(),
                    forbidden_literals=("PRIVATE_SENTINEL",),
                )
        self.assertEqual(raised.exception.reason_code, "live_permit_consumed")

    def test_actual_output_destination_is_rejected_before_any_live_action(self) -> None:
        controller = RecordingController()
        with tempfile.TemporaryDirectory() as tmp:
            output = Path(tmp) / "out"
            output.mkdir()
            (output / "already-here.txt").write_text("occupied", encoding="utf-8")
            with self.assertRaises(FileExistsError):
                run_r1_live(
                    _config(), _permit(), controller, MatchVerifier(), output,
                    attempts=(_attempt(),), scaffold=ScriptedR1Scaffold(),
                    forbidden_literals=("PRIVATE_SENTINEL",),
                )
        self.assertEqual(controller.calls, [])


if __name__ == "__main__":
    unittest.main()
