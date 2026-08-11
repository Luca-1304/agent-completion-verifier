from __future__ import annotations

import errno
import os
import stat
from pathlib import Path

from .filesystem import ObservationRoot, UnsafeObservationPath
from .models import PostconditionObservation, TextFileContract


def _evidence(
    *,
    exists: bool = False,
    regular_file: bool = False,
    size_matches: bool = False,
    content_matches: bool = False,
) -> dict[str, object]:
    return {
        "exists": exists,
        "regular_file": regular_file,
        "size_matches": size_matches,
        "content_matches": content_matches,
    }


def _read_regular_file_no_follow(target: Path) -> bytes:
    flags = os.O_RDONLY | getattr(os, "O_BINARY", 0) | getattr(os, "O_NOFOLLOW", 0)
    fd = os.open(target, flags)
    try:
        info = os.fstat(fd)
        if not stat.S_ISREG(info.st_mode):
            raise IsADirectoryError
        chunks: list[bytes] = []
        while True:
            chunk = os.read(fd, 65536)
            if not chunk:
                return b"".join(chunks)
            chunks.append(chunk)
    finally:
        os.close(fd)


class TextFileVerifier:
    def verify(
        self, contract: TextFileContract, root: Path
    ) -> PostconditionObservation:
        if not isinstance(contract, TextFileContract):
            raise ValueError("TextFileVerifier requires a TextFileContract.")

        try:
            target = ObservationRoot(root).target(contract.path)
        except (UnsafeObservationPath, ValueError):
            return PostconditionObservation(
                kind=contract.kind,
                trusted=False,
                matches=False,
                evidence=_evidence(),
                reason="unsafe_path",
            )

        try:
            info = os.lstat(target)
        except FileNotFoundError:
            return PostconditionObservation(
                kind=contract.kind,
                trusted=True,
                matches=False,
                evidence=_evidence(),
                reason="missing",
            )
        except OSError:
            return PostconditionObservation(
                kind=contract.kind,
                trusted=False,
                matches=False,
                evidence=_evidence(),
                reason="io_error",
            )

        if stat.S_ISLNK(info.st_mode):
            return PostconditionObservation(
                kind=contract.kind,
                trusted=False,
                matches=False,
                evidence=_evidence(exists=True),
                reason="unsafe_path",
            )
        if not stat.S_ISREG(info.st_mode):
            return PostconditionObservation(
                kind=contract.kind,
                trusted=True,
                matches=False,
                evidence=_evidence(exists=True),
                reason="wrong_type",
            )

        try:
            data = _read_regular_file_no_follow(target)
        except FileNotFoundError:
            return PostconditionObservation(
                kind=contract.kind,
                trusted=True,
                matches=False,
                evidence=_evidence(),
                reason="missing",
            )
        except OSError as exc:
            unsafe = exc.errno in {errno.ELOOP, errno.EMLINK}
            return PostconditionObservation(
                kind=contract.kind,
                trusted=False,
                matches=False,
                evidence=_evidence(exists=True, regular_file=True),
                reason="unsafe_path" if unsafe else "io_error",
            )

        expected = contract.expected_text.encode("utf-8")
        size_matches = len(data) == len(expected)
        content_matches = data == expected
        matches = size_matches and content_matches
        return PostconditionObservation(
            kind=contract.kind,
            trusted=True,
            matches=matches,
            evidence=_evidence(
                exists=True,
                regular_file=True,
                size_matches=size_matches,
                content_matches=content_matches,
            ),
            reason=None if matches else "content_mismatch",
        )
