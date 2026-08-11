from __future__ import annotations

import os
import stat
from pathlib import Path

from .models import validate_relative_path


class UnsafeObservationPath(ValueError):
    """Raised when an observation path cannot be trusted without following links."""


class ObservationRoot:
    """Read-only confined path resolver for postcondition observations."""

    def __init__(self, root: Path):
        self.root = Path(root)
        try:
            info = os.lstat(self.root)
        except OSError as exc:
            raise UnsafeObservationPath("unsafe observation root") from exc
        if stat.S_ISLNK(info.st_mode) or not stat.S_ISDIR(info.st_mode):
            raise UnsafeObservationPath("unsafe observation root")

    def target(self, relative: str) -> Path:
        portable = validate_relative_path(relative)
        parts = portable.split("/")
        current = self.root
        for part in parts[:-1]:
            current = current / part
            try:
                info = os.lstat(current)
            except FileNotFoundError:
                return current.joinpath(*parts[parts.index(part) + 1 :])
            except OSError as exc:
                raise UnsafeObservationPath("unsafe observation path") from exc
            if stat.S_ISLNK(info.st_mode) or not stat.S_ISDIR(info.st_mode):
                raise UnsafeObservationPath("unsafe observation path")
        return current / parts[-1]
