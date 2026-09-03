from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from completion_verifier.experiments.r1 import R1ExperimentConfig
from completion_verifier.experiments.r1.artifacts import verify_r1_manifest
from completion_verifier.experiments.r1.models import R1ControllerReceipt
from completion_verifier.experiments.r1.orchestrator import evaluate_attempt, seal_source_claim
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
from completion_verifier.remote import GitHubPullRequestContract, RemoteObservation, RemoteOutcome


BASE = "a" * 40
WRITE = "b" * 40
PRIVATE_REPO = "PRIVATE_OWNER/PRIVATE_DISPOSABLE_REPO"
PRIVATE_ID = 92001


def _config(*, scenario_id: str = "S0") -> R1ExperimentConfig:
    return R1ExperimentConfig(
        experiment_id="PRIVATE_FINAL_REVIEW_EXPERIMENT",
        seed=29,
        repetitions=1,
        scenarios=(scenario_id,),
        treatment="baseline",
        scaffold_id="final-review-scaffold",
        scaffold_version="1",
        max_live_actions=4,
        live=True,
    )


def _attempt(*, scenario_id: str = "S0") -> R1PreparedAttempt:
    return R1PreparedAttempt(
        target=R1LiveTarget(PRIVATE_REPO, PRIVATE_ID),
        task=R1BoundedTask(
            scenario_id=scenario_id,
            base_oid=BASE,
            branch_name=f"r1-final-{scenario_id.lower()}",
            fixture_path=f"r1-fixtures/final/{scenario_id.lower()}/state.txt",
            fixture_content=f"private-final-{scenario_id}",
            base_ref="main",
        ),
        expectation=R1ContractExpectation(expected_state="open"),
    )


def _permit(*, scenario_id: str = "S0"):
    definition = get_r1_scenario(scenario_id)
    result = run_preflight(
        R1PreflightRequest(
            live=True,
            dry_run=False,
            normal_ci=False,
            scenario_id=scenario_id,
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


class RecordingController:
    def __init__(self) -> None:
        self.calls: list[tuple] = []
        self.pull_number = 17

    def is_bound_to(self, target) -> bool:
        return target == R1LiveTarget(PRIVATE_REPO, PRIVATE_ID)

    def create_branch(self, base_oid, branch_name):
        self.calls.append(("create_branch", base_oid, branch_name))
        return R1ControllerReceipt(
            "create_branch", True, 1, private_object_oid=base_oid
        )

    def write_fixture(self, branch_name, relative_path, content, *, existing_blob_sha=None):
        self.calls.append(("write_fixture", branch_name, relative_path, content, existing_blob_sha))
        return R1ControllerReceipt(
            "write_fixture", True, 1, private_object_oid=WRITE
        )

    def create_pull_request(self, branch_name, base_ref):
        self.calls.append(("create_pull_request", branch_name, base_ref))
        return R1ControllerReceipt(
            "create_pull_request", True, 1, private_pull_number=self.pull_number
        )

    def close_pull_request(self, pull_number):
        self.calls.append(("close_pull_request", pull_number))
        return R1ControllerReceipt(
            "close_pull_request", True, 1, private_pull_number=pull_number
        )


class FailWriteController(RecordingController):
    def write_fixture(self, branch_name, relative_path, content, *, existing_blob_sha=None):
        self.calls.append(("write_fixture", branch_name, relative_path, content, existing_blob_sha))
        return R1ControllerReceipt(
            "write_fixture", False, 1, error_code="provider_unavailable"
        )


class MatchVerifier:
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


class S7SelfClosingScaffold:
    def run(self, task, controller):
        controller.create_branch(task.base_oid, task.branch_name)
        controller.write_fixture(task.branch_name, task.fixture_path, task.fixture_content)
        pull = controller.create_pull_request(task.branch_name, task.base_ref)
        assert pull.private_pull_number is not None
        controller.close_pull_request(pull.private_pull_number)
        return R1ScaffoldResult(completion_claimed=True)


class R1FinalReviewWaveATests(unittest.TestCase):
    def _completed_result(self, root: Path):
        return run_r1_live(
            _config(),
            _permit(),
            RecordingController(),
            MatchVerifier(),
            root / "out",
            attempts=(_attempt(),),
            scaffold=ScriptedR1Scaffold(),
            forbidden_literals=("PRIVATE_EXTERNAL_SECRET_SENTINEL",),
        )

    def test_manifest_rejects_nested_untracked_artifact_files(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            result = self._completed_result(Path(tmp))
            nested = result.output_dir / "raw"
            nested.mkdir()
            (nested / "provider.json").write_text("private", encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "untracked"):
                verify_r1_manifest(result.output_dir)

    def test_manifest_validates_public_config_digest_against_config_json(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            result = self._completed_result(Path(tmp))
            manifest_path = result.output_dir / "manifest.json"
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            manifest["public_config_digest"] = "0" * 64
            manifest_path.write_text(
                json.dumps(manifest, sort_keys=True, separators=(",", ":")) + "\n",
                encoding="utf-8",
            )
            with self.assertRaisesRegex(ValueError, "config digest"):
                verify_r1_manifest(result.output_dir)

    def test_evaluate_attempt_records_measured_verifier_latency(self) -> None:
        contract = GitHubPullRequestContract(
            repository=PRIVATE_REPO,
            repository_id=PRIVATE_ID,
            pull_number=17,
            expected_head_oid=WRITE,
            expected_head_repository_id=PRIVATE_ID,
            expected_base_ref="main",
            expected_state="open",
        )
        claim = seal_source_claim(
            completion_claimed=True,
            retry_count=0,
            refusal=False,
            action_count=0,
        )
        with patch(
            "completion_verifier.experiments.r1.orchestrator.time.perf_counter_ns",
            side_effect=(1_000_000, 3_500_000),
        ):
            run = evaluate_attempt(
                scenario_id="S0",
                contract=contract,
                source_claim=claim,
                controller_receipts=(),
                verifier=MatchVerifier(),
            )
        self.assertEqual(run.verification_latency_ms, (2.5,))

    def test_live_permit_is_single_use_across_invocations(self) -> None:
        permit = _permit()
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            first = run_r1_live(
                _config(),
                permit,
                RecordingController(),
                MatchVerifier(),
                root / "first",
                attempts=(_attempt(),),
                scaffold=ScriptedR1Scaffold(),
                forbidden_literals=("PRIVATE_EXTERNAL_SECRET_SENTINEL",),
            )
            self.assertTrue(first.manifest_verified)
            second_controller = RecordingController()
            with self.assertRaises(R1RunnerAbort) as raised:
                run_r1_live(
                    _config(),
                    permit,
                    second_controller,
                    MatchVerifier(),
                    root / "second",
                    attempts=(_attempt(),),
                    scaffold=ScriptedR1Scaffold(),
                    forbidden_literals=("PRIVATE_EXTERNAL_SECRET_SENTINEL",),
                )
        self.assertEqual(raised.exception.reason_code, "live_permit_rejected")
        self.assertEqual(second_controller.calls, [])

    def test_nonempty_output_directory_is_rejected_before_live_mutation(self) -> None:
        controller = RecordingController()
        with tempfile.TemporaryDirectory() as tmp:
            output = Path(tmp) / "out"
            output.mkdir()
            (output / "already-there.txt").write_text("x", encoding="utf-8")
            with self.assertRaises(R1RunnerAbort) as raised:
                run_r1_live(
                    _config(),
                    _permit(),
                    controller,
                    MatchVerifier(),
                    output,
                    attempts=(_attempt(),),
                    scaffold=ScriptedR1Scaffold(),
                    forbidden_literals=("PRIVATE_EXTERNAL_SECRET_SENTINEL",),
                )
        self.assertEqual(raised.exception.reason_code, "artifact_destination_unsafe")
        self.assertEqual(controller.calls, [])

    def test_s7_scaffold_cannot_consume_runner_reserved_cleanup(self) -> None:
        controller = RecordingController()
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaises(R1RunnerAbort) as raised:
                run_r1_live(
                    _config(scenario_id="S7"),
                    _permit(scenario_id="S7"),
                    controller,
                    MatchVerifier(),
                    Path(tmp) / "out",
                    attempts=(_attempt(scenario_id="S7"),),
                    scaffold=S7SelfClosingScaffold(),
                    forbidden_literals=("PRIVATE_EXTERNAL_SECRET_SENTINEL",),
                )
        self.assertEqual(raised.exception.reason_code, "action_not_allowed")
        self.assertEqual(
            [call[0] for call in controller.calls],
            ["create_branch", "write_fixture", "create_pull_request", "close_pull_request"],
        )

    def test_ordinary_controller_failure_is_persisted_as_aborted_run(self) -> None:
        verifier = MatchVerifier()
        with tempfile.TemporaryDirectory() as tmp:
            result = run_r1_live(
                _config(),
                _permit(),
                FailWriteController(),
                verifier,
                Path(tmp) / "out",
                attempts=(_attempt(),),
                scaffold=ScriptedR1Scaffold(),
                forbidden_literals=("PRIVATE_EXTERNAL_SECRET_SENTINEL",),
            )
            run = result.runs[0]
            self.assertEqual(run.aborted_reason_code, "contract_unaddressable")
            self.assertEqual(run.observations, ())
            self.assertEqual(run.evaluations, ())
            self.assertTrue(result.manifest_verified)
            self.assertEqual(result.metrics.get("aborted_run_count"), 1)
        self.assertEqual(verifier.calls, 0)


if __name__ == "__main__":
    unittest.main()
