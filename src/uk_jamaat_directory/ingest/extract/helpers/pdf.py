"""PDF helpers for repo extractors.

Extractors that target PDF files receive the raw PDF bytes in
``artifact.body``. These helpers wrap ``pymupdf`` (fitz) to parse text
and tables from the PDF.
"""

from __future__ import annotations

from typing import Any


def open_pdf(body: bytes) -> Any:
    """Open a PDF from raw bytes and return a ``pymupdf`` document.

    The caller is responsible for closing the document.
    """
    import pymupdf

    return pymupdf.open(stream=body, filetype="pdf")


def extract_text(body: bytes) -> str:
    """Extract all plain text from the PDF bytes.

    Returns an empty string if the PDF is empty or has no extractable text.
    """
    try:
        import pymupdf
    except ImportError:
        return ""
    try:
        doc = pymupdf.open(stream=body, filetype="pdf")
        text = ""
        for page in doc:
            text += page.get_text()
        doc.close()
        return text
    except Exception:
        return ""


def extract_tables(body: bytes) -> list[list[list[str]]]:
    """Extract tables from the PDF bytes.

    Returns a list of pages, where each page is a list of tables, where each
    table is a list of rows, where each row is a list of cell strings.

    This is a best-effort heuristic; many PDFs do not have well-formed tables.
    """
    try:
        import pymupdf
    except ImportError:
        return []
    try:
        doc = pymupdf.open(stream=body, filetype="pdf")
        all_tables: list[list[list[str]]] = []
        for page in doc:
            tabs = page.find_tables()
            tables = []
            for tab in tabs:
                if hasattr(tab, "extract"):
                    tables.append(tab.extract())
            all_tables.append(tables)
        doc.close()
        return all_tables
    except Exception:
        return []
