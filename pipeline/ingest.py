"""Read a thesis file into plain text."""

from __future__ import annotations

from pathlib import Path

from pypdf import PdfReader

TEXT_SUFFIXES = {".md", ".markdown", ".txt"}


def thesis_text(path: Path) -> str:
    """PDFs are converted to text locally. Markdown and plain text are read as is."""
    suffix = path.suffix.lower()
    if suffix == ".pdf":
        return "\n".join(page.extract_text() or "" for page in PdfReader(path).pages)
    if suffix in TEXT_SUFFIXES:
        return path.read_text(encoding="utf-8")
    raise ValueError(f"Unsupported thesis format '{suffix}'. Use a PDF or a markdown file.")
