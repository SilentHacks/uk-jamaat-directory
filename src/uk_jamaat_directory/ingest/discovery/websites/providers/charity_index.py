"""Charity Commission for England and Wales bulk register index.

The Charity Commission publishes a daily TSV extract of every registered
charity (https://register-of-charities.charitycommission.gov.uk/en/register/full-register-download).
We use it as a public, OGL v3.0-licensed source of UK mosque websites:
charities that look like mosque/masjid/islamic organisations carry a
contact website on their row, and our mosques with matching postcodes
+ fuzzy name match can inherit that URL as a low-risk discovery lead.

This module loads the extract into a postcode-indexed in-memory list.
The full extract is ~200K rows and ~50MB, well within memory budget
for a one-shot discovery CLI. A second-tier cache keyed by
``(charity_number)`` deduplicates repeated matches.
"""

from __future__ import annotations

import csv
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class CharityRecord:
    """One row from the Charity Commission ``charity`` table."""

    charity_number: str
    name: str
    postcode: str | None
    website: str | None
    status: str | None


# Columns by 1-based index in the daily extract.
# Header is tab-delimited and matches the spec; we use named column
# positions from the data definition to keep the parser robust to header
# re-ordering.
_COL_NUMBER = "registered_charity_number"
_COL_NAME = "charity_name"
_COL_STATUS = "charity_registration_status"
_COL_POSTCODE = "charity_contact_postcode"
_COL_WEB = "charity_contact_web"


def _clean(value: str | None) -> str:
    return (value or "").strip()


def load_charity_index(path: Path) -> dict[str, list[CharityRecord]]:
    """Load the charity extract and return a postcode-indexed dict.

    The postcode key is the canonical UK form (no spaces, upper-cased).
    Charities with a blank postcode are dropped — they cannot be joined
    against a mosque on postcode.
    """
    from uk_jamaat_directory.ingest.normalize import normalize_postcode

    # The charity activities column can run to 100K+ characters; the
    # default csv field limit truncates silently otherwise.
    csv.field_size_limit(2**20)

    by_postcode: dict[str, list[CharityRecord]] = {}
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle, delimiter="\t")
        for row in reader:
            web = _clean(row.get(_COL_WEB))
            postcode = _clean(row.get(_COL_POSTCODE))
            if not web or not postcode:
                continue
            normalized = normalize_postcode(postcode)
            if not normalized:
                continue
            key = normalized.replace(" ", "").upper()
            record = CharityRecord(
                charity_number=_clean(row.get(_COL_NUMBER)),
                name=_clean(row.get(_COL_NAME)),
                postcode=normalized,
                website=web,
                status=_clean(row.get(_COL_STATUS)) or None,
            )
            by_postcode.setdefault(key, []).append(record)
    return by_postcode
