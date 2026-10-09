#!/usr/bin/env python3
"""Is this REQUISITION still open? Three answers: live, gone, uncertain. No LLM.

Why: "the page answered and carries no 'posting gone' phrase" is not the same as "the job
is open". A careers home page, a JavaScript shell that answers 200 for any id, a board the
employer has moved away from, and an announcement that closed but stays online all pass
that test. So each applicant-tracking system is asked about the requisition itself, and a
page with no adapter is only called live when it still looks like one posting.

The one rule that matters: ONLY AN AUTHORITATIVE SIGNAL SAYS "gone". A wrong "gone" drops
a posting the applicant could still apply to. A timeout, 403, 429, 5xx, bot challenge or a
body that does not parse is "uncertain", never "gone". Every API "gone" below is checked
against a second answer from the same employer system (the board exists, the site search
works, the board search does not list the requisition) before it is said.

"uncertain" means a person or a browser has to look: scripts/verify_url.py prints it and
/start-next-app tells the session to read the page before any writing.

Used through scripts/verify_url.py, which fetches the posting page once and hands it in.
Standard library plus `requests` (which verify_url.py already needs), imported when the
first API call is made.
Tests: `python3 -m unittest discover -s tests` from the kit root, all offline.
"""
from __future__ import annotations

import html as _html
import json
import re
import urllib.parse
from dataclasses import dataclass
from typing import Callable, Optional

UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36")
# An API that has not answered in this many seconds is "uncertain" now and can be asked again.
API_TIMEOUT = 10

LIVE, GONE, UNCERTAIN = "live", "gone", "uncertain"


@dataclass
class Liveness:
    state: str                      # live | gone | uncertain
    method: str                     # which check decided
    evidence: str                   # the observation, short and quotable
    reason: Optional[str] = None    # set only when gone: verify_url.py's posting_gone_reason


@dataclass
class Resp:
    status: int
    text: str
    url: str

    def json(self):
        try:
            return json.loads(self.text)
        except ValueError:
            return None


@dataclass
class Page:
    """The posting page verify_url.py already fetched."""
    status: int
    url: str        # final URL after redirects
    text: str       # raw HTML


class FetchError(Exception):
    """Nothing came back from an API call (timeout, DNS, connection reset)."""


Fetch = Callable[..., Resp]


def http_fetch(method: str, url: str, headers: Optional[dict] = None,
               body: Optional[dict] = None) -> Resp:
    import requests
    try:
        r = requests.request(method, url, headers={"User-Agent": UA, **(headers or {})},
                             json=body, timeout=API_TIMEOUT, allow_redirects=True)
    except requests.RequestException as e:
        raise FetchError(type(e).__name__) from e
    return Resp(r.status_code, r.text or "", r.url)


def _live(method: str, evidence: str) -> Liveness:
    return Liveness(LIVE, method, evidence[:240])


def _gone(method: str, evidence: str) -> Liveness:
    return Liveness(GONE, method, evidence[:240], reason="req_gone:" + method)


def _uncertain(method: str, evidence: str) -> Liveness:
    return Liveness(UNCERTAIN, method, evidence[:240])


def _call(fetch: Fetch, method: str, http_method: str, url: str,
          headers: Optional[dict] = None, body: Optional[dict] = None):
    """(Resp, None), or (None, an uncertain Liveness) when nothing came back."""
    try:
        return fetch(http_method, url, headers, body), None
    except FetchError as e:
        return None, _uncertain(method, f"API request failed: {e}")


def _odd(method: str, resp: Resp, what: str) -> Liveness:
    """An answer that is neither yes nor no: 403, 429, 5xx, an unexpected body."""
    return _uncertain(method, f"{what} answered HTTP {resp.status}, not a yes or a no")


def _quote(s, n: int = 70) -> str:
    return re.sub(r"\s+", " ", str(s or "")).strip()[:n]


def visible_text(page_html: str) -> str:
    """What a reader would see: scripts, styles and tags removed."""
    s = re.sub(r"<(script|style|noscript)[^>]*>.*?</\1>", " ", page_html or "", flags=re.S | re.I)
    s = re.sub(r"<[^>]+>", " ", s)
    s = _html.unescape(s)
    return re.sub(r"\s+", " ", s).strip()


# --------------------------------------------------------------------------
# Adapters. Each returns None when the URL is not its system, else a Liveness.
# --------------------------------------------------------------------------

def greenhouse_api(url: str):
    """(board, job id, API URL)."""
    m = re.search(r"greenhouse\.io/([^/]+)/jobs/(\d+)", url)
    if not m:
        return None
    return m.group(1), m.group(2), ("https://boards-api.greenhouse.io/v1/boards/"
                                    f"{m.group(1)}/jobs/{m.group(2)}")


def _greenhouse(url: str, page: Page, fetch: Fetch) -> Optional[Liveness]:
    """Boards API by job id: 200 with that id is live, 404 is gone. The public page of
    a removed job can redirect to the board and read as a live page. A board token that
    does not exist answers the same 404 for every job, so a 404 only counts once the
    board itself answers 200."""
    got = greenhouse_api(url)
    if not got:
        return None
    board, job, api = got
    me = "greenhouse_api"
    r, bad = _call(fetch, me, "GET", api, {"Accept": "application/json"})
    if bad:
        return bad
    d = r.json()
    if r.status == 200 and isinstance(d, dict) and str(d.get("id")) == job:
        return _live(me, f"boards API 200, job {job} '{_quote(d.get('title'))}'")
    if r.status == 404:
        rb, bad = _call(fetch, me, "GET", f"https://boards-api.greenhouse.io/v1/boards/{board}",
                        {"Accept": "application/json"})
        if bad:
            return bad
        if rb.status == 200 and isinstance(rb.json(), dict):
            return _gone(me, f"boards API: job {job} not found, and the board '{board}' itself answers")
        if rb.status == 404:
            return _uncertain(me, f"board '{board}' not found: the employer may have moved its job board")
        return _odd(me, rb, "Greenhouse board lookup")
    return _odd(me, r, "Greenhouse boards API")


def workday_api(url: str):
    """(site base URL, job path, API URL)."""
    m = re.match(r"https?://([^.]+)\.(wd\d+)\.myworkdayjobs\.com/(?:[a-z]{2}-[A-Z]{2}/)?([^/]+)/job/(.+)$",
                 url.split("#")[0].split("?")[0])
    if not m:
        return None
    tenant, wd, site, tail = m.groups()
    base = f"https://{tenant}.{wd}.myworkdayjobs.com/wday/cxs/{tenant}/{site}"
    return base, tail, f"{base}/job/{tail}"


def _workday(url: str, page: Page, fetch: Fetch) -> Optional[Liveness]:
    """Per-job CXS endpoint. 200 with jobPostingInfo is live.

    A closed requisition answers 404 (errorCode S21, 'not found') or 403 with errorCode
    S22 ('permission denied'). S22 is observed behaviour, not Workday documentation. Any
    other 403 is a block, not an answer. Because Workday can re-path a posting that is
    still open, neither code says gone until the board's own search, asked for the
    requisition id, comes back without it."""
    if "myworkdayjobs.com" not in url:
        return None
    me = "workday_cxs"
    got = workday_api(url)
    if not got:
        return _uncertain("workday_board", "a Workday board or search URL, no /job/ requisition path in it")
    base, tail, api = got
    r, bad = _call(fetch, me, "GET", api, {"Accept": "application/json"})
    if bad:
        return bad
    d = r.json() if isinstance(r.json(), dict) else {}
    if r.status == 200:
        ji = d.get("jobPostingInfo")
        if not isinstance(ji, dict):
            return _uncertain(me, "CXS answered 200 without jobPostingInfo")
        if ji.get("posted") is False or ji.get("canApply") is False:
            return _uncertain(me, f"CXS 200 for {ji.get('jobReqId')} but posted={ji.get('posted')}, "
                                  f"canApply={ji.get('canApply')}")
        return _live(me, f"CXS 200, {ji.get('jobReqId')} '{_quote(ji.get('title'))}', canApply true")
    code = d.get("errorCode")
    if r.status == 404 or (r.status == 403 and code == "S22"):
        anchor = tail.rstrip("/").split("/")[-1]
        if "_" not in anchor:
            return _uncertain(me, f"CXS {r.status} {code or ''}, and no req id in the URL to look for on the board")
        req = re.sub(r"-\d{1,2}$", "", anchor.split("_", 1)[1])      # a trailing -1 is posting 1 of that req
        rs, bad = _call(fetch, me, "POST", base + "/jobs",
                        {"Accept": "application/json", "Content-Type": "application/json"},
                        {"appliedFacets": {}, "limit": 20, "offset": 0, "searchText": req})
        if bad:
            return bad
        ds = rs.json()
        if rs.status != 200 or not isinstance(ds, dict) or not isinstance(ds.get("jobPostings"), list):
            return _odd(me, rs, "Workday board search")
        hit = [p.get("externalPath") for p in ds["jobPostings"]
               if isinstance(p, dict) and ("_" + req) in str(p.get("externalPath"))]
        if hit:
            return _uncertain(me, f"CXS {r.status} at this path but the board lists {req} at {hit[0]}: "
                                  "the posting moved, use that URL")
        return _gone(me, f"CXS {r.status} {code or ''} ({_quote(d.get('message'), 30)}) "
                         f"and the board's own search has no {req}")
    return _odd(me, r, "Workday CXS")


def smartrecruiters_api(url: str):
    """(posting id, API URL)."""
    m = re.search(r"smartrecruiters\.com/([^/]+)/(\d+)", url)
    if not m:
        return None
    return m.group(2), ("https://api.smartrecruiters.com/v1/companies/"
                        f"{m.group(1)}/postings/{m.group(2)}")


def _smartrecruiters(url: str, page: Page, fetch: Fetch) -> Optional[Liveness]:
    """Posting API: `active` true is live, false is gone, anything else is uncertain.
    A closed posting keeps answering 200 on its public page and 200 with active=false here."""
    got = smartrecruiters_api(url)
    if not got:
        return None
    pid, api = got
    me = "smartrecruiters_api"
    r, bad = _call(fetch, me, "GET", api, {"Accept": "application/json"})
    if bad:
        return bad
    d = r.json()
    if r.status == 200 and isinstance(d, dict) and str(d.get("id")) == pid:
        if d.get("active") is True:
            return _live(me, f"posting {pid} active=true, '{_quote(d.get('name'))}'")
        if d.get("active") is False:
            return _gone(me, f"posting {pid} active=false, '{_quote(d.get('name'))}'")
        return _uncertain(me, f"posting {pid} answered 200 with no active flag")
    return _odd(me, r, "SmartRecruiters posting API")


def oracle_hcm_api(url: str):
    """(host, site, req id, API URL)."""
    m = re.match(r"(https?://[^/]+)/hcmUI/CandidateExperience/(?:[^/]+/)?sites/([^/]+)/job/([^/?#]+)", url)
    if not m:
        return None
    host, site, jid = m.groups()
    api = (f"{host}/hcmRestApi/resources/latest/recruitingCEJobRequisitionDetails?expand=all"
           f"&finder=ById;Id=%22{urllib.parse.quote(jid)}%22,siteNumber=%22{urllib.parse.quote(site)}%22")
    return host, site, jid, api


def _oracle_hcm(url: str, page: Page, fetch: Fetch) -> Optional[Liveness]:
    """Oracle Recruiting Cloud, by the ById finder: 1 item with that Id is live, 0 items
    is gone. The CandidateExperience page is a JavaScript shell that answers 200 for any
    id. A wrong host also answers 0 items, so 0 only counts once the same host's site
    search lists jobs."""
    got = oracle_hcm_api(url)
    if not got:
        return None
    host, site, jid, api = got
    me = "oracle_hcm_byid"
    r, bad = _call(fetch, me, "GET", api, {"Accept": "application/json"})
    if bad:
        return bad
    d = r.json()
    if r.status != 200 or not isinstance(d, dict) or not isinstance(d.get("items"), list):
        return _odd(me, r, "Oracle HCM ById")
    items = [i for i in d["items"] if isinstance(i, dict) and str(i.get("Id")) == jid]
    if items:
        return _live(me, f"ById {jid} returns 1 item, '{_quote(items[0].get('Title'))}'")
    if d["items"]:
        return _uncertain(me, f"ById {jid} returned an item with another Id")
    rs, bad = _call(fetch, me, "GET",
                    f"{host}/hcmRestApi/resources/latest/recruitingCEJobRequisitions?onlyData=true"
                    f"&finder=findReqs;siteNumber={urllib.parse.quote(site)},limit=1",
                    {"Accept": "application/json"})
    if bad:
        return bad
    ds = rs.json()
    try:
        total = int(ds["items"][0]["TotalJobsCount"])
    except (TypeError, KeyError, IndexError, ValueError):
        return _odd(me, rs, "Oracle HCM site search")
    if total > 0:
        return _gone(me, f"ById {jid} returns 0 items while the same site lists {total} jobs")
    return _uncertain(me, f"ById {jid} returns 0 items and the site search lists none either")


_UKG_DETAIL = re.compile(r"CandidateOpportunityDetail\((\{.*?\})\);", re.S)


def _ultipro(url: str, page: Page, fetch: Fetch) -> Optional[Liveness]:
    """UltiPro / UKG, from the OpportunityDetail page verify_url.py already fetched: no
    second request.

    A posted opportunity ships its record in the page
    (CandidateOpportunityDetail({... "OpportunityIsClosed": false})). One that has been
    taken down ships the board's own error block instead, keyed
    Opportunity.OpportunityError.OpportunityUnavailableMessage. An id the board never
    had gets NotFoundErrorMessage, which may be a mistyped URL, so that is uncertain."""
    if "ultipro.com" not in url:
        return None
    m = re.search(r"opportunityId=([0-9a-fA-F-]{36})", url)
    if not m:
        return _uncertain("ultipro_board", "an UltiPro job board URL with no opportunityId in it")
    if page.status != 200:
        return None                                   # 404, 5xx: the page rules below
    oid = m.group(1).lower()
    me = "ultipro_detail"
    md = _UKG_DETAIL.search(page.text)
    if md:
        try:
            d = json.loads(md.group(1))
        except ValueError:
            return _uncertain(me, "the opportunity record in the page does not parse")
        if str(d.get("Id", "")).lower() != oid:
            return _uncertain(me, "the page carries a record for another opportunity")
        label = f"{d.get('RequisitionNumber')} '{_quote(d.get('Title'))}'"
        if d.get("OpportunityIsClosed"):
            return _gone("ultipro_closed", f"{label}: OpportunityIsClosed is true")
        return _live(me, f"{label}: record in the page, OpportunityIsClosed false")
    if "OpportunityError.OpportunityUnavailableMessage" in page.text:
        return _gone("ultipro_unavailable",
                     f"the board answers opportunity {oid[:8]} with its 'opportunity unavailable' block")
    if "OpportunityError.NotFoundErrorMessage" in page.text:
        return _uncertain(me, f"the board does not know opportunity {oid[:8]}: wrong id, or purged")
    return _uncertain(me, "neither an opportunity record nor the board's error block in the page")


def _usajobs(url: str, page: Page, fetch: Fetch) -> Optional[Liveness]:
    """USAJobs keeps a closed announcement at HTTP 200 and still prints its 'must be
    submitted by' sentence. The status block is the tell: 'This job announcement has
    closed' and a 'Closed date:' line, under a badge reading 'Reviewing applications' or
    'Job canceled'. An open one reads 'Accepting applications'. No date is copied out of
    the page: a close date is read by a person on the employer's page."""
    if not re.search(r"usajobs\.gov(?::\d+)?/job/\d+", url) or page.status != 200:
        return None
    me = "usajobs_status_block"
    txt = visible_text(page.text)
    closed = re.search(r"This job announcement has closed", txt, re.I)
    closed_date = re.search(r"\bClosed date:", txt)
    if closed or closed_date:
        badge = re.search(r"Reviewing applications|Job canceled", txt, re.I)
        said = "'This job announcement has closed'" if closed else "a 'Closed date:' line"
        return _gone("usajobs_closed", f"the page says {said}" + (f", status '{badge.group(0)}'" if badge else ""))
    if re.search(r"Accepting applications", txt):
        return _live(me, "status 'Accepting applications', no closed line")
    return _uncertain(me, "neither 'Accepting applications' nor a closed line on the page")


def _neogov(url: str, page: Page, fetch: Fetch) -> Optional[Liveness]:
    """NEOGOV / governmentjobs.com stays HTTP 200 after a recruitment stops. A paused
    one says so in its description ('... to place a hold on accepting new applications');
    an id that has expired lands on a page reading 'Job posting is not found or expired'."""
    m = re.search(r"governmentjobs\.com/careers/([^/?#]+)(?:/jobs/(\d+))?", url)
    if not m:
        return None
    if not m.group(2):
        return _uncertain("neogov_agency_home", f"the {m.group(1)} agency job list, no job id in the URL")
    if page.status != 200:
        return None
    me = "neogov_page"
    txt = visible_text(page.text)
    hold = re.search(r"[^.]{0,90}to place a hold on accepting new applications", txt, re.I)
    if hold:
        return _gone("neogov_hold", f"the posting says '{_quote(hold.group(0), 170)}'")
    if re.search(r"Job posting is not found or expired", txt, re.I):
        return _gone("neogov_expired", "the page says 'Job posting is not found or expired'")
    if m.group(2) in page.url and re.search(r"\bClosing Date\b", txt):
        return _live(me, f"job {m.group(2)} page with its Closing Date block, no hold or expired text")
    return _uncertain(me, f"job {m.group(2)}: no posting header and no hold or expired text")


def icims_api(url: str):
    """(job id, in-frame posting URL, portal search URL)."""
    m = re.match(r"https?://([^/]+\.icims\.com)/jobs/(\d+)", url)
    if not m:
        return None
    host, jid = m.groups()
    return jid, f"https://{host}/jobs/{jid}/job?in_iframe=1", f"https://{host}/jobs/search?in_iframe=1"


_ICIMS_NOT_OPEN = "either does not exist or is no longer open"


def _icims(url: str, page: Page, fetch: Fetch) -> Optional[Liveness]:
    """iCIMS. The public page is a frame around /jobs/<id>/job?in_iframe=1, so the page
    verify_url.py fetched has no text; the frame's own URL is the posting.

    Observed behaviour, not vendor documentation: an open job answers 200 with a
    schema.org JobPosting whose url names the id. A job that is not open answers HTTP
    410, either with 'The job that you were looking for either does not exist or is no
    longer open' or with nothing but a script sending the reader to the employer's
    careers site. An id the tenant never issued answers the same 410. The 410 counts once
    the tenant's own /jobs/search answers 200 (a host that is not an iCIMS portal answers
    404 there). A 200 that only lost the id is uncertain."""
    got = icims_api(url)
    if not got:
        return None
    jid, api, search = got
    me = "icims_frame"
    r, bad = _call(fetch, me, "GET", api, {"Accept": "text/html,*/*"})
    if bad:
        return bad
    said = _ICIMS_NOT_OPEN in r.text
    if r.status == 410 or (r.status == 200 and said):
        rs, bad = _call(fetch, me, "GET", search, {"Accept": "text/html,*/*"})
        if bad:
            return bad
        if rs.status != 200:
            return _odd(me, rs, "iCIMS portal search page")
        what = f"iCIMS answers HTTP {r.status} for job {jid}"
        if said:
            what += ": 'The job that you were looking for either does not exist or is no longer open'"
        return _gone("icims_not_open", what + "; the tenant's portal itself answers")
    if r.status != 200:
        return _odd(me, r, "iCIMS posting frame")
    for node in jobposting_nodes(r.text):
        if f"/jobs/{jid}/" in str(node.get("url", "")) or f"/jobs/{jid}/" in r.url:
            return _live(me, f"job {jid} '{_quote(node.get('title'))}': posting data in the frame")
    if f"/jobs/{jid}/" not in r.url:
        return _uncertain(me, f"asked for job {jid}, landed on {_quote(r.url, 100)} without it and no closed message")
    return _uncertain(me, f"job {jid}: the frame answered 200 with no posting data and no closed message")


ADAPTERS = (_greenhouse, _workday, _smartrecruiters, _oracle_hcm, _ultipro,
            _usajobs, _neogov, _icims)


# --------------------------------------------------------------------------
# Pages with no adapter.
# --------------------------------------------------------------------------

# "A job id" in a URL: five or more digits, a UUID, or a 32-hex guid.
_ID = re.compile(r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}|[0-9a-f]{32}|\d{5,}", re.I)
_CAREERS_WORD = re.compile(r"career|job|search|hiring|employment|recruit|opportunit|vacanc", re.I)
_JSONLD = re.compile(r'<script[^>]+application/ld\+json[^>]*>(.*?)</script>', re.S | re.I)
_JSON_DESC = re.compile(r'"description"\s*:\s*"((?:[^"\\]|\\.)*)"')
_CHALLENGE = re.compile(r"Just a moment|Attention Required|Pardon Our Interruption|Access Denied|"
                        r"captcha-delivery|cf-chl|Incapsula|verify you are (a )?human", re.I)
SHELL_CHARS = 300        # a posting page a person can read runs to thousands


def url_ids(url: str) -> list:
    p = urllib.parse.urlsplit(url)
    return _ID.findall(p.path + "?" + p.query)


def jobposting_nodes(page_html: str) -> list:
    """schema.org JobPosting blocks in a page."""
    out = []
    for blob in _JSONLD.findall(page_html):
        try:
            data = json.loads(blob.strip())
        except ValueError:
            continue
        for node in (data if isinstance(data, list) else [data]):
            if isinstance(node, dict) and "JobPosting" in str(node.get("@type", "")):
                out.append(node)
    return out


def jobposting_title(page_html: str) -> Optional[str]:
    nodes = jobposting_nodes(page_html)
    return str(nodes[0].get("title") or "untitled") if nodes else None


def is_page_blip(reason: Optional[str]) -> bool:
    """A network error or 5xx on the posting page: no evidence either way."""
    return bool(reason) and reason.startswith(("network_error", "http_5"))


def _page_gone(reason: str, page: Page) -> Liveness:
    """The page evidence verify_url.py has always used (HTTP 404 or 410, or a gone
    phrase), kept as it was and quoted."""
    if not reason.startswith("marker:"):
        return Liveness(GONE, "http_status", "the posting URL answered HTTP " + reason.replace("http_", ""),
                        reason=reason)
    try:
        m = re.search(reason[7:], re.sub(r"\s+", " ", page.text).lower())
    except re.error:
        m = None
    said = f"the page says '{_quote(m.group(0))}'" if m else "the page carries a posting-gone phrase"
    return Liveness(GONE, "gone_phrase", said[:240], reason=reason)


def _generic(url: str, page: Page, page_gone: Optional[str]) -> Liveness:
    if page_gone:
        if is_page_blip(page_gone):
            return _uncertain("http_status", "the posting URL answered HTTP " + str(page.status))
        return _page_gone(page_gone, page)
    txt = visible_text(page.text)
    if page.status != 200:
        what = " behind a bot challenge" if (len(txt) < 2000 and _CHALLENGE.search(page.text)) else ""
        return _uncertain("http_status", f"the posting URL answered HTTP {page.status}{what}")
    if len(txt) < 2000 and _CHALLENGE.search(page.text) and not jobposting_title(page.text):
        return _uncertain("bot_challenge", f"a bot challenge page, not the posting: '{_quote(txt, 60)}'")
    ids = url_ids(url)
    if ids and ids[-1].lower() not in page.url.lower():
        return _uncertain("redirect_lost_id",
                          f"asked for {ids[-1][:12]}, landed on {_quote(page.url, 110)} without it")
    if not ids:
        p = urllib.parse.urlsplit(url)
        if p.path in ("", "/") or _CAREERS_WORD.search(p.netloc + p.path + "?" + p.query):
            return _uncertain("no_req_id", "a careers, program or search page: no requisition id in the URL, "
                                           "so the page answering says nothing about one req")
    title = jobposting_title(page.text)
    described = max((len(x) for x in _JSON_DESC.findall(page.text)), default=0) >= 600
    if len(txt) < SHELL_CHARS and not title and not described:
        return _uncertain("shell_page", f"HTTP 200 with {len(txt)} characters of text and no posting data: "
                                        "a JavaScript shell, unread")
    if title:
        return _live("page", f"HTTP 200, the page carries the posting '{_quote(title)}', no gone phrase")
    return _live("page", "HTTP 200, readable text, no gone phrase")


def check(url: str, status: int, final_url: str, text: str,
          page_gone: Optional[str] = None, fetch: Optional[Fetch] = None) -> Liveness:
    """Decide one posting URL. `status`, `final_url` and `text` are the page
    verify_url.py fetched; `page_gone` is what its detect_posting_gone said. An
    adapter's live or gone stands. When the adapter cannot tell, a page 404, 410 or gone
    phrase still counts, exactly as before this module existed."""
    page = Page(status, final_url or url, text or "")
    fetch = fetch or http_fetch
    for adapter in ADAPTERS:
        lv = adapter(url, page, fetch)
        if lv is None:
            continue
        if lv.state == UNCERTAIN and page_gone and not is_page_blip(page_gone):
            return _page_gone(page_gone, page)
        return lv
    return _generic(url, page, page_gone)
