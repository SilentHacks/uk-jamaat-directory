from __future__ import annotations


def pdf_text_available() -> bool:
    try:
        import pymupdf  # noqa: F401
    except ImportError:
        return False
    return True


def ocr_available() -> bool:
    try:
        import pytesseract  # noqa: F401
    except ImportError:
        return False
    return True


def render_html_available() -> bool:
    try:
        import playwright  # noqa: F401
    except ImportError:
        return False
    return True
