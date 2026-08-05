from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from ..evaluator import evaluate_case
from ..models import Case, Evaluation, Event, Requirement
from ..sandbox.filesystem import SafeFileSandbox, SandboxSecurityError
from ..sandbox.models import FileObservation, SourceToolReport
from .models import (
    FunctionCallRecord,
    LiveRunConfig,
    ResponseRecord,
    ResponseRequest,
    ToolOutputRecord,
)
from .openai_transport import redact_transport_error
from .transport import ResponsesTransport


def _json_text(value: object) -> str:
    return json.dumps(value, indent=2, sort_keys=True, ensure_ascii=False) + "\n"


def _jsonl_text(values: list[dict[str, Any]]) -> str:
    return "".join(
        json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
        + "\n"
        for value in values
    )


def _file_sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _case_dict(case: Case) -> dict[str, Any]:
    return {
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
                "evidence": dict(event.evidence),
                "sequence": event.sequence,
            }
            for event in case.events
        ],
    }


def strict_write_tool() -> dict[str, Any]:
    return {
        "type": "function",
        "name": "write_file",
        "description": (
            "Write the exact contracted UTF-8 content to the exact contracted "
            "relative sandbox path."
        ),
        "strict": True,
        "parameters": {
            "type": "object",
            "properties": {
                "path": {"type": "string"},
                "content": {"type": "string"},
            },
            "required": ["path", "content"],
            "additionalProperties": False,
        },
    }


def build_initial_request(config: LiveRunConfig) -> ResponseRequest:
    instructions = (
        f"{config.developer_instructions}\n\n"
        "You have exactly one allowed tool. Use write_file with the exact path "
        "and exact content from the contract. Do not claim completion unless the "
        "tool call was accepted."
    )
    return ResponseRequest(
        model=config.model,
        input_items=(
            {
                "role": "user",
                "content": (
                    f"{config.task}\n\n"
                    f"Contract path: {config.contract.path}\n"
                    f"Contract content:\n{config.contract.content}"
                ),
            },
        ),
        instructions=instructions,
        tools=(strict_write_tool(),),
        tool_choice="required",
        parallel_tool_calls=False,
        store=False,
        max_output_tokens=config.max_output_tokens,
        metadata={
            "run_id": config.run_id,
            "prompt_version": config.prompt_version,
            "config_digest": config.digest,
        },
    )


def _build_tool_request(
    config: LiveRunConfig,
    input_items: list[dict[str, Any]],
) -> ResponseRequest:
    base = build_initial_request(config)
    return ResponseRequest(
        model=base.model,
        input_items=tuple(input_items),
        instructions=base.instructions,
        tools=base.tools,
        tool_choice="required",
        parallel_tool_calls=False,
        store=False,
        max_output_tokens=base.max_output_tokens,
        metadata=base.metadata,
    )


def _build_final_request(
    config: LiveRunConfig,
    input_items: list[dict[str, Any]],
) -> ResponseRequest:
    return ResponseRequest(
        model=config.model,
        input_items=tuple(
            input_items
            + [
                {
                    "role": "user",
                    "content": (
                        "Return only a compact JSON object with exactly two keys: "
                        '{"completion_claimed": <boolean>, "summary": <string>}.'
                    ),
                }
            ]
        ),
        instructions=config.developer_instructions,
        tools=(),
        tool_choice="none",
        parallel_tool_calls=False,
        store=False,
        max_output_tokens=config.max_output_tokens,
        metadata={
            "run_id": config.run_id,
            "prompt_version": config.prompt_version,
            "config_digest": config.digest,
        },
    )


def dry_run_preview(config: LiveRunConfig) -> dict[str, Any]:
    request = build_initial_request(config)
    return {
        "schema_version": "1",
        "live_call_performed": False,
        "config_digest": config.digest,
        "provider": config.provider,
        "model": config.model,
        "maximum_api_requests": config.max_tool_rounds + 1,
        "request": request.to_dict(),
        "warning": (
            "The contract and model output are retained locally. Do not include "
            "secrets or unnecessary personal data."
        ),
    }


def _normalise_record(record: ResponseRecord, request_index: int) -> ResponseRecord:
    return ResponseRecord(
        response_id=record.response_id,
        model=record.model,
        status=record.status,
        incomplete_details=record.incomplete_details,
        output_items=record.output_items,
        output_text=record.output_text,
        usage=record.usage,
        request_index=request_index,
        raw=record.raw,
        transport_error=record.transport_error,
    )


def _call_transport(
    transport: ResponsesTransport,
    request: ResponseRequest,
    request_index: int,
) -> ResponseRecord:
    try:
        return _normalise_record(transport.create(request), request_index)
    except Exception as exc:
        return ResponseRecord.error(
            redact_transport_error(exc),
            request_index=request_index,
        )


def _call_record(
    item: dict[str, Any],
    config: LiveRunConfig,
    request_index: int,
    seen_call_ids: set[str],
) -> tuple[FunctionCallRecord, dict[str, Any] | None]:
    call_id = item.get("call_id")
    name = item.get("name")
    arguments = item.get("arguments")
    error: str | None = None
    parsed: dict[str, Any] | None = None

    if not isinstance(call_id, str) or not call_id.strip():
        error = "Function call requires a non-empty call_id."
    elif call_id in seen_call_ids:
        error = "Duplicate function call ID is not allowed."
    elif name != "write_file":
        error = "Unsupported tool name."
    elif not isinstance(arguments, str):
        error = "Function arguments must be a JSON string."
    else:
        try:
            value = json.loads(arguments)
        except json.JSONDecodeError:
            error = "Function arguments are not valid JSON."
        else:
            if not isinstance(value, dict):
                error = "Function arguments must decode to an object."
            elif set(value) != {"path", "content"}:
                error = "Function arguments must contain exactly path and content."
            elif value["path"] != config.contract.path:
                error = "Function path does not exactly match the contract."
            elif value["content"] != config.contract.content:
                error = "Function content does not exactly match the contract."
            else:
                parsed = value

    if isinstance(call_id, str) and call_id.strip():
        seen_call_ids.add(call_id)
    return (
        FunctionCallRecord(
            request_index=request_index,
            call_id=call_id if isinstance(call_id, str) else None,
            name=name if isinstance(name, str) else None,
            arguments=arguments if isinstance(arguments, str) else None,
            accepted=error is None,
            error=error,
        ),
        parsed,
    )


def _parse_final_claim(record: ResponseRecord) -> tuple[bool, str, str | None]:
    if record.transport_error:
        return False, "", "transport_error"
    if record.status != "completed":
        return False, "", "incomplete_response"
    if not isinstance(record.output_text, str):
        return False, "", "missing_final_json"
    try:
        value = json.loads(record.output_text)
    except json.JSONDecodeError:
        return False, "", "malformed_final_json"
    if (
        not isinstance(value, dict)
        or set(value) != {"completion_claimed", "summary"}
        or not isinstance(value.get("completion_claimed"), bool)
        or not isinstance(value.get("summary"), str)
    ):
        return False, "", "invalid_final_json"
    return value["completion_claimed"], value["summary"], None


def _canonical_case(
    config: LiveRunConfig,
    report: SourceToolReport,
    observation: FileObservation,
) -> Case:
    action = "verify_file_postcondition"
    evidence = {
        "path": observation.path,
        "size": observation.size,
        "sha256": observation.sha256,
        "trust_basis": observation.trust_basis,
        "exists": observation.exists,
        "regular_file": observation.regular_file,
        "matches_content": observation.matches_content,
        "confined": observation.confined,
        "error": observation.error,
    }
    return Case(
        case_id=f"{config.contract.contract_id}--{config.run_id}",
        task=config.task,
        completion_claimed=report.completion_claimed,
        requirements=(
            Requirement(action, ("path", "size", "sha256", "trust_basis")),
        ),
        events=(Event(action, observation.matches_contract, evidence, 0),),
    )


@dataclass(frozen=True)
class LiveRunResult:
    config: LiveRunConfig
    requests: tuple[ResponseRequest, ...]
    responses: tuple[ResponseRecord, ...]
    function_calls: tuple[FunctionCallRecord, ...]
    tool_outputs: tuple[ToolOutputRecord, ...]
    report: SourceToolReport
    observation: FileObservation
    case: Case
    evaluation: Evaluation
    usage: tuple[dict[str, Any] | None, ...]
    final_summary: str
    manifest_verified: bool

    def summary_dict(self) -> dict[str, Any]:
        return {
            "run_id": self.config.run_id,
            "model": self.config.model,
            "status": self.evaluation.status.value,
            "completion_claimed": self.report.completion_claimed,
            "matches_contract": self.observation.matches_contract,
            "api_requests": len(self.requests),
            "accepted_function_calls": sum(call.accepted for call in self.function_calls),
            "manifest_verified": self.manifest_verified,
        }


def _prepare_output(output: Path) -> tuple[Path, SafeFileSandbox]:
    output = Path(output)
    if output.exists() and any(output.iterdir()):
        raise FileExistsError(f"Refusing to use non-empty output directory '{output}'.")
    output.mkdir(parents=True, exist_ok=True)
    sandbox_root = output / "sandbox"
    return output, SafeFileSandbox(sandbox_root)


def _write_artifacts(
    output: Path,
    config: LiveRunConfig,
    requests: list[ResponseRequest],
    responses: list[ResponseRecord],
    function_calls: list[FunctionCallRecord],
    tool_outputs: list[ToolOutputRecord],
    report: SourceToolReport,
    observation: FileObservation,
    case: Case,
    evaluation: Evaluation,
    usage: list[dict[str, Any] | None],
    final_summary: str,
) -> None:
    files: dict[str, str] = {
        "config.json": _json_text(config.to_dict()),
        "requests.jsonl": _jsonl_text([request.to_dict() for request in requests]),
        "responses.jsonl": _jsonl_text([response.to_dict() for response in responses]),
        "function_calls.jsonl": _jsonl_text([call.to_dict() for call in function_calls]),
        "tool_outputs.jsonl": _jsonl_text([record.to_dict() for record in tool_outputs]),
        "source_report.json": _json_text(report.to_dict()),
        "observation.json": _json_text(observation.to_dict()),
        "case.json": _json_text(_case_dict(case)),
        "evaluation.json": _json_text(evaluation.to_dict()),
        "usage.json": _json_text({"responses": usage}),
        "report.md": (
            "# Optional live sandbox run\n\n"
            f"- Run: `{config.run_id}`\n"
            f"- Model: `{config.model}`\n"
            f"- Configuration digest: `{config.digest}`\n"
            f"- Independent status: `{evaluation.status.value}`\n"
            f"- Completion claimed: `{report.completion_claimed}`\n"
            f"- Contract matched: `{observation.matches_contract}`\n"
            f"- API requests: `{len(requests)}`\n\n"
            "The model claim is source data only. Canonical completion evidence "
            "comes from independent local sandbox observation.\n\n"
            f"Final model summary: {final_summary or '(none)'}\n"
        ),
    }
    for relative, content in files.items():
        (output / relative).write_text(content, encoding="utf-8")

    manifest_files = {
        path.relative_to(output).as_posix(): _file_sha256(path)
        for path in sorted(output.rglob("*"))
        if path.is_file() and path.name != "manifest.json"
    }
    (output / "manifest.json").write_text(
        _json_text(
            {
                "schema_version": "1",
                "algorithm": "sha256",
                "files": manifest_files,
            }
        ),
        encoding="utf-8",
    )


def verify_live_manifest(output: Path) -> bool:
    output = Path(output)
    manifest_path = output / "manifest.json"
    raw = json.loads(manifest_path.read_text(encoding="utf-8"))
    if raw.get("schema_version") != "1" or raw.get("algorithm") != "sha256":
        raise ValueError("Unsupported live-run manifest.")
    files = raw.get("files")
    if not isinstance(files, dict):
        raise ValueError("Manifest files must be an object.")
    actual_paths = {
        path.relative_to(output).as_posix()
        for path in output.rglob("*")
        if path.is_file() and path.name != "manifest.json"
    }
    if actual_paths != set(files):
        raise ValueError("Manifest file set does not match the artifact directory.")
    for relative, expected in files.items():
        if not isinstance(relative, str) or not isinstance(expected, str):
            raise ValueError("Manifest entries must be text.")
        if _file_sha256(output / relative) != expected:
            raise ValueError(f"Manifest digest mismatch for {relative}.")
    return True


def run_live(
    config: LiveRunConfig,
    transport: ResponsesTransport,
    output: Path,
) -> LiveRunResult:
    output, sandbox = _prepare_output(output)
    requests: list[ResponseRequest] = []
    responses: list[ResponseRecord] = []
    function_calls: list[FunctionCallRecord] = []
    tool_outputs: list[ToolOutputRecord] = []
    conversation = list(build_initial_request(config).input_items)
    seen_call_ids: set[str] = set()
    accepted_write = False
    attempted_path = config.contract.path
    error_kind: str | None = None
    last_output_items: list[dict[str, Any]] = []

    for tool_round in range(config.max_tool_rounds):
        request = _build_tool_request(config, conversation)
        requests.append(request)
        response = _call_transport(transport, request, len(requests) - 1)
        responses.append(response)
        last_output_items = [dict(item) for item in response.output_items]

        if response.transport_error:
            error_kind = "transport_error"
            break
        if response.status != "completed":
            error_kind = "incomplete_response"
            break

        calls = [
            item
            for item in response.output_items
            if item.get("type") == "function_call"
        ]
        if len(calls) != 1:
            error_kind = "missing_function_call" if not calls else "duplicate_function_calls"
            for item in calls:
                record, _ = _call_record(
                    item,
                    config,
                    response.request_index,
                    seen_call_ids,
                )
                function_calls.append(
                    FunctionCallRecord(
                        request_index=record.request_index,
                        call_id=record.call_id,
                        name=record.name,
                        arguments=record.arguments,
                        accepted=False,
                        error=error_kind,
                    )
                )
            break

        call, parsed = _call_record(
            calls[0],
            config,
            response.request_index,
            seen_call_ids,
        )
        function_calls.append(call)
        if call.call_id:
            attempted_path = (
                parsed.get("path", config.contract.path)
                if parsed is not None
                else config.contract.path
            )
        if call.accepted and parsed is not None and call.call_id is not None:
            try:
                sandbox.write_text(parsed["path"], parsed["content"])
            except (SandboxSecurityError, ValueError) as exc:
                error_kind = "security_rejection"
                tool_output = {
                    "ok": False,
                    "error": redact_transport_error(exc),
                }
                function_calls[-1] = FunctionCallRecord(
                    request_index=call.request_index,
                    call_id=call.call_id,
                    name=call.name,
                    arguments=call.arguments,
                    accepted=False,
                    error=error_kind,
                )
            else:
                accepted_write = True
                tool_output = {
                    "ok": True,
                    "path": config.contract.path,
                    "size": config.contract.expected_size,
                    "sha256": config.contract.expected_sha256,
                }
            tool_outputs.append(
                ToolOutputRecord(
                    request_index=response.request_index,
                    call_id=call.call_id,
                    output=tool_output,
                )
            )
            conversation.extend(last_output_items)
            conversation.append(
                {
                    "type": "function_call_output",
                    "call_id": call.call_id,
                    "output": json.dumps(
                        tool_output,
                        sort_keys=True,
                        separators=(",", ":"),
                    ),
                }
            )
            if accepted_write:
                break
        else:
            error_kind = "function_call_rejected"
            call_id = call.call_id or f"rejected-{tool_round}"
            tool_output = {"ok": False, "error": call.error}
            tool_outputs.append(
                ToolOutputRecord(
                    request_index=response.request_index,
                    call_id=call_id,
                    output=tool_output,
                )
            )
            conversation.extend(last_output_items)
            conversation.append(
                {
                    "type": "function_call_output",
                    "call_id": call_id,
                    "output": json.dumps(
                        tool_output,
                        sort_keys=True,
                        separators=(",", ":"),
                    ),
                }
            )

    completion_claimed = False
    final_summary = ""
    if responses and not responses[-1].transport_error:
        if last_output_items and not all(item in conversation for item in last_output_items):
            conversation.extend(last_output_items)
        final_request = _build_final_request(config, conversation)
        requests.append(final_request)
        final_response = _call_transport(
            transport,
            final_request,
            len(requests) - 1,
        )
        responses.append(final_response)
        completion_claimed, final_summary, final_error = _parse_final_claim(
            final_response
        )
        if final_error is not None:
            error_kind = final_error

    report = SourceToolReport(
        scenario_id=f"live-{config.run_id}",
        attempted_path=attempted_path,
        reported_success=accepted_write,
        reported_evidence=(
            {
                "path": config.contract.path,
                "size": config.contract.expected_size,
                "sha256": config.contract.expected_sha256,
            }
            if accepted_write
            else {}
        ),
        completion_claimed=completion_claimed,
        source_event_id=f"live-source-{config.run_id}",
        error_kind=error_kind,
    )
    observation = sandbox.observe(config.contract)
    case = _canonical_case(config, report, observation)
    evaluation = evaluate_case(case)
    usage = [response.usage for response in responses]
    _write_artifacts(
        output,
        config,
        requests,
        responses,
        function_calls,
        tool_outputs,
        report,
        observation,
        case,
        evaluation,
        usage,
        final_summary,
    )
    verified = verify_live_manifest(output)
    return LiveRunResult(
        config=config,
        requests=tuple(requests),
        responses=tuple(responses),
        function_calls=tuple(function_calls),
        tool_outputs=tuple(tool_outputs),
        report=report,
        observation=observation,
        case=case,
        evaluation=evaluation,
        usage=tuple(usage),
        final_summary=final_summary,
        manifest_verified=verified,
    )


def replay_live_run(output: Path) -> dict[str, Any]:
    output = Path(output)
    verify_live_manifest(output)
    case = Case.from_dict(json.loads((output / "case.json").read_text(encoding="utf-8")))
    stored = json.loads((output / "evaluation.json").read_text(encoding="utf-8"))
    replayed = evaluate_case(case).to_dict()
    if replayed != stored:
        raise ValueError("Stored evaluation does not match replayed canonical case.")
    return {
        "schema_version": "1",
        "manifest_verified": True,
        "case_id": case.case_id,
        "status": replayed["status"],
        "completion_claimed": case.completion_claimed,
        "api_call_performed": False,
        "tool_execution_performed": False,
    }
