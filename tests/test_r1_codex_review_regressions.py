from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from completion_verifier.experiments.r1 import R1ExperimentConfig
from completion_verifier.experiments.r1.artifacts import verify_r1_manifest
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


def _config(scenario_id: str = "S0") -> R1ExperimentConfig:
    return R1ExperimentConfig(
        experiment_id=f"PRIVATE_CODEX_REVIEW_{scenario_id}",
        seed=19,
        repetitions=1,
        scenarios=(scenario_id,),
        treatment="baseline",
        scaffold_id="codex-review-scaffold",
        scaffold_version="1",
        max_live_actions=4,
        live=True,
    )


def _attempt(
    scenario_id: str = "S0",
    *,
    locator: str = PRIVATE_REPO,
    repository_id: int = PRIVATE_ID,
) -> R1PreparedAttempt:
    return R1PreparedAttempt(
        target=R1LiveTarget(locator, repository_id),
        task=R1BoundedTask(
            scenario_id=scenario_id,
            base_oid=BASE,
            branch_name=f"r1-codex-{scenario_id.lower()}",
            fixture_path=f"r1-fixtures/codex/{scenario_id.lower()}/state.txt",
            fixture_content=f"private-codex-{scenario_id.lower()}",
            base_ref="main",
        ),
        expectation=R1ContractExpectation(expected_state="open"),
    )


def _permit(scenario_id: str = "S0"):
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
    def __init__(self, target: R1LiveTarget | None = None) -> None:
        self.target = target or R1LiveTarget(PRIVATE_REPO, PRIVATE_ID)
        self.calls: list[tuple] = []
        self.next_pull_number = 41

    def is_bound_to(self, target) -> bool:
        return target == self.target

    def create_branch(self, base_oid, branch_name):
        self.calls.append(("create_branch", base_oid, branch_name))
        return R1ControllerReceipt("create_branch", True, 1, private_object_oid=base_oid)

    def write_fixture(self, branch_name, relative_path, content, *, existing_blob_sha=None):
        self.calls.append(("write_fixture", branch_name, relative_path, content, existing_blob_sha))
        return R1ControllerReceipt("write_fixture", True, 1, private_object_oid=WRITE)

    def create_pull_request(self, branch_name, base_ref):
        number = self.next_pull_number
        self.next_pull_number += 1
        self.calls.append(("create_pull_request", branch_name, base_ref, number))
        return R1ControllerReceipt("create_pull_request", True, 1, private_pull_number=number)

    def close_pull_request(self, pull_number):
        self.calls.append(("close_pull_request", pull_number))
        return R1ControllerReceipt("close_pull_request", True, 1, private_pull_number=pull_number)

    def reconcile_pull_request(self, branch_name, base_ref):
        self.calls.append(("reconcile_pull_request", branch_name, base_ref))
        return self.next_pull_number - 1


class WriteFailingController(RecordingController):
    def write_fixture(self, branch_name, relative_path, content, *, existing_blob_sha=None):
        self.calls.append(("write_fixture", branch_name, relative_path, content, existing_blob_sha))
        return R1ControllerReceipt(
            "write_fixture", False, 1, error_code="provider_unavailable"
        )


class AmbiguousPullController(RecordingController):
    def create_pull_request(self, branch_name, base_ref):
        self.calls.append(("create_pull_request", branch_name, base_ref, None))
        return R1ControllerReceipt(
            "create_pull_request",
            False,
            1,
            error_code="accepted_unaddressable",
            private_target_ref=branch_name,
        )

    def reconcile_pull_request(self, branch_name, base_ref):
        self.calls.append(("reconcile_pull_request", branch_name, base_ref))
        return 73


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


class SequenceVerifier:
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


class S7CloseAttemptScaffold:
    def run(self, task, controller):
        controller.create_branch(task.base_oid, task.branch_name)
        controller.write_fixture(task.branch_name, task.fixture_path, task.fixture_content)
        pull = controller.create_pull_request(task.branch_name, task.base_ref)
        try:
            controller.close_pull_request(pull.private_pull_number)
        except R1RunnerAbort as exc:
            if exc.reason_code != "action_not_allowed":
                raise
        return R1ScaffoldResult(completion_claimed=True)


class DelegateProbeScaffold:
    def __init__(self) -> None:
        self.delegate_visible = False

    def run(self, task, controller):
        self.delegate_visible = hasattr(controller, "_delegate")
        controller.create_branch(task.base_oid, task.branch_name)
        controller.write_fixture(task.branch_name, task.fixture_path, task.fixture_content)
        pull = controller.create_pull_request(task.branch_name, task.base_ref)
        return R1ScaffoldResult(completion_claimed=pull.success)


class R1CodexReviewRegressionTests(unittest.TestCase):
    def test_live_permit_binds_exact_verified_locator_not_only_numeric_id(self) -> None:
        substituted = "OTHER_OWNER/OTHER_DISPOSABLE_REPO"
        controller = RecordingController(R1LiveTarget(substituted, PRIVATE_ID))
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaises(R1RunnerAbort) as raised:
                run_r1_live(
                    _config(),
                    _permit(),
                    controller,
                    MatchVerifier(),
                    Path(tmp) / "out",
                    attempts=(_attempt(locator=substituted),),
                    scaffold=ScriptedR1Scaffold(),
                    forbidden_literals=("PRIVATE_SENTINEL",),
                )
        self.assertEqual(raised.exception.reason_code, "live_permit_rejected")
        self.assertEqual(controller.calls, [])

    def test_live_permit_is_single_use_across_sequential_invocations(self) -> None:
        permit = _permit()
        controller = RecordingController()
        with tempfile.TemporaryDirectory() as tmp:
            run_r1_live(
                _config(), permit, controller, MatchVerifier(), Path(tmp) / "first",
                attempts=(_attempt(),), scaffold=ScriptedR1Scaffold(),
                forbidden_literals=("PRIVATE_SENTINEL",),
            )
            first_call_count = len(controller.calls)
            with self.assertRaises(R1RunnerAbort) as raised:
                run_r1_live(
                    _config(), permit, controller, MatchVerifier(), Path(tmp) / "second",
                    attempts=(_attempt(),), scaffold=ScriptedR1Scaffold(),
                    forbidden_literals=("PRIVATE_SENTINEL",),
                )
        self.assertEqual(raised.exception.reason_code, "live_permit_rejected")
        self.assertEqual(len(controller.calls), first_call_count)

    def test_s7_close_is_runner_reserved_and_second_observation_is_preserved(self) -> None:
        controller = RecordingController()
        verifier = SequenceVerifier()
        with tempfile.TemporaryDirectory() as tmp:
            result = run_r1_live(
                _config("S7"), _permit("S7"), controller, verifier, Path(tmp) / "out",
                attempts=(_attempt("S7"),), scaffold=S7CloseAttemptScaffold(),
                forbidden_literals=("PRIVATE_SENTINEL",),
            )
        self.assertEqual(len(result.runs[0].observations), 2)
        self.assertEqual(
            [item.outcome for item in result.runs[0].observations],
            [RemoteOutcome.MATCH, RemoteOutcome.MISMATCH],
        )
        self.assertEqual([call[0] for call in controller.calls].count("close_pull_request"), 1)

    def test_normal_controller_failure_is_persisted_without_fabricating_remote_evidence(self) -> None:
        controller = WriteFailingController()
        with tempfile.TemporaryDirectory() as tmp:
            result = run_r1_live(
                _config(), _permit(), controller, MatchVerifier(), Path(tmp) / "out",
                attempts=(_attempt(),), scaffold=ScriptedR1Scaffold(),
                forbidden_literals=("PRIVATE_SENTINEL",),
            )
        run = result.runs[0]
        self.assertEqual(run.run_status, "aborted")
        self.assertEqual(run.abort_reason_code, "controller_failure")
        self.assertEqual(run.observations, ())
        self.assertEqual(run.evaluations, ())
        self.assertEqual(result.metrics["aborted_run_count"], 1)
        self.assertTrue(result.manifest_verified)

    def test_accepted_but_unaddressable_pr_creation_uses_branch_reconciliation_for_cleanup(self) -> None:
        controller = AmbiguousPullController()
        with tempfile.TemporaryDirectory() as tmp:
            result = run_r1_live(
                _config(), _permit(), controller, MatchVerifier(), Path(tmp) / "out",
                attempts=(_attempt(),), scaffold=ScriptedR1Scaffold(),
                forbidden_literals=("PRIVATE_SENTINEL",),
            )
        self.assertEqual(result.runs[0].run_status, "aborted")
        self.assertIn(("reconcile_pull_request", "r1-codex-s0", "main"), controller.calls)
        self.assertIn(("close_pull_request", 73), controller.calls)

    def test_manifest_rejects_nested_untracked_files(self) -> None:
        controller = RecordingController()
        with tempfile.TemporaryDirectory() as tmp:
            result = run_r1_live(
                _config(), _permit(), controller, MatchVerifier(), Path(tmp) / "out",
                attempts=(_attempt(),), scaffold=ScriptedR1Scaffold(),
                forbidden_literals=("PRIVATE_SENTINEL",),
            )
            nested = result.output_dir / "raw"
            nested.mkdir()
            (nested / "provider.json").write_text("PRIVATE", encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "untracked"):
                verify_r1_manifest(result.output_dir)

    def test_manifest_recomputes_public_config_digest(self) -> None:
        controller = RecordingController()
        with tempfile.TemporaryDirectory() as tmp:
            result = run_r1_live(
                _config(), _permit(), controller, MatchVerifier(), Path(tmp) / "out",
                attempts=(_attempt(),), scaffold=ScriptedR1Scaffold(),
                forbidden_literals=("PRIVATE_SENTINEL",),
            )
            manifest_path = result.output_dir / "manifest.json"
            raw = json.loads(manifest_path.read_text(encoding="utf-8"))
            raw["public_config_digest"] = "0" * 64
            manifest_path.write_text(json.dumps(raw, sort_keys=True) + "\n", encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "configuration digest"):
                verify_r1_manifest(result.output_dir)

    def test_scaffold_facing_controller_does_not_directly_expose_provider_delegate(self) -> None:
        controller = RecordingController()
        scaffold = DelegateProbeScaffold()
        with tempfile.TemporaryDirectory() as tmp:
            run_r1_live(
                _config(), _permit(), controller, MatchVerifier(), Path(tmp) / "out",
                attempts=(_attempt(),), scaffold=scaffold,
                forbidden_literals=("PRIVATE_SENTINEL",),
            )
        self.assertFalse(scaffold.delegate_visible)

    def test_live_output_destination_is_validated_before_any_remote_mutation(self) -> None:
        permit = _permit()
        controller = RecordingController()
        with tempfile.TemporaryDirectory() as tmp:
            output = Path(tmp) / "out"
            output.mkdir()
            (output / "existing.txt").write_text("occupied", encoding="utf-8")
            with self.assertRaises(R1RunnerAbort) as raised:
                run_r1_live(
                    _config(), permit, controller, MatchVerifier(), output,
                    attempts=(_attempt(),), scaffold=ScriptedR1Scaffold(),
                    forbidden_literals=("PRIVATE_SENTINEL",),
                )
            self.assertEqual(raised.exception.reason_code, "artifact_destination_unsafe")
            self.assertEqual(controller.calls, [])

    def test_runner_measures_each_verifier_read_latency_including_s7_second_read(self) -> None:
        controller = RecordingController()
        verifier = SequenceVerifier()
        with tempfile.TemporaryDirectory() as tmp:
            result = run_r1_live(
                _config("S7"), _permit("S7"), controller, verifier, Path(tmp) / "out",
                attempts=(_attempt("S7"),), scaffold=ScriptedR1Scaffold(),
                forbidden_literals=("PRIVATE_SENTINEL",),
            )
        latencies = result.runs[0].verification_latency_ms
        self.assertEqual(len(latencies), 2)
        self.assertTrue(all(value is not None and value >= 0 for value in latencies))


if __name__ == "__main__":
    unittest.main()
