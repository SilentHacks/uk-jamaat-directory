"""Tests for the hardened authoring pipeline: domain policy, helpers,
declarative extractors, semantic checks, failure taxonomy, and prompts."""

from __future__ import annotations

from datetime import date, time

from uk_jamaat_directory.domain import AuthoringFailureCategory, AuthoringTargetKind, Prayer
from uk_jamaat_directory.ingest.authoring.authoring_prompt import (
    build_authoring_prompt,
    build_repair_prompt,
)
from uk_jamaat_directory.ingest.authoring.failure_taxonomy import classify_failure
from uk_jamaat_directory.ingest.domain_policy import (
    is_aggregator_domain,
    is_aggregator_url,
    is_trusted_widget_url,
    is_umbrella_domain,
)
from uk_jamaat_directory.ingest.extract.helpers.dates import (
    add_months,
    parse_date_flexible,
    parse_day_of_month,
)
from uk_jamaat_directory.ingest.extract.helpers.html import (
    extract_tables,
    find_table,
    header_matches,
)
from uk_jamaat_directory.ingest.extract.helpers.rows import carry_forward
from uk_jamaat_directory.ingest.extract.helpers.times import coerce_time, infer_ampm
from uk_jamaat_directory.ingest.extract.repo_extractors.contract import (
    ExtractContext,
    ExtractorArtifact,
    ExtractorEvidence,
    ExtractorResult,
    ExtractorRow,
    RefreshPolicy,
    RunFrequency,
    SourceMatch,
    TargetKind,
    TargetSpec,
)
from uk_jamaat_directory.ingest.extract.repo_extractors.declarative import (
    TableTimetableExtractor,
)
from uk_jamaat_directory.ingest.extract.repo_extractors.semantics import (
    check_result_semantics,
)
from uk_jamaat_directory.ingest.extract.repo_extractors.sync import (
    source_id_hint_from_key,
)
from uk_jamaat_directory.ingest.extract.repo_extractors.validator import (
    check_target_url,
)

# --- domain policy ---


def test_aggregator_domains() -> None:
    assert is_aggregator_domain("mosquedirectory.co.uk")
    assert is_aggregator_domain("www.mosquedirectory.co.uk")
    assert is_aggregator_url("https://mosqueradar.com/mosque/x")
    assert not is_aggregator_domain("greenlanemasjid.org")


def test_umbrella_domains() -> None:
    assert is_umbrella_domain("towerhamletsmosques.co.uk")
    assert is_umbrella_domain("heritage.ismaili.net")
    assert not is_umbrella_domain("examplemosque.org")


def test_trusted_widget_hosts() -> None:
    assert is_trusted_widget_url("https://mawaqit.net/en/some-mosque")
    assert is_trusted_widget_url("https://masjidbox.com/prayer-times/x")
    assert not is_trusted_widget_url("https://example.com")


# --- validator target url ---


def test_check_target_url_rejects_aggregator_even_on_own_domain() -> None:
    issue = check_target_url(
        "https://mosquedirectory.co.uk/mosques/x", allowed_domain="mosquedirectory.co.uk"
    )
    assert issue is not None and "aggregator" in issue


def test_check_target_url_allows_trusted_widget() -> None:
    assert check_target_url("https://masjidbox.com/x", allowed_domain="mymosque.org") is None


def test_check_target_url_same_domain_ok() -> None:
    assert check_target_url("https://www.mymosque.org/times", allowed_domain="mymosque.org") is None
    issue = check_target_url("https://other.org/times", allowed_domain="mymosque.org")
    assert issue is not None and "outside allowed domain" in issue


# --- times / ampm inference ---


def test_infer_ampm_shifts_into_window() -> None:
    assert infer_ampm(time(9, 45), prayer="isha") == time(21, 45)
    assert infer_ampm(time(1, 30), prayer="dhuhr") == time(13, 30)
    assert infer_ampm(time(5, 0), prayer="fajr") == time(5, 0)
    assert infer_ampm(time(13, 15), prayer="fajr") == time(13, 15)  # unambiguous


def test_coerce_time_with_prayer() -> None:
    assert coerce_time("9.45", prayer="isha") == time(21, 45)
    assert coerce_time("6:30 pm", prayer="maghrib") == time(18, 30)
    assert coerce_time("garbage", prayer="fajr") is None


# --- dates ---


def test_parse_date_flexible() -> None:
    assert parse_date_flexible("01/06/2026", default_year=2025) == date(2026, 6, 1)
    assert parse_date_flexible("1/6", default_year=2026) == date(2026, 6, 1)
    assert parse_date_flexible("1 June", default_year=2026) == date(2026, 6, 1)
    assert parse_date_flexible("June 1 2026", default_year=2020) == date(2026, 6, 1)
    assert parse_date_flexible("1st Jun", default_year=2026) == date(2026, 6, 1)
    assert parse_date_flexible("", default_year=2026) is None


def test_add_months_clamps() -> None:
    assert add_months(date(2026, 1, 31), 1) == date(2026, 2, 28)
    assert add_months(date(2026, 12, 15), 1) == date(2027, 1, 15)


# --- rows ---


def test_carry_forward() -> None:
    assert carry_forward(["5:00", "", '"', "5:15", ""]) == [
        "5:00",
        "5:00",
        "5:00",
        "5:15",
        "5:15",
    ]


# --- html multi-table ---


def test_extract_tables_one_per_table_element() -> None:
    html = """
    <table><tr><th>Nav</th></tr><tr><td>Home</td></tr></table>
    <table><tr><th>Date</th><th>Fajr</th></tr><tr><td>1/6</td><td>4:00</td></tr></table>
    """
    tables = extract_tables(html)
    assert len(tables) == 2
    assert tables[1].header == ["Date", "Fajr"]
    assert tables[1].body() == [["1/6", "4:00"]]


def test_find_table_fuzzy_header() -> None:
    html = """
    <table><tr><th>Menu</th></tr></table>
    <table><tr><th>Date (Gregorian)</th><th>Fajr Jamaat</th></tr>
    <tr><td>1/6</td><td>4:00</td></tr></table>
    """
    table = find_table(html, header_keywords=["date", "fajr"])
    assert table is not None
    assert header_matches(table.header, ["date", "fajr"])


# --- declarative extractor ---


class _DemoExtractor(TableTimetableExtractor):
    key = "demo_mosque_12345678"
    version = "2026.06.10.1"
    source_match = SourceMatch(domains=("demo.org",))
    refresh_policy = RefreshPolicy(frequency=RunFrequency.DAILY)
    targets = (TargetSpec(label="timetable", url="https://demo.org/times", kind=TargetKind.HTML),)
    table_keywords = ("date", "fajr")
    date_column = "date"
    prayer_columns = {
        Prayer.FAJR: "fajr",
        Prayer.ISHA: "isha",
    }


def _ctx(html: str) -> ExtractContext:
    return ExtractContext(
        source_id="s",
        mosque_name="Demo",
        mosque_id=None,
        source_url="https://demo.org",
        timezone="Europe/London",
        artifacts={
            "timetable": ExtractorArtifact(
                target_label="timetable",
                target_url="https://demo.org/times",
                content_type="text/html",
                body=html.encode(),
            )
        },
    )


def test_declarative_table_extractor() -> None:
    year = date.today().year
    html = f"""
    <table>
      <tr><th>Date</th><th>Fajr Jamaat</th><th>Isha Jamaat</th></tr>
      <tr><td>1/6/{year}</td><td>4:00</td><td>10:00</td></tr>
      <tr><td>2/6/{year}</td><td>4:05</td><td>10:00</td></tr>
    </table>
    """
    result = _DemoExtractor().extract(_ctx(html))
    assert len(result.rows) == 4
    fajr = [r for r in result.rows if r.prayer == Prayer.FAJR]
    isha = [r for r in result.rows if r.prayer == Prayer.ISHA]
    assert fajr[0].jamaat_time == time(4, 0)
    # 10:00 isha disambiguated to PM
    assert isha[0].jamaat_time == time(22, 0)
    assert all(r.evidence.raw_text for r in result.rows)


def test_declarative_table_extractor_bare_day_numbers() -> None:
    """Monthly tables often print only the day-of-month in the date column
    (and repeat the header as the first body row); both must be handled."""
    today = date.today()
    html = """
    <table>
      <tr><th>Date</th><th>Day</th><th>Fajr Iqamah</th><th>Isha Iqamah</th></tr>
      <tr><td>Date</td><td>Day</td><td>Fajr Iqamah</td><td>Isha Iqamah</td></tr>
      <tr><td>1</td><td>Mon</td><td>4:10</td><td>10:30</td></tr>
      <tr><td>2</td><td>Tue</td><td>4:10</td><td>10:30</td></tr>
    </table>
    """
    result = _DemoExtractor().extract(_ctx(html))
    assert len(result.rows) == 4
    assert {r.date for r in result.rows} == {
        date(today.year, today.month, 1),
        date(today.year, today.month, 2),
    }


def test_parse_day_of_month() -> None:
    assert parse_day_of_month("1") == 1
    assert parse_day_of_month("21st") == 21
    assert parse_day_of_month("Mon 1st") == 1
    assert parse_day_of_month("1 Tue") == 1
    assert parse_day_of_month("32") is None
    assert parse_day_of_month("0") is None
    assert parse_day_of_month("1 6") is None  # ambiguous two numbers
    assert parse_day_of_month("1 June") is None  # full date, not a bare day
    assert parse_day_of_month("Date") is None
    assert parse_day_of_month("") is None


def test_declarative_table_extractor_no_table() -> None:
    result = _DemoExtractor().extract(_ctx("<p>no tables here</p>"))
    assert result.rows == []
    assert result.no_schedule_reason


# --- semantics ---


def _row(prayer: Prayer, jamaat: time, d: date, start: time | None = None) -> ExtractorRow:
    return ExtractorRow(
        date=d,
        prayer=prayer,
        jamaat_time=jamaat,
        start_time=start,
        evidence=ExtractorEvidence(
            target_label="timetable",
            target_url="https://demo.org",
            extractor_key="k",
            extractor_version="v",
        ),
    )


def test_semantics_accepts_plausible_result() -> None:
    today = date.today()
    rows = [
        _row(Prayer.FAJR, time(4, 30), today),
        _row(Prayer.DHUHR, time(13, 15), today),
        _row(Prayer.ASR, time(17, 0), today),
        _row(Prayer.MAGHRIB, time(21, 20), today),
        _row(Prayer.ISHA, time(22, 45), today),
    ]
    assert check_result_semantics(ExtractorResult(rows=rows), today=today) == []


def test_semantics_flags_disorder_and_window() -> None:
    today = date.today()
    rows = [
        _row(Prayer.FAJR, time(11, 0), today),  # outside fajr window
        _row(Prayer.DHUHR, time(13, 0), today),
        _row(Prayer.ISHA, time(12, 0), today),  # before dhuhr + outside window
    ]
    issues = check_result_semantics(ExtractorResult(rows=rows), today=today)
    assert any("plausible window" in issue for issue in issues)
    assert any("chronological" in issue for issue in issues)


def test_semantics_flags_stale_dates() -> None:
    today = date.today()
    old = date(today.year - 2, 6, 1)
    rows = [_row(Prayer.FAJR, time(4, 30), old)]
    issues = check_result_semantics(ExtractorResult(rows=rows), today=today)
    assert any("today" in issue for issue in issues)
    assert any("hardcoded year" in issue for issue in issues)


def test_semantics_empty_allowed_reasons() -> None:
    ok = ExtractorResult(rows=[], no_schedule_reason="image target — awaiting OCR")
    assert check_result_semantics(ok) == []
    bad = ExtractorResult(rows=[], no_schedule_reason="could not parse")
    assert check_result_semantics(bad)


# --- failure taxonomy ---


def test_classify_failure() -> None:
    assert (
        classify_failure(preflight_error="robots.txt disallows fetch")
        == AuthoringFailureCategory.BLOCKED_ROBOTS
    )
    assert (
        classify_failure(preflight_error="cannot resolve host: x.org")
        == AuthoringFailureCategory.DEAD_SITE
    )
    assert classify_failure(preflight_error="http 404") == AuthoringFailureCategory.DEAD_SITE
    assert (
        classify_failure(preflight_error="http 503") == AuthoringFailureCategory.TRANSIENT_NETWORK
    )
    assert (
        classify_failure(agent_reason="no jamaat times found")
        == AuthoringFailureCategory.PERMANENT_NO_JAMAAT
    )
    assert (
        classify_failure(agent_reason="aggregator listing") == AuthoringFailureCategory.AGGREGATOR
    )
    assert classify_failure(agent_timed_out=True) == AuthoringFailureCategory.TIMEOUT
    assert (
        classify_failure(validation_issues=["banned import: os"])
        == AuthoringFailureCategory.VALIDATION_FAILED
    )


# --- sync hint ---


def test_source_id_hint_from_key() -> None:
    assert source_id_hint_from_key("al_amanah_mosque_79d4c155") == "79d4c155"
    assert source_id_hint_from_key("no_hint_here") is None


# --- prompts ---


def test_authoring_prompt_content() -> None:
    prompt = build_authoring_prompt(
        source_id="abc",
        mosque_name="Demo Mosque",
        website_url="https://demo.org",
        extractor_key="demo_mosque_12345678",
        script_path="src/.../demo_mosque_12345678.py",
        result_path="data/authoring_results/abc.json",
        domain="demo.org",
        predicted_kind=AuthoringTargetKind.HTML,
        max_pages=8,
    )
    assert "aggregator" in prompt
    assert "smoke-test-repo-extractor" in prompt
    assert "NEVER hardcode" in prompt
    assert "TableTimetableExtractor" in prompt
    assert "relative.add_months" not in prompt
    assert "YYYY.MM.DD" not in prompt
    assert "mawaqit.net" in prompt


def test_repair_prompt_content() -> None:
    prompt = build_repair_prompt(
        mosque_name="Demo Mosque",
        extractor_key="demo_mosque_12345678",
        script_path="src/.../demo.py",
        result_path="data/authoring_results/abc.json",
        source_url="https://demo.org",
        issues=["smoke test failed: no rows"],
        attempt=1,
    )
    assert "no rows" in prompt
    assert "smoke-test-repo-extractor" in prompt
