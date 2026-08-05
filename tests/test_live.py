import contextlib
import io
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from completion_verifier.live import (
    FakeResponsesTransport,
    LiveRunConfig,
    build_initial_request,
    dry_run_preview,
    replay_live_run,
    run_live,
    strict_write_tool,
    verify_live_manifest,
)
from completion_verifier.models import Status


BASE = {
    "run_id": "live-test-v1",
    "provider": "openai",
    "prompt_version": "p1",
    "developer_instructions": "Follow the exact contract.",
    "task": "Write the customer update.",
    "generated_at": "2026-08-05T00:00:00Z",
    "max_tool_rounds": 2,
    "max_output_tokens": 256,
    "contract": {
        "contract_id": "write-update",
        "path": "output/update.txt",
        "content": "done\n",
    },
}


def config(**updates):
    raw = dict(BASE)
    raw.update(updates)
    return LiveRunConfig.from_dict(raw, model="gpt-test")


def tool_response(
    *,
    path="output/update.txt",
    content="done\n",
    call_id="call-1",
    name="write_file",
    arguments=None,
    calls=1,
    status="completed",
    usage=None,
):
    if arguments is None:
        arguments = json.dumps({"path": path, "content": content})
    output = [
        {
            "type": "function_call",
            "call_id": f"{call_id}-{index}" if calls > 1 else call_id,
            "name": name,
            "arguments": arguments,
        }
        for index in range(calls)
    ]
    return {
        "id": "resp-tool",
        "model": "gpt-test",
        "status": status,
        "output": output,
        "usage": usage,
    }


def final_response(claim=True, summary="done", *, raw_text=None, status="completed", usage=None):
    return {
        "id": "resp-final",
        "model": "gpt-test",
        "status": status,
        "output": [],
        "output_text": raw_text
        if raw_text is not None
        else json.dumps({"completion_claimed": claim, "summary": summary}),
        "usage": usage,
    }


class ConfigAndRequestTests(unittest.TestCase):
    def test_model_is_explicit(self):
        with self.assertRaisesRegex(ValueError, "model"):
            LiveRunConfig.from_dict(BASE)

    def test_provider_is_fixed(self):
        with self.assertRaisesRegex(ValueError, "openai"):
            config(provider="other")

    def test_round_bounds(self):
        for value in (0, 5, True):
            with self.subTest(value=value), self.assertRaises(ValueError):
                config(max_tool_rounds=value)

    def test_output_token_bounds(self):
        for value in (0, 4097, True):
            with self.subTest(value=value), self.assertRaises(ValueError):
                config(max_output_tokens=value)

    def test_digest_is_deterministic(self):
        self.assertEqual(config().digest, config().digest)
        self.assertEqual(len(config().digest), 64)

    def test_request_has_cost_and_privacy_controls(self):
        request = build_initial_request(config()).to_dict()
        self.assertFalse(request["store"])
        self.assertFalse(request["parallel_tool_calls"])
        self.assertEqual(request["tool_choice"], "required")
        self.assertEqual(request["max_output_tokens"], 256)
        self.assertEqual(request["model"], "gpt-test")

    def test_tool_schema_is_strict_and_single_purpose(self):
        tool = strict_write_tool()
        self.assertEqual(tool["name"], "write_file")
        self.assertTrue(tool["strict"])
        self.assertFalse(tool["parameters"]["additionalProperties"])
        self.assertEqual(tool["parameters"]["required"], ["path", "content"])

    def test_dry_run_has_no_live_side_effect(self):
        preview = dry_run_preview(config())
        self.assertFalse(preview["live_call_performed"])
        self.assertEqual(preview["maximum_api_requests"], 3)
        self.assertFalse(preview["request"]["store"])


class TransportAndRunnerTests(unittest.TestCase):
    def run_case(self, fixtures):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        output = Path(temp.name) / "run"
        transport = FakeResponsesTransport(fixtures)
        result = run_live(config(), transport, output)
        return result, output, transport

    def test_fake_transport_records_requests(self):
        result, _, transport = self.run_case([tool_response(), final_response()])
        self.assertEqual(len(transport.requests), 2)
        self.assertEqual(len(result.requests), 2)

    def test_valid_write_is_independently_verified(self):
        result, output, _ = self.run_case([tool_response(), final_response()])
        self.assertTrue(result.observation.matches_contract)
        self.assertEqual(result.evaluation.status, Status.VERIFIED_COMPLETE)
        self.assertEqual((output / "sandbox/output/update.txt").read_text(), "done\n")

    def test_valid_write_without_claim_remains_verified(self):
        result, _, _ = self.run_case([tool_response(), final_response(False)])
        self.assertFalse(result.report.completion_claimed)
        self.assertEqual(result.evaluation.status, Status.VERIFIED_COMPLETE)

    def test_wrong_path_is_rejected_without_write(self):
        result, output, _ = self.run_case(
            [tool_response(path="other.txt"), tool_response(path="other.txt", call_id="call-2"), final_response(True)]
        )
        self.assertFalse(result.observation.exists)
        self.assertFalse((output / "sandbox/other.txt").exists())
        self.assertTrue(all(not call.accepted for call in result.function_calls))

    def test_wrong_content_is_rejected(self):
        result, _, _ = self.run_case(
            [tool_response(content="wrong"), tool_response(content="wrong", call_id="call-2"), final_response(True)]
        )
        self.assertFalse(result.observation.exists)
        self.assertEqual(result.evaluation.status, Status.FAILED)

    def test_malformed_arguments_are_rejected(self):
        result, _, _ = self.run_case(
            [tool_response(arguments="{"), tool_response(arguments="{", call_id="call-2"), final_response(True)]
        )
        self.assertIn("valid JSON", result.function_calls[0].error)

    def test_extra_argument_is_rejected(self):
        args = json.dumps({"path": "output/update.txt", "content": "done\n", "extra": True})
        result, _, _ = self.run_case(
            [tool_response(arguments=args), tool_response(arguments=args, call_id="call-2"), final_response(True)]
        )
        self.assertIn("exactly", result.function_calls[0].error)

    def test_unsupported_tool_is_rejected(self):
        result, _, _ = self.run_case(
            [tool_response(name="shell"), tool_response(name="shell", call_id="call-2"), final_response(True)]
        )
        self.assertIn("Unsupported", result.function_calls[0].error)

    def test_duplicate_calls_fail_closed(self):
        result, _, _ = self.run_case([tool_response(calls=2), final_response(True)])
        self.assertFalse(result.observation.exists)
        self.assertEqual(result.report.error_kind, "duplicate_function_calls")
        self.assertTrue(all(not call.accepted for call in result.function_calls))

    def test_missing_call_id_is_rejected(self):
        response = tool_response()
        response["output"][0]["call_id"] = None
        result, _, _ = self.run_case([response, response, final_response(True)])
        self.assertIn("call_id", result.function_calls[0].error)

    def test_incomplete_response_fails_closed(self):
        result, _, _ = self.run_case([tool_response(status="incomplete"), final_response(True)])
        self.assertFalse(result.observation.exists)
        self.assertEqual(result.report.error_kind, "incomplete_response")
        self.assertEqual(result.evaluation.status, Status.FAILED)

    def test_transport_exception_is_recorded(self):
        result, _, _ = self.run_case([RuntimeError("Bearer secret-token")])
        self.assertIn("[REDACTED]", result.responses[0].transport_error)
        self.assertFalse(result.observation.exists)

    def test_no_tool_call_fails_closed(self):
        response = {"id": "r", "model": "m", "status": "completed", "output": []}
        result, _, _ = self.run_case([response, final_response(True)])
        self.assertEqual(result.report.error_kind, "missing_function_call")
        self.assertFalse(result.observation.exists)
        self.assertEqual(result.evaluation.status, Status.FAILED)

    def test_malformed_final_json_does_not_claim_completion(self):
        result, _, _ = self.run_case([tool_response(), final_response(raw_text="{")])
        self.assertFalse(result.report.completion_claimed)
        self.assertEqual(result.report.error_kind, "malformed_final_json")
        self.assertEqual(result.evaluation.status, Status.VERIFIED_COMPLETE)

    def test_fabricated_claim_cannot_override_observation(self):
        response = {"id": "r", "model": "m", "status": "completed", "output": []}
        result, _, _ = self.run_case([response, final_response(True)])
        self.assertTrue(result.report.completion_claimed)
        self.assertFalse(result.observation.matches_contract)
        self.assertEqual(result.evaluation.status, Status.FAILED)

    def test_usage_is_preserved_not_estimated(self):
        first = {"input_tokens": 12, "output_tokens": 3, "total_tokens": 15}
        second = {"input_tokens": 20, "output_tokens": 4, "total_tokens": 24}
        result, output, _ = self.run_case(
            [tool_response(usage=first), final_response(usage=second)]
        )
        self.assertEqual(result.usage, (first, second))
        self.assertEqual(json.loads((output / "usage.json").read_text())["responses"], [first, second])

    def test_output_directory_must_be_empty(self):
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "run"
            output.mkdir()
            (output / "keep").write_text("x")
            with self.assertRaisesRegex(FileExistsError, "non-empty"):
                run_live(config(), FakeResponsesTransport([]), output)

    def test_artifacts_are_separated(self):
        _, output, _ = self.run_case([tool_response(), final_response()])
        for name in (
            "config.json",
            "requests.jsonl",
            "responses.jsonl",
            "function_calls.jsonl",
            "tool_outputs.jsonl",
            "source_report.json",
            "observation.json",
            "case.json",
            "evaluation.json",
            "usage.json",
            "report.md",
            "manifest.json",
        ):
            self.assertTrue((output / name).is_file(), name)

    def test_manifest_detects_tampering(self):
        _, output, _ = self.run_case([tool_response(), final_response()])
        (output / "evaluation.json").write_text("{}")
        with self.assertRaisesRegex(ValueError, "digest mismatch"):
            verify_live_manifest(output)

    def test_manifest_detects_untracked_file(self):
        _, output, _ = self.run_case([tool_response(), final_response()])
        (output / "extra.txt").write_text("x")
        with self.assertRaisesRegex(ValueError, "file set"):
            verify_live_manifest(output)

    def test_replay_rechecks_case_without_call_or_write(self):
        _, output, _ = self.run_case([tool_response(), final_response()])
        replay = replay_live_run(output)
        self.assertTrue(replay["manifest_verified"])
        self.assertFalse(replay["api_call_performed"])
        self.assertFalse(replay["tool_execution_performed"])
        self.assertEqual(replay["status"], "VERIFIED_COMPLETE")

    def test_api_key_is_not_persisted(self):
        secret = "sk-test-super-secret-value"
        with mock.patch.dict(os.environ, {"OPENAI_API_KEY": secret}):
            _, output, _ = self.run_case([tool_response(), final_response()])
        retained = "\n".join(
            path.read_text(encoding="utf-8", errors="ignore")
            for path in output.rglob("*")
            if path.is_file()
        )
        self.assertNotIn(secret, retained)


class CliTests(unittest.TestCase):
    def write_config(self, root):
        path = root / "config.json"
        path.write_text(json.dumps(BASE))
        return path

    def test_cli_dry_run_needs_no_key_or_sdk(self):
        from completion_verifier.live_cli import main
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            config_path = self.write_config(root)
            stdout = io.StringIO()
            with contextlib.redirect_stdout(stdout), mock.patch.dict(os.environ, {}, clear=True), mock.patch(
                "sys.argv",
                ["completion-verifier-live", "openai", "--config", str(config_path), "--output", str(root / "out"), "--model", "gpt-test", "--dry-run"],
            ):
                self.assertEqual(main(), 0)
            payload = json.loads(stdout.getvalue())
            self.assertFalse(payload["live_call_performed"])
            self.assertFalse((root / "out").exists())

    def test_cli_requires_confirmation(self):
        from completion_verifier.live_cli import main
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            config_path = self.write_config(root)
            with mock.patch(
                "sys.argv",
                ["completion-verifier-live", "openai", "--config", str(config_path), "--output", str(root / "out"), "--model", "gpt-test"],
            ), self.assertRaisesRegex(SystemExit, "confirm-live"):
                main()

    def test_cli_requires_key(self):
        from completion_verifier.live_cli import main
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            config_path = self.write_config(root)
            with mock.patch.dict(os.environ, {}, clear=True), mock.patch(
                "sys.argv",
                ["completion-verifier-live", "openai", "--config", str(config_path), "--output", str(root / "out"), "--model", "gpt-test", "--confirm-live"],
            ), self.assertRaisesRegex(SystemExit, "OPENAI_API_KEY"):
                main()


if __name__ == "__main__":
    unittest.main()
