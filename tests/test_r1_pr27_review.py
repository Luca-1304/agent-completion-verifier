from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from completion_verifier.experiments.r1 import R1ExperimentConfig
from completion_verifier.experiments.r1.artifacts import verify_r1_manifest
from completion_verifier.experiments.r1.github_controller import GitHubR1Controller
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
OTHER_REPO = "OTHER_OWNER/OTHER_DISPOSABLE_REPO"


def _config(*, scenario: str = "S0") -> R1ExperimentConfig:
    return R1ExperimentConfig(
        experiment_id="PRIVATE_PR27_REVIEW",
        seed=27,
        repetitions=1,
        scenarios=(scenario,),
        treatment="baseline",
        scaffold_id="review-scaffold",
        scaffold_version="1",
        max_live_actions=4,
        live=True,
    )


def _attempt(*, target: R1LiveTarget | None = None, scenario: str = "S0") -> R1PreparedAttempt:
    live_target = target or R1LiveTarget(PRIVATE_REPO, PRIVATE_ID)
    return R1PreparedAttempt(
        target=live_target,
        task=R1BoundedTask(
            scenario_id=scenario,
            base_oid=BASE,
            branch_name=f"r1-pr27-{scenario.lower()}",
            fixture_path=f"r1-fixtures/pr27/{scenario.lower()}/state.txt",
            fixture_content=f"private-pr27-{scenario}",
            base_ref="main",
        ),
        expectation=R1ContractExpectation(expected_state="open"),
    )


def _permit(*, target: R1LiveTarget | None = None, scenario: str = "S0"):
    live_target = target or R1LiveTarget(PRIVATE_REPO, PRIVATE_ID)
    definition = get_r1_scenario(scenario)
    result = run_preflight(
        R1PreflightRequest(
            live=True,
            dry_run=False,
            normal_ci=False,
            scenario_id=scenario,
            target=live_target,
            approved_repository_id=live_target.repository_id,
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

    def is_bound_to(self, target) -> bool:
        return target == self.target

    def create_branch(self, base_oid, branch_name):
        self.calls.append(("create_branch", base_oid, branch_name))
        return R1ControllerReceipt("create_branch", True, 1, private_object_oid=base_oid)

    def write_fixture(self, branch_name, relative_path, content, *, existing_blob_sha=None):
        self.calls.append(("write_fixture", branch_name, relative_path, content))
        return R1ControllerReceipt("write_fixture", True, 1, private_object_oid=WRITE)

    def create_pull_request(self, branch_name, base_ref):
        self.calls.append(("create_pull_request", branch_name, base_ref))
        return R1ControllerReceipt("create_pull_request", True, 1, private_pull_number=17)

    def close_pull_request(self, pull_number):
        self.calls.append(("close_pull_request", pull_number))
        return R1ControllerReceipt("close_pull_request", True, 1, private_pull_number=pull_number)


class FailingWriteController(RecordingController):
    def write_fixture(self, branch_name, relative_path, content, *, existing_blob_sha=None):
        self.calls.append(("write_fixture", branch_name, relative_path, content))
        return R1ControllerReceipt(
            "write_fixture", False, 1, error_code="provider_unavailable"
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


class DelegateBypassScaffold:
    def run(self, task, controller):
        controller._delegate.create_branch(task.base_oid, "r1-bypass")
        return R1ScaffoldResult(completion_claimed=False)


class CredentialProvider:
    def authorization_header(self) -> str:
        return "Bearer PRIVATE_PR27_TOKEN"


class FakeResponse:
    def __init__(self, status: int, raw_body: bytes) -> None:
        self.status = status
        self.raw_body = raw_body

    def getheader(self, name: str, default=None):
        del name
        return default

    def read(self, amount: int | None = None) -> bytes:
        if amount is None:
            return self.raw_body
        return self.raw_body[:amount]


class FakeConnection:
    def __init__(self, response: FakeResponse) -> None:
        self.response = response
        self.requests: list[tuple[str, str]] = []

    def request(self, method: str, path: str, body=None, headers=None) -> None:
        del body, headers
        self.requests.append((method, path))

    def getresponse(self) -> FakeResponse:
        return self.response

    def close(self) -> None:
        pass


class R1PR27ReviewTests(unittest.TestCase):
    def test_permit_is_bound_to_verified_repository_locator_not_only_numeric_id(self) -> None:
        approved = R1LiveTarget(PRIVATE_REPO, PRIVATE_ID)
        substituted = R1LiveTarget(OTHER_REPO, PRIVATE_ID)
        controller = RecordingController(substituted)
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaises(R1RunnerAbort) as raised:
                run_r1_live(
                    _config(),
                    _permit(target=approved),
                    controller,
                    MatchVerifier(),
                    Path(tmp) / "out",
                    attempts=(_attempt(target=substituted),),
                    scaffold=ScriptedR1Scaffold(),
                    forbidden_literals=("PRIVATE_PR27_SENTINEL",),
                )
        self.assertEqual(raised.exception.reason_code, "live_permit_rejected")
        self.assertEqual(controller.calls, [])

    def test_live_permit_is_single_use_across_sequential_invocations(self) -> None:
        permit = _permit()
        with tempfile.TemporaryDirectory() as tmp:
            first = RecordingController()
            run_r1_live(
                _config(),
                permit,
                first,
                MatchVerifier(),
                Path(tmp) / "one",
                attempts=(_attempt(),),
                scaffold=ScriptedR1Scaffold(),
                forbidden_literals=("PRIVATE_PR27_SENTINEL",),
            )
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
                    forbidden_literals=("PRIVATE_PR27_SENTINEL",),
                )
        self.assertEqual(raised.exception.reason_code, "live_permit_consumed")
        self.assertEqual(second.calls, [])

    def test_live_pilot_rejects_untrusted_in_process_scaffold_before_delegate_access(self) -> None:
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
                    scaffold=DelegateBypassScaffold(),
                    forbidden_literals=("PRIVATE_PR27_SENTINEL",),
                )
        self.assertEqual(raised.exception.reason_code, "live_scaffold_untrusted")
        self.assertEqual(controller.calls, [])

    def test_nonempty_output_destination_is_rejected_before_any_remote_mutation(self) -> None:
        controller = RecordingController()
        with tempfile.TemporaryDirectory() as tmp:
            output = Path(tmp) / "out"
            output.mkdir()
            (output / "preexisting.txt").write_text("do not overwrite", encoding="utf-8")
            with self.assertRaises(R1RunnerAbort) as raised:
                run_r1_live(
                    _config(),
                    _permit(),
                    controller,
                    MatchVerifier(),
                    output,
                    attempts=(_attempt(),),
                    scaffold=ScriptedR1Scaffold(),
                    forbidden_literals=("PRIVATE_PR27_SENTINEL",),
                )
        self.assertEqual(raised.exception.reason_code, "artifact_destination_unsafe")
        self.assertEqual(controller.calls, [])

    def test_normal_controller_failure_is_persisted_as_aborted_run_instead_of_discarded(self) -> None:
        controller = FailingWriteController()
        with tempfile.TemporaryDirectory() as tmp:
            result = run_r1_live(
                _config(),
                _permit(),
                controller,
                MatchVerifier(),
                Path(tmp) / "out",
                attempts=(_attempt(),),
                scaffold=ScriptedR1Scaffold(),
                forbidden_literals=("PRIVATE_PR27_SENTINEL",),
            )
        self.assertEqual(len(result.runs), 1)
        run = result.runs[0]
        self.assertEqual(run.abort_reason, "controller_failure")
        self.assertEqual(run.observations, ())
        self.assertEqual(run.evaluations, ())
        self.assertEqual(result.metrics.get("harness_aborted_count"), 1)

    def test_accepted_but_unaddressable_pr_creation_is_distinguished_from_rejection(self) -> None:
        response = FakeResponse(201, b"{not-json")
        connection = FakeConnection(response)
        controller = GitHubR1Controller(
            CredentialProvider(),
            R1LiveTarget(PRIVATE_REPO, PRIVATE_ID),
            connection_factory=lambda host, *, timeout: connection,
        )
        receipt = controller.create_pull_request("r1-pr27-s0", "main")
        self.assertFalse(receipt.success)
        self.assertEqual(receipt.error_code, "accepted_unaddressable")
        self.assertEqual(receipt.private_target_ref, "r1-pr27-s0")

    def test_manifest_rejects_nested_untracked_files(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            result = run_r1_live(
                _config(),
                _permit(),
                RecordingController(),
                MatchVerifier(),
                Path(tmp) / "out",
                attempts=(_attempt(),),
                scaffold=ScriptedR1Scaffold(),
                forbidden_literals=("PRIVATE_PR27_SENTINEL",),
            )
            nested = result.output_dir / "raw"
            nested.mkdir()
            (nested / "provider.json").write_text("PRIVATE_PROVIDER_BODY", encoding="utf-8")
            with self.assertRaises(ValueError):
                verify_r1_manifest(result.output_dir)

    def test_manifest_recomputes_public_configuration_digest(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            result = run_r1_live(
                _config(),
                _permit(),
                RecordingController(),
                MatchVerifier(),
                Path(tmp) / "out",
                attempts=(_attempt(),),
                scaffold=ScriptedR1Scaffold(),
                forbidden_literals=("PRIVATE_PR27_SENTINEL",),
            )
            manifest_path = result.output_dir / "manifest.json"
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            manifest["public_config_digest"] = "0" * 64
            manifest_path.write_text(
                json.dumps(manifest, sort_keys=True, separators=(",", ":")) + "\n",
                encoding="utf-8",
            )
            with self.assertRaises(ValueError):
                verify_r1_manifest(result.output_dir)

    def test_runner_records_real_verifier_latency(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            result = run_r1_live(
                _config(),
                _permit(),
                RecordingController(),
                MatchVerifier(),
                Path(tmp) / "out",
                attempts=(_attempt(),),
                scaffold=ScriptedR1Scaffold(),
                forbidden_literals=("PRIVATE_PR27_SENTINEL",),
            )
        latency = result.runs[0].verification_latency_ms[0]
        self.assertIsNotNone(latency)
        assert latency is not None
        self.assertGreaterEqual(latency, 0.0)


if __name__ == "__main__":
    unittest.main()
