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
PRIVATE_ID = 91001


def _config(*, repetitions: int = 1, max_actions: int = 4) -> R1ExperimentConfig:
    return R1ExperimentConfig(
        experiment_id="PRIVATE_REVIEW_EXPERIMENT",
        seed=11,
        repetitions=repetitions,
        scenarios=("S0",),
        treatment="baseline",
        scaffold_id="review-scaffold",
        scaffold_version="1",
        max_live_actions=max_actions,
        live=True,
    )


def _attempt(index: int = 1) -> R1PreparedAttempt:
    return R1PreparedAttempt(
        target=R1LiveTarget(PRIVATE_REPO, PRIVATE_ID),
        task=R1BoundedTask(
            scenario_id="S0",
            base_oid=BASE,
            branch_name=f"r1-review-{index}",
            fixture_path=f"r1-fixtures/review/{index}/state.txt",
            fixture_content=f"private-fixture-{index}",
            base_ref="main",
        ),
        expectation=R1ContractExpectation(expected_state="open"),
    )


def _permit(*, max_actions: int = 4):
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
            max_live_actions=max_actions,
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
    def __init__(self) -> None:
        self.calls: list[tuple] = []
        self.next_pull_number = 7

    def is_bound_to(self, target) -> bool:
        return target == R1LiveTarget(PRIVATE_REPO, PRIVATE_ID)

    def create_branch(self, base_oid, branch_name):
        self.calls.append(("create_branch", base_oid, branch_name))
        return R1ControllerReceipt(
            "create_branch", True, 1, private_object_oid=base_oid
        )

    def write_fixture(self, branch_name, relative_path, content, *, existing_blob_sha=None):
        self.calls.append(
            (
                "write_fixture",
                branch_name,
                relative_path,
                content,
                existing_blob_sha,
            )
        )
        return R1ControllerReceipt(
            "write_fixture", True, 1, private_object_oid=WRITE
        )

    def create_pull_request(self, branch_name, base_ref):
        number = self.next_pull_number
        self.next_pull_number += 1
        self.calls.append(("create_pull_request", branch_name, base_ref, number))
        return R1ControllerReceipt(
            "create_pull_request", True, 1, private_pull_number=number
        )

    def close_pull_request(self, pull_number):
        self.calls.append(("close_pull_request", pull_number))
        return R1ControllerReceipt(
            "close_pull_request", True, 1, private_pull_number=pull_number
        )


class CleanupFailingController(RecordingController):
    def close_pull_request(self, pull_number):
        self.calls.append(("close_pull_request", pull_number))
        return R1ControllerReceipt(
            "close_pull_request", False, 1, error_code="provider_unavailable"
        )


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


class RaisingVerifier:
    def __init__(self) -> None:
        self.error = RuntimeError("PRIVATE_VERIFIER_EXCEPTION")

    def verify(self, contract):
        del contract
        raise self.error


class AlternateBranchScaffold:
    def run(self, task, controller):
        controller.create_branch(task.base_oid, "r1-not-the-prepared-branch")
        return R1ScaffoldResult(completion_claimed=False)


class WrongPullCloseScaffold:
    def run(self, task, controller):
        controller.create_branch(task.base_oid, task.branch_name)
        controller.write_fixture(task.branch_name, task.fixture_path, task.fixture_content)
        controller.create_pull_request(task.branch_name, task.base_ref)
        controller.close_pull_request(999)
        return R1ScaffoldResult(completion_claimed=True)


class DuplicatePullScaffold:
    def run(self, task, controller):
        controller.create_branch(task.base_oid, task.branch_name)
        controller.write_fixture(task.branch_name, task.fixture_path, task.fixture_content)
        controller.create_pull_request(task.branch_name, task.base_ref)
        controller.create_pull_request(task.branch_name, task.base_ref)
        return R1ScaffoldResult(completion_claimed=True)


class R1AdversarialReviewTests(unittest.TestCase):
    def test_verifier_exception_after_pr_creation_still_closes_once_and_preserves_original_error(self) -> None:
        controller = RecordingController()
        verifier = RaisingVerifier()
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaises(RuntimeError) as raised:
                run_r1_live(
                    _config(),
                    _permit(),
                    controller,
                    verifier,
                    Path(tmp) / "out",
                    attempts=(_attempt(),),
                    scaffold=ScriptedR1Scaffold(),
                    forbidden_literals=("PRIVATE_REVIEW_SENTINEL",),
                )
        self.assertIs(raised.exception, verifier.error)
        self.assertEqual(
            [call[0] for call in controller.calls],
            ["create_branch", "write_fixture", "create_pull_request", "close_pull_request"],
        )
        self.assertEqual(controller.calls[-1], ("close_pull_request", 7))

    def test_failed_cleanup_is_headline_visible_in_metrics_and_report(self) -> None:
        controller = CleanupFailingController()
        with tempfile.TemporaryDirectory() as tmp:
            result = run_r1_live(
                _config(),
                _permit(),
                controller,
                MatchVerifier(),
                Path(tmp) / "out",
                attempts=(_attempt(),),
                scaffold=ScriptedR1Scaffold(),
                forbidden_literals=("PRIVATE_REVIEW_SENTINEL",),
            )
            self.assertEqual(result.metrics.get("cleanup_failure_count"), 1)
            report = (result.output_dir / "report.md").read_text(encoding="utf-8")
            self.assertIn("Cleanup failures: 1", report)

    def test_caller_defined_live_scaffold_cannot_change_prepared_branch(self) -> None:
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
                    scaffold=AlternateBranchScaffold(),
                    forbidden_literals=("PRIVATE_REVIEW_SENTINEL",),
                )
        self.assertEqual(raised.exception.reason_code, "live_scaffold_untrusted")
        self.assertEqual(controller.calls, [])

    def test_caller_defined_live_scaffold_cannot_close_any_pull_request(self) -> None:
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
                    scaffold=WrongPullCloseScaffold(),
                    forbidden_literals=("PRIVATE_REVIEW_SENTINEL",),
                )
        self.assertEqual(raised.exception.reason_code, "live_scaffold_untrusted")
        self.assertEqual(controller.calls, [])

    def test_caller_defined_live_scaffold_cannot_create_duplicate_pull_requests(self) -> None:
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
                    scaffold=DuplicatePullScaffold(),
                    forbidden_literals=("PRIVATE_REVIEW_SENTINEL",),
                )
        self.assertEqual(raised.exception.reason_code, "live_scaffold_untrusted")
        self.assertEqual(controller.calls, [])

    def test_initial_live_permit_cannot_authorize_multiple_repetitions(self) -> None:
        controller = RecordingController()
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaises(R1RunnerAbort) as raised:
                run_r1_live(
                    _config(repetitions=2),
                    _permit(),
                    controller,
                    MatchVerifier(),
                    Path(tmp) / "out",
                    attempts=(_attempt(1), _attempt(2)),
                    scaffold=ScriptedR1Scaffold(),
                    forbidden_literals=("PRIVATE_REVIEW_SENTINEL",),
                )
        self.assertEqual(raised.exception.reason_code, "live_repetition_limit")
        self.assertEqual(controller.calls, [])

    def test_live_execution_requires_at_least_one_explicit_privacy_sentinel(self) -> None:
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
                    scaffold=ScriptedR1Scaffold(),
                )
        self.assertEqual(raised.exception.reason_code, "privacy_sentinel_required")
        self.assertEqual(controller.calls, [])

    def test_live_privacy_scan_derives_actual_private_target_sentinels(self) -> None:
        leaky_config = R1ExperimentConfig(
            experiment_id="PRIVATE_REVIEW_EXPERIMENT",
            seed=11,
            repetitions=1,
            scenarios=("S0",),
            treatment="baseline",
            scaffold_id=PRIVATE_REPO,
            scaffold_version="1",
            max_live_actions=4,
            live=True,
        )
        controller = RecordingController()
        with tempfile.TemporaryDirectory() as tmp:
            output = Path(tmp) / "out"
            with self.assertRaisesRegex(ValueError, "privacy sentinel failed"):
                run_r1_live(
                    leaky_config,
                    _permit(),
                    controller,
                    MatchVerifier(),
                    output,
                    attempts=(_attempt(),),
                    scaffold=ScriptedR1Scaffold(),
                    forbidden_literals=("IRRELEVANT_CALLER_SENTINEL",),
                )
            self.assertTrue(output.is_dir())
            self.assertEqual(list(output.iterdir()), [])

    def test_live_target_locator_is_conservative_ascii_owner_repo_form(self) -> None:
        invalid = (
            "../repo",
            "owner/..",
            "./repo",
            "owner/.",
            "owner/re po",
            "owner/repo%2Fother",
            "owner/repo?x=1",
            "owner/repo#frag",
            "оwner/repo",
            "owner/rеpo",
        )
        for locator in invalid:
            with self.subTest(locator=locator), self.assertRaises(ValueError):
                R1LiveTarget(locator, 123)
        self.assertEqual(
            R1LiveTarget("safe-owner/safe_repo-1.0", 123).repository_locator,
            "safe-owner/safe_repo-1.0",
        )


if __name__ == "__main__":
    unittest.main()
