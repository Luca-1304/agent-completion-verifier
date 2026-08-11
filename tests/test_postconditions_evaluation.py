from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from completion_verifier.models import Status
from completion_verifier.postconditions import (
    DirectoryContract,
    JsonObjectContract,
    TextFileContract,
    evaluate_postcondition,
    postcondition_case,
    verify_postcondition,
)


class RegistryAndEvaluationTests(unittest.TestCase):
    def test_closed_registry_dispatches_all_three_builtin_contracts(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "result.txt").write_text("ok", encoding="utf-8")
            (root / "output").mkdir()
            (root / "state.json").write_text('{"ready":true}', encoding="utf-8")
            contracts = (
                TextFileContract("result.txt", "ok"),
                DirectoryContract("output"),
                JsonObjectContract("state.json", {"ready": True}),
            )
            observations = [verify_postcondition(contract, root) for contract in contracts]
            self.assertEqual([item.kind for item in observations], [
                "text_file",
                "directory",
                "json_object",
            ])
            self.assertTrue(all(item.matches for item in observations))

    def test_unknown_contract_kind_is_rejected(self) -> None:
        class UnknownContract:
            kind = "unknown"

        with tempfile.TemporaryDirectory() as directory:
            with self.assertRaisesRegex(ValueError, "Unknown postcondition contract"):
                verify_postcondition(UnknownContract(), Path(directory))  # type: ignore[arg-type]

    def test_matching_postcondition_uses_existing_evaluator(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "result.txt").write_text("ok", encoding="utf-8")
            evaluation = evaluate_postcondition(TextFileContract("result.txt", "ok"), root)
            self.assertEqual(evaluation.status, Status.VERIFIED_COMPLETE)
            self.assertEqual(evaluation.proven_actions, ("verify_postcondition:text_file",))

    def test_non_matching_postcondition_is_failed_by_existing_evaluator(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "result.txt").write_text("wrong", encoding="utf-8")
            evaluation = evaluate_postcondition(
                TextFileContract("result.txt", "expected"), root
            )
            self.assertEqual(evaluation.status, Status.FAILED)
            self.assertEqual(evaluation.failed_actions, ("verify_postcondition:text_file",))

    def test_evaluator_case_contains_no_caller_controlled_identifiers(self) -> None:
        with tempfile.TemporaryDirectory(prefix="PRIVATE_CASE_ROOT-") as directory:
            root = Path(directory)
            (root / "PRIVATE_CASE_FILE.txt").write_text("PRIVATE_CASE_CONTENT")
            contract = TextFileContract(
                "PRIVATE_CASE_FILE.txt",
                "PRIVATE_CASE_CONTENT",
                contract_id="PRIVATE_CASE_ID",
            )
            observation = verify_postcondition(contract, root)
            case = postcondition_case(contract, observation)
            payload = json.dumps(
                {
                    "case_id": case.case_id,
                    "task": case.task,
                    "completion_claimed": case.completion_claimed,
                    "requirements": [
                        {
                            "action": requirement.action,
                            "evidence_fields": list(requirement.evidence_fields),
                        }
                        for requirement in case.requirements
                    ],
                    "events": [
                        {
                            "action": event.action,
                            "success": event.success,
                            "evidence": event.evidence,
                        }
                        for event in case.events
                    ],
                },
                sort_keys=True,
            )
            for secret in (
                str(root),
                "PRIVATE_CASE_ROOT",
                "PRIVATE_CASE_FILE",
                "PRIVATE_CASE_CONTENT",
                "PRIVATE_CASE_ID",
            ):
                self.assertNotIn(secret, payload)
            self.assertIn("independent_local_state", payload)

    def test_case_rejects_contract_observation_kind_mismatch(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "result.txt").write_text("ok")
            text_contract = TextFileContract("result.txt", "ok")
            text_observation = verify_postcondition(text_contract, root)
            with self.assertRaisesRegex(ValueError, "kind"):
                postcondition_case(DirectoryContract("output"), text_observation)


if __name__ == "__main__":
    unittest.main()
