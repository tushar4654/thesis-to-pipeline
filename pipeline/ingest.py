"""Read a thesis file into Claude message content blocks."""

from __future__ import annotations

import base64
from pathlib import Path
from typing import List

TEXT_SUFFIXES = {".md", ".markdown", ".txt"}


def thesis_content(path: Path) -> List[dict]:
    """PDFs go to Claude as a document block so charts and tables are kept.
    Markdown and plain text go in as text."""
    suffix = path.suffix.lower()
    if suffix == ".pdf":
        data = base64.standard_b64encode(path.read_bytes()).decode("ascii")
        return [{
            "type": "document",
            "source": {"type": "base64", "media_type": "application/pdf", "data": data},
            "title": path.stem,
        }]
    if suffix in TEXT_SUFFIXES:
        text = path.read_text(encoding="utf-8")
        return [{"type": "text", "text": f"<thesis title=\"{path.stem}\">\n{text}\n</thesis>"}]
    raise ValueError(f"Unsupported thesis format '{suffix}'. Use a PDF or a markdown file.")
