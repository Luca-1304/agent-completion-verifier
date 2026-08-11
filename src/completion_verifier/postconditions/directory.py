from __future__ import annotations

import os
import stat
from pathlib import Path

from .filesystem import ObservationRoot, UnsafeObservationPath
from .models import DirectoryContract, PostconditionObservation


def _evidence(
    *,
    exists: bool = False,
    directory: bool = False,
    required_children_present: bool = False,
    required_child_count: int = 0,
    empty: bool | None = None,
) -> dict[str, object]:
    payload: dict[str, object] = {
        "exists": exists,
        "directory": directory,
        "required_children_present": required_children_present,
        "required_child_count": required_child_count,
    }
    if empty is not None:
        payload["empty"] = empty
    return payload


class DirectoryVerifier:
    def verify(
        self, contract: DirectoryContract, root: Path
    ) -> PostconditionObservation:
        if not isinstance(contract, DirectoryContract):
            raise ValueError("DirectoryVerifier requires a DirectoryContract.")

        count = len(contract.required_children)
        try:
            target = ObservationRoot(root).target(contract.path)
        except (UnsafeObservationPath, ValueError):
            return PostconditionObservation(
                kind=contract.kind,
                trusted=False,
                matches=False,
                evidence=_evidence(required_child_count=count),
                reason="unsafe_path",
            )

        try:
            info = os.lstat(target)
        except FileNotFoundError:
            return PostconditionObservation(
                kind=contract.kind,
                trusted=True,
                matches=False,
                evidence=_evidence(required_child_count=count),
                reason="missing",
            )
        except OSError:
            return PostconditionObservation(
                kind=contract.kind,
                trusted=False,
                matches=False,
                evidence=_evidence(required_child_count=count),
                reason="io_error",
            )

        if stat.S_ISLNK(info.st_mode):
            return PostconditionObservation(
                kind=contract.kind,
                trusted=False,
                matches=False,
                evidence=_evidence(exists=True, required_child_count=count),
                reason="unsafe_path",
            )
        if not stat.S_ISDIR(info.st_mode):
            return PostconditionObservation(
                kind=contract.kind,
                trusted=True,
                matches=False,
                evidence=_evidence(exists=True, required_child_count=count),
                reason="wrong_type",
            )

        required = set(contract.required_children)
        found: set[str] = set()
        is_empty = True
        try:
            with os.scandir(target) as entries:
                for entry in entries:
                    is_empty = False
                    if entry.name in required:
                        found.add(entry.name)
                    if contract.exact_empty:
                        break
                    if required and found == required:
                        break
        except OSError:
            return PostconditionObservation(
                kind=contract.kind,
                trusted=False,
                matches=False,
                evidence=_evidence(
                    exists=True,
                    directory=True,
                    required_child_count=count,
                    empty=None if not contract.exact_empty else False,
                ),
                reason="io_error",
            )

        required_present = found == required
        if contract.exact_empty and not is_empty:
            return PostconditionObservation(
                kind=contract.kind,
                trusted=True,
                matches=False,
                evidence=_evidence(
                    exists=True,
                    directory=True,
                    required_children_present=True,
                    required_child_count=count,
                    empty=False,
                ),
                reason="not_empty",
            )
        if not required_present:
            return PostconditionObservation(
                kind=contract.kind,
                trusted=True,
                matches=False,
                evidence=_evidence(
                    exists=True,
                    directory=True,
                    required_children_present=False,
                    required_child_count=count,
                ),
                reason="required_children_missing",
            )

        return PostconditionObservation(
            kind=contract.kind,
            trusted=True,
            matches=True,
            evidence=_evidence(
                exists=True,
                directory=True,
                required_children_present=True,
                required_child_count=count,
                empty=True if contract.exact_empty else None,
            ),
            reason=None,
        )
