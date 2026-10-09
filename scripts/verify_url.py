#!/usr/bin/env python3
"""Fetch a job posting URL and report:

  - is_live: True iff the page exists AND does not contain "posting gone" markers
  - close_at: parsed close datetime if the page text states one (else None)
  - close_source_text: the raw matched snippet (for the audit log)
  - posting_gone_reason: short string explaining why is_live=False (else None)
  - liveness, liveness_method, liveness_evidence: the requisition-level answer from
    req_liveness.py, which asks the employer's job system about the requisition itself
    and may say "uncertain". `is_live` stays a bool: True for live AND uncertain, False
    for gone (and, as before, when the posting page itself did not answer or gave a 5xx).

NO LLM. Plain regex + heuristics, scoped to ATS patterns we've observed in
this project's nursing job pipeline (Workday, SmartRecruiters, LinkedIn,
Built In, Providence, REDCap, ICIMS). Adding a new ATS = add a regex.

Datetime parsing is hand-rolled (no `dateutil` available on this Python).
Patterns supported:
  "3 pm- June 4, 2026"           El Camino / ECH Workday wording
  "3pm- Friday December 19"      ECH wording with weekday
  "3 PM PT on June 4, 2026"
  "until 11:59 PM PT 6/4/2026"
  "Applications close on Aug 11, 2026 at 5:00 PM"
  "removed at 02:24 a.m. (CST) on Friday, Jun 05, 2026"    (Built In)
  "2026-06-04T15:00:00-07:00"    ISO already
Add patterns case-by-case as they show up. Failing to parse → close_at=None
and the daemon falls back to the YAML-declared close_at.
"""
from __future__ import annotations

import re
import sys
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional
from zoneinfo import ZoneInfo

import requests

sys.path.insert(0, str(Path(__file__).resolve().parent))
try:
    import req_liveness          # same directory; the requisition-level check
except Exception:                # the page evidence still works without it
    req_liveness = None

PACIFIC = ZoneInfo("America/Los_Angeles")
USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 14_6) AppleWebKit/605.1.15 "
    "(KHTML, like Gecko) Version/17.6 Safari/605.1.15"
)
REQUEST_TIMEOUT = 25

POSTING_GONE_MARKERS = [
    r"sorry,?\s+this\s+job\s+was\s+removed",
    r"this\s+(job|position|posting)\s+is\s+no\s+longer\s+(available|active|open|accepting)",
    r"posting\s+(has\s+)?expired",
    r"this\s+position\s+has\s+been\s+filled",
    r"no\s+longer\s+accepting\s+applications",
    r"applications\s+are\s+closed",
    r"this\s+req(uisition)?\s+is\s+closed",
    r"page\s+not\s+found",
    r"404\s+not\s+found",
]

# "open until 3 pm– June 4, 2026" / "open until 3pm– Friday December 19" /
# "remain open until 3 pm- June 4, 2026" — accept en/em/hyphen, optional weekday.
OPEN_UNTIL_RX = re.compile(
    r"open\s+until\s+(?P<hour>\d{1,2})(?::(?P<min>\d{2}))?\s*"
    r"(?P<ampm>[ap]\.?m\.?)?\s*"
    r"(?P<tz>[A-Z]{2,4})?\s*"
    r"[\-–—]?\s*"
    r"(?:(?P<wd>Mon|Tue|Wed|Thu|Fri|Sat|Sun)\w*,?\s+)?"
    r"(?P<month>Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Sept|Oct|Nov|Dec)\w*\s+"
    r"(?P<day>\d{1,2})(?:,?\s+(?P<year>\d{4}))?",
    re.IGNORECASE,
)

# "removed at 02:24 a.m. (CST) on Friday, Jun 05, 2026"
REMOVED_AT_RX = re.compile(
    r"removed\s+at\s+(?P<hour>\d{1,2}):(?P<min>\d{2})\s*"
    r"(?P<ampm>[ap]\.?m\.?)\s*"
    r"\((?P<tz>[A-Z]{2,4})\)\s+on\s+"
    r"(?:(?P<wd>Mon|Tue|Wed|Thu|Fri|Sat|Sun)\w*,?\s+)?"
    r"(?P<month>Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Sept|Oct|Nov|Dec)\w*\s+"
    r"(?P<day>\d{1,2}),?\s+(?P<year>\d{4})",
    re.IGNORECASE,
)

# "applications close on Aug 11, 2026 at 5:00 PM PT"
CLOSE_ON_RX = re.compile(
    r"(?:applications?\s+(?:close|due)|deadline\s+is)\s+(?:on\s+)?"
    r"(?P<month>Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Sept|Oct|Nov|Dec)\w*\s+"
    r"(?P<day>\d{1,2}),?\s+(?P<year>\d{4})"
    r"(?:\s+at\s+(?P<hour>\d{1,2})(?::(?P<min>\d{2}))?\s*(?P<ampm>[ap]\.?m\.?)?\s*(?P<tz>[A-Z]{2,4})?)?",
    re.IGNORECASE,
)

# "11:59 PM PT 6/4/2026"
NUMERIC_DATE_RX = re.compile(
    r"(?P<hour>\d{1,2}):(?P<min>\d{2})\s*(?P<ampm>[ap]\.?m\.?)\s*(?P<tz>[A-Z]{2,4})?"
    r"\s+(?P<m>\d{1,2})/(?P<d>\d{1,2})/(?P<y>\d{2,4})",
    re.IGNORECASE,
)

MONTHS = {
    "jan": 1, "feb": 2, "mar": 3, "apr": 4, "may": 5, "jun": 6,
    "jul": 7, "aug": 8, "sep": 9, "sept": 9, "oct": 10, "nov": 11, "dec": 12,
}
TZ_OFFSETS = {  # rough — we only need this for Workday-class postings that say PT/ET
    "PT": ZoneInfo("America/Los_Angeles"),
    "PDT": ZoneInfo("America/Los_Angeles"),
    "PST": ZoneInfo("America/Los_Angeles"),
    "ET": ZoneInfo("America/New_York"),
    "EDT": ZoneInfo("America/New_York"),
    "EST": ZoneInfo("America/New_York"),
    "CT": ZoneInfo("America/Chicago"),
    "CDT": ZoneInfo("America/Chicago"),
    "CST": ZoneInfo("America/Chicago"),
    "MT": ZoneInfo("America/Denver"),
    "MDT": ZoneInfo("America/Denver"),
    "MST": ZoneInfo("America/Denver"),
}


@dataclass
class VerifyResult:
    url: str
    http_status: int
    is_live: bool
    close_at: Optional[datetime]
    close_source_text: Optional[str]
    posting_gone_reason: Optional[str]
    fetched_at: datetime
    liveness: str = "uncertain"         # live | gone | uncertain
    liveness_method: str = ""           # which check decided
    liveness_evidence: str = ""         # the observation, short


def _to_24h(hour: int, ampm: Optional[str]) -> int:
    if not ampm:
        return hour
    ap = ampm.replace(".", "").lower()
    if ap == "pm" and hour != 12:
        return hour + 12
    if ap == "am" and hour == 12:
        return 0
    return hour


def _resolve_tz(tz_str: Optional[str]) -> ZoneInfo:
    if not tz_str:
        return PACIFIC
    return TZ_OFFSETS.get(tz_str.upper(), PACIFIC)


def _build_dt(year: int, month: int, day: int, hour: int, minute: int, tz: ZoneInfo) -> datetime:
    return datetime(year, month, day, hour, minute, 0, tzinfo=tz)


def parse_close_date(text: str, posted_at: Optional[datetime] = None) -> tuple[Optional[datetime], Optional[str]]:
    """Return (close_at, source_snippet). None if no pattern matches."""
    # OPEN UNTIL
    m = OPEN_UNTIL_RX.search(text)
    if m:
        hour = _to_24h(int(m.group("hour")), m.group("ampm"))
        minute = int(m.group("min") or 0)
        month = MONTHS[m.group("month")[:3].lower()]
        day = int(m.group("day"))
        year_str = m.group("year")
        if year_str:
            year = int(year_str)
        else:
            year = (posted_at or datetime.now(PACIFIC)).year
            tentative = _build_dt(year, month, day, hour, minute, _resolve_tz(m.group("tz")))
            if tentative < (posted_at or datetime.now(PACIFIC)) - timedelta(days=30):
                year += 1
        tz = _resolve_tz(m.group("tz"))
        return _build_dt(year, month, day, hour, minute, tz), m.group(0)

    # REMOVED AT (Built In)
    m = REMOVED_AT_RX.search(text)
    if m:
        hour = _to_24h(int(m.group("hour")), m.group("ampm"))
        minute = int(m.group("min"))
        month = MONTHS[m.group("month")[:3].lower()]
        day = int(m.group("day"))
        year = int(m.group("year"))
        tz = _resolve_tz(m.group("tz"))
        return _build_dt(year, month, day, hour, minute, tz), m.group(0)

    # CLOSE ON / DEADLINE IS
    m = CLOSE_ON_RX.search(text)
    if m:
        hour = _to_24h(int(m.group("hour") or 23), m.group("ampm"))
        minute = int(m.group("min") or 59)
        month = MONTHS[m.group("month")[:3].lower()]
        day = int(m.group("day"))
        year = int(m.group("year"))
        tz = _resolve_tz(m.group("tz"))
        return _build_dt(year, month, day, hour, minute, tz), m.group(0)

    # 11:59 PM PT 6/4/2026
    m = NUMERIC_DATE_RX.search(text)
    if m:
        hour = _to_24h(int(m.group("hour")), m.group("ampm"))
        minute = int(m.group("min"))
        month = int(m.group("m"))
        day = int(m.group("d"))
        year = int(m.group("y"))
        if year < 100:
            year += 2000
        tz = _resolve_tz(m.group("tz"))
        return _build_dt(year, month, day, hour, minute, tz), m.group(0)

    return None, None


def detect_posting_gone(text: str, http_status: int) -> Optional[str]:
    if http_status in (404, 410):
        return f"http_{http_status}"
    if http_status >= 500:
        return f"http_{http_status}"
    if http_status == 0:
        return "network_error"
    low = text.lower()
    for rx in POSTING_GONE_MARKERS:
        if re.search(rx, low):
            return f"marker:{rx}"
    return None


def verify(url: str) -> VerifyResult:
    fetched_at = datetime.now(PACIFIC)
    try:
        r = requests.get(
            url,
            timeout=REQUEST_TIMEOUT,
            headers={"User-Agent": USER_AGENT, "Accept": "text/html,*/*"},
            allow_redirects=True,
        )
        status = r.status_code
        text = r.text or ""
    except requests.RequestException as e:
        return VerifyResult(
            url=url,
            http_status=0,
            is_live=False,
            close_at=None,
            close_source_text=None,
            posting_gone_reason=f"network_error:{type(e).__name__}",
            fetched_at=fetched_at,
            liveness="uncertain",
            liveness_method="page_fetch",
            liveness_evidence=f"the posting URL did not answer: {type(e).__name__}",
        )

    text_simple = re.sub(r"\s+", " ", text)
    close_at, snippet = parse_close_date(text_simple)
    gone = detect_posting_gone(text_simple, status)

    # A page without a "gone" phrase is not proof the job is open: a careers home page, a
    # JavaScript shell and a closed announcement that stays online all pass. req_liveness
    # asks the employer's system about the requisition itself and may answer "uncertain".
    page_blip = bool(gone) and gone.startswith(("network_error", "http_5"))
    try:
        lv = req_liveness.check(url, status, r.url, text, gone)
        liveness, method, evidence = lv.state, lv.method, lv.evidence
        if lv.state == "gone":
            is_live, gone = False, lv.reason
        elif lv.state == "live":
            is_live, gone = True, None
        else:                        # uncertain: not gone; a page that gave a 5xx stays not live
            is_live, gone = (not page_blip), (gone if page_blip else None)
    except Exception as e:           # the old answer stands if the new check breaks
        is_live = gone is None
        liveness = "gone" if (gone and not page_blip) else "uncertain"
        method = "liveness_check_failed"
        evidence = f"req_liveness did not run ({type(e).__name__}); page evidence only"

    return VerifyResult(
        url=url,
        http_status=status,
        is_live=is_live,
        close_at=close_at,
        close_source_text=snippet,
        posting_gone_reason=gone,
        fetched_at=fetched_at,
        liveness=liveness,
        liveness_method=method,
        liveness_evidence=evidence,
    )


if __name__ == "__main__":
    import sys
    if len(sys.argv) < 2:
        print("usage: verify_url.py <url> [<url> ...]")
        sys.exit(2)
    for u in sys.argv[1:]:
        rv = verify(u)
        print(f"== {u}")
        print(f"   http {rv.http_status}  live={rv.is_live}  gone={rv.posting_gone_reason}")
        print(f"   close_at={rv.close_at}")
        print(f"   snippet={rv.close_source_text!r}")
        print(f"   liveness={rv.liveness}  method={rv.liveness_method}  evidence={rv.liveness_evidence}")
