from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from completion_verifier.experiments.r1 import R1ExperimentConfig
from completion_verifier.experiments.r1.artifacts import verify_r1_manifest, write_r1_artifacts
from completion_verifier.experiments.r1.controller import DryRunR1Controller
from completion_verifier.experiments.r1.models import R1ControllerReceipt, R1RunRecord, R1SourceClaim
from completion_verifier.experiments.r1.orchestrator import evaluate_attempt
from completion_verifier.experiments.r1.preflight import (
    R1LiveTarget,
    R1PreflightRequest,
    artifact_destination_binding,
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
from completion_verifier.remote import GitHubPullRequestContract, RemoteObservation, RemoteOutcome
from completion_verifier.remote.evaluation import evaluate_remote_observation

BASE = "a" * 40
WRITE = "b" * 40
REPO_A = "PRIVATE_OWNER/PRIVATE_DISPOSABLE_REPO"
REPO_B = "OTHER_OWNER/OTHER_DISPOSABLE_REPO"
REPO_ID = 91001


def config(*, scenario: str = "S0", live: bool = True) -> R1ExperimentConfig:
    return R1ExperimentConfig(
        experiment_id="PRIVATE_ROUND2_EXPERIMENT",
        seed=23,
        repetitions=1,
        scenarios=(scenario,),
        treatment="baseline",
        scaffold_id="scripted-r1",
        scaffold_version="1",
        max_live_actions=4,
        live=live,
    )


def attempt(*, scenario: str = "S0", repo: str = REPO_A) -> R1PreparedAttempt:
    return R1PreparedAttempt(
        target=R1LiveTarget(repo, REPO_ID),
        task=R1BoundedTask(
            scenario_id=scenario,
            base_oid=BASE,
            branch_name=f"r1-round2-{scenario.lower()}",
            fixture_path=f"r1-fixtures/round2/{scenario.lower()}/state.txt",
            fixture_content=f"private-round2-{scenario}",
            base_ref="main",
        ),
        expectation=R1ContractExpectation(expected_state="open"),
    )


def permit(output_dir: Path, *, scenario: str = "S0", repo: str = REPO_A):
    definition = get_r1_scenario(scenario)
    result = run_preflight(
        R1PreflightRequest(
            live=True,
            dry_run=False,
            normal_ci=False,
            scenario_id=scenario,
            target=R1LiveTarget(repo, REPO_ID),
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
            artifact_destination_binding=artifact_destination_binding(output_dir),
        )
    )
    assert result.permit is not None
    return result.permit


class RecordingController:
    def __init__(self, repo: str = REPO_A) -> None:
        self.target = R1LiveTarget(repo, REPO_ID)
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


class MaliciousScaffold:
    def run(self, task, controller):
        delegate = getattr(controller, "_delegate")
        delegate.create_branch(task.base_oid, "r1-escaped")
        return R1ScaffoldResult(completion_claimed=False)


class S7SelfClosingScaffold:
    def run(self, task, controller):
        controller.create_branch(task.base_oid, task.branch_name)
        controller.write_fixture(task.branch_name, task.fixture_path, task.fixture_content)
        pull = controller.create_pull_request(task.branch_name, task.base_ref)
        assert pull.private_pull_number is not None
        controller.close_pull_request(pull.private_pull_number)
        return R1ScaffoldResult(completion_claimed=True)


class R1PermitAndRunnerRound2Tests(unittest.TestCase):
    def test_permit_binds_verified_locator_not_only_numeric_repository_id(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / "out"
            issued = permit(out, repo=REPO_A)
            controller = RecordingController(repo=REPO_B)
            with self.assertRaises(R1RunnerAbort) as raised:
                run_r1_live(
                    config(),
                    issued,
                    controller,
                    MatchVerifier(),
                    out,
                    attempts=(attempt(repo=REPO_B),),
                    scaffold=ScriptedR1Scaffold(),
                    forbidden_literals=("PRIVATE_SENTINEL",),
                )
        self.assertEqual(raised.exception.reason_code, "live_permit_rejected")
        self.assertEqual(controller.calls, [])

    def test_live_permit_is_single_use_across_separate_invocations(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            first_out = root / "first"
            issued = permit(first_out)
            first = RecordingController()
            run_r1_live(
                config(),
                issued,
                first,
                MatchVerifier(),
                first_out,
                attempts=(attempt(),),
                scaffold=ScriptedR1Scaffold(),
                forbidden_literals=("PRIVATE_SENTINEL",),
            )
            second = RecordingController()
            with self.assertRaises(R1RunnerAbort) as raised:
                run_r1_live(
                    config(),
                    issued,
                    second,
                    MatchVerifier(),
                    root / "second",
                    attempts=(attempt(),),
                    scaffold=ScriptedR1Scaffold(),
                    forbidden_literals=("PRIVATE_SENTINEL",),
                )
        self.assertEqual(raised.exception.reason_code, "live_permit_rejected")
        self.assertEqual(second.calls, [])

    def test_live_artifact_destination_is_validated_and_bound_before_mutation(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            approved = root / "approved"
            issued = permit(approved)
            wrong = root / "wrong"
            wrong.mkdir()
            (wrong / "existing.txt").write_text("occupied", encoding="utf-8")
            controller = RecordingController()
            with self.assertRaises(R1RunnerAbort) as raised:
                run_r1_live(
                    config(),
                    issued,
                    controller,
                    MatchVerifier(),
                    wrong,
                    attempts=(attempt(),),
                    scaffold=ScriptedR1Scaffold(),
                    forbidden_literals=("PRIVATE_SENTINEL",),
                )
        self.assertEqual(raised.exception.reason_code, "artifact_destination_unsafe")
        self.assertEqual(controller.calls, [])

    def test_initial_live_pilot_rejects_arbitrary_in_process_scaffolds(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / "out"
            controller = RecordingController()
            with self.assertRaises(R1RunnerAbort) as raised:
                run_r1_live(
                    config(),
                    permit(out),
                    controller,
                    MatchVerifier(),
                    out,
                    attempts=(attempt(),),
                    scaffold=MaliciousScaffold(),
                    forbidden_literals=("PRIVATE_SENTINEL",),
                )
        self.assertEqual(raised.exception.reason_code, "live_scaffold_untrusted")
        self.assertEqual(controller.calls, [])

    def test_s7_scaffold_cannot_consume_runner_reserved_close(self) -> None:
        dry_config = config(scenario="S7", live=False)
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaises(R1RunnerAbort) as raised:
                run_r1_dry(
                    dry_config,
                    DryRunR1Controller(),
                    MatchVerifier(),
                    Path(tmp) / "out",
                    attempts=(attempt(scenario="S7"),),
                    scaffold=S7SelfClosingScaffold(),
                    forbidden_literals=("PRIVATE_SENTINEL",),
                )
        self.assertEqual(raised.exception.reason_code, "action_not_allowed")


class R1ArtifactRound2Tests(unittest.TestCase):
    def _run(self) -> R1RunRecord:
        observation = RemoteObservation(
            provider="github",
            kind="pull_request",
            outcome=RemoteOutcome.MATCH,
            trusted=True,
            reason="matched",
            evidence={"fresh": True},
        )
        evaluation = evaluate_remote_observation(observation, completion_claimed=True)
        return R1RunRecord(
            scenario_id="S0",
            source_claim=R1SourceClaim(True, 0, False, 3),
            controller_receipts=(),
            observations=(observation,),
            evaluations=(evaluation,),
        )

    def test_manifest_rejects_nested_untracked_files(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / "out"
            write_r1_artifacts(out, config(live=False), (self._run(),), {"total_runs": 1})
            nested = out / "raw"
            nested.mkdir()
            (nested / "provider.json").write_text("PRIVATE", encoding="utf-8")
            with self.assertRaises(ValueError):
                verify_r1_manifest(out)

    def test_manifest_validates_public_config_digest_against_config_json(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / "out"
            write_r1_artifacts(out, config(live=False), (self._run(),), {"total_runs": 1})
            manifest_path = out / "manifest.json"
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            manifest["public_config_digest"] = "0" * 64
            manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
            with self.assertRaises(ValueError):
                verify_r1_manifest(out)


class R1LatencyRound2Tests(unittest.TestCase):
    def test_evaluate_attempt_records_monotonic_verifier_latency(self) -> None:
        contract = GitHubPullRequestContract(
            repository=REPO_A,
            repository_id=REPO_ID,
            pull_number=17,
            expected_head_oid=WRITE,
            expected_head_repository_id=REPO_ID,
            expected_base_ref="main",
            expected_state="open",
        )
        claim = R1SourceClaim(True, 0, False, 3)
        with patch(
            "completion_verifier.experiments.r1.orchestrator.time.perf_counter",
            side_effect=(10.0, 10.007),
        ):
            run = evaluate_attempt(
                scenario_id="S0",
                contract=contract,
                source_claim=claim,
                controller_receipts=(),
                verifier=MatchVerifier(),
            )
        self.assertEqual(len(run.verification_latency_ms), 1)
        self.assertAlmostEqual(run.verification_latency_ms[0] or 0.0, 7.0, places=6)


if __name__ == "__main__":
    unittest.main()
