from __future__ import annotations

import contextlib
import io
import json
import tempfile
import unittest
from pathlib import Path

from completion_verifier.cli import load_cases, main
from completion_verifier.evaluator import evaluate_case
from completion_verifier.models import Case, Status


class EvaluatorTests(unittest.TestCase):
    def make_case(self, **overrides: object) -> Case:
        raw = {
            "case_id": "case",
            "task": "Do a thing.",
            "completion_claimed": True,
            "requirements": [
                {"action": "act", "evidence_fields": ["receipt"]}
            ],
            "events": [],
        }
        raw.update(overrides)
        return Case.from_dict(raw)

    def test_verified_complete(self) -> None:
        case = self.make_case(
            events=[
                {"action": "act", "success": True, "evidence": {"receipt": "r1"}}
            ]
        )
        result = evaluate_case(case)
        self.assertEqual(result.status, Status.VERIFIED_COMPLETE)
        self.assertEqual(result.proven_actions, ("act",))

    def test_unverified_claim_only(self) -> None:
        result = evaluate_case(self.make_case())
        self.assertEqual(result.status, Status.UNVERIFIED)
        self.assertIn("act", result.missing_actions)
        self.assertTrue(any("claimed completion" in value for value in result.reasons))

    def test_failed_latest_event(self) -> None:
        case = self.make_case(
            events=[{"action": "act", "success": False, "evidence": {}}]
        )
        result = evaluate_case(case)
        self.assertEqual(result.status, Status.FAILED)
        self.assertEqual(result.failed_actions, ("act",))

    def test_successful_retry_recovers_failure(self) -> None:
        case = self.make_case(
            events=[
                {"action": "act", "success": False, "evidence": {}},
                {"action": "act", "success": True, "evidence": {"receipt": "r2"}},
            ]
        )
        self.assertEqual(evaluate_case(case).status, Status.VERIFIED_COMPLETE)

    def test_later_failure_overrides_success(self) -> None:
        case = self.make_case(
            events=[
                {"action": "act", "success": True, "evidence": {"receipt": "r1"}},
                {"action": "act", "success": False, "evidence": {"error": "rollback"}},
            ]
        )
        self.assertEqual(evaluate_case(case).status, Status.FAILED)

    def test_missing_evidence_is_unverified(self) -> None:
        case = self.make_case(
            events=[{"action": "act", "success": True, "evidence": {}}]
        )
        self.assertEqual(evaluate_case(case).status, Status.UNVERIFIED)

    def test_empty_string_evidence_is_missing(self) -> None:
        case = self.make_case(
            events=[
                {"action": "act", "success": True, "evidence": {"receipt": "  "}}
            ]
        )
        self.assertEqual(evaluate_case(case).status, Status.UNVERIFIED)

    def test_empty_collection_evidence_is_missing(self) -> None:
        case = self.make_case(
            events=[
                {"action": "act", "success": True, "evidence": {"receipt": []}}
            ]
        )
        self.assertEqual(evaluate_case(case).status, Status.UNVERIFIED)

    def test_numeric_zero_is_valid_evidence(self) -> None:
        case = self.make_case(
            events=[
                {"action": "act", "success": True, "evidence": {"receipt": 0}}
            ]
        )
        self.assertEqual(evaluate_case(case).status, Status.VERIFIED_COMPLETE)

    def test_false_is_valid_evidence_value(self) -> None:
        case = self.make_case(
            events=[
                {"action": "act", "success": True, "evidence": {"receipt": False}}
            ]
        )
        self.assertEqual(evaluate_case(case).status, Status.VERIFIED_COMPLETE)

    def test_wrong_action_does_not_satisfy_requirement(self) -> None:
        case = self.make_case(
            events=[
                {"action": "other", "success": True, "evidence": {"receipt": "r"}}
            ]
        )
        self.assertEqual(evaluate_case(case).status, Status.UNVERIFIED)

    def test_partial_when_some_requirements_proven(self) -> None:
        case = self.make_case(
            requirements=[
                {"action": "first", "evidence_fields": ["id"]},
                {"action": "second", "evidence_fields": ["id"]},
            ],
            events=[
                {"action": "first", "success": True, "evidence": {"id": "1"}}
            ],
        )
        self.assertEqual(evaluate_case(case).status, Status.PARTIAL)

    def test_failure_precedes_partial(self) -> None:
        case = self.make_case(
            requirements=[
                {"action": "first", "evidence_fields": ["id"]},
                {"action": "second", "evidence_fields": ["id"]},
            ],
            events=[
                {"action": "first", "success": True, "evidence": {"id": "1"}},
                {"action": "second", "success": False, "evidence": {}},
            ],
        )
        self.assertEqual(evaluate_case(case).status, Status.FAILED)

    def test_silent_evidenced_completion_is_verified(self) -> None:
        case = self.make_case(
            completion_claimed=False,
            events=[
                {"action": "act", "success": True, "evidence": {"receipt": "r"}}
            ],
        )
        result = evaluate_case(case)
        self.assertEqual(result.status, Status.VERIFIED_COMPLETE)
        self.assertTrue(any("no completion claim" in value for value in result.reasons))

    def test_duplicate_requirement_actions_are_each_evaluated(self) -> None:
        case = self.make_case(
            requirements=[
                {"action": "act", "evidence_fields": ["receipt"]},
                {"action": "act", "evidence_fields": ["receipt"]},
            ],
            events=[
                {"action": "act", "success": True, "evidence": {"receipt": "r"}}
            ],
        )
        result = evaluate_case(case)
        self.assertEqual(result.status, Status.VERIFIED_COMPLETE)
        self.assertEqual(result.proven_actions, ("act", "act"))


class InputValidationTests(unittest.TestCase):
    def test_case_requires_identifier(self) -> None:
        with self.assertRaises(ValueError):
            self.make_case(case_id="")

    def test_case_requires_task(self) -> None:
        with self.assertRaises(ValueError):
            self.make_case(task="")

    def test_completion_claimed_must_be_boolean(self) -> None:
        with self.assertRaises(ValueError):
            self.make_case(completion_claimed="yes")

    def test_requirements_must_not_be_empty(self) -> None:
        with self.assertRaises(ValueError):
            self.make_case(requirements=[])

    def test_events_must_be_a_list(self) -> None:
        with self.assertRaises(ValueError):
            self.make_case(events={})

    def test_requirement_requires_action(self) -> None:
        with self.assertRaises(ValueError):
            self.make_case(requirements=[{"action": "", "evidence_fields": []}])

    def test_evidence_fields_must_be_strings(self) -> None:
        with self.assertRaises(ValueError):
            self.make_case(
                requirements=[{"action": "act", "evidence_fields": [1]}]
            )

    def test_event_requires_action(self) -> None:
        with self.assertRaises(ValueError):
            self.make_case(events=[{"action": "", "success": True}])

    def test_event_success_must_be_boolean(self) -> None:
        with self.assertRaises(ValueError):
            self.make_case(events=[{"action": "act", "success": 1}])

    def test_event_evidence_must_be_object(self) -> None:
        with self.assertRaises(ValueError):
            self.make_case(
                events=[{"action": "act", "success": True, "evidence": []}]
            )


class LoaderAndCliTests(unittest.TestCase):
    def write_jsonl(self, *rows: str) -> Path:
        handle = tempfile.NamedTemporaryFile("w", encoding="utf-8", delete=False)
        self.addCleanup(lambda: Path(handle.name).unlink(missing_ok=True))
        with handle:
            handle.write("\n".join(rows))
        return Path(handle.name)

    def test_load_cases(self) -> None:
        path = self.write_jsonl(
            json.dumps(
                {
                    "case_id": "c1",
                    "task": "Task",
                    "completion_claimed": False,
                    "requirements": [{"action": "act", "evidence_fields": []}],
                    "events": [],
                }
            )
        )
        self.assertEqual(load_cases(path)[0].case_id, "c1")

    def test_loader_reports_line_number(self) -> None:
        path = self.write_jsonl("{}", "not-json")
        with self.assertRaisesRegex(ValueError, r":1:"):
            load_cases(path)

    def test_loader_rejects_empty_file(self) -> None:
        path = self.write_jsonl("")
        with self.assertRaisesRegex(ValueError, "No cases"):
            load_cases(path)

    def test_cli_text_output(self) -> None:
        path = self.write_jsonl(
            json.dumps(
                {
                    "case_id": "c1",
                    "task": "Task",
                    "completion_claimed": False,
                    "requirements": [{"action": "act", "evidence_fields": []}],
                    "events": [],
                }
            )
        )
        stdout = io.StringIO()
        with contextlib.redirect_stdout(stdout):
            with unittest.mock.patch("sys.argv", ["completion-verifier", str(path)]):
                self.assertEqual(main(), 0)
        self.assertIn("UNVERIFIED", stdout.getvalue())

    def test_cli_json_output(self) -> None:
        path = self.write_jsonl(
            json.dumps(
                {
                    "case_id": "c1",
                    "task": "Task",
                    "completion_claimed": False,
                    "requirements": [{"action": "act", "evidence_fields": []}],
                    "events": [],
                }
            )
        )
        stdout = io.StringIO()
        with contextlib.redirect_stdout(stdout):
            with unittest.mock.patch(
                "sys.argv", ["completion-verifier", str(path), "--json"]
            ):
                self.assertEqual(main(), 0)
        payload = json.loads(stdout.getvalue())
        self.assertEqual(payload[0]["status"], "UNVERIFIED")

    def test_invalid_json_exits_through_argparse(self) -> None:
        path = self.write_jsonl("not-json")
        with contextlib.redirect_stderr(io.StringIO()):
            with unittest.mock.patch("sys.argv", ["completion-verifier", str(path)]):
                with self.assertRaises(SystemExit):
                    main()


if __name__ == "__main__":
    unittest.main()
