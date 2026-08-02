"""Document parsing for BFPC."""

from bfpc.parser.models import Block, BlockKind, Document, Page, Source
from bfpc.parser.base import DocumentReader
from bfpc.parser.docx_reader import DocxReader
from bfpc.parser.markdown_reader import MarkdownReader
from bfpc.parser.pdf_reader import PdfReader

__all__ = [
    "Block",
    "BlockKind",
    "Document",
    "DocumentReader",
    "DocxReader",
    "MarkdownReader",
    "Page",
    "PdfReader",
    "Source",
]
