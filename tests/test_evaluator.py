import json
import tempfile
import unittest
from pathlib import Path

from completion_verifier.cli import load_cases
from completion_verifier.evaluator import evaluate_case, evaluate_cases
from completion_verifier.models import Case, Event, Requirement, Status


def make_case(
    claimed=True, requirements=None, events=None, case_id="case"
):
    return Case(
        case_id,
        "Test task",
        claimed,
        tuple(requirements or [Requirement("send_email", ("message_id",))]),
        tuple(events or []),
    )


class EvaluationTests(unittest.TestCase):
    def test_verified_single_action(self):
        result = evaluate_case(
            make_case(events=[Event("send_email", True, {"message_id": "1"})])
        )
        self.assertEqual(result.status, Status.VERIFIED_COMPLETE)

    def test_claim_without_events_is_unverified(self):
        self.assertEqual(evaluate_case(make_case()).status, Status.UNVERIFIED)

    def test_failed_action_is_failed(self):
        result = evaluate_case(make_case(events=[Event("send_email", False, {})]))
        self.assertEqual(result.status, Status.FAILED)

    def test_missing_evidence_is_unverified(self):
        result = evaluate_case(make_case(events=[Event("send_email", True, {})]))
        self.assertEqual(result.status, Status.UNVERIFIED)

    def test_empty_evidence_is_unverified(self):
        result = evaluate_case(
            make_case(events=[Event("send_email", True, {"message_id": ""})])
        )
        self.assertEqual(result.status, Status.UNVERIFIED)

    def test_whitespace_evidence_is_unverified(self):
        result = evaluate_case(
            make_case(events=[Event("send_email", True, {"message_id": "  "})])
        )
        self.assertEqual(result.status, Status.UNVERIFIED)

    def test_zero_is_a_valid_evidence_value(self):
        case = make_case(
            requirements=[Requirement("record_amount", ("amount",))],
            events=[Event("record_amount", True, {"amount": 0})],
        )
        self.assertEqual(evaluate_case(case).status, Status.VERIFIED_COMPLETE)

    def test_retry_recovers_failure(self):
        case = make_case(
            events=[
                Event("send_email", False, {}, 0),
                Event("send_email", True, {"message_id": "2"}, 1),
            ]
        )
        self.assertEqual(evaluate_case(case).status, Status.VERIFIED_COMPLETE)

    def test_later_failure_overrides_success(self):
        case = make_case(
            events=[
                Event("send_email", True, {"message_id": "2"}, 0),
                Event("send_email", False, {}, 1),
            ]
        )
        self.assertEqual(evaluate_case(case).status, Status.FAILED)

    def test_sequence_controls_latest_event_not_tuple_order(self):
        case = make_case(
            events=[
                Event("send_email", True, {"message_id": "2"}, 2),
                Event("send_email", False, {}, 1),
            ]
        )
        self.assertEqual(evaluate_case(case).status, Status.VERIFIED_COMPLETE)

    def test_wrong_action_does_not_prove(self):
        result = evaluate_case(
            make_case(events=[Event("archive_email", True, {"message_id": "2"})])
        )
        self.assertEqual(result.status, Status.UNVERIFIED)

    def test_partial_when_one_of_two_proven(self):
        case = make_case(
            requirements=[Requirement("a", ("id",)), Requirement("b", ("id",))],
            events=[Event("a", True, {"id": "1"})],
        )
        self.assertEqual(evaluate_case(case).status, Status.PARTIAL)

    def test_failure_takes_priority(self):
        case = make_case(
            requirements=[Requirement("a", ("id",)), Requirement("b", ("id",))],
            events=[Event("a", True, {"id": "1"}), Event("b", False, {})],
        )
        self.assertEqual(evaluate_case(case).status, Status.FAILED)

    def test_no_claim_can_still_be_verified(self):
        result = evaluate_case(
            make_case(
                claimed=False,
                events=[Event("send_email", True, {"message_id": "1"})],
            )
        )
        self.assertEqual(result.status, Status.VERIFIED_COMPLETE)

    def test_claim_warning_added(self):
        self.assertTrue(
            any("claimed completion" in reason for reason in evaluate_case(make_case()).reasons)
        )

    def test_proven_and_missing_reported(self):
        case = make_case(
            requirements=[Requirement("a", ("id",)), Requirement("b", ("id",))],
            events=[Event("a", True, {"id": "1"})],
        )
        result = evaluate_case(case)
        self.assertEqual(result.proven_actions, ("a",))
        self.assertEqual(result.missing_actions, ("b",))

    def test_failed_actions_reported(self):
        result = evaluate_case(make_case(events=[Event("send_email", False, {})]))
        self.assertEqual(result.failed_actions, ("send_email",))

    def test_multiple_fields_required(self):
        case = make_case(
            requirements=[Requirement("write", ("path", "sha"))],
            events=[Event("write", True, {"path": "/tmp/a"})],
        )
        self.assertEqual(evaluate_case(case).status, Status.UNVERIFIED)

    def test_multiple_fields_complete(self):
        case = make_case(
            requirements=[Requirement("write", ("path", "sha"))],
            events=[Event("write", True, {"path": "/tmp/a", "sha": "x"})],
        )
        self.assertEqual(evaluate_case(case).status, Status.VERIFIED_COMPLETE)

    def test_evaluate_cases_order(self):
        results = evaluate_cases([make_case(case_id="a"), make_case(case_id="b")])
        self.assertEqual([result.case_id for result in results], ["a", "b"])


class ParsingTests(unittest.TestCase):
    def test_event_requires_object(self):
        with self.assertRaises(ValueError):
            Event.from_dict([], 0)  # type: ignore[arg-type]

    def test_event_requires_action(self):
        with self.assertRaises(ValueError):
            Event.from_dict({"action": "", "success": True}, 0)

    def test_event_requires_boolean_success(self):
        with self.assertRaises(ValueError):
            Event.from_dict({"action": "x", "success": "yes"}, 0)

    def test_evidence_must_be_object(self):
        with self.assertRaises(ValueError):
            Event.from_dict({"action": "x", "success": True, "evidence": []}, 0)

    def test_requirement_requires_object(self):
        with self.assertRaises(ValueError):
            Requirement.from_dict([])  # type: ignore[arg-type]

    def test_requirement_requires_action(self):
        with self.assertRaises(ValueError):
            Requirement.from_dict({"action": "", "evidence_fields": []})

    def test_requirement_fields_must_be_strings(self):
        with self.assertRaises(ValueError):
            Requirement.from_dict({"action": "x", "evidence_fields": [1]})

    def test_case_requires_object(self):
        with self.assertRaises(ValueError):
            Case.from_dict([])  # type: ignore[arg-type]

    def test_case_requires_id(self):
        with self.assertRaises(ValueError):
            Case.from_dict(
                {
                    "case_id": "",
                    "task": "x",
                    "completion_claimed": True,
                    "requirements": [{"action": "x"}],
                    "events": [],
                }
            )

    def test_case_requires_boolean_claim(self):
        with self.assertRaises(ValueError):
            Case.from_dict(
                {
                    "case_id": "x",
                    "task": "x",
                    "completion_claimed": "yes",
                    "requirements": [{"action": "x"}],
                    "events": [],
                }
            )

    def test_case_requires_requirements(self):
        with self.assertRaises(ValueError):
            Case.from_dict(
                {
                    "case_id": "x",
                    "task": "x",
                    "completion_claimed": True,
                    "requirements": [],
                    "events": [],
                }
            )

    def test_load_cases_reads_jsonl(self):
        raw = {
            "case_id": "x",
            "task": "x",
            "completion_claimed": True,
            "requirements": [
                {"action": "send_email", "evidence_fields": ["message_id"]}
            ],
            "events": [],
        }
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "cases.jsonl"
            path.write_text(json.dumps(raw) + "\n", encoding="utf-8")
            self.assertEqual(load_cases(path)[0].case_id, "x")

    def test_load_cases_rejects_empty(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "cases.jsonl"
            path.write_text("", encoding="utf-8")
            with self.assertRaises(ValueError):
                load_cases(path)

    def test_load_cases_bad_json(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "cases.jsonl"
            path.write_text("{bad}\n", encoding="utf-8")
            with self.assertRaises(ValueError):
                load_cases(path)


if __name__ == "__main__":
    unittest.main()
