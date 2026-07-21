import contextlib
import io
import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from completion_verifier.adapters import (
    AdaptedEvent,
    TraceAdapterError,
    TraceEnvelope,
    TraceSource,
    canonical_json_sha256,
)
from completion_verifier.evaluator import evaluate_case
from completion_verifier.models import Requirement, Status


class EnvelopeTests(unittest.TestCase):
    def test_digest_is_deterministic_for_equivalent_json(self) -> None:
        left = {"b": 2, "a": [1, {"x": True}]}
        right = {"a": [1, {"x": True}], "b": 2}
        self.assertEqual(canonical_json_sha256(left), canonical_json_sha256(right))

    def test_envelope_converts_without_putting_provenance_in_evidence(self) -> None:
        envelope = TraceEnvelope(
            trace_id="trace-1",
            task="Send an email",
            completion_claimed=True,
            requirements=(Requirement("send_email", ("message_id",)),),
            events=(
                AdaptedEvent(
                    action="send_email",
                    success=True,
                    evidence={},
                    sequence=0,
                    source_event_id="event-1",
                ),
            ),
            source=TraceSource(
                adapter="generic-json@1",
                source_type="generic-json",
                source_ref="run-1",
                raw_sha256="a" * 64,
            ),
        )
        case = envelope.to_case()
        self.assertEqual(evaluate_case(case).status, Status.UNVERIFIED)
        self.assertNotIn("source_event_id", case.events[0].evidence)

    def test_empty_source_reference_is_rejected(self) -> None:
        with self.assertRaises(TraceAdapterError):
            TraceSource("generic-json@1", "generic-json", "", "a" * 64)

    def test_invalid_digest_is_rejected(self) -> None:
        with self.assertRaises(TraceAdapterError):
            TraceSource("generic-json@1", "generic-json", "run-1", "not-a-digest")

    def test_envelope_serialization_separates_case_and_source(self) -> None:
        envelope = TraceEnvelope(
            trace_id="trace-2",
            task="Archive a file",
            completion_claimed=False,
            requirements=(Requirement("archive_file", ("path",)),),
            events=(
                AdaptedEvent(
                    action="archive_file",
                    success=True,
                    evidence={"path": "/tmp/a"},
                    sequence=0,
                    source_event_id="event-2",
                ),
            ),
            source=TraceSource(
                adapter="generic-json@1",
                source_type="generic-json",
                source_ref="run-2",
                raw_sha256="b" * 64,
            ),
        )
        payload = envelope.to_dict()
        case_payload = envelope.case_dict()
        self.assertEqual(payload["source"]["source_ref"], "run-2")
        self.assertEqual(payload["events"][0]["source_event_id"], "event-2")
        self.assertNotIn("source", case_payload)
        self.assertNotIn("source_event_id", case_payload["events"][0])


class GenericJsonAdapterTests(unittest.TestCase):
    def setUp(self) -> None:
        from completion_verifier.adapters import GenericJsonTraceAdapter

        self.adapter = GenericJsonTraceAdapter()
        self.requirements = (Requirement("send_email", ("message_id",)),)

    def trace(self, events: list[dict[str, object]]) -> dict[str, object]:
        return {
            "trace_id": "generic-1",
            "task": "Send an email",
            "completion_claimed": True,
            "events": events,
        }

    def adapt(self, events: list[dict[str, object]]):
        return self.adapter.adapt(
            self.trace(events),
            requirements=self.requirements,
            source_ref="run-1",
        )

    def test_successful_event_is_adapted(self) -> None:
        envelope = self.adapt([
            {
                "source_event_id": "e1",
                "action": "send_email",
                "success": True,
                "evidence": {"message_id": "m1"},
            }
        ])
        self.assertEqual(envelope.to_case().events[0].sequence, 0)
        self.assertEqual(evaluate_case(envelope.to_case()).status, Status.VERIFIED_COMPLETE)

    def test_timeout_failure_is_preserved(self) -> None:
        envelope = self.adapt([
            {
                "source_event_id": "e1",
                "action": "send_email",
                "success": False,
                "evidence": {"error": "timeout"},
            }
        ])
        self.assertEqual(evaluate_case(envelope.to_case()).status, Status.FAILED)

    def test_permission_failure_is_preserved(self) -> None:
        envelope = self.adapt([
            {
                "source_event_id": "e1",
                "action": "send_email",
                "success": False,
                "evidence": {"error": "permission_denied"},
            }
        ])
        self.assertEqual(envelope.events[0].evidence["error"], "permission_denied")

    def test_retry_preserves_order_and_recovers(self) -> None:
        envelope = self.adapt([
            {"source_event_id": "e1", "action": "send_email", "success": False, "evidence": {"error": "timeout"}},
            {"source_event_id": "e2", "action": "send_email", "success": True, "evidence": {"message_id": "m2"}},
        ])
        self.assertEqual([event.sequence for event in envelope.events], [0, 1])
        self.assertEqual(evaluate_case(envelope.to_case()).status, Status.VERIFIED_COMPLETE)

    def test_later_rollback_overrides_success(self) -> None:
        envelope = self.adapt([
            {"source_event_id": "e1", "action": "send_email", "success": True, "evidence": {"message_id": "m1"}},
            {"source_event_id": "e2", "action": "send_email", "success": False, "evidence": {"error": "rollback"}},
        ])
        self.assertEqual(evaluate_case(envelope.to_case()).status, Status.FAILED)

    def test_missing_receipt_remains_unverified(self) -> None:
        envelope = self.adapt([
            {"source_event_id": "e1", "action": "send_email", "success": True, "evidence": {}}
        ])
        self.assertEqual(evaluate_case(envelope.to_case()).status, Status.UNVERIFIED)

    def test_unrelated_unknown_action_is_retained_but_does_not_prove(self) -> None:
        envelope = self.adapt([
            {"source_event_id": "e1", "action": "archive_email", "success": True, "evidence": {"message_id": "m1"}}
        ])
        self.assertEqual(envelope.events[0].action, "archive_email")
        self.assertEqual(evaluate_case(envelope.to_case()).status, Status.UNVERIFIED)

    def test_non_boolean_success_is_rejected(self) -> None:
        with self.assertRaisesRegex(TraceAdapterError, "success"):
            self.adapt([
                {"source_event_id": "e1", "action": "send_email", "success": "yes", "evidence": {}}
            ])

    def test_non_object_evidence_is_rejected(self) -> None:
        with self.assertRaisesRegex(TraceAdapterError, "evidence"):
            self.adapt([
                {"source_event_id": "e1", "action": "send_email", "success": True, "evidence": []}
            ])

    def test_duplicate_source_event_id_is_rejected(self) -> None:
        with self.assertRaisesRegex(TraceAdapterError, "duplicate"):
            self.adapt([
                {"source_event_id": "e1", "action": "send_email", "success": False, "evidence": {}},
                {"source_event_id": "e1", "action": "send_email", "success": True, "evidence": {"message_id": "m2"}},
            ])

    def test_raw_digest_matches_source_object(self) -> None:
        raw = self.trace([
            {"source_event_id": "e1", "action": "send_email", "success": True, "evidence": {"message_id": "m1"}}
        ])
        envelope = self.adapter.adapt(raw, requirements=self.requirements, source_ref="run-2")
        self.assertEqual(envelope.source.raw_sha256, canonical_json_sha256(raw))


class OpenAITraceAdapterTests(unittest.TestCase):
    def setUp(self) -> None:
        from completion_verifier.adapters import OpenAIToolTraceAdapter

        self.adapter = OpenAIToolTraceAdapter()
        self.requirements = (Requirement("send_email", ("message_id",)),)

    def trace(self, records: list[dict[str, object]]) -> dict[str, object]:
        return {
            "trace_id": "openai-1",
            "task": "Send an email",
            "completion_claimed": True,
            "records": records,
        }

    def adapt(self, records: list[dict[str, object]]):
        return self.adapter.adapt(
            self.trace(records),
            requirements=self.requirements,
            source_ref="response-1",
        )

    def test_call_and_result_are_paired_by_id(self) -> None:
        envelope = self.adapt([
            {"type": "tool_call", "tool_call_id": "call-1", "name": "send_email", "arguments": {"to": "a@example.com"}},
            {"type": "tool_result", "tool_call_id": "call-1", "success": True, "evidence": {"message_id": "m1"}},
        ])
        self.assertEqual(envelope.events[0].source_event_id, "call-1")
        self.assertEqual(envelope.events[0].action, "send_email")
        self.assertNotIn("to", envelope.events[0].evidence)
        self.assertEqual(evaluate_case(envelope.to_case()).status, Status.VERIFIED_COMPLETE)

    def test_unmatched_call_is_rejected(self) -> None:
        with self.assertRaisesRegex(TraceAdapterError, "no result"):
            self.adapt([
                {"type": "tool_call", "tool_call_id": "call-1", "name": "send_email", "arguments": {}}
            ])

    def test_unmatched_result_is_rejected(self) -> None:
        with self.assertRaisesRegex(TraceAdapterError, "no call"):
            self.adapt([
                {"type": "tool_result", "tool_call_id": "call-1", "success": True, "evidence": {"message_id": "m1"}}
            ])

    def test_duplicate_call_id_is_rejected(self) -> None:
        with self.assertRaisesRegex(TraceAdapterError, "duplicate tool_call"):
            self.adapt([
                {"type": "tool_call", "tool_call_id": "call-1", "name": "send_email", "arguments": {}},
                {"type": "tool_call", "tool_call_id": "call-1", "name": "send_email", "arguments": {}},
                {"type": "tool_result", "tool_call_id": "call-1", "success": True, "evidence": {"message_id": "m1"}},
            ])

    def test_duplicate_result_id_is_rejected(self) -> None:
        with self.assertRaisesRegex(TraceAdapterError, "duplicate tool_result"):
            self.adapt([
                {"type": "tool_call", "tool_call_id": "call-1", "name": "send_email", "arguments": {}},
                {"type": "tool_result", "tool_call_id": "call-1", "success": False, "evidence": {"error": "timeout"}},
                {"type": "tool_result", "tool_call_id": "call-1", "success": True, "evidence": {"message_id": "m1"}},
            ])

    def test_unsupported_record_type_is_rejected(self) -> None:
        with self.assertRaisesRegex(TraceAdapterError, "unsupported record type"):
            self.adapt([{"type": "assistant_message", "text": "done"}])

    def test_result_success_must_be_boolean(self) -> None:
        with self.assertRaisesRegex(TraceAdapterError, "success"):
            self.adapt([
                {"type": "tool_call", "tool_call_id": "call-1", "name": "send_email", "arguments": {}},
                {"type": "tool_result", "tool_call_id": "call-1", "success": "yes", "evidence": {}},
            ])

    def test_result_evidence_must_be_object(self) -> None:
        with self.assertRaisesRegex(TraceAdapterError, "evidence"):
            self.adapt([
                {"type": "tool_call", "tool_call_id": "call-1", "name": "send_email", "arguments": {}},
                {"type": "tool_result", "tool_call_id": "call-1", "success": True, "evidence": []},
            ])

    def test_call_arguments_must_be_object(self) -> None:
        with self.assertRaisesRegex(TraceAdapterError, "arguments"):
            self.adapt([
                {"type": "tool_call", "tool_call_id": "call-1", "name": "send_email", "arguments": []},
                {"type": "tool_result", "tool_call_id": "call-1", "success": True, "evidence": {"message_id": "m1"}},
            ])

    def test_event_order_follows_call_order_not_result_order(self) -> None:
        requirements = (
            Requirement("first", ("id",)),
            Requirement("second", ("id",)),
        )
        envelope = self.adapter.adapt(
            self.trace([
                {"type": "tool_call", "tool_call_id": "call-1", "name": "first", "arguments": {}},
                {"type": "tool_call", "tool_call_id": "call-2", "name": "second", "arguments": {}},
                {"type": "tool_result", "tool_call_id": "call-2", "success": True, "evidence": {"id": "2"}},
                {"type": "tool_result", "tool_call_id": "call-1", "success": True, "evidence": {"id": "1"}},
            ]),
            requirements=requirements,
            source_ref="response-2",
        )
        self.assertEqual([event.action for event in envelope.events], ["first", "second"])
        self.assertEqual([event.sequence for event in envelope.events], [0, 1])


class AdapterCliTests(unittest.TestCase):
    def write_json(self, root: Path, name: str, payload: object) -> Path:
        path = root / name
        path.write_text(json.dumps(payload), encoding="utf-8")
        return path

    def fixture_paths(self, root: Path) -> tuple[Path, Path]:
        trace_path = self.write_json(
            root,
            "trace.json",
            {
                "trace_id": "cli-1",
                "task": "Send",
                "completion_claimed": True,
                "events": [
                    {
                        "source_event_id": "e1",
                        "action": "send_email",
                        "success": True,
                        "evidence": {"message_id": "m1"},
                    }
                ],
            },
        )
        requirements_path = self.write_json(
            root,
            "requirements.json",
            [{"action": "send_email", "evidence_fields": ["message_id"]}],
        )
        return trace_path, requirements_path

    def test_generic_cli_emits_case_json(self) -> None:
        from completion_verifier.adapter_cli import main as adapter_main

        with tempfile.TemporaryDirectory() as directory:
            trace_path, requirements_path = self.fixture_paths(Path(directory))
            stdout = io.StringIO()
            with contextlib.redirect_stdout(stdout), mock.patch(
                "sys.argv",
                [
                    "completion-verifier-adapt",
                    "generic",
                    str(trace_path),
                    str(requirements_path),
                    "--source-ref",
                    "run-1",
                ],
            ):
                self.assertEqual(adapter_main(), 0)
        payload = json.loads(stdout.getvalue())
        self.assertEqual(payload["case_id"], "cli-1")
        self.assertNotIn("source", payload)

    def test_envelope_flag_emits_provenance(self) -> None:
        from completion_verifier.adapter_cli import main as adapter_main

        with tempfile.TemporaryDirectory() as directory:
            trace_path, requirements_path = self.fixture_paths(Path(directory))
            stdout = io.StringIO()
            with contextlib.redirect_stdout(stdout), mock.patch(
                "sys.argv",
                [
                    "completion-verifier-adapt",
                    "generic",
                    str(trace_path),
                    str(requirements_path),
                    "--source-ref",
                    "run-1",
                    "--envelope",
                ],
            ):
                self.assertEqual(adapter_main(), 0)
        payload = json.loads(stdout.getvalue())
        self.assertEqual(payload["source"]["source_ref"], "run-1")
        self.assertEqual(len(payload["source"]["raw_sha256"]), 64)

    def test_requirements_file_must_be_a_non_empty_list(self) -> None:
        from completion_verifier.adapter_cli import load_requirements

        with tempfile.TemporaryDirectory() as directory:
            path = self.write_json(Path(directory), "requirements.json", {})
            with self.assertRaisesRegex(ValueError, "non-empty JSON array"):
                load_requirements(path)

    def test_unknown_adapter_is_rejected_by_argparse(self) -> None:
        from completion_verifier.adapter_cli import main as adapter_main

        with contextlib.redirect_stderr(io.StringIO()), mock.patch(
            "sys.argv", ["completion-verifier-adapt", "unknown", "a", "b", "--source-ref", "x"]
        ):
            with self.assertRaises(SystemExit):
                adapter_main()


if __name__ == "__main__":
    unittest.main()
