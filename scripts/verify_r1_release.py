"""Verify the R1 experimental harness without credentials or provider I/O."""

from __future__ import annotations

import tempfile
from pathlib import Path

from completion_verifier.experiments.r1 import R1ExperimentConfig
from completion_verifier.experiments.r1.artifacts import verify_r1_manifest
from completion_verifier.experiments.r1.controller import DryRunR1Controller
from completion_verifier.experiments.r1.preflight import R1LiveTarget
from completion_verifier.experiments.r1.runner import (
    R1BoundedTask,
    R1ContractExpectation,
    R1PreparedAttempt,
    ScriptedR1Scaffold,
    preview_r1,
    run_r1_dry,
)
from completion_verifier.remote import RemoteObservation, RemoteOutcome


class _FakeVerifier:
    def __init__(self) -> None:
        self._outcomes = [
            RemoteOutcome.MATCH,
            RemoteOutcome.MATCH,
            RemoteOutcome.MISMATCH,
        ]

    def verify(self, contract):
        del contract
        outcome = self._outcomes.pop(0)
        if outcome is RemoteOutcome.MATCH:
            return RemoteObservation(
                provider="github",
                kind="pull_request",
                outcome=outcome,
                trusted=True,
                reason="matched",
                evidence={"fresh": True},
            )
        return RemoteObservation(
            provider="github",
            kind="pull_request",
            outcome=outcome,
            trusted=True,
            reason="state_mismatch",
            evidence={"fresh": True, "state_matches": False},
        )


def _attempt(scenario_id: str, target: R1LiveTarget) -> R1PreparedAttempt:
    return R1PreparedAttempt(
        target=target,
        task=R1BoundedTask(
            scenario_id=scenario_id,
            base_oid="a" * 40,
            branch_name=f"r1-release-{scenario_id.lower()}",
            fixture_path=f"r1-fixtures/release/{scenario_id.lower()}.txt",
            fixture_content="PRIVATE_FIXTURE_SENTINEL",
            base_ref="PRIVATE_BASE_REF_SENTINEL",
        ),
        expectation=R1ContractExpectation(expected_state="open"),
    )


def main() -> int:
    config = R1ExperimentConfig(
        experiment_id="PRIVATE_EXPERIMENT_SENTINEL",
        seed=17,
        repetitions=1,
        scenarios=("S0", "S7"),
        treatment="baseline",
        scaffold_id="scripted-reference",
        scaffold_version="1",
        max_live_actions=4,
        live=False,
    )
    preview = preview_r1(config)
    if preview["scenarios"][0]["scenario_id"] != "S0":
        raise AssertionError("R1 preview lost its scenario ordering.")

    target = R1LiveTarget("PRIVATE_OWNER/PRIVATE_REPOSITORY", 987654321)
    attempts = (_attempt("S0", target), _attempt("S7", target))
    forbidden = (
        "PRIVATE_EXPERIMENT_SENTINEL",
        "PRIVATE_OWNER/PRIVATE_REPOSITORY",
        "987654321",
        "PRIVATE_BASE_REF_SENTINEL",
        "PRIVATE_FIXTURE_SENTINEL",
        "a" * 40,
        "r1-release-s0",
        "r1-release-s7",
        "r1-fixtures/release/s0.txt",
        "r1-fixtures/release/s7.txt",
    )

    with tempfile.TemporaryDirectory() as directory:
        result = run_r1_dry(
            config,
            DryRunR1Controller(),
            _FakeVerifier(),
            Path(directory) / "r1-release-smoke",
            attempts=attempts,
            scaffold=ScriptedR1Scaffold(),
            forbidden_literals=forbidden,
        )
        if not result.manifest_verified or not verify_r1_manifest(result.output_dir):
            raise AssertionError("R1 release smoke manifest did not verify.")
        if len(result.runs) != 2:
            raise AssertionError("R1 release smoke produced the wrong run count.")
        if result.runs[0].observations[-1].outcome is not RemoteOutcome.MATCH:
            raise AssertionError("R1 release smoke lost the S0 match.")
        if [item.outcome for item in result.runs[1].observations] != [
            RemoteOutcome.MATCH,
            RemoteOutcome.MISMATCH,
        ]:
            raise AssertionError("R1 release smoke lost the explicit S7 second read.")

    print("R1 release verification passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
