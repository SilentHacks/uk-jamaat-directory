from __future__ import annotations

import re
from collections.abc import Iterable, Sequence
from html.parser import HTMLParser

_HTML_TAG = re.compile(r"<[^>]+>")
_WHITESPACE = re.compile(r"\s+")


def strip_tags(html: str) -> str:
    return _WHITESPACE.sub(" ", _HTML_TAG.sub(" ", html)).strip()


def normalize_whitespace(value: str) -> str:
    return _WHITESPACE.sub(" ", value).strip()


class _TextCollector(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self._chunks: list[str] = []
        self._skip_depth = 0

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag in {"script", "style", "noscript"}:
            self._skip_depth += 1

    def handle_endtag(self, tag: str) -> None:
        if tag in {"script", "style", "noscript"} and self._skip_depth > 0:
            self._skip_depth -= 1

    def handle_data(self, data: str) -> None:
        if self._skip_depth == 0:
            text = data.strip()
            if text:
                self._chunks.append(text)

    @property
    def text(self) -> str:
        return normalize_whitespace(" ".join(self._chunks))


def html_to_text(html: str) -> str:
    collector = _TextCollector()
    collector.feed(html)
    return collector.text


class Table:
    def __init__(self, rows: list[list[str]]):
        self.rows = [list(row) for row in rows]

    @property
    def header(self) -> list[str]:
        return self.rows[0] if self.rows else []

    def body(self) -> list[list[str]]:
        return self.rows[1:] if len(self.rows) > 1 else []

    def cell(self, row_index: int, col_index: int) -> str:
        rows = self.rows
        if row_index < 0 or row_index >= len(rows):
            return ""
        row = rows[row_index]
        if col_index < 0 or col_index >= len(row):
            return ""
        return row[col_index]


class _TableParser(HTMLParser):
    """Parses each ``<table>`` element into its own row list.

    Nested tables are flattened into their outermost table (rare on mosque
    sites; keeps the parser simple and the row stream intact).
    """

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.tables: list[list[list[str]]] = []
        self._table_depth = 0
        self._current_rows: list[list[str]] | None = None
        self._current_row: list[str] | None = None
        self._current_cell: list[str] | None = None
        self._skip_depth = 0

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag == "table":
            self._table_depth += 1
            if self._table_depth == 1:
                self._current_rows = []
        elif tag == "tr" and self._table_depth:
            self._current_row = []
        elif tag in {"td", "th"} and self._table_depth:
            self._current_cell = []
        elif tag in {"script", "style"}:
            self._skip_depth += 1

    def handle_endtag(self, tag: str) -> None:
        if tag == "table" and self._table_depth:
            self._table_depth -= 1
            if self._table_depth == 0 and self._current_rows is not None:
                self.tables.append(self._current_rows)
                self._current_rows = None
                self._current_row = None
                self._current_cell = None
        elif tag == "tr" and self._current_row is not None:
            if self._current_rows is not None:
                self._current_rows.append(self._current_row)
            self._current_row = None
        elif tag in {"td", "th"} and self._current_cell is not None:
            if self._current_row is None:
                self._current_row = []
            self._current_row.append(normalize_whitespace("".join(self._current_cell)))
            self._current_cell = None
        elif tag in {"script", "style"} and self._skip_depth > 0:
            self._skip_depth -= 1

    def handle_data(self, data: str) -> None:
        if self._skip_depth:
            return
        if self._current_cell is not None:
            self._current_cell.append(data)


def extract_tables(html: str) -> list[Table]:
    """Return one ``Table`` per ``<table>`` element on the page."""
    parser = _TableParser()
    parser.feed(html)
    tables: list[Table] = []
    for raw_rows in parser.tables:
        rows = [row for row in raw_rows if any(cell.strip() for cell in row)]
        if rows:
            tables.append(Table(rows))
    return tables


def header_matches(header: Sequence[str], keywords: Sequence[str]) -> bool:
    """Fuzzy header check: every keyword appears (case/whitespace tolerant)
    as a substring of some header cell."""
    cells = [normalize_whitespace(cell).lower() for cell in header]
    return all(any(keyword.lower() in cell for cell in cells) for keyword in keywords)


def find_table(html: str, *, header_keywords: Sequence[str]) -> Table | None:
    """Return the first table whose header row matches all keywords."""
    for table in extract_tables(html):
        if table.header and header_matches(table.header, header_keywords):
            return table
    return None


def select_text(html: str, keywords: Iterable[str]) -> str:
    text = html_to_text(html).lower()
    for keyword in keywords:
        if keyword.lower() in text:
            return keyword
    return ""
