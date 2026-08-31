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
    ScriptedR1Scaffold,
    run_r1_live,
)
from completion_verifier.experiments.r1.scenarios import get_r1_scenario
from completion_verifier.remote import RemoteObservation, RemoteOutcome


BASE = "a" * 40
WRITE = "b" * 40
PRIVATE_REPO = "PRIVATE_OWNER/PRIVATE_DISPOSABLE_REPO"
PRIVATE_ID = 92001


def _config() -> R1ExperimentConfig:
    return R1ExperimentConfig(
        experiment_id="PRIVATE_CODEX_REVIEW_R2",
        seed=17,
        repetitions=1,
        scenarios=("S0",),
        treatment="baseline",
        scaffold_id="scripted-reference",
        scaffold_version="1",
        max_live_actions=4,
        live=True,
    )


def _permit():
    definition = get_r1_scenario("S0")
    result = run_preflight(
        R1PreflightRequest(
            live=True,
            dry_run=False,
            normal_ci=False,
            scenario_id="S0",
            target=R1LiveTarget(PRIVATE_REPO, PRIVATE_ID),
            approved_repository_id=PRIVATE_ID,
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


def _attempt(target: R1LiveTarget | None = None) -> R1PreparedAttempt:
    return R1PreparedAttempt(
        target=target or R1LiveTarget(PRIVATE_REPO, PRIVATE_ID),
        task=R1BoundedTask(
            scenario_id="S0",
            base_oid=BASE,
            branch_name="r1-codex-review-r2",
            fixture_path="r1-fixtures/codex-review-r2/state.txt",
            fixture_content="PRIVATE_CODEX_REVIEW_FIXTURE",
            base_ref="main",
        ),
        expectation=R1ContractExpectation(expected_state="open"),
    )


class RecordingController:
    def __init__(self, target: R1LiveTarget | None = None) -> None:
        self.target = target or R1LiveTarget(PRIVATE_REPO, PRIVATE_ID)
        self.calls: list[tuple[object, ...]] = []

    def is_bound_to(self, target: R1LiveTarget) -> bool:
        return target == self.target

    def create_branch(self, base_oid: str, branch_name: str) -> R1ControllerReceipt:
        self.calls.append(("create_branch", base_oid, branch_name))
        return R1ControllerReceipt("create_branch", True, 1, private_object_oid=base_oid)

    def write_fixture(
        self,
        branch_name: str,
        relative_path: str,
        content: str,
        *,
        existing_blob_sha: str | None = None,
    ) -> R1ControllerReceipt:
        self.calls.append(("write_fixture", branch_name, relative_path, content, existing_blob_sha))
        return R1ControllerReceipt("write_fixture", True, 1, private_object_oid=WRITE)

    def create_pull_request(self, branch_name: str, base_ref: str) -> R1ControllerReceipt:
        self.calls.append(("create_pull_request", branch_name, base_ref))
        return R1ControllerReceipt("create_pull_request", True, 1, private_pull_number=77)

    def close_pull_request(self, pull_number: int) -> R1ControllerReceipt:
        self.calls.append(("close_pull_request", pull_number))
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


class DelegateEscapeScaffold:
    def run(self, task, controller):
        # A live caller-supplied in-process scaffold must never receive a
        # credential-bearing provider delegate. The first pilot accepts only
        # the built-in scripted scaffold until a real process/RPC boundary exists.
        controller._delegate.create_branch(task.base_oid, "r1-escaped-directly")
        return R1ScaffoldResult(completion_claimed=False)


class R1CodexReviewRound2TrustTests(unittest.TestCase):
    def test_live_permit_binds_verified_locator_not_only_numeric_repository_id(self) -> None:
        substituted = R1LiveTarget("OTHER_OWNER/OTHER_DISPOSABLE_REPO", PRIVATE_ID)
        controller = RecordingController(substituted)
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaises(R1RunnerAbort) as raised:
                run_r1_live(
                    _config(),
                    _permit(),
                    controller,
                    MatchVerifier(),
                    Path(tmp) / "out",
                    attempts=(_attempt(substituted),),
                    scaffold=ScriptedR1Scaffold(),
                    forbidden_literals=("PRIVATE_EXTERNAL_SECRET",),
                )
        self.assertEqual(raised.exception.reason_code, "live_permit_rejected")
        self.assertEqual(controller.calls, [])

    def test_live_permit_is_single_use_across_sequential_runner_invocations(self) -> None:
        permit = _permit()
        with tempfile.TemporaryDirectory() as tmp:
            first = RecordingController()
            result = run_r1_live(
                _config(),
                permit,
                first,
                MatchVerifier(),
                Path(tmp) / "one",
                attempts=(_attempt(),),
                scaffold=ScriptedR1Scaffold(),
                forbidden_literals=("PRIVATE_EXTERNAL_SECRET",),
            )
            self.assertTrue(result.manifest_verified)

            second = RecordingController()
            with self.assertRaises(R1RunnerAbort) as raised:
                run_r1_live(
                    _config(),
                    permit,
                    second,
                    MatchVerifier(),
                    Path(tmp) / "two",
                    attempts=(_attempt(),),
                    scaffold=ScriptedR1Scaffold(),
                    forbidden_literals=("PRIVATE_EXTERNAL_SECRET",),
                )
        self.assertEqual(raised.exception.reason_code, "live_permit_rejected")
        self.assertEqual(second.calls, [])

    def test_live_runner_rejects_caller_supplied_in_process_scaffold_before_mutation(self) -> None:
        controller = RecordingController()
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaises(R1RunnerAbort) as raised:
                run_r1_live(
                    _config(),
                    _permit(),
                    controller,
                    MatchVerifier(),
                    Path(tmp) / "out",
                    attempts=(_attempt(),),
                    scaffold=DelegateEscapeScaffold(),
                    forbidden_literals=("PRIVATE_EXTERNAL_SECRET",),
                )
        self.assertEqual(raised.exception.reason_code, "scaffold_invalid")
        self.assertEqual(controller.calls, [])


if __name__ == "__main__":
    unittest.main()
