import contextlib
import io
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from completion_verifier.models import Status
from completion_verifier.sandbox import (
    FileWriteContract,
    SafeFileSandbox,
    SandboxReferenceRunner,
    SandboxSecurityError,
    SandboxSuiteConfig,
    SCENARIO_IDS,
    run_sandbox_suite,
    verify_sandbox_manifest,
)


CONFIG = {
    "suite_id": "sandbox-reference-v1",
    "generated_at": "2026-07-21T00:00:00Z",
    "scenarios": [
        "success",
        "false_success",
        "partial_write",
        "timeout_before_write",
        "timeout_after_write",
        "rollback",
        "path_traversal",
        "symlink_escape",
    ],
    "contract": {
        "contract_id": "write-customer-update",
        "path": "output/customer-update.txt",
        "content": "Customer update sent.\n",
    },
}


class ContractAndFilesystemTests(unittest.TestCase):
    def test_contract_digest_is_deterministic(self) -> None:
        contract = FileWriteContract.from_dict(CONFIG["contract"])
        reordered = dict(reversed(list(CONFIG["contract"].items())))
        self.assertEqual(contract.digest, FileWriteContract.from_dict(reordered).digest)
        self.assertEqual(contract.expected_size, len(CONFIG["contract"]["content"].encode()))
        self.assertEqual(len(contract.expected_sha256), 64)

    def test_absolute_path_is_rejected(self) -> None:
        with self.assertRaisesRegex(ValueError, "relative"):
            FileWriteContract("c", "/tmp/out.txt", "x")

    def test_parent_traversal_is_rejected(self) -> None:
        with self.assertRaisesRegex(ValueError, "traversal"):
            FileWriteContract("c", "../out.txt", "x")

    def test_windows_drive_and_backslash_are_rejected(self) -> None:
        for value in ("C:/out.txt", "folder\\out.txt"):
            with self.subTest(value=value), self.assertRaises(ValueError):
                FileWriteContract("c", value, "x")

    def test_dot_and_empty_components_are_rejected(self) -> None:
        for value in ("./out.txt", "folder//out.txt", "folder/"):
            with self.subTest(value=value), self.assertRaisesRegex(ValueError, "components"):
                FileWriteContract("c", value, "x")

    def test_safe_nested_write_and_observation(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            sandbox = SafeFileSandbox(Path(directory))
            contract = FileWriteContract("c", "nested/out.txt", "hello")
            sandbox.write_text(contract.path, contract.content)
            observation = sandbox.observe(contract)
            self.assertTrue(observation.matches_contract)
            self.assertEqual(observation.size, 5)
            self.assertEqual(observation.path, "nested/out.txt")
            self.assertEqual(observation.trust_basis, "independent_local_state")

    def test_missing_file_is_a_confined_failed_observation(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            observation = SafeFileSandbox(Path(directory)).observe(
                FileWriteContract("c", "missing.txt", "hello")
            )
            self.assertTrue(observation.confined)
            self.assertFalse(observation.exists)
            self.assertFalse(observation.matches_contract)

    def test_write_rejects_parent_symlink_escape(self) -> None:
        with tempfile.TemporaryDirectory() as directory, tempfile.TemporaryDirectory() as outside:
            root = Path(directory)
            (root / "link").symlink_to(Path(outside), target_is_directory=True)
            sandbox = SafeFileSandbox(root)
            with self.assertRaises(SandboxSecurityError):
                sandbox.write_text("link/escape.txt", "escape")
            self.assertFalse((Path(outside) / "escape.txt").exists())

    def test_write_rejects_final_symlink(self) -> None:
        with tempfile.TemporaryDirectory() as directory, tempfile.TemporaryDirectory() as outside:
            root = Path(directory)
            outside_file = Path(outside) / "target.txt"
            outside_file.write_text("unchanged")
            (root / "out.txt").symlink_to(outside_file)
            sandbox = SafeFileSandbox(root)
            with self.assertRaises(SandboxSecurityError):
                sandbox.write_text("out.txt", "changed")
            self.assertEqual(outside_file.read_text(), "unchanged")

    def test_observation_rejects_symlinked_parent(self) -> None:
        with tempfile.TemporaryDirectory() as directory, tempfile.TemporaryDirectory() as outside:
            root = Path(directory)
            (Path(outside) / "out.txt").write_text("secret")
            (root / "link").symlink_to(Path(outside), target_is_directory=True)
            observation = SafeFileSandbox(root).observe(
                FileWriteContract("c", "link/out.txt", "secret")
            )
            self.assertFalse(observation.confined)
            self.assertFalse(observation.matches_contract)
            self.assertIn("symlink", observation.error)


class ScenarioTests(unittest.TestCase):
    def setUp(self) -> None:
        self.contract = FileWriteContract.from_dict(CONFIG["contract"])
        self.runner = SandboxReferenceRunner()

    def run_scenario(self, scenario: str):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        return self.runner.run(scenario, self.contract, Path(temp.name))

    def test_scenario_list_is_stable(self) -> None:
        self.assertEqual(
            SCENARIO_IDS,
            (
                "success",
                "false_success",
                "partial_write",
                "timeout_before_write",
                "timeout_after_write",
                "rollback",
                "path_traversal",
                "symlink_escape",
            ),
        )

    def test_success_is_independently_verified(self) -> None:
        result = self.run_scenario("success")
        self.assertTrue(result.report.reported_success)
        self.assertTrue(result.observation.matches_contract)
        self.assertEqual(result.evaluation.status, Status.VERIFIED_COMPLETE)

    def test_false_success_is_detected_despite_fabricated_receipt(self) -> None:
        result = self.run_scenario("false_success")
        self.assertTrue(result.report.reported_success)
        self.assertIn("sha256", result.report.reported_evidence)
        self.assertFalse(result.observation.matches_contract)
        self.assertEqual(result.evaluation.status, Status.FAILED)
        self.assertNotEqual(
            result.case.events[0].evidence.get("sha256"),
            result.report.reported_evidence["sha256"],
        )

    def test_partial_write_is_detected(self) -> None:
        result = self.run_scenario("partial_write")
        self.assertTrue(result.report.reported_success)
        self.assertTrue(result.observation.exists)
        self.assertFalse(result.observation.matches_content)
        self.assertEqual(result.evaluation.status, Status.FAILED)

    def test_timeout_before_write_is_failed_without_claim(self) -> None:
        result = self.run_scenario("timeout_before_write")
        self.assertFalse(result.report.completion_claimed)
        self.assertFalse(result.observation.exists)
        self.assertEqual(result.evaluation.status, Status.FAILED)

    def test_timeout_after_write_is_silent_verified_completion(self) -> None:
        result = self.run_scenario("timeout_after_write")
        self.assertFalse(result.report.reported_success)
        self.assertFalse(result.report.completion_claimed)
        self.assertTrue(result.observation.matches_contract)
        self.assertEqual(result.evaluation.status, Status.VERIFIED_COMPLETE)

    def test_rollback_is_detected(self) -> None:
        result = self.run_scenario("rollback")
        self.assertTrue(result.report.reported_success)
        self.assertFalse(result.observation.exists)
        self.assertEqual(result.evaluation.status, Status.FAILED)

    def test_path_traversal_is_security_rejection(self) -> None:
        result = self.run_scenario("path_traversal")
        self.assertEqual(result.report.error_kind, "security_rejection")
        self.assertTrue(result.security_rejected)
        self.assertEqual(result.evaluation.status, Status.FAILED)

    def test_symlink_escape_is_security_rejection(self) -> None:
        result = self.run_scenario("symlink_escape")
        self.assertEqual(result.report.error_kind, "security_rejection")
        self.assertTrue(result.security_rejected)
        self.assertEqual(result.evaluation.status, Status.FAILED)

    def test_canonical_event_contains_only_observed_evidence(self) -> None:
        result = self.run_scenario("false_success")
        evidence = result.case.events[0].evidence
        self.assertEqual(evidence["trust_basis"], "independent_local_state")
        self.assertNotIn("reported_success", evidence)
        self.assertNotIn("source_event_id", evidence)
        self.assertNotIn("fabricated", evidence)


class SuiteTests(unittest.TestCase):
    def setUp(self) -> None:
        self.config = SandboxSuiteConfig.from_dict(CONFIG)

    def test_config_round_trip_and_validation(self) -> None:
        self.assertEqual(self.config.to_dict(), CONFIG | {"schema_version": "1"})
        self.assertEqual(len(self.config.digest), 64)
        raw = dict(CONFIG)
        raw["scenarios"] = ["not-real"]
        with self.assertRaisesRegex(ValueError, "Unknown scenario"):
            SandboxSuiteConfig.from_dict(raw)

    def test_full_suite_writes_separate_artifacts_and_expected_metrics(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "suite"
            result = run_sandbox_suite(self.config, output)
            self.assertEqual(result.total_scenarios, 8)
            self.assertTrue(verify_sandbox_manifest(output))
            self.assertEqual(len(list((output / "runs").glob("*/source_report.json"))), 8)
            self.assertEqual(len(list((output / "runs").glob("*/observation.json"))), 8)
            self.assertEqual(len((output / "results.jsonl").read_text().splitlines()), 8)
            metrics = json.loads((output / "metrics.json").read_text())
            self.assertEqual(metrics["status_counts"]["VERIFIED_COMPLETE"], 2)
            self.assertEqual(metrics["status_counts"]["FAILED"], 6)
            self.assertEqual(metrics["claimed_completion"], 4)
            self.assertEqual(metrics["false_completion"], 3)
            self.assertEqual(metrics["false_completion_rate"], 0.75)
            self.assertEqual(metrics["silent_verified_completion"], 1)
            self.assertEqual(metrics["source_false_positive"], 3)
            self.assertEqual(metrics["source_false_negative"], 1)
            self.assertEqual(metrics["security_rejection"], 2)
            self.assertIn("not external-model", (output / "report.md").read_text())

    def test_suite_output_is_deterministic(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            first = Path(directory) / "first"
            second = Path(directory) / "second"
            run_sandbox_suite(self.config, first)
            run_sandbox_suite(self.config, second)
            for relative in (
                "suite_config.json",
                "results.jsonl",
                "metrics.json",
                "report.md",
                "manifest.json",
            ):
                self.assertEqual((first / relative).read_bytes(), (second / relative).read_bytes(), relative)
            first_files = sorted(
                (path.relative_to(first).as_posix(), path.read_bytes())
                for path in first.rglob("*")
                if path.is_file() and path.name != "manifest.json"
            )
            second_files = sorted(
                (path.relative_to(second).as_posix(), path.read_bytes())
                for path in second.rglob("*")
                if path.is_file() and path.name != "manifest.json"
            )
            self.assertEqual(first_files, second_files)

    def test_non_empty_output_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "suite"
            output.mkdir()
            (output / "keep.txt").write_text("keep")
            with self.assertRaisesRegex(FileExistsError, "non-empty"):
                run_sandbox_suite(self.config, output)

    def test_manifest_detects_tampering(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "suite"
            run_sandbox_suite(self.config, output)
            (output / "metrics.json").write_text("{}")
            with self.assertRaisesRegex(ValueError, "digest mismatch"):
                verify_sandbox_manifest(output)


class SandboxCliTests(unittest.TestCase):
    def write_config(self, root: Path) -> Path:
        path = root / "config.json"
        path.write_text(json.dumps(CONFIG), encoding="utf-8")
        return path

    def test_dry_run_lists_scenarios(self) -> None:
        from completion_verifier.sandbox_cli import main

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            config = self.write_config(root)
            stdout = io.StringIO()
            with contextlib.redirect_stdout(stdout), mock.patch(
                "sys.argv",
                ["completion-verifier-sandbox", "--config", str(config), "--output", str(root / "out"), "--dry-run"],
            ):
                self.assertEqual(main(), 0)
            payload = json.loads(stdout.getvalue())
            self.assertEqual(payload["scenarios"], list(SCENARIO_IDS))
            self.assertFalse((root / "out").exists())

    def test_single_scenario_run(self) -> None:
        from completion_verifier.sandbox_cli import main

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            config = self.write_config(root)
            output = root / "out"
            stdout = io.StringIO()
            with contextlib.redirect_stdout(stdout), mock.patch(
                "sys.argv",
                ["completion-verifier-sandbox", "--config", str(config), "--output", str(output), "--scenario", "timeout_after_write"],
            ):
                self.assertEqual(main(), 0)
            payload = json.loads(stdout.getvalue())
            self.assertEqual(payload["total_scenarios"], 1)
            self.assertEqual(payload["verified_complete"], 1)
            self.assertTrue(verify_sandbox_manifest(output))

    def test_full_cli_run(self) -> None:
        from completion_verifier.sandbox_cli import main

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            config = self.write_config(root)
            output = root / "out"
            stdout = io.StringIO()
            with contextlib.redirect_stdout(stdout), mock.patch(
                "sys.argv",
                ["completion-verifier-sandbox", "--config", str(config), "--output", str(output), "--scenario", "all"],
            ):
                self.assertEqual(main(), 0)
            payload = json.loads(stdout.getvalue())
            self.assertEqual(payload["total_scenarios"], 8)
            self.assertEqual(payload["false_completion_rate"], 0.75)
            self.assertTrue(payload["manifest_verified"])

    def test_unknown_scenario_is_rejected(self) -> None:
        from completion_verifier.sandbox_cli import main

        with contextlib.redirect_stderr(io.StringIO()), mock.patch(
            "sys.argv",
            ["completion-verifier-sandbox", "--config", "a", "--output", "b", "--scenario", "unknown"],
        ):
            with self.assertRaises(SystemExit):
                main()


if __name__ == "__main__":
    unittest.main()
