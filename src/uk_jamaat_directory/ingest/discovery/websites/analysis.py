"""Aggregate analysis of discovery-lead audit rows.

Queries ``ModerationAction`` rows where ``entity_type="discovery_lead"`` and
parses the free-text ``reason`` field to produce actionable reports.
"""

from __future__ import annotations

import re
from collections import Counter
from dataclasses import dataclass, field
from urllib.parse import urlparse

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from uk_jamaat_directory.models.core import ModerationAction

# ---------------------------------------------------------------------------
# Data model
# ---------------------------------------------------------------------------


@dataclass
class LeadFailure:
    """A single parsed discovery lead failure."""

    provider: str
    reason: str
    url: str
    domain: str
    name_ratio: float | None
    matched_postcode: bool | None
    matched_address: bool | None
    outcome: str  # "fetch_failed", "no_match", "denied"
    notes: str
    location_hint: str | None


@dataclass
class DiscoveryAnalysisReport:
    """Aggregate report over all discovery lead audit rows."""

    total_leads: int = 0
    fetch_failed: int = 0
    no_match: int = 0
    denied: int = 0
    domain_counts: Counter[str] = field(default_factory=Counter)
    provider_counts: Counter[str] = field(default_factory=Counter)
    name_ratio_buckets: dict[str, int] = field(
        default_factory=lambda: {
            "0-39": 0,
            "40-59": 0,
            "60-79": 0,
            "80-100": 0,
        }
    )
    top_no_match_domains: list[tuple[str, int]] = field(default_factory=list)
    fetch_failures_by_status: Counter[str] = field(default_factory=Counter)
    leads_with_name_ratio_40_59: list[LeadFailure] = field(default_factory=list)
    location_cluster: Counter[str] = field(default_factory=Counter)

    def as_dict(self) -> dict:
        return {
            "total_leads": self.total_leads,
            "fetch_failed": self.fetch_failed,
            "no_match": self.no_match,
            "denied": self.denied,
            "domain_counts": dict(self.domain_counts.most_common(40)),
            "provider_counts": dict(self.provider_counts.most_common(20)),
            "name_ratio_buckets": self.name_ratio_buckets,
            "top_no_match_domains": self.top_no_match_domains,
            "fetch_failures_by_status": dict(self.fetch_failures_by_status.most_common(20)),
            "prime_contact_page_candidates": len(self.leads_with_name_ratio_40_59),
            "location_cluster": dict(self.location_cluster.most_common(20)),
        }


# ---------------------------------------------------------------------------
# Parsing
# ---------------------------------------------------------------------------


def _domain_from_url(url: str) -> str:
    host = (urlparse(url).hostname or "").lower()
    if host.startswith("www."):
        host = host[4:]
    return host


# The notes string written by _record_lead in website_discovery.py looks like:
#   provider=search_engine reason=search_engine url=https://... \
#   notes=name_ratio=45 postcode=False address=False \
#   extra=query=... result_title=... result_rank=1
#
# For fetch failures:
#   provider=search_engine reason=search_engine url=https://... \
#   notes=fetch failed or non-html response extra=...


_RE_NAME_RATIO = re.compile(r"name_ratio=(\d+(?:\.\d+)?)")
_RE_POSTCODE = re.compile(r"postcode=(True|False)")
_RE_ADDRESS = re.compile(r"address=(True|False)")
_RE_PROVIDER = re.compile(r"provider=(\S+)")
_RE_REASON = re.compile(r"reason=(\S+)")
_RE_URL = re.compile(r"url=(\S+)")


def _group1(pattern: re.Pattern, text: str, default: str = "") -> str:
    m = pattern.search(text)
    return m.group(1) if m else default


def _parse_lead_notes(notes: str | None) -> LeadFailure:
    text = notes or ""
    provider = _group1(_RE_PROVIDER, text) or "unknown"
    reason = _group1(_RE_REASON, text) or "unknown"
    url = _group1(_RE_URL, text)
    domain = _domain_from_url(url)

    ratio_match = _RE_NAME_RATIO.search(text)
    name_ratio = float(ratio_match.group(1)) if ratio_match else None

    pc_match = _RE_POSTCODE.search(text)
    matched_postcode = pc_match.group(1) == "True" if pc_match else None

    addr_match = _RE_ADDRESS.search(text)
    matched_address = addr_match.group(1) == "True" if addr_match else None

    if name_ratio is None:
        outcome = "fetch_failed"
    else:
        outcome = "no_match"

    return LeadFailure(
        provider=provider,
        reason=reason,
        url=url,
        domain=domain,
        name_ratio=name_ratio,
        matched_postcode=matched_postcode,
        matched_address=matched_address,
        outcome=outcome,
        notes=text,
        location_hint=None,
    )


# ---------------------------------------------------------------------------
# Aggregation
# ---------------------------------------------------------------------------


def _bucket_name_ratio(ratio: float) -> str:
    if ratio < 40:
        return "0-39"
    if ratio < 60:
        return "40-59"
    if ratio < 80:
        return "60-79"
    return "80-100"


async def analyse_discovery_leads(session: AsyncSession) -> DiscoveryAnalysisReport:
    """Query all discovery-lead audit rows and produce an aggregate report."""
    stmt = select(ModerationAction).where(
        ModerationAction.entity_type == "discovery_lead",
        ModerationAction.action == "discovery_lead",
    )
    result = await session.execute(stmt)
    rows = result.scalars().all()

    report = DiscoveryAnalysisReport()
    report.total_leads = len(rows)

    for row in rows:
        lead = _parse_lead_notes(row.reason)
        lead.location_hint = row.metadata_.get("location_hint") if row.metadata_ else None
        report.provider_counts[lead.provider] += 1
        report.domain_counts[lead.domain] += 1

        if lead.location_hint:
            report.location_cluster[lead.location_hint] += 1

        if lead.outcome == "fetch_failed":
            report.fetch_failed += 1
            # Try to classify fetch failure from the raw notes
            if "non-html" in lead.notes.lower():
                report.fetch_failures_by_status["non_html"] += 1
            elif "403" in lead.notes or "cloudflare" in lead.notes.lower():
                report.fetch_failures_by_status["403_cloudflare"] += 1
            elif "timeout" in lead.notes.lower():
                report.fetch_failures_by_status["timeout"] += 1
            else:
                report.fetch_failures_by_status["other"] += 1
        elif lead.outcome == "no_match":
            report.no_match += 1
            if lead.name_ratio is not None:
                bucket = _bucket_name_ratio(lead.name_ratio)
                report.name_ratio_buckets[bucket] += 1
                if bucket == "40-59":
                    # Prime candidates for contact-page fallback
                    report.leads_with_name_ratio_40_59.append(lead)

    # Top no-match domains (excluding obvious directories if desired)
    no_match_domains = Counter()
    for row in rows:
        lead = _parse_lead_notes(row.reason)
        if lead.outcome == "no_match" and lead.domain:
            no_match_domains[lead.domain] += 1
    report.top_no_match_domains = no_match_domains.most_common(30)

    return report
