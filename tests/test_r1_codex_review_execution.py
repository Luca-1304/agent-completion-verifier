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
    R1RunnerAbort,
    R1ScaffoldResult,
    ScriptedR1Scaffold,
    run_r1_live,
)
from completion_verifier.experiments.r1.scenarios import get_r1_scenario
from completion_verifier.remote import RemoteObservation, RemoteOutcome


REPO = "review-owner/disposable_repo"
REPO_ID = 93001
BASE = "a" * 40
WRITE = "b" * 40


def _config(scenario_id: str) -> R1ExperimentConfig:
    return R1ExperimentConfig(
        experiment_id=f"PRIVATE_{scenario_id}_EXECUTION_REVIEW",
        seed=31,
        repetitions=1,
        scenarios=(scenario_id,),
        treatment="baseline",
        scaffold_id="trusted-review-scaffold",
        scaffold_version="1",
        max_live_actions=4,
        live=True,
    )


def _attempt(scenario_id: str) -> R1PreparedAttempt:
    return R1PreparedAttempt(
        target=R1LiveTarget(REPO, REPO_ID),
        task=R1BoundedTask(
            scenario_id=scenario_id,
            base_oid=BASE,
            branch_name=f"r1-review-{scenario_id.lower()}",
            fixture_path=f"r1-fixtures/review/{scenario_id.lower()}/state.txt",
            fixture_content=f"PRIVATE_{scenario_id}_FIXTURE",
            base_ref="main",
        ),
        expectation=R1ContractExpectation(expected_state="open"),
    )


def _permit(scenario_id: str):
    definition = get_r1_scenario(scenario_id)
    result = run_preflight(
        R1PreflightRequest(
            live=True,
            dry_run=False,
            normal_ci=False,
            scenario_id=scenario_id,
            target=R1LiveTarget(REPO, REPO_ID),
            approved_repository_id=REPO_ID,
            target_locator_verified=True,
            protected_repository_ids=frozenset({999}),
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


class RecordingController:
    def __init__(self, *, fail_write: bool = False) -> None:
        self.fail_write = fail_write
        self.calls: list[tuple] = []

    def is_bound_to(self, target) -> bool:
        return target == R1LiveTarget(REPO, REPO_ID)

    def create_branch(self, base_oid, branch_name):
        self.calls.append(("create_branch", branch_name))
        return R1ControllerReceipt("create_branch", True, 1, private_object_oid=base_oid)

    def write_fixture(self, branch_name, relative_path, content, *, existing_blob_sha=None):
        del content, existing_blob_sha
        self.calls.append(("write_fixture", branch_name, relative_path))
        if self.fail_write:
            return R1ControllerReceipt(
                "write_fixture", False, 1, error_code="provider_unavailable"
            )
        return R1ControllerReceipt("write_fixture", True, 1, private_object_oid=WRITE)

    def create_pull_request(self, branch_name, base_ref):
        self.calls.append(("create_pull_request", branch_name, base_ref))
        return R1ControllerReceipt("create_pull_request", True, 1, private_pull_number=81)

    def close_pull_request(self, pull_number):
        self.calls.append(("close_pull_request", pull_number))
        return R1ControllerReceipt("close_pull_request", True, 1, private_pull_number=pull_number)


class MatchThenMismatchVerifier:
    def __init__(self) -> None:
        self.calls = 0

    def verify(self, contract):
        del contract
        self.calls += 1
        outcome = RemoteOutcome.MATCH if self.calls == 1 else RemoteOutcome.MISMATCH
        return RemoteObservation(
            provider="github",
            kind="pull_request",
            outcome=outcome,
            trusted=True,
            reason="matched" if outcome is RemoteOutcome.MATCH else "state_mismatch",
            evidence={"fresh": True},
        )


class CountingVerifier:
    def __init__(self) -> None:
        self.calls = 0

    def verify(self, contract):
        del contract
        self.calls += 1
        return RemoteObservation(
            provider="github",
            kind="pull_request",
            outcome=RemoteOutcome.MATCH,
            trusted=True,
            reason="matched",
            evidence={"fresh": True},
        )


class SelfClosingS7Scaffold:
    def run(self, task, controller):
        controller.create_branch(task.base_oid, task.branch_name)
        controller.write_fixture(task.branch_name, task.fixture_path, task.fixture_content)
        pull = controller.create_pull_request(task.branch_name, task.base_ref)
        assert pull.private_pull_number is not None
        controller.close_pull_request(pull.private_pull_number)
        return R1ScaffoldResult(completion_claimed=True)


class R1CodexReviewExecutionTests(unittest.TestCase):
    def test_s7_scaffold_cannot_consume_runner_owned_rollback(self) -> None:
        controller = RecordingController()
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaises(R1RunnerAbort) as raised:
                run_r1_live(
                    _config("S7"),
                    _permit("S7"),
                    controller,
                    MatchThenMismatchVerifier(),
                    Path(tmp) / "out",
                    attempts=(_attempt("S7"),),
                    scaffold=SelfClosingS7Scaffold(),
                    forbidden_literals=("PRIVATE_SENTINEL",),
                )
        self.assertEqual(raised.exception.reason_code, "action_not_allowed")
        self.assertEqual(
            [call[0] for call in controller.calls],
            ["create_branch", "write_fixture", "create_pull_request", "close_pull_request"],
        )

    def test_controller_failure_is_preserved_without_fabricating_remote_observation(self) -> None:
        controller = RecordingController(fail_write=True)
        verifier = CountingVerifier()
        with tempfile.TemporaryDirectory() as tmp:
            result = run_r1_live(
                _config("S0"),
                _permit("S0"),
                controller,
                verifier,
                Path(tmp) / "out",
                attempts=(_attempt("S0"),),
                scaffold=ScriptedR1Scaffold(),
                forbidden_literals=("PRIVATE_SENTINEL",),
            )
        self.assertTrue(result.manifest_verified)
        self.assertEqual(verifier.calls, 0)
        self.assertEqual(len(result.runs), 1)
        run = result.runs[0]
        self.assertEqual(run.observations, ())
        self.assertEqual(run.evaluations, ())
        self.assertIsNone(run.evaluation)
        self.assertEqual(result.metrics["preverification_abort_count"], 1)
        self.assertEqual(result.metrics["remote_observed_run_count"], 0)
        self.assertIsNone(result.metrics["remote_match_rate"])
        self.assertEqual(
            [receipt.to_public_dict() for receipt in run.controller_receipts][-1]["error_code"],
            "provider_unavailable",
        )


if __name__ == "__main__":
    unittest.main()
