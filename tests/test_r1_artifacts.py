from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from completion_verifier.remote import RemoteObservation, RemoteOutcome
from completion_verifier.remote.evaluation import evaluate_remote_observation
from completion_verifier.experiments.r1 import (
    R1ControllerReceipt,
    R1ExperimentConfig,
    R1SourceClaim,
)
from completion_verifier.experiments.r1.artifacts import (
    privacy_sentinel,
    verify_r1_manifest,
    write_r1_artifacts,
)
from completion_verifier.experiments.r1.models import R1RunRecord


_FORBIDDEN = (
    "TOKEN_SENTINEL",
    "PRIVATE_OWNER/PRIVATE_REPO",
    "9001",
    "PR_NUMBER_SENTINEL",
    "PRIVATE_BRANCH_SENTINEL",
    "OBJECT_ID_SENTINEL",
    "PRIVATE_USERNAME_SENTINEL",
    "PRIVATE_EMAIL_SENTINEL",
    "/private/local/root",
    "RAW_MODEL_TEXT_SENTINEL",
)


def _config() -> R1ExperimentConfig:
    return R1ExperimentConfig(
        experiment_id="PRIVATE_EXPERIMENT_SENTINEL",
        seed=7,
        repetitions=1,
        scenarios=("S0",),
        treatment="baseline",
        scaffold_id="scaffold-a",
        scaffold_version="1",
        max_live_actions=4,
    )


def _run() -> R1RunRecord:
    observation = RemoteObservation(
        provider="github",
        kind="pull_request",
        outcome=RemoteOutcome.MATCH,
        trusted=True,
        reason="matched",
        evidence={"fresh": True, "head_matches": True},
    )
    evaluation = evaluate_remote_observation(observation, completion_claimed=True)
    return R1RunRecord(
        scenario_id="S0",
        source_claim=R1SourceClaim(
            completion_claimed=True,
            retry_count=0,
            refusal=False,
            action_count=3,
            private_trace_ref="RAW_MODEL_TEXT_SENTINEL",
        ),
        controller_receipts=(
            R1ControllerReceipt(
                "create_branch",
                True,
                1,
                private_target_ref="PRIVATE_OWNER/PRIVATE_REPO:PRIVATE_BRANCH_SENTINEL",
            ),
        ),
        observations=(observation,),
        evaluations=(evaluation,),
    )


class R1ArtifactTests(unittest.TestCase):
    def test_privacy_sentinel_detects_nested_values_and_keys(self) -> None:
        self.assertFalse(
            privacy_sentinel(
                [{"safe": ["nested", {"value": "TOKEN_SENTINEL"}]}],
                _FORBIDDEN,
            )
        )
        self.assertFalse(
            privacy_sentinel(
                [{"TOKEN_SENTINEL": "safe-value"}],
                _FORBIDDEN,
            )
        )
        self.assertTrue(privacy_sentinel([{"safe": [1, True, None]}], _FORBIDDEN))

    def test_privacy_sentinel_rejects_empty_forbidden_literal(self) -> None:
        with self.assertRaises(ValueError):
            privacy_sentinel([{"safe": True}], ("",))

    def test_writer_creates_fixed_public_artifact_set(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            output = Path(tmp) / "r1-output"
            result = write_r1_artifacts(
                output,
                _config(),
                (_run(),),
                metrics={"schema_version": "1", "remote_match_rate": 1.0},
            )
            self.assertEqual(result, output)
            self.assertEqual(
                {path.name for path in output.iterdir()},
                {
                    "config.json",
                    "runs.jsonl",
                    "observations.jsonl",
                    "evaluations.jsonl",
                    "metrics.json",
                    "report.md",
                    "manifest.json",
                },
            )
            self.assertTrue(verify_r1_manifest(output))

    def test_writer_uses_public_serializers_and_does_not_leak_private_values(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            output = Path(tmp) / "r1-output"
            write_r1_artifacts(
                output,
                _config(),
                (_run(),),
                metrics={"schema_version": "1", "remote_match_rate": 1.0},
            )
            combined = "\n".join(
                path.name + "\n" + path.read_text(encoding="utf-8")
                for path in sorted(output.iterdir())
            )
            for forbidden in _FORBIDDEN + ("PRIVATE_EXPERIMENT_SENTINEL",):
                with self.subTest(forbidden=forbidden):
                    self.assertNotIn(forbidden, combined)
            self.assertIn('"remote_outcomes":["MATCH"]', combined)
            self.assertIn("R1 controlled real-provider experiment", combined)

    def test_public_config_digest_depends_only_on_public_config(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            first = Path(tmp) / "first"
            second = Path(tmp) / "second"
            a = _config()
            b = R1ExperimentConfig(
                experiment_id="DIFFERENT_PRIVATE_EXPERIMENT_ID",
                seed=a.seed,
                repetitions=a.repetitions,
                scenarios=a.scenarios,
                treatment=a.treatment,
                scaffold_id=a.scaffold_id,
                scaffold_version=a.scaffold_version,
                max_live_actions=a.max_live_actions,
            )
            write_r1_artifacts(first, a, (_run(),), metrics={"schema_version": "1"})
            write_r1_artifacts(second, b, (_run(),), metrics={"schema_version": "1"})
            manifest_a = json.loads((first / "manifest.json").read_text(encoding="utf-8"))
            manifest_b = json.loads((second / "manifest.json").read_text(encoding="utf-8"))
            self.assertEqual(manifest_a["public_config_digest"], manifest_b["public_config_digest"])

    def test_manifest_detects_changed_file(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            output = Path(tmp) / "r1-output"
            write_r1_artifacts(output, _config(), (_run(),), metrics={"schema_version": "1"})
            (output / "metrics.json").write_text("{}\n", encoding="utf-8")
            with self.assertRaises(ValueError):
                verify_r1_manifest(output)

    def test_manifest_detects_missing_file(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            output = Path(tmp) / "r1-output"
            write_r1_artifacts(output, _config(), (_run(),), metrics={"schema_version": "1"})
            (output / "runs.jsonl").unlink()
            with self.assertRaises(ValueError):
                verify_r1_manifest(output)

    def test_manifest_detects_untracked_extra_file(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            output = Path(tmp) / "r1-output"
            write_r1_artifacts(output, _config(), (_run(),), metrics={"schema_version": "1"})
            (output / "PRIVATE_BRANCH_SENTINEL.txt").write_text("x", encoding="utf-8")
            with self.assertRaises(ValueError):
                verify_r1_manifest(output)

    def test_output_directory_must_be_new_or_empty(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            output = Path(tmp) / "r1-output"
            output.mkdir()
            (output / "existing.txt").write_text("x", encoding="utf-8")
            with self.assertRaises(FileExistsError):
                write_r1_artifacts(
                    output,
                    _config(),
                    (_run(),),
                    metrics={"schema_version": "1"},
                )

    def test_writer_rejects_private_metrics_payload(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaises(ValueError):
                write_r1_artifacts(
                    Path(tmp) / "r1-output",
                    _config(),
                    (_run(),),
                    metrics={"schema_version": "1", "note": "TOKEN_SENTINEL"},
                    forbidden_literals=_FORBIDDEN,
                )


if __name__ == "__main__":
    unittest.main()
