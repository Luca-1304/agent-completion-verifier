from __future__ import annotations

import re
from typing import Any

from .models import ResponseRecord, ResponseRequest

_SECRET_PATTERNS = (
    re.compile(r"Bearer\s+[A-Za-z0-9._\-]+", re.IGNORECASE),
    re.compile(r"\bsk-[A-Za-z0-9_\-]{8,}\b"),
)


def redact_transport_error(value: object) -> str:
    text = str(value)
    for pattern in _SECRET_PATTERNS:
        text = pattern.sub("[REDACTED]", text)
    return text[:1000]


def _serialise_response(response: object) -> dict[str, Any]:
    if hasattr(response, "model_dump"):
        raw = response.model_dump(mode="json")
    elif hasattr(response, "to_dict"):
        raw = response.to_dict()
    elif isinstance(response, dict):
        raw = response
    else:
        raise TypeError("OpenAI response object is not serialisable.")
    if not isinstance(raw, dict):
        raise TypeError("OpenAI response serialisation did not return an object.")
    return dict(raw)


class OpenAIResponsesTransport:
    name = "openai-responses"
    version = "1"

    def __init__(self) -> None:
        try:
            from openai import OpenAI
        except ImportError as exc:
            raise RuntimeError(
                "The OpenAI SDK is optional. Install with "
                "'pip install agent-completion-verifier[openai]'."
            ) from exc
        self._client = OpenAI(max_retries=0, timeout=60.0)

    def create(self, request: ResponseRequest) -> ResponseRecord:
        try:
            response = self._client.responses.create(**request.to_dict())
            raw = _serialise_response(response)
            return ResponseRecord.from_dict(raw, request_index=0)
        except Exception as exc:
            return ResponseRecord.error(
                redact_transport_error(exc),
                request_index=0,
            )
