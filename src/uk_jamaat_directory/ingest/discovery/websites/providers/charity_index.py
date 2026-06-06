"""UK charity register index loader.

Both the Charity Commission for England and Wales and the Office of the
Scottish Charity Regulator (OSCR) publish daily bulk extracts of their
registers under the Open Government Licence v3.0. The two extracts
share a common shape (charity number, name, postcode, website) but
differ in file format (TSV vs CSV with quoted fields) and column
headings. :func:`load_register` takes a column map and a delimiter and
returns a postcode-indexed list of :class:`CharityRecord` entries.

The full CC extract is ~200K rows and ~50MB; the OSCR extract is ~25K
rows and ~8MB. Both fit comfortably in memory for a one-shot discovery
CLI.
"""
from __future__ import annotations

import csv
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class CharityRecord:
    """One row from a UK charity register."""

    charity_number: str
    name: str
    postcode: str | None
    website: str | None
    status: str | None


def _clean(value: str | None) -> str:
    return (value or "").strip()


def load_register(
    path: Path,
    *,
    column_number: str,
    column_name: str,
    column_status: str | None,
    column_postcode: str,
    column_web: str,
    delimiter: str = ",",
) -> dict[str, list[CharityRecord]]:
    """Load a charity register and return a postcode-indexed dict.

    The postcode key is the canonical UK form (no spaces, upper-cased).
    Rows with a blank postcode or a blank website are dropped — they
    cannot be joined against a mosque.
    """
    from uk_jamaat_directory.ingest.normalize import normalize_postcode

    # Charity activities / objectives can run to 100K+ characters; the
    # default csv field limit truncates silently otherwise.
    csv.field_size_limit(2**20)

    by_postcode: dict[str, list[CharityRecord]] = {}
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle, delimiter=delimiter)
        for row in reader:
            web = _clean(row.get(column_web))
            postcode = _clean(row.get(column_postcode))
            if not web or not postcode:
                continue
            normalized = normalize_postcode(postcode)
            if not normalized:
                continue
            key = normalized.replace(" ", "").upper()
            record = CharityRecord(
                charity_number=_clean(row.get(column_number)),
                name=_clean(row.get(column_name)),
                postcode=normalized,
                website=web,
                status=(
                    _clean(row.get(column_status))
                    if column_status
                    else None
                )
                or None,
            )
            by_postcode.setdefault(key, []).append(record)
    return by_postcode


# Convenience: the Charity Commission for England and Wales daily
# extract column names. Kept here so callers don't repeat the spec.
CC_COLUMNS = {
    "number": "registered_charity_number",
    "name": "charity_name",
    "status": "charity_registration_status",
    "postcode": "charity_contact_postcode",
    "web": "charity_contact_web",
}


def load_charity_index(path: Path) -> dict[str, list[CharityRecord]]:
    """Load the Charity Commission for England and Wales daily TSV."""
    return load_register(
        path,
        column_number=CC_COLUMNS["number"],
        column_name=CC_COLUMNS["name"],
        column_status=CC_COLUMNS["status"],
        column_postcode=CC_COLUMNS["postcode"],
        column_web=CC_COLUMNS["web"],
        delimiter="\t",
    )


# Convenience: the Office of the Scottish Charity Regulator daily
# export column names. OSCR's header is unquoted; the values are
# quoted, so the standard csv module handles both.
OSCR_COLUMNS = {
    "number": "Charity Number",
    "name": "Charity Name",
    "status": "Charity Status",
    "postcode": "Postcode",
    "web": "Website",
}


def load_oscr_index(path: Path) -> dict[str, list[CharityRecord]]:
    """Load the Office of the Scottish Charity Regulator daily CSV."""
    return load_register(
        path,
        column_number=OSCR_COLUMNS["number"],
        column_name=OSCR_COLUMNS["name"],
        column_status=OSCR_COLUMNS["status"],
        column_postcode=OSCR_COLUMNS["postcode"],
        column_web=OSCR_COLUMNS["web"],
        delimiter=",",
    )
