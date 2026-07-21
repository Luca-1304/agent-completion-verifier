from __future__ import annotations

import hashlib
import os
import stat
import tempfile
from pathlib import Path

from .models import FileObservation, FileWriteContract, validate_relative_path


class SandboxSecurityError(ValueError):
    """Raised when a sandbox path could escape or follow a symlink."""


class SafeFileSandbox:
    def __init__(self, root: Path):
        supplied = Path(root)
        if supplied.exists() and supplied.is_symlink():
            raise SandboxSecurityError("Sandbox root cannot be a symlink.")
        supplied.mkdir(parents=True, exist_ok=True)
        self.root = supplied.resolve(strict=True)
        if not self.root.is_dir():
            raise SandboxSecurityError("Sandbox root must be a directory.")

    def _target(self, relative: str, *, create_parents: bool) -> tuple[Path, bool]:
        portable = validate_relative_path(relative)
        parts = portable.split("/")
        current = self.root
        parents_exist = True
        for index, part in enumerate(parts[:-1]):
            child = current / part
            try:
                info = os.lstat(child)
            except FileNotFoundError:
                parents_exist = False
                if create_parents:
                    os.mkdir(child, 0o700)
                    parents_exist = True
                else:
                    return current.joinpath(*parts[index:]), False
            else:
                if stat.S_ISLNK(info.st_mode):
                    raise SandboxSecurityError(f"symlink parent component '{part}' is not allowed.")
                if not stat.S_ISDIR(info.st_mode):
                    raise SandboxSecurityError(f"Parent component '{part}' is not a directory.")
            current = child
        return current / parts[-1], parents_exist

    @staticmethod
    def _reject_unsafe_final(target: Path) -> None:
        try:
            info = os.lstat(target)
        except FileNotFoundError:
            return
        if stat.S_ISLNK(info.st_mode):
            raise SandboxSecurityError(f"Final path '{target.name}' cannot be a symlink.")
        if not stat.S_ISREG(info.st_mode):
            raise SandboxSecurityError(f"Final path '{target.name}' must be a regular file.")

    def write_text(self, relative: str, content: str) -> None:
        if not isinstance(content, str):
            raise ValueError("Sandbox content must be text.")
        target, _ = self._target(relative, create_parents=True)
        self._reject_unsafe_final(target)
        fd, temporary = tempfile.mkstemp(prefix=".acv-write-", dir=target.parent)
        temporary_path = Path(temporary)
        try:
            with os.fdopen(fd, "wb") as handle:
                handle.write(content.encode("utf-8"))
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temporary_path, target)
        finally:
            if temporary_path.exists():
                temporary_path.unlink()

    def remove(self, relative: str) -> None:
        target, parents_exist = self._target(relative, create_parents=False)
        if not parents_exist:
            return
        self._reject_unsafe_final(target)
        try:
            target.unlink()
        except FileNotFoundError:
            return

    def observe(self, contract: FileWriteContract) -> FileObservation:
        try:
            target, parents_exist = self._target(contract.path, create_parents=False)
            if not parents_exist:
                return self._missing(contract)
            self._reject_unsafe_final(target)
        except SandboxSecurityError as exc:
            return FileObservation(
                contract_id=contract.contract_id,
                path=contract.path,
                confined=False,
                exists=False,
                regular_file=False,
                size=None,
                sha256=None,
                matches_content=False,
                matches_contract=False,
                error=str(exc),
            )
        try:
            info = os.lstat(target)
        except FileNotFoundError:
            return self._missing(contract)
        if not stat.S_ISREG(info.st_mode):
            return FileObservation(
                contract.contract_id,
                contract.path,
                True,
                True,
                False,
                None,
                None,
                False,
                False,
                "Observed path is not a regular file.",
            )
        data = target.read_bytes()
        digest = hashlib.sha256(data).hexdigest()
        matches = data == contract.expected_bytes
        return FileObservation(
            contract_id=contract.contract_id,
            path=contract.path,
            confined=True,
            exists=True,
            regular_file=True,
            size=len(data),
            sha256=digest,
            matches_content=matches,
            matches_contract=(
                matches
                and len(data) == contract.expected_size
                and digest == contract.expected_sha256
            ),
            error=None,
        )

    @staticmethod
    def _missing(contract: FileWriteContract) -> FileObservation:
        return FileObservation(
            contract_id=contract.contract_id,
            path=contract.path,
            confined=True,
            exists=False,
            regular_file=False,
            size=None,
            sha256=None,
            matches_content=False,
            matches_contract=False,
            error=None,
        )
