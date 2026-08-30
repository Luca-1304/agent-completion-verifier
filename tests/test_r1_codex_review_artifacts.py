from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from completion_verifier.experiments.r1.artifacts import verify_r1_manifest, write_r1_artifacts
from completion_verifier.experiments.r1.models import R1ExperimentConfig, R1RunRecord, R1SourceClaim
from completion_verifier.remote import RemoteObservation, RemoteOutcome
from completion_verifier.remote.evaluation import evaluate_remote_observation


class R1CodexReviewArtifactTests(unittest.TestCase):
    def _artifact_set(self, output: Path) -> Path:
        config = R1ExperimentConfig(
            experiment_id="PRIVATE_ARTIFACT_REVIEW",
            seed=23,
            repetitions=1,
            scenarios=("S0",),
            treatment="baseline",
            scaffold_id="artifact-review",
            scaffold_version="1",
            max_live_actions=4,
            live=False,
        )
        claim = R1SourceClaim(
            completion_claimed=True,
            retry_count=0,
            refusal=False,
            action_count=0,
        )
        observation = RemoteObservation(
            provider="github",
            kind="pull_request",
            outcome=RemoteOutcome.MATCH,
            trusted=True,
            reason="matched",
            evidence={"fresh": True},
        )
        evaluation = evaluate_remote_observation(observation, completion_claimed=True)
        run = R1RunRecord(
            scenario_id="S0",
            source_claim=claim,
            controller_receipts=(),
            observations=(observation,),
            evaluations=(evaluation,),
        )
        metrics = {
            "schema_version": "1",
            "total_runs": 1,
            "cleanup_failure_count": 0,
        }
        return write_r1_artifacts(output, config, (run,), metrics)

    def test_manifest_rejects_nested_untracked_file(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            output = self._artifact_set(Path(tmp) / "out")
            nested = output / "raw"
            nested.mkdir()
            (nested / "provider.json").write_text("private", encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "untracked"):
                verify_r1_manifest(output)

    def test_manifest_validates_public_config_digest_against_config_json(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            output = self._artifact_set(Path(tmp) / "out")
            manifest_path = output / "manifest.json"
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            manifest["public_config_digest"] = "f" * 64
            manifest_path.write_text(
                json.dumps(manifest, sort_keys=True, separators=(",", ":")) + "\n",
                encoding="utf-8",
            )
            with self.assertRaisesRegex(ValueError, "config digest"):
                verify_r1_manifest(output)


if __name__ == "__main__":
    unittest.main()
