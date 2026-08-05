from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from ..adapters import canonical_json_sha256
from ..sandbox.models import FileWriteContract, required_text


def _json_object(value: object, name: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ValueError(f"'{name}' must be a JSON object.")
    return dict(value)


@dataclass(frozen=True)
class LiveRunConfig:
    run_id: str
    provider: str
    model: str
    prompt_version: str
    developer_instructions: str
    task: str
    contract: FileWriteContract
    generated_at: str
    max_tool_rounds: int = 2
    max_output_tokens: int = 512
    schema_version: str = "1"

    def __post_init__(self) -> None:
        for name in (
            "run_id",
            "provider",
            "model",
            "prompt_version",
            "developer_instructions",
            "task",
            "generated_at",
            "schema_version",
        ):
            object.__setattr__(self, name, required_text(getattr(self, name), name))
        if self.provider != "openai":
            raise ValueError("The first live runner supports provider 'openai' only.")
        if self.schema_version != "1":
            raise ValueError(f"Unsupported live schema_version '{self.schema_version}'.")
        if type(self.max_tool_rounds) is not int or not 1 <= self.max_tool_rounds <= 4:
            raise ValueError("'max_tool_rounds' must be an integer from 1 to 4.")
        if type(self.max_output_tokens) is not int or not 1 <= self.max_output_tokens <= 4096:
            raise ValueError("'max_output_tokens' must be an integer from 1 to 4096.")

    @classmethod
    def from_dict(cls, raw: object, *, model: str | None = None) -> "LiveRunConfig":
        data = _json_object(raw, "configuration")
        resolved_model = model if model is not None else data.get("model")
        return cls(
            run_id=data.get("run_id"),
            provider=data.get("provider", "openai"),
            model=resolved_model,
            prompt_version=data.get("prompt_version"),
            developer_instructions=data.get("developer_instructions"),
            task=data.get("task"),
            contract=FileWriteContract.from_dict(data.get("contract")),
            generated_at=data.get("generated_at"),
            max_tool_rounds=data.get("max_tool_rounds", 2),
            max_output_tokens=data.get("max_output_tokens", 512),
            schema_version=data.get("schema_version", "1"),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "run_id": self.run_id,
            "provider": self.provider,
            "model": self.model,
            "prompt_version": self.prompt_version,
            "developer_instructions": self.developer_instructions,
            "task": self.task,
            "contract": self.contract.to_dict(),
            "generated_at": self.generated_at,
            "max_tool_rounds": self.max_tool_rounds,
            "max_output_tokens": self.max_output_tokens,
            "schema_version": self.schema_version,
        }

    @property
    def digest(self) -> str:
        return canonical_json_sha256(self.to_dict())


@dataclass(frozen=True)
class ResponseRequest:
    model: str
    input_items: tuple[dict[str, Any], ...]
    instructions: str
    tools: tuple[dict[str, Any], ...]
    tool_choice: str
    parallel_tool_calls: bool
    store: bool
    max_output_tokens: int
    metadata: dict[str, str]

    def to_dict(self) -> dict[str, Any]:
        value: dict[str, Any] = {
            "model": self.model,
            "input": [dict(item) for item in self.input_items],
            "instructions": self.instructions,
            "tools": [dict(tool) for tool in self.tools],
            "tool_choice": self.tool_choice,
            "parallel_tool_calls": self.parallel_tool_calls,
            "store": self.store,
            "max_output_tokens": self.max_output_tokens,
            "metadata": dict(self.metadata),
        }
        if not self.tools:
            value.pop("tools")
            value.pop("parallel_tool_calls")
        return value


@dataclass(frozen=True)
class ResponseRecord:
    response_id: str | None
    model: str | None
    status: str | None
    incomplete_details: dict[str, Any] | None
    output_items: tuple[dict[str, Any], ...]
    output_text: str | None
    usage: dict[str, Any] | None
    request_index: int
    raw: dict[str, Any]
    transport_error: str | None = None

    @classmethod
    def from_dict(cls, raw: object, *, request_index: int) -> "ResponseRecord":
        data = _json_object(raw, "response")
        output = data.get("output", [])
        if not isinstance(output, list) or not all(isinstance(item, dict) for item in output):
            raise ValueError("'output' must be a list of objects.")
        usage = data.get("usage")
        if usage is not None and not isinstance(usage, dict):
            raise ValueError("'usage' must be an object or null.")
        incomplete = data.get("incomplete_details")
        if incomplete is not None and not isinstance(incomplete, dict):
            raise ValueError("'incomplete_details' must be an object or null.")
        output_text = data.get("output_text")
        if output_text is None:
            fragments: list[str] = []
            for item in output:
                if item.get("type") != "message":
                    continue
                content = item.get("content", [])
                if not isinstance(content, list):
                    continue
                for part in content:
                    if (
                        isinstance(part, dict)
                        and part.get("type") == "output_text"
                        and isinstance(part.get("text"), str)
                    ):
                        fragments.append(part["text"])
            output_text = "".join(fragments) or None
        if output_text is not None and not isinstance(output_text, str):
            raise ValueError("'output_text' must be text or null.")
        return cls(
            response_id=data.get("id"),
            model=data.get("model"),
            status=data.get("status"),
            incomplete_details=dict(incomplete) if incomplete is not None else None,
            output_items=tuple(dict(item) for item in output),
            output_text=output_text,
            usage=dict(usage) if usage is not None else None,
            request_index=request_index,
            raw=dict(data),
            transport_error=None,
        )

    @classmethod
    def error(cls, message: str, *, request_index: int) -> "ResponseRecord":
        return cls(
            response_id=None,
            model=None,
            status=None,
            incomplete_details=None,
            output_items=(),
            output_text=None,
            usage=None,
            request_index=request_index,
            raw={},
            transport_error=message,
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "response_id": self.response_id,
            "model": self.model,
            "status": self.status,
            "incomplete_details": self.incomplete_details,
            "output_items": [dict(item) for item in self.output_items],
            "output_text": self.output_text,
            "usage": dict(self.usage) if self.usage is not None else None,
            "request_index": self.request_index,
            "raw": dict(self.raw),
            "transport_error": self.transport_error,
        }


@dataclass(frozen=True)
class FunctionCallRecord:
    request_index: int
    call_id: str | None
    name: str | None
    arguments: str | None
    accepted: bool
    error: str | None

    def to_dict(self) -> dict[str, Any]:
        return {
            "request_index": self.request_index,
            "call_id": self.call_id,
            "name": self.name,
            "arguments": self.arguments,
            "accepted": self.accepted,
            "error": self.error,
        }


@dataclass(frozen=True)
class ToolOutputRecord:
    request_index: int
    call_id: str
    output: dict[str, Any]

    def to_dict(self) -> dict[str, Any]:
        return {
            "request_index": self.request_index,
            "call_id": self.call_id,
            "output": dict(self.output),
        }
