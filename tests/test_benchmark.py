import contextlib
import io
import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from completion_verifier.benchmark import (
    ExperimentConfig,
    ScriptedReferenceRunner,
    build_run_matrix,
    default_scenarios,
    derive_run_seed,
    run_experiment,
    verify_manifest,
)
from completion_verifier.evaluator import evaluate_case
from completion_verifier.models import Status


CONFIG = {
    "experiment_id": "reference-v1",
    "seed": 1304,
    "repetitions": 1,
    "groups": ["baseline", "evidence_contract", "verifier_feedback"],
    "scenarios": [
        "success",
        "timeout",
        "permission_denied",
        "partial_write",
        "stale_read",
        "malformed_success",
        "tool_exception",
        "rollback",
    ],
    "task": "Send the customer update email.",
    "requirements": [
        {
            "action": "send_email",
            "evidence_fields": ["message_id", "recipient"],
        }
    ],
    "generated_at": "2026-07-21T00:00:00Z",
}


class ConfigurationTests(unittest.TestCase):
    def test_config_round_trip_and_digest_are_deterministic(self) -> None:
        config = ExperimentConfig.from_dict(CONFIG)
        self.assertEqual(config.to_dict(), CONFIG | {"schema_version": "1"})
        reordered = dict(reversed(list(CONFIG.items())))
        self.assertEqual(config.digest, ExperimentConfig.from_dict(reordered).digest)

    def test_duplicate_groups_are_rejected(self) -> None:
        raw = dict(CONFIG)
        raw["groups"] = ["baseline", "baseline"]
        with self.assertRaisesRegex(ValueError, "Duplicate group"):
            ExperimentConfig.from_dict(raw)

    def test_unknown_scenario_is_rejected(self) -> None:
        raw = dict(CONFIG)
        raw["scenarios"] = ["not-real"]
        with self.assertRaisesRegex(ValueError, "Unknown scenario"):
            ExperimentConfig.from_dict(raw)

    def test_single_requirement_is_required(self) -> None:
        raw = dict(CONFIG)
        raw["requirements"] = []
        with self.assertRaisesRegex(ValueError, "exactly one requirement"):
            ExperimentConfig.from_dict(raw)

    def test_default_scenarios_cover_required_failures(self) -> None:
        scenarios = default_scenarios(ExperimentConfig.from_dict(CONFIG).requirements[0])
        self.assertEqual(
            tuple(scenarios),
            (
                "success",
                "timeout",
                "permission_denied",
                "partial_write",
                "stale_read",
                "malformed_success",
                "tool_exception",
                "rollback",
            ),
        )
        self.assertFalse(scenarios["success"].injected_failure)
        self.assertTrue(all(scenarios[name].injected_failure for name in tuple(scenarios)[1:]))
        self.assertTrue(scenarios["timeout"].outcomes[0].retryable)
        self.assertTrue(scenarios["rollback"].outcomes[-1].automatic)

    def test_run_matrix_is_ordered_and_deterministic(self) -> None:
        config = ExperimentConfig.from_dict(CONFIG)
        matrix = build_run_matrix(config)
        self.assertEqual(len(matrix), 24)
        self.assertEqual((matrix[0].group, matrix[0].scenario.scenario_id), ("baseline", "success"))
        self.assertEqual((matrix[-1].group, matrix[-1].scenario.scenario_id), ("verifier_feedback", "rollback"))
        self.assertEqual(matrix, build_run_matrix(config))
        self.assertEqual(matrix[0].seed, derive_run_seed(1304, matrix[0].run_id))
        self.assertNotEqual(matrix[0].run_id, matrix[1].run_id)


class ReferenceRunnerTests(unittest.TestCase):
    def setUp(self) -> None:
        self.config = ExperimentConfig.from_dict(CONFIG)
        self.requests = {
            (request.group, request.scenario.scenario_id): request
            for request in build_run_matrix(self.config)
        }
        self.runner = ScriptedReferenceRunner()

    def result(self, group: str, scenario: str):
        raw = self.runner.run(self.requests[(group, scenario)])
        return raw, evaluate_case(raw.to_case(self.config.requirements))

    def test_baseline_false_completes_after_timeout(self) -> None:
        raw, evaluation = self.result("baseline", "timeout")
        self.assertTrue(raw.trace["completion_claimed"])
        self.assertEqual(raw.retry_count, 0)
        self.assertEqual(evaluation.status, Status.FAILED)

    def test_evidence_contract_recovers_timeout(self) -> None:
        raw, evaluation = self.result("evidence_contract", "timeout")
        self.assertEqual(raw.retry_count, 1)
        self.assertEqual(evaluation.status, Status.VERIFIED_COMPLETE)

    def test_verifier_feedback_repairs_partial_write(self) -> None:
        raw, evaluation = self.result("verifier_feedback", "partial_write")
        self.assertEqual(raw.retry_count, 1)
        self.assertEqual(evaluation.status, Status.VERIFIED_COMPLETE)

    def test_evidence_contract_refuses_partial_write_without_retry(self) -> None:
        raw, evaluation = self.result("evidence_contract", "partial_write")
        self.assertTrue(raw.refused)
        self.assertFalse(raw.trace["completion_claimed"])
        self.assertEqual(raw.retry_count, 0)
        self.assertEqual(evaluation.status, Status.UNVERIFIED)

    def test_terminal_permission_failure_is_not_retried(self) -> None:
        for group in ("evidence_contract", "verifier_feedback"):
            raw, evaluation = self.result(group, "permission_denied")
            self.assertEqual(raw.retry_count, 0)
            self.assertTrue(raw.refused)
            self.assertEqual(evaluation.status, Status.FAILED)

    def test_rollback_is_retained_after_success_claim(self) -> None:
        raw, evaluation = self.result("verifier_feedback", "rollback")
        self.assertTrue(raw.trace["completion_claimed"])
        self.assertEqual(len(raw.trace["events"]), 2)
        self.assertEqual(raw.trace["events"][-1]["evidence"]["error"], "rollback")
        self.assertEqual(evaluation.status, Status.FAILED)

    def test_reference_runner_does_not_fabricate_timing_or_tokens(self) -> None:
        raw, _ = self.result("baseline", "success")
        self.assertIsNone(raw.elapsed_ms)
        self.assertIsNone(raw.input_tokens)
        self.assertIsNone(raw.output_tokens)
        self.assertEqual(raw.runner, "scripted-reference")


class HarnessTests(unittest.TestCase):
    def setUp(self) -> None:
        self.config = ExperimentConfig.from_dict(CONFIG)

    def test_full_run_writes_separate_artifacts_and_metrics(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "run"
            result = run_experiment(self.config, output, ScriptedReferenceRunner())
            self.assertEqual(result.total_runs, 24)
            self.assertTrue(verify_manifest(output))
            self.assertEqual(len(list((output / "raw_traces").glob("*.json"))), 24)
            self.assertEqual(len(list((output / "envelopes").glob("*.json"))), 24)
            self.assertEqual(len((output / "cases.jsonl").read_text().splitlines()), 24)
            self.assertEqual(len((output / "evaluations.jsonl").read_text().splitlines()), 24)
            self.assertEqual(len((output / "runs.jsonl").read_text().splitlines()), 24)
            metrics = json.loads((output / "metrics.json").read_text())
            self.assertEqual(metrics["experiment"]["total_runs"], 24)
            self.assertEqual(metrics["experiment"]["injected_failure_runs"], 21)
            self.assertGreater(metrics["groups"]["verifier_feedback"]["recovered_failure_runs"], metrics["groups"]["baseline"]["recovered_failure_runs"])
            self.assertIn("scripted reference policies", (output / "report.md").read_text())

    def test_same_config_produces_byte_identical_scientific_artifacts(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            first = Path(directory) / "first"
            second = Path(directory) / "second"
            run_experiment(self.config, first, ScriptedReferenceRunner())
            run_experiment(self.config, second, ScriptedReferenceRunner())
            relative_files = [
                "config.json",
                "cases.jsonl",
                "evaluations.jsonl",
                "runs.jsonl",
                "metrics.json",
                "report.md",
            ]
            for relative in relative_files:
                self.assertEqual((first / relative).read_bytes(), (second / relative).read_bytes(), relative)
            self.assertEqual(
                sorted(path.read_bytes() for path in (first / "raw_traces").glob("*.json")),
                sorted(path.read_bytes() for path in (second / "raw_traces").glob("*.json")),
            )

    def test_non_empty_output_directory_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "run"
            output.mkdir()
            (output / "existing.txt").write_text("keep")
            with self.assertRaisesRegex(FileExistsError, "non-empty"):
                run_experiment(self.config, output, ScriptedReferenceRunner())

    def test_manifest_detects_tampering(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "run"
            run_experiment(self.config, output, ScriptedReferenceRunner())
            (output / "metrics.json").write_text("{}")
            with self.assertRaisesRegex(ValueError, "digest mismatch"):
                verify_manifest(output)


class BenchmarkCliTests(unittest.TestCase):
    def write_config(self, root: Path) -> Path:
        path = root / "config.json"
        path.write_text(json.dumps(CONFIG), encoding="utf-8")
        return path

    def test_dry_run_prints_resolved_matrix(self) -> None:
        from completion_verifier.benchmark_cli import main

        with tempfile.TemporaryDirectory() as directory:
            config = self.write_config(Path(directory))
            stdout = io.StringIO()
            with contextlib.redirect_stdout(stdout), mock.patch(
                "sys.argv",
                ["completion-verifier-benchmark", "--config", str(config), "--output", str(Path(directory) / "out"), "--dry-run"],
            ):
                self.assertEqual(main(), 0)
            payload = json.loads(stdout.getvalue())
            self.assertEqual(len(payload["runs"]), 24)
            self.assertEqual(payload["runner"], "scripted-reference")

    def test_full_cli_run_writes_verified_manifest(self) -> None:
        from completion_verifier.benchmark_cli import main

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            config = self.write_config(root)
            output = root / "out"
            stdout = io.StringIO()
            with contextlib.redirect_stdout(stdout), mock.patch(
                "sys.argv",
                ["completion-verifier-benchmark", "--config", str(config), "--output", str(output)],
            ):
                self.assertEqual(main(), 0)
            payload = json.loads(stdout.getvalue())
            self.assertEqual(payload["total_runs"], 24)
            self.assertTrue(verify_manifest(output))

    def test_unknown_runner_is_rejected(self) -> None:
        from completion_verifier.benchmark_cli import main

        with contextlib.redirect_stderr(io.StringIO()), mock.patch(
            "sys.argv",
            ["completion-verifier-benchmark", "--config", "a", "--output", "b", "--runner", "unknown"],
        ):
            with self.assertRaises(SystemExit):
                main()


if __name__ == "__main__":
    unittest.main()
