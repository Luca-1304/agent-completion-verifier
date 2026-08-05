from __future__ import annotations

from collections.abc import Iterable
from typing import Protocol

from .models import ResponseRecord, ResponseRequest


class ResponsesTransport(Protocol):
    name: str
    version: str

    def create(self, request: ResponseRequest) -> ResponseRecord:
        ...


class FakeResponsesTransport:
    name = "fake-responses"
    version = "1"

    def __init__(self, fixtures: Iterable[ResponseRecord | dict | BaseException]):
        self._fixtures = list(fixtures)
        self.requests: list[ResponseRequest] = []
        self._index = 0

    def create(self, request: ResponseRequest) -> ResponseRecord:
        self.requests.append(request)
        request_index = self._index
        if request_index >= len(self._fixtures):
            self._index += 1
            return ResponseRecord.error(
                "Fake transport fixture sequence exhausted.",
                request_index=request_index,
            )
        fixture = self._fixtures[request_index]
        self._index += 1
        if isinstance(fixture, BaseException):
            raise fixture
        if isinstance(fixture, ResponseRecord):
            return ResponseRecord(
                response_id=fixture.response_id,
                model=fixture.model,
                status=fixture.status,
                incomplete_details=fixture.incomplete_details,
                output_items=fixture.output_items,
                output_text=fixture.output_text,
                usage=fixture.usage,
                request_index=request_index,
                raw=fixture.raw,
                transport_error=fixture.transport_error,
            )
        return ResponseRecord.from_dict(fixture, request_index=request_index)
