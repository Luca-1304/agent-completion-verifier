from __future__ import annotations

import json
import shutil
import tempfile
import time
import unittest
from pathlib import Path

from completion_verifier.experiments.r1.artifacts import verify_r1_manifest
from completion_verifier.experiments.r1.controller import DryRunR1Controller
from completion_verifier.experiments.r1.github_controller import GitHubR1Controller
from completion_verifier.experiments.r1.models import R1ControllerReceipt, R1ExperimentConfig
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
    run_r1_dry,
    run_r1_live,
)
from completion_verifier.experiments.r1.scenarios import get_r1_scenario
from completion_verifier.remote import RemoteObservation, RemoteOutcome


BASE = "a" * 40
WRITE = "b" * 40
PRIVATE_REPO = "PRIVATE_OWNER/PRIVATE_DISPOSABLE_REPO"
ALT_PRIVATE_REPO = "OTHER_PRIVATE_OWNER/OTHER_PRIVATE_DISPOSABLE_REPO"
PRIVATE_ID = 91001


def _config(*, scenario: str = "S0", live: bool = True) -> R1ExperimentConfig:
    return R1ExperimentConfig(
        experiment_id="PRIVATE_PR27_EXPERIMENT",
        seed=27,
        repetitions=1,
        scenarios=(scenario,),
        treatment="baseline",
        scaffold_id="review-scaffold",
        scaffold_version="1",
        max_live_actions=4,
        live=live,
    )


def _target(locator: str = PRIVATE_REPO) -> R1LiveTarget:
    return R1LiveTarget(locator, PRIVATE_ID)


def _attempt(*, scenario: str = "S0", target: R1LiveTarget | None = None) -> R1PreparedAttempt:
    return R1PreparedAttempt(
        target=target or _target(),
        task=R1BoundedTask(
            scenario_id=scenario,
            base_oid=BASE,
            branch_name=f"r1-pr27-{scenario.lower()}",
            fixture_path=f"r1-fixtures/pr27/{scenario.lower()}/state.txt",
            fixture_content=f"private-fixture-{scenario}",
            base_ref="main",
        ),
        expectation=R1ContractExpectation(expected_state="open"),
    )


def _permit(output_dir: Path, *, scenario: str = "S0", target: R1LiveTarget | None = None):
    target = target or _target()
    definition = get_r1_scenario(scenario)
    request = R1PreflightRequest(
        live=True,
        dry_run=False,
        normal_ci=False,
        scenario_id=scenario,
        target=target,
        approved_repository_id=target.repository_id,
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
    # This is deliberately attached before production grows the explicit field.
    # The regression proves the approved destination must become permit-bound.
    object.__setattr__(request, "artifact_destination", str(output_dir.resolve()))
    result = run_preflight(request)
    assert result.permit is not None
    return result.permit


class RecordingController:
    def __init__(self, target: R1LiveTarget | None = None) -> None:
        self.target = target or _target()
        self.calls: list[tuple] = []
        self.next_pull_number = 7

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


class FailedBranchController(RecordingController):
    def create_branch(self, base_oid, branch_name):
        self.calls.append(("create_branch", base_oid, branch_name))
        return R1ControllerReceipt(
            "create_branch", False, 1, error_code="provider_unavailable"
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


class SlowMatchVerifier(MatchVerifier):
    def verify(self, contract):
        time.sleep(0.001)
        return super().verify(contract)


class SequenceVerifier:
    def __init__(self) -> None:
        self.calls = 0

    def verify(self, contract):
        del contract
        self.calls += 1
        if self.calls == 1:
            return RemoteObservation(
                provider="github",
                kind="pull_request",
                outcome=RemoteOutcome.MATCH,
                trusted=True,
                reason="matched",
                evidence={"fresh": True},
            )
        return RemoteObservation(
            provider="github",
            kind="pull_request",
            outcome=RemoteOutcome.MISMATCH,
            trusted=True,
            reason="state_mismatch",
            evidence={"state_matches": False, "fresh": True},
        )


class DelegateEscapeScaffold:
    def run(self, task, controller):
        # A live caller must never receive a credential-bearing delegate reference.
        controller._delegate.create_branch(task.base_oid, "r1-escaped")
        return R1ScaffoldResult(completion_claimed=False)


class _Credential:
    def authorization_header(self) -> str:
        return "Bearer PRIVATE_TOKEN"


class _Response:
    status = 201

    def getheader(self, name):
        del name
        return None

    def read(self, limit):
        del limit
        return b"{}"


class _Connection:
    def __init__(self, *args, **kwargs) -> None:
        del args, kwargs
        self.requests: list[tuple] = []

    def request(self, method, path, body=None, headers=None):
        self.requests.append((method, path, body, headers))

    def getresponse(self):
        return _Response()

    def close(self):
        return None


class PR27ReviewRegressionTests(unittest.TestCase):
    def test_permit_binds_verified_locator_not_only_numeric_repository_id(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            output = Path(tmp) / "out"
            permit = _permit(output)
            alternate = _target(ALT_PRIVATE_REPO)
            controller = RecordingController(alternate)
            with self.assertRaises(R1RunnerAbort) as raised:
                run_r1_live(
                    _config(),
                    permit,
                    controller,
                    MatchVerifier(),
                    output,
                    attempts=(_attempt(target=alternate),),
                    scaffold=ScriptedR1Scaffold(),
                    forbidden_literals=("PRIVATE_EXTERNAL_SENTINEL",),
                )
        self.assertEqual(raised.exception.reason_code, "live_permit_rejected")
        self.assertEqual(controller.calls, [])

    def test_live_permit_is_single_use_across_sequential_invocations(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            output = Path(tmp) / "out"
            permit = _permit(output)
            first = RecordingController()
            run_r1_live(
                _config(),
                permit,
                first,
                MatchVerifier(),
                output,
                attempts=(_attempt(),),
                scaffold=ScriptedR1Scaffold(),
                forbidden_literals=("PRIVATE_EXTERNAL_SENTINEL",),
            )
            shutil.rmtree(output)
            second = RecordingController()
            with self.assertRaises(R1RunnerAbort) as raised:
                run_r1_live(
                    _config(),
                    permit,
                    second,
                    MatchVerifier(),
                    output,
                    attempts=(_attempt(),),
                    scaffold=ScriptedR1Scaffold(),
                    forbidden_literals=("PRIVATE_EXTERNAL_SENTINEL",),
                )
        self.assertEqual(raised.exception.reason_code, "live_permit_rejected")
        self.assertEqual(second.calls, [])

    def test_live_output_directory_must_match_preflight_approved_destination(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            approved = Path(tmp) / "approved"
            other = Path(tmp) / "other"
            permit = _permit(approved)
            controller = RecordingController()
            with self.assertRaises(R1RunnerAbort) as raised:
                run_r1_live(
                    _config(),
                    permit,
                    controller,
                    MatchVerifier(),
                    other,
                    attempts=(_attempt(),),
                    scaffold=ScriptedR1Scaffold(),
                    forbidden_literals=("PRIVATE_EXTERNAL_SENTINEL",),
                )
        self.assertEqual(raised.exception.reason_code, "artifact_destination_mismatch")
        self.assertEqual(controller.calls, [])

    def test_live_output_directory_is_actually_reserved_before_remote_mutation(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            output = Path(tmp) / "out"
            output.write_text("not-a-directory", encoding="utf-8")
            permit = _permit(output)
            controller = RecordingController()
            with self.assertRaises(R1RunnerAbort) as raised:
                run_r1_live(
                    _config(),
                    permit,
                    controller,
                    MatchVerifier(),
                    output,
                    attempts=(_attempt(),),
                    scaffold=ScriptedR1Scaffold(),
                    forbidden_literals=("PRIVATE_EXTERNAL_SENTINEL",),
                )
        self.assertEqual(raised.exception.reason_code, "artifact_destination_unsafe")
        self.assertEqual(controller.calls, [])

    def test_live_mode_rejects_arbitrary_in_process_scaffolds_before_authority_exposure(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            output = Path(tmp) / "out"
            controller = RecordingController()
            with self.assertRaises(R1RunnerAbort) as raised:
                run_r1_live(
                    _config(),
                    _permit(output),
                    controller,
                    MatchVerifier(),
                    output,
                    attempts=(_attempt(),),
                    scaffold=DelegateEscapeScaffold(),
                    forbidden_literals=("PRIVATE_EXTERNAL_SENTINEL",),
                )
        self.assertEqual(raised.exception.reason_code, "scaffold_untrusted")
        self.assertEqual(controller.calls, [])

    def test_normal_controller_failure_is_persisted_as_indeterminate_run(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            output = Path(tmp) / "out"
            result = run_r1_live(
                _config(),
                _permit(output),
                FailedBranchController(),
                MatchVerifier(),
                output,
                attempts=(_attempt(),),
                scaffold=ScriptedR1Scaffold(),
                forbidden_literals=("PRIVATE_EXTERNAL_SENTINEL",),
            )
        self.assertEqual(len(result.runs), 1)
        run = result.runs[0]
        self.assertEqual(run.controller_receipts[0].error_code, "provider_unavailable")
        self.assertIs(run.observations[0].outcome, RemoteOutcome.INDETERMINATE)
        self.assertEqual(run.observations[0].reason, "resource_unobservable")

    def test_accepted_but_unaddressable_pr_creation_is_distinguished_from_rejection(self) -> None:
        connection = _Connection()
        controller = GitHubR1Controller(
            _Credential(),
            _target(),
            connection_factory=lambda *args, **kwargs: connection,
        )
        receipt = controller.create_pull_request("r1-pr27-s0", "main")
        self.assertFalse(receipt.success)
        self.assertEqual(receipt.error_code, "accepted_unaddressable")
        self.assertEqual(receipt.private_target_ref, "r1-pr27-s0")

    def test_manifest_rejects_nested_untracked_files(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            output = Path(tmp) / "out"
            run_r1_dry(
                _config(live=False),
                DryRunR1Controller(),
                MatchVerifier(),
                output,
                attempts=(_attempt(),),
                scaffold=ScriptedR1Scaffold(),
            )
            nested = output / "raw"
            nested.mkdir()
            (nested / "provider.json").write_text("PRIVATE_RAW", encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "untracked"):
                verify_r1_manifest(output)

    def test_manifest_validates_public_configuration_digest(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            output = Path(tmp) / "out"
            run_r1_dry(
                _config(live=False),
                DryRunR1Controller(),
                MatchVerifier(),
                output,
                attempts=(_attempt(),),
                scaffold=ScriptedR1Scaffold(),
            )
            manifest_path = output / "manifest.json"
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            manifest["public_config_digest"] = "0" * 64
            manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "configuration digest"):
                verify_r1_manifest(output)

    def test_runner_records_measured_verification_latency(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            result = run_r1_dry(
                _config(live=False),
                DryRunR1Controller(),
                SlowMatchVerifier(),
                Path(tmp) / "out",
                attempts=(_attempt(),),
                scaffold=ScriptedR1Scaffold(),
            )
        latency = result.runs[0].verification_latency_ms[0]
        self.assertIsNotNone(latency)
        assert latency is not None
        self.assertGreaterEqual(latency, 0.0)

    def test_s7_records_latency_for_both_explicit_reads(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            result = run_r1_dry(
                _config(scenario="S7", live=False),
                DryRunR1Controller(),
                SequenceVerifier(),
                Path(tmp) / "out",
                attempts=(_attempt(scenario="S7"),),
                scaffold=ScriptedR1Scaffold(),
            )
        run = result.runs[0]
        self.assertEqual(len(run.observations), 2)
        self.assertEqual(len(run.verification_latency_ms), 2)
        self.assertTrue(all(value is not None for value in run.verification_latency_ms))


if __name__ == "__main__":
    unittest.main()
