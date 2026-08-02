"""Reader interface that every document source implements."""

from __future__ import annotations

from pathlib import Path
from typing import Protocol

from bfpc.parser.models import Document


class DocumentReader(Protocol):
    """Read a file into an in-memory :class:`Document`.

    Implementations must:
    - raise ``FileNotFoundError`` for a missing path;
    - raise ``ValueError`` for a path it cannot parse.
    """

    def read(self, path: Path) -> Document:
        """Parse ``path`` and return its document model.

        :param path: absolute or relative path to the input file.
        :return: the parsed document.
        :raises FileNotFoundError: if the file does not exist.
        :raises ValueError: if the file is malformed or unsupported.
        """
        ...
