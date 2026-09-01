from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from completion_verifier.adapters import canonical_json_sha256
from completion_verifier.experiments.r1.artifacts import verify_r1_manifest, write_r1_artifacts
from completion_verifier.experiments.r1.models import R1ExperimentConfig, R1RunRecord, R1SourceClaim
from completion_verifier.remote import RemoteObservation, RemoteOutcome
from completion_verifier.remote.evaluation import evaluate_remote_observation


def _fixture_run() -> tuple[R1ExperimentConfig, tuple[R1RunRecord, ...], dict[str, object]]:
    config = R1ExperimentConfig(
        experiment_id="PRIVATE_ARTIFACT_REVIEW",
        seed=3,
        repetitions=1,
        scenarios=("S0",),
        treatment="baseline",
        scaffold_id="artifact-review",
        scaffold_version="1",
        max_live_actions=4,
        live=False,
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
        source_claim=R1SourceClaim(True, 0, False, 0),
        controller_receipts=(),
        observations=(observation,),
        evaluations=(evaluation,),
    )
    metrics: dict[str, object] = {"run_count": 1}
    return config, (run,), metrics


class PostMergeArtifactReviewTests(unittest.TestCase):
    def test_manifest_rejects_nested_untracked_file(self) -> None:
        config, runs, metrics = _fixture_run()
        with tempfile.TemporaryDirectory() as tmp:
            output = write_r1_artifacts(Path(tmp) / "out", config, runs, metrics)
            nested = output / "raw"
            nested.mkdir()
            (nested / "provider.json").write_text("PRIVATE_PROVIDER_BODY", encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "untracked"):
                verify_r1_manifest(output)

    def test_manifest_recomputes_public_config_digest_from_config_json(self) -> None:
        config, runs, metrics = _fixture_run()
        with tempfile.TemporaryDirectory() as tmp:
            output = write_r1_artifacts(Path(tmp) / "out", config, runs, metrics)
            manifest_path = output / "manifest.json"
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            self.assertEqual(
                manifest["public_config_digest"],
                canonical_json_sha256(json.loads((output / "config.json").read_text(encoding="utf-8"))),
            )
            manifest["public_config_digest"] = "0" * 64
            manifest_path.write_text(
                json.dumps(manifest, sort_keys=True, separators=(",", ":")) + "\n",
                encoding="utf-8",
            )
            with self.assertRaisesRegex(ValueError, "config digest"):
                verify_r1_manifest(output)


if __name__ == "__main__":
    unittest.main()
