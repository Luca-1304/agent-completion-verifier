from __future__ import annotations

import errno
import json
import os
import stat
from pathlib import Path
from typing import Any

from .filesystem import ObservationRoot, UnsafeObservationPath
from .models import JsonObjectContract, PostconditionObservation
from .text_file import _read_regular_file_no_follow


class _DuplicateKeyError(ValueError):
    pass


def _strict_object_pairs(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise _DuplicateKeyError
        result[key] = value
    return result


def _evidence(
    *,
    exists: bool = False,
    regular_file: bool = False,
    valid_utf8: bool = False,
    valid_json: bool = False,
    top_level_object: bool = False,
    expected_keys_present: bool = False,
    expected_values_match: bool = False,
    expected_key_count: int = 0,
    key_count_matches: bool | None = None,
) -> dict[str, object]:
    payload: dict[str, object] = {
        "exists": exists,
        "regular_file": regular_file,
        "valid_utf8": valid_utf8,
        "valid_json": valid_json,
        "top_level_object": top_level_object,
        "expected_keys_present": expected_keys_present,
        "expected_values_match": expected_values_match,
        "expected_key_count": expected_key_count,
    }
    if key_count_matches is not None:
        payload["key_count_matches"] = key_count_matches
    return payload


class JsonObjectVerifier:
    def verify(
        self, contract: JsonObjectContract, root: Path
    ) -> PostconditionObservation:
        if not isinstance(contract, JsonObjectContract):
            raise ValueError("JsonObjectVerifier requires a JsonObjectContract.")

        count = len(contract.expected)
        exact_default = False if contract.exact_keys else None
        try:
            target = ObservationRoot(root).target(contract.path)
        except (UnsafeObservationPath, ValueError):
            return PostconditionObservation(
                kind=contract.kind,
                trusted=False,
                matches=False,
                evidence=_evidence(
                    expected_key_count=count,
                    key_count_matches=exact_default,
                ),
                reason="unsafe_path",
            )

        try:
            info = os.lstat(target)
        except FileNotFoundError:
            return PostconditionObservation(
                kind=contract.kind,
                trusted=True,
                matches=False,
                evidence=_evidence(
                    expected_key_count=count,
                    key_count_matches=exact_default,
                ),
                reason="missing",
            )
        except OSError:
            return PostconditionObservation(
                kind=contract.kind,
                trusted=False,
                matches=False,
                evidence=_evidence(
                    expected_key_count=count,
                    key_count_matches=exact_default,
                ),
                reason="io_error",
            )

        if stat.S_ISLNK(info.st_mode):
            return PostconditionObservation(
                kind=contract.kind,
                trusted=False,
                matches=False,
                evidence=_evidence(
                    exists=True,
                    expected_key_count=count,
                    key_count_matches=exact_default,
                ),
                reason="unsafe_path",
            )
        if not stat.S_ISREG(info.st_mode):
            return PostconditionObservation(
                kind=contract.kind,
                trusted=True,
                matches=False,
                evidence=_evidence(
                    exists=True,
                    expected_key_count=count,
                    key_count_matches=exact_default,
                ),
                reason="wrong_type",
            )

        try:
            data = _read_regular_file_no_follow(target)
        except FileNotFoundError:
            return PostconditionObservation(
                kind=contract.kind,
                trusted=True,
                matches=False,
                evidence=_evidence(
                    expected_key_count=count,
                    key_count_matches=exact_default,
                ),
                reason="missing",
            )
        except OSError as exc:
            unsafe = exc.errno in {errno.ELOOP, errno.EMLINK}
            return PostconditionObservation(
                kind=contract.kind,
                trusted=False,
                matches=False,
                evidence=_evidence(
                    exists=True,
                    regular_file=True,
                    expected_key_count=count,
                    key_count_matches=exact_default,
                ),
                reason="unsafe_path" if unsafe else "io_error",
            )

        try:
            text = data.decode("utf-8")
        except UnicodeDecodeError:
            return PostconditionObservation(
                kind=contract.kind,
                trusted=True,
                matches=False,
                evidence=_evidence(
                    exists=True,
                    regular_file=True,
                    expected_key_count=count,
                    key_count_matches=exact_default,
                ),
                reason="invalid_utf8",
            )

        try:
            parsed = json.loads(text, object_pairs_hook=_strict_object_pairs)
        except _DuplicateKeyError:
            return PostconditionObservation(
                kind=contract.kind,
                trusted=True,
                matches=False,
                evidence=_evidence(
                    exists=True,
                    regular_file=True,
                    valid_utf8=True,
                    expected_key_count=count,
                    key_count_matches=exact_default,
                ),
                reason="duplicate_key",
            )
        except (json.JSONDecodeError, ValueError):
            return PostconditionObservation(
                kind=contract.kind,
                trusted=True,
                matches=False,
                evidence=_evidence(
                    exists=True,
                    regular_file=True,
                    valid_utf8=True,
                    expected_key_count=count,
                    key_count_matches=exact_default,
                ),
                reason="invalid_json",
            )

        if not isinstance(parsed, dict):
            return PostconditionObservation(
                kind=contract.kind,
                trusted=True,
                matches=False,
                evidence=_evidence(
                    exists=True,
                    regular_file=True,
                    valid_utf8=True,
                    valid_json=True,
                    expected_key_count=count,
                    key_count_matches=exact_default,
                ),
                reason="wrong_top_level",
            )

        keys_present = all(key in parsed for key in contract.expected)
        values_match = keys_present and all(
            parsed[key] == expected for key, expected in contract.expected.items()
        )
        key_count_matches = len(parsed) == count
        matches = keys_present and values_match and (
            key_count_matches if contract.exact_keys else True
        )
        return PostconditionObservation(
            kind=contract.kind,
            trusted=True,
            matches=matches,
            evidence=_evidence(
                exists=True,
                regular_file=True,
                valid_utf8=True,
                valid_json=True,
                top_level_object=True,
                expected_keys_present=keys_present,
                expected_values_match=values_match,
                expected_key_count=count,
                key_count_matches=(
                    key_count_matches if contract.exact_keys else None
                ),
            ),
            reason=None if matches else "key_mismatch",
        )
