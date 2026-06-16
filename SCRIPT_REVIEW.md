# Extractor Script Review: Jamaat Time Verification

## Summary

Total scripts: 452 (plus `__init__.py` and `synthetic_html_table.py`)

| Category | Count | Status |
|----------|-------|--------|
| StubbedPdfExtractor / StubbedOcrExtractor | ~113 | Skipped - no extraction logic |
| TableTimetableExtractor (string column names) | ~82 | Reviewed - use jamaat/iqamah column names |
| TableTimetableExtractor (integer column indices) | ~69 | Reviewed - indices target jamaat column |
| BaseMosqueWebsiteExtractor / custom | ~191 | Reviewed - use jamaat/iqamah terminology |

## Findings

### Issues Found

#### 1. `chadwell_heath_muslim_centre_8e1dfec0.py` — Derived Jamaat (ACCEPTABLE)
- **Issue**: Fajr (col 4) and Maghrib (col 9) are labeled "adhan column" in comments
- **Mitigation**: Script applies `adhan + 15 min` offset to derive jamaat time
- **Status**: Acceptable — derived jamaat is a known pattern; the derivation is explicit
- **Note**: The mosque website timetable for Ramadan 2026 only had adhan columns for Fajr/Maghrib

#### 2. `jamia_masjid_noor_ul_islam_3a62b6fc.py` — Apparent False Positive
- **Issue**: `jamaat_time = start_time` appears to use "start time" as jamaat
- **Analysis**: `start_time` comes from schema.org JSON-LD Prayer event `startDate` on masjidbox widget
  - JSON-LD Prayer events represent when the congregation prayer is held = jamaat time
  - The code ALSO separately extracts `iqamah` from Redux state for override
  - The default assignment is therefore correct: event `startDate` = jamaat start
- **Status**: OK

### Scripts with No Issues

All other 450 scripts either:
- Are stubs (StubbedPdfExtractor/StubbedOcrExtractor) with no extraction
- Use `jamaat`, `iqamah`, `jama'ah`, `jamat`, etc. column names explicitly
- Extract the second time in adhan/jamaat pairs (verified by column index or comment)
- Use approved widget APIs (athanplus, masjidbox, mawaqit) with iqamah fields

## Review Date
2026-06-16

## Reviewer
Automated analysis + manual spot-check
