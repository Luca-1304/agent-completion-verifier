from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from completion_verifier.experiments.r1 import R1ExperimentConfig
from completion_verifier.experiments.r1.controller import DryRunR1Controller
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
    preview_r1,
    run_r1_dry,
    run_r1_live,
)
from completion_verifier.remote import RemoteObservation, RemoteOutcome


BASE = "a" * 40
WRITE = "b" * 40
WRONG = "c" * 40
PRIVATE_REPO = "PRIVATE_OWNER/PRIVATE_DISPOSABLE_REPO"
PRIVATE_ID = 9001


def config(*, live: bool, scenarios=("S0",), max_actions: int = 4, repetitions: int = 1):
    return R1ExperimentConfig(
        experiment_id="PRIVATE_EXPERIMENT_ID",
        seed=7,
        repetitions=repetitions,
        scenarios=scenarios,
        treatment="baseline",
        scaffold_id="scripted-reference",
        scaffold_version="1",
        max_live_actions=max_actions,
        live=live,
    )


def attempt(scenario_id: str = "S0") -> R1PreparedAttempt:
    target = R1LiveTarget(PRIVATE_REPO, PRIVATE_ID)
    task = R1BoundedTask(
        scenario_id=scenario_id,
        base_oid=BASE,
        branch_name=f"r1-{scenario_id.lower()}-001",
        fixture_path=f"r1-fixtures/{scenario_id.lower()}-001/state.txt",
        fixture_content="fixture-state",
        base_ref="main",
    )
    expectation = R1ContractExpectation(
        expected_head_oid=None if scenario_id not in {"S1", "S2"} else WRONG,
        expected_base_ref="wrong-base" if scenario_id == "S3" else None,
        expected_state="closed" if scenario_id == "S4" else "open",
        expected_pull_number=7 if scenario_id in {"S6", "S8"} else None,
    )
    if scenario_id in {"S6", "S8"}:
        expectation = R1ContractExpectation(
            expected_head_oid=WRITE,
            expected_base_ref="main",
            expected_state="open",
            expected_pull_number=7,
        )
    return R1PreparedAttempt(target=target, task=task, expectation=expectation)


class SequenceVerifier:
    def __init__(self, outcomes: tuple[RemoteOutcome, ...]):
        self.outcomes = list(outcomes)
        self.contracts = []

    def verify(self, contract):
        self.contracts.append(contract)
        outcome = self.outcomes.pop(0)
        if outcome is RemoteOutcome.MATCH:
            return RemoteObservation(
                provider="github",
                kind="pull_request",
                outcome=outcome,
                trusted=True,
                reason="matched",
                evidence={"fresh": True},
            )
        if outcome is RemoteOutcome.MISMATCH:
            return RemoteObservation(
                provider="github",
                kind="pull_request",
                outcome=outcome,
                trusted=True,
                reason="state_mismatch",
                evidence={"fresh": True, "state_matches": False},
            )
        return RemoteObservation(
            provider="github",
            kind="pull_request",
            outcome=outcome,
            trusted=False,
            reason="provider_unavailable",
            evidence={"fresh": False},
        )


class FakeLiveController:
    def __init__(self, *, bound: bool = True):
        self.bound = bound
        self.calls: list[str] = []
        self.pull_number = 7

    def is_bound_to(self, target):
        return self.bound and target.repository_id == PRIVATE_ID

    def create_branch(self, base_oid, branch_name):
        self.calls.append("create_branch")
        return R1ControllerReceipt(
            "create_branch", True, 1, private_object_oid=base_oid
        )

    def write_fixture(self, branch_name, relative_path, content, *, existing_blob_sha=None):
        self.calls.append("write_fixture")
        return R1ControllerReceipt(
            "write_fixture", True, 1, private_object_oid=WRITE
        )

    def create_pull_request(self, branch_name, base_ref):
        self.calls.append("create_pull_request")
        return R1ControllerReceipt(
            "create_pull_request", True, 1, private_pull_number=self.pull_number
        )

    def close_pull_request(self, pull_number):
        self.calls.append("close_pull_request")
        return R1ControllerReceipt(
            "close_pull_request", True, 1, private_pull_number=pull_number
        )


class NetworkSentinelController:
    def __init__(self):
        self.calls = 0

    def _explode(self, *args, **kwargs):
        self.calls += 1
        raise AssertionError("dry run attempted network-capable controller")

    create_branch = _explode
    write_fixture = _explode
    create_pull_request = _explode
    close_pull_request = _explode


def permit_for(scenario_id: str, *, max_actions: int = 4):
    from completion_verifier.experiments.r1.scenarios import get_r1_scenario

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
            protected_repository_ids=frozenset({123}),
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


class R1RunnerPreviewTests(unittest.TestCase):
    def test_preview_contains_only_public_plan_fields(self) -> None:
        preview = preview_r1(config(live=False, scenarios=("S0", "S7")))
        rendered = str(preview)
        self.assertEqual(preview["schema_version"], "1")
        self.assertEqual(preview["scenarios"][0]["scenario_id"], "S0")
        self.assertEqual(preview["scenarios"][1]["scenario_id"], "S7")
        self.assertEqual(preview["max_live_actions"], 4)
        self.assertIn("manifest", preview["artifact_classes"])
        for secret in (PRIVATE_REPO, str(PRIVATE_ID), "PRIVATE_EXPERIMENT_ID"):
            self.assertNotIn(secret, rendered)

    def test_prepared_attempt_repr_is_private(self) -> None:
        value = attempt("S0")
        rendered = repr(value)
        self.assertEqual(rendered, "R1PreparedAttempt()")
        self.assertNotIn(PRIVATE_REPO, rendered)


class R1DryRunnerTests(unittest.TestCase):
    def test_dry_run_rejects_network_capable_controller_before_any_call(self) -> None:
        controller = NetworkSentinelController()
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaises(R1RunnerAbort) as raised:
                run_r1_dry(
                    config(live=False),
                    controller,
                    SequenceVerifier((RemoteOutcome.MATCH,)),
                    Path(tmp) / "out",
                    attempts=(attempt("S0"),),
                    scaffold=ScriptedR1Scaffold(),
                )
        self.assertEqual(raised.exception.reason_code, "dry_controller_required")
        self.assertEqual(controller.calls, 0)

    def test_dry_run_executes_fake_path_and_writes_verified_public_artifacts(self) -> None:
        verifier = SequenceVerifier((RemoteOutcome.MATCH,))
        with tempfile.TemporaryDirectory() as tmp:
            result = run_r1_dry(
                config(live=False),
                DryRunR1Controller(),
                verifier,
                Path(tmp) / "out",
                attempts=(attempt("S0"),),
                scaffold=ScriptedR1Scaffold(),
                forbidden_literals=(PRIVATE_REPO, str(PRIVATE_ID), "PRIVATE_EXPERIMENT_ID"),
            )
            self.assertTrue(result.manifest_verified)
            self.assertEqual(len(result.runs), 1)
            self.assertEqual(len(result.runs[0].controller_receipts), 4)
            self.assertEqual(result.runs[0].evaluation.status.value, "VERIFIED_COMPLETE")
            combined = "\n".join(
                path.read_text(encoding="utf-8")
                for path in result.output_dir.iterdir()
                if path.is_file()
            )
            for secret in (PRIVATE_REPO, str(PRIVATE_ID), "PRIVATE_EXPERIMENT_ID"):
                self.assertNotIn(secret, combined)


class R1LiveRunnerTests(unittest.TestCase):
    def test_live_requires_real_permit_before_controller_binding_or_calls(self) -> None:
        controller = FakeLiveController()
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaises(R1RunnerAbort) as raised:
                run_r1_live(
                    config(live=True),
                    None,
                    controller,
                    SequenceVerifier((RemoteOutcome.MATCH,)),
                    Path(tmp) / "out",
                    attempts=(attempt("S0"),),
                    scaffold=ScriptedR1Scaffold(),
                    forbidden_literals=("PRIVATE_TEST_SENTINEL",),
                )
        self.assertEqual(raised.exception.reason_code, "live_permit_required")
        self.assertEqual(controller.calls, [])

    def test_live_controller_target_binding_is_checked_before_mutation(self) -> None:
        controller = FakeLiveController(bound=False)
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaises(R1RunnerAbort) as raised:
                run_r1_live(
                    config(live=True),
                    permit_for("S0"),
                    controller,
                    SequenceVerifier((RemoteOutcome.MATCH,)),
                    Path(tmp) / "out",
                    attempts=(attempt("S0"),),
                    scaffold=ScriptedR1Scaffold(),
                    forbidden_literals=("PRIVATE_TEST_SENTINEL",),
                )
        self.assertEqual(raised.exception.reason_code, "controller_target_mismatch")
        self.assertEqual(controller.calls, [])

    def test_action_budget_reserves_cleanup_before_pr_creation(self) -> None:
        controller = FakeLiveController()
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaises(R1RunnerAbort) as raised:
                run_r1_live(
                    config(live=True, max_actions=3),
                    permit_for("S0", max_actions=3),
                    controller,
                    SequenceVerifier((RemoteOutcome.MATCH,)),
                    Path(tmp) / "out",
                    attempts=(attempt("S0"),),
                    scaffold=ScriptedR1Scaffold(),
                    forbidden_literals=("PRIVATE_TEST_SENTINEL",),
                )
        self.assertEqual(raised.exception.reason_code, "action_budget_exceeded")
        self.assertEqual(controller.calls, ["create_branch", "write_fixture"])

    def test_permit_cannot_be_reused_for_another_scenario(self) -> None:
        controller = FakeLiveController()
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaises(R1RunnerAbort) as raised:
                run_r1_live(
                    config(live=True, scenarios=("S1",)),
                    permit_for("S0"),
                    controller,
                    SequenceVerifier((RemoteOutcome.MISMATCH,)),
                    Path(tmp) / "out",
                    attempts=(attempt("S1"),),
                    scaffold=ScriptedR1Scaffold(),
                    forbidden_literals=("PRIVATE_TEST_SENTINEL",),
                )
        self.assertEqual(raised.exception.reason_code, "live_permit_rejected")
        self.assertEqual(controller.calls, [])

    def test_s7_has_one_explicit_second_read_after_single_close(self) -> None:
        controller = FakeLiveController()
        verifier = SequenceVerifier((RemoteOutcome.MATCH, RemoteOutcome.MISMATCH))
        with tempfile.TemporaryDirectory() as tmp:
            result = run_r1_live(
                config(live=True, scenarios=("S7",)),
                permit_for("S7"),
                controller,
                verifier,
                Path(tmp) / "out",
                attempts=(attempt("S7"),),
                scaffold=ScriptedR1Scaffold(),
                forbidden_literals=(PRIVATE_REPO, str(PRIVATE_ID), "PRIVATE_EXPERIMENT_ID"),
            )
        self.assertEqual(
            controller.calls,
            ["create_branch", "write_fixture", "create_pull_request", "close_pull_request"],
        )
        self.assertEqual(len(verifier.contracts), 2)
        self.assertEqual(
            result.runs[0].to_public_dict()["remote_outcomes"],
            ["MATCH", "MISMATCH"],
        )
        self.assertEqual(result.metrics["post_verification_divergence_count"], 1)

    def test_attempt_matrix_must_match_config_repetitions(self) -> None:
        controller = FakeLiveController()
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaises(ValueError):
                run_r1_live(
                    config(live=True),
                    permit_for("S0"),
                    controller,
                    SequenceVerifier((RemoteOutcome.MATCH,)),
                    Path(tmp) / "out",
                    attempts=(attempt("S1"),),
                    scaffold=ScriptedR1Scaffold(),
                    forbidden_literals=("PRIVATE_TEST_SENTINEL",),
                )
        self.assertEqual(controller.calls, [])


if __name__ == "__main__":
    unittest.main()
