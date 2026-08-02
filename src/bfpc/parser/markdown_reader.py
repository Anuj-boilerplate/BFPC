"""Markdown reader.

Markdown has no paging concept, so the whole file maps to a single page.
Block kinds are inferred from the line syntax (ATX/Setext headings, list
markers, fenced code). Table support is left out of v1; pipe rows are
treated as plain text blocks.
"""

from __future__ import annotations

from pathlib import Path

from bfpc.parser.models import Block, BlockKind, Document, Page, Source


class MarkdownReader:
    """Parse a Markdown file into a :class:`Document`."""

    def read(self, path: Path) -> Document:
        """Parse ``path`` and return its document model.

        :param path: path to a Markdown file.
        :return: a single-page document.
        :raises FileNotFoundError: if the file does not exist.
        """
        path = Path(path)
        if not path.is_file():
            raise FileNotFoundError(f"Markdown not found: {path}")

        # utf-8-sig strips a leading BOM (common on Windows-authored files).
        text = path.read_text(encoding="utf-8-sig")
        blocks = self._extract_blocks(text)
        return Document(
            path=path,
            source=Source.MARKDOWN,
            pages=[Page(number=1, blocks=blocks)],
            metadata={"line_count": len(text.splitlines())},
        )

    @staticmethod
    def _extract_blocks(text: str) -> list[Block]:
        blocks: list[Block] = []
        current: list[str] = []
        fence: str | None = None
        current_kind: BlockKind = BlockKind.TEXT

        def flush() -> None:
            nonlocal current
            if current:
                blocks.append(Block(text="\n".join(current), source=Source.MARKDOWN, kind=current_kind))
                current = []

        for raw_line in text.splitlines():
            line = raw_line.rstrip()

            if line.startswith("```"):
                if fence is None:
                    flush()
                    fence = line
                    current_kind = BlockKind.TEXT
                    current.append(line)
                else:
                    current.append(line)
                    flush()
                    fence = None
                continue

            if fence is not None:
                current.append(line)
                continue

            if line.strip() == "":
                flush()
                current_kind = BlockKind.TEXT
                continue

            if line.startswith("#"):
                flush()
                blocks.append(Block(text=line, source=Source.MARKDOWN, kind=BlockKind.HEADING))
                continue

            if _is_list_line(line):
                if current_kind != BlockKind.LIST:
                    flush()
                    current_kind = BlockKind.LIST
                current.append(line)
                continue

            if current_kind == BlockKind.LIST:
                flush()
                current_kind = BlockKind.TEXT

            current.append(line)

        flush()
        return blocks


def _is_list_line(line: str) -> bool:
    """True if the line is an unordered or ordered list item."""
    stripped = line.lstrip()
    if stripped.startswith(("-", "•", "*", "+")) and len(stripped) > 1 and stripped[1] in " \t":
        return True
    if len(stripped) > 2 and stripped[0].isdigit() and stripped[1] in ". )" and stripped[2] in " \t":
        return True
    return False
