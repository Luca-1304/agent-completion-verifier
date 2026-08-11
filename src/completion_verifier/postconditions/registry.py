from __future__ import annotations

from pathlib import Path

from .directory import DirectoryVerifier
from .json_object import JsonObjectVerifier
from .models import (
    DirectoryContract,
    JsonObjectContract,
    PostconditionContract,
    PostconditionObservation,
    TextFileContract,
)
from .text_file import TextFileVerifier


_TEXT = TextFileVerifier()
_DIRECTORY = DirectoryVerifier()
_JSON = JsonObjectVerifier()


def verify_postcondition(
    contract: PostconditionContract, root: Path
) -> PostconditionObservation:
    """Verify one built-in postcondition using independent local state."""
    if isinstance(contract, TextFileContract):
        return _TEXT.verify(contract, root)
    if isinstance(contract, DirectoryContract):
        return _DIRECTORY.verify(contract, root)
    if isinstance(contract, JsonObjectContract):
        return _JSON.verify(contract, root)
    raise ValueError("Unknown postcondition contract.")
