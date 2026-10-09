#!/usr/bin/env python3
"""Tests for scripts/req_liveness.py and its wiring in scripts/verify_url.py. No network:
every answer is a fixture.

    python3 -m unittest discover -s tests        (from the kit root)

The fixtures under tests/fixtures/req_liveness/ are synthetic. Each keeps the SHAPE of
what that job system answers (field names, status codes, the phrases the rules look for);
every employer, tenant, board, job id, title and city in them is invented. A page or API
answer this module misreads goes in there, rewritten the same way, before the rule changes.
"""
import contextlib
import io
import json
import runpy
import sys
import unittest
from pathlib import Path

KIT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(KIT / "scripts"))
import req_liveness as rl  # noqa: E402

try:
    import verify_url  # noqa: E402  (needs `requests`, which the kit's .venv has)
except ImportError:
    verify_url = None

FX = Path(__file__).resolve().parent / "fixtures" / "req_liveness"


def fx(name):
    return (FX / name).read_text(encoding="utf-8")


class FakeFetch:
    """Answers API calls from a list of (URL fragment, status, body-or-exception)."""

    def __init__(self, *routes):
        self.routes, self.calls = routes, []

    def __call__(self, method, url, headers=None, body=None):
        self.calls.append((method, url, body))
        for frag, status, payload in self.routes:
            if frag in url:
                if isinstance(payload, Exception):
                    raise payload
                return rl.Resp(status, payload, url)
        raise AssertionError("unexpected request: " + url)


def no_fetch(*a, **k):
    raise AssertionError("this adapter must not make a request")


SHELL = "<html><body><div id='root'></div></body></html>"
READABLE = "<html><body><h1>Registered Nurse</h1><p>" + ("Provides nursing care. " * 40) + "</p></body></html>"

GH_LIVE = "https://job-boards.greenhouse.io/examplehealth/jobs/123456"
GH_DEAD = "https://job-boards.greenhouse.io/examplehealth/jobs/654321"
WD_SITE = "https://examplehealth.wd5.myworkdayjobs.com/ExampleCareers"
WD = WD_SITE + "/job/Anytown/Registered-Nurse---Example-Unit_REQ123456"
WD_LIVE = WD_SITE + "/job/Anytown/Unit-Clerk---Example-Unit_REQ654321"
SR = "https://jobs.smartrecruiters.com/ExampleCounty/1234567890-registered-nurse-example-unit"
SR_CLOSED = "https://jobs.smartrecruiters.com/ExampleCounty/9876543210"
ORA = "https://example.fa.us2.oraclecloud.com/hcmUI/CandidateExperience/en/sites/CX_1/job/123456"
ORA_DEAD = "https://example.fa.us2.oraclecloud.com/hcmUI/CandidateExperience/en/sites/CX_1/job/654321"
UKG_BOARD = "https://recruiting2.ultipro.com/EXA1000/JobBoard/00000000-aaaa-bbbb-cccc-000000000001/"
UKG = UKG_BOARD + "OpportunityDetail?opportunityId="
UKG_LIVE, UKG_DEAD = UKG + "11111111-aaaa-bbbb-cccc-000000000001", UKG + "22222222-aaaa-bbbb-cccc-000000000002"
USA_CLOSED, USA_OPEN = "https://www.usajobs.gov/job/123456789", "https://www.usajobs.gov:443/job/987654321"
NEO = "https://www.governmentjobs.com/careers/examplecounty/jobs/"
ICIMS_HOST = "https://careers-examplehealth.icims.com"
ICIMS = ICIMS_HOST + "/jobs/123456/job"
ICIMS_DEAD = ICIMS_HOST + "/jobs/654321"
ICIMS_SLUG = ICIMS_HOST + "/jobs/222222/staff-nurse/job"
JOB = "https://jobs.example.org/Recruiting/Jobs/Details/123456"


def check(url, text=SHELL, status=200, final=None, page_gone=None, fetch=no_fetch):
    return rl.check(url, status, final or url, text, page_gone, fetch)


class Greenhouse(unittest.TestCase):
    def test_200_with_matching_id_is_live(self):
        lv = check(GH_LIVE, fetch=FakeFetch(("/jobs/123456", 200, fx("greenhouse_job_live.json"))))
        self.assertEqual((lv.state, lv.method), ("live", "greenhouse_api"))
        self.assertIn("123456", lv.evidence)

    def test_404_with_the_board_answering_is_gone(self):
        # The public page of a removed job can redirect to the board and read as a live page.
        f = FakeFetch(("/jobs/654321", 404, fx("greenhouse_job_404.json")),
                      ("/boards/examplehealth", 200, fx("greenhouse_board.json")))
        lv = check(GH_DEAD, READABLE, fetch=f)
        self.assertEqual((lv.state, lv.reason), ("gone", "req_gone:greenhouse_api"))

    def test_404_when_the_board_itself_is_missing_is_uncertain(self):
        f = FakeFetch(("/jobs/654321", 404, fx("greenhouse_job_404.json")),
                      ("/boards/examplehealth", 404, fx("greenhouse_board_404.json")))
        self.assertEqual(check(GH_DEAD, fetch=f).state, "uncertain")

    def test_200_for_another_id_is_uncertain(self):
        lv = check(GH_DEAD, fetch=FakeFetch(("/jobs/654321", 200, fx("greenhouse_job_live.json"))))
        self.assertEqual(lv.state, "uncertain")


class Workday(unittest.TestCase):
    def test_200_is_live(self):
        lv = check(WD_LIVE, fetch=FakeFetch(("/wday/cxs/examplehealth/", 200, fx("workday_job_live.json"))))
        self.assertEqual((lv.state, lv.method), ("live", "workday_cxs"))
        self.assertIn("REQ654321", lv.evidence)

    def test_403_s22_and_absent_from_the_board_is_gone(self):
        f = FakeFetch(("/ExampleCareers/job/", 403, fx("workday_job_403_s22.json")),
                      ("/ExampleCareers/jobs", 200, fx("workday_search_absent.json")))
        lv = check(WD, fetch=f)
        self.assertEqual((lv.state, lv.reason), ("gone", "req_gone:workday_cxs"))
        self.assertEqual(f.calls[1][2]["searchText"], "REQ123456")

    def test_404_and_absent_from_the_board_is_gone(self):
        f = FakeFetch(("/ExampleCareers/job/", 404, fx("workday_job_404_s21.json")),
                      ("/ExampleCareers/jobs", 200, fx("workday_search_absent.json")))
        self.assertEqual(check(WD, fetch=f).state, "gone")

    def test_403_s22_but_still_listed_is_uncertain(self):
        url = WD.replace("REQ123456", "REQ654321")
        f = FakeFetch(("/ExampleCareers/job/", 403, fx("workday_job_403_s22.json")),
                      ("/ExampleCareers/jobs", 200, fx("workday_search_listed.json")))
        lv = check(url, fetch=f)
        self.assertEqual(lv.state, "uncertain")
        self.assertIn("moved", lv.evidence)

    def test_a_plain_403_is_a_block_not_an_answer(self):
        lv = check(WD, fetch=FakeFetch(("/ExampleCareers/job/", 403, "<html>Access Denied</html>")))
        self.assertEqual(lv.state, "uncertain")
        self.assertIsNone(lv.reason)

    def test_gone_needs_the_board_search_to_answer(self):
        f = FakeFetch(("/ExampleCareers/job/", 403, fx("workday_job_403_s22.json")),
                      ("/ExampleCareers/jobs", 429, "slow down"))
        self.assertEqual(check(WD, fetch=f).state, "uncertain")

    def test_200_with_canapply_false_is_uncertain(self):
        d = json.loads(fx("workday_job_live.json"))
        d["jobPostingInfo"]["canApply"] = False
        lv = check(WD_LIVE, fetch=FakeFetch(("/wday/cxs/examplehealth/", 200, json.dumps(d))))
        self.assertEqual(lv.state, "uncertain")

    def test_locale_prefix_reaches_the_same_endpoint(self):
        self.assertEqual(rl.workday_api(WD.replace("/ExampleCareers/", "/en-US/ExampleCareers/")), rl.workday_api(WD))

    def test_board_or_search_url_is_uncertain_without_a_request(self):
        lv = check(WD_SITE + "?q=nurse")
        self.assertEqual((lv.state, lv.method), ("uncertain", "workday_board"))


class SmartRecruiters(unittest.TestCase):
    def test_active_true_is_live(self):
        lv = check(SR, fetch=FakeFetch(("/postings/1234567890", 200, fx("smartrecruiters_active.json"))))
        self.assertEqual((lv.state, lv.method), ("live", "smartrecruiters_api"))

    def test_active_false_is_gone(self):
        lv = check(SR_CLOSED, READABLE, fetch=FakeFetch(("/postings/9876543210", 200, fx("smartrecruiters_inactive.json"))))
        self.assertEqual((lv.state, lv.reason), ("gone", "req_gone:smartrecruiters_api"))

    def test_anything_else_is_uncertain(self):
        lv = check(SR, fetch=FakeFetch(("/postings/", 404, fx("smartrecruiters_404.json"))))
        self.assertEqual(lv.state, "uncertain")
        d = json.loads(fx("smartrecruiters_active.json"))
        del d["active"]
        self.assertEqual(check(SR, fetch=FakeFetch(("/postings/", 200, json.dumps(d)))).state, "uncertain")


class OracleHCM(unittest.TestCase):
    def test_one_item_is_live(self):
        lv = check(ORA, fetch=FakeFetch(("recruitingCEJobRequisitionDetails", 200, fx("oracle_byid_1.json"))))
        self.assertEqual((lv.state, lv.method), ("live", "oracle_hcm_byid"))
        self.assertIn("123456 returns 1 item", lv.evidence)

    def test_zero_items_with_the_site_search_answering_is_gone(self):
        # The CandidateExperience page is a shell that answers 200 for any id.
        f = FakeFetch(("recruitingCEJobRequisitionDetails", 200, fx("oracle_byid_0.json")),
                      ("recruitingCEJobRequisitions?", 200, fx("oracle_site_search.json")))
        lv = check(ORA_DEAD, fetch=f)
        self.assertEqual((lv.state, lv.reason), ("gone", "req_gone:oracle_hcm_byid"))
        self.assertIn("654321 returns 0 items", lv.evidence)

    def test_zero_items_and_a_site_search_that_does_not_answer_is_uncertain(self):
        f = FakeFetch(("recruitingCEJobRequisitionDetails", 200, fx("oracle_byid_0.json")),
                      ("recruitingCEJobRequisitions?", 200, '{"items": []}'))
        self.assertEqual(check(ORA_DEAD, fetch=f).state, "uncertain")

    def test_an_item_with_another_id_is_uncertain(self):
        lv = check(ORA_DEAD, fetch=FakeFetch(("recruitingCEJobRequisitionDetails", 200, fx("oracle_byid_1.json"))))
        self.assertEqual(lv.state, "uncertain")


class UltiPro(unittest.TestCase):
    def test_record_in_the_page_is_live(self):
        lv = check(UKG_LIVE, fx("ultipro_detail_live.html"))
        self.assertEqual((lv.state, lv.method), ("live", "ultipro_detail"))
        self.assertIn("REQ000123", lv.evidence)

    def test_unavailable_block_is_gone(self):
        lv = check(UKG_DEAD, fx("ultipro_detail_unavailable.html"))
        self.assertEqual((lv.state, lv.reason), ("gone", "req_gone:ultipro_unavailable"))

    def test_closed_flag_is_gone(self):
        lv = check(UKG_LIVE, fx("ultipro_detail_closed_flag.html"))
        self.assertEqual((lv.state, lv.reason), ("gone", "req_gone:ultipro_closed"))

    def test_an_id_the_board_never_had_is_uncertain(self):
        lv = check(UKG + "33333333-aaaa-bbbb-cccc-000000000003", fx("ultipro_detail_notfound.html"))
        self.assertEqual(lv.state, "uncertain")

    def test_record_for_another_opportunity_is_uncertain(self):
        self.assertEqual(check(UKG_DEAD, fx("ultipro_detail_live.html")).state, "uncertain")

    def test_board_url_without_an_opportunity_is_uncertain(self):
        lv = check(UKG_BOARD, READABLE)
        self.assertEqual((lv.state, lv.method), ("uncertain", "ultipro_board"))


class USAJobs(unittest.TestCase):
    def test_closed_announcement_is_gone_though_the_date_sentence_still_prints(self):
        page = fx("usajobs_closed.html")
        self.assertIn("must be submitted by", page)
        lv = check(USA_CLOSED, page)
        self.assertEqual((lv.state, lv.reason), ("gone", "req_gone:usajobs_closed"))
        self.assertNotRegex(lv.evidence, r"\d{1,2}/\d{1,2}/\d{4}")       # no date leaves the page

    def test_a_closed_date_line_alone_is_gone(self):
        page = fx("usajobs_closed.html").replace("This job announcement has closed", "")
        self.assertEqual(check(USA_CLOSED, page).state, "gone")

    def test_accepting_applications_is_live_with_or_without_a_port_in_the_url(self):
        for url in (USA_OPEN, USA_OPEN.replace(":443", "")):
            lv = check(url, fx("usajobs_open.html"))
            self.assertEqual((lv.state, lv.method), ("live", "usajobs_status_block"), url)

    def test_neither_signal_is_uncertain(self):
        self.assertEqual(check(USA_OPEN, READABLE).state, "uncertain")


class Neogov(unittest.TestCase):
    def test_posting_with_its_header_is_live(self):
        lv = check(NEO + "1234567/registered-nurse-example-unit", fx("neogov_live.html"))
        self.assertEqual((lv.state, lv.method), ("live", "neogov_page"))

    def test_hold_on_new_applications_is_gone(self):
        lv = check(NEO + "7654321/registered-nurse-example-unit", fx("neogov_hold.html"))
        self.assertEqual((lv.state, lv.reason), ("gone", "req_gone:neogov_hold"))
        self.assertIn("to place a hold on accepting new applications", lv.evidence)

    def test_not_found_or_expired_is_gone(self):
        lv = check(NEO + "1111111", fx("neogov_expired.html"), final=NEO + "1111111-0/some-other-title")
        self.assertEqual((lv.state, lv.reason), ("gone", "req_gone:neogov_expired"))

    def test_agency_home_is_uncertain(self):
        lv = check("https://www.governmentjobs.com/careers/examplecounty", READABLE)
        self.assertEqual((lv.state, lv.method), ("uncertain", "neogov_agency_home"))


class Icims(unittest.TestCase):
    """The public page is a frame with no text; the adapter reads the frame's own URL."""

    def test_posting_data_for_this_id_is_live(self):
        f = FakeFetch(("/jobs/123456/job?in_iframe=1", 200, fx("icims_frame_live.html")))
        lv = check(ICIMS, fx("generic_shell.html"), fetch=f)
        self.assertEqual((lv.state, lv.method), ("live", "icims_frame"))
        self.assertIn("123456", lv.evidence)

    def test_slug_in_the_url_does_not_change_the_request(self):
        f = FakeFetch(("/jobs/222222/job?in_iframe=1", 410, fx("icims_frame_410_message.html")),
                      ("/jobs/search?in_iframe=1", 200, fx("icims_search_listing.html")))
        lv = check(ICIMS_SLUG, fetch=f)
        self.assertEqual((lv.state, lv.reason), ("gone", "req_gone:icims_not_open"))
        self.assertIn("either does not exist or is no longer open", lv.evidence)

    def test_410_with_only_a_redirect_script_is_gone_once_the_portal_answers(self):
        f = FakeFetch(("/jobs/654321/job?in_iframe=1", 410, fx("icims_frame_410_redirect.html")),
                      ("/jobs/search?in_iframe=1", 200, fx("icims_search_redirect.html")))
        lv = check(ICIMS_DEAD, fetch=f)
        self.assertEqual((lv.state, lv.reason), ("gone", "req_gone:icims_not_open"))

    def test_410_when_the_portal_does_not_answer_is_uncertain(self):
        f = FakeFetch(("/jobs/654321/job?in_iframe=1", 410, fx("icims_frame_410_redirect.html")),
                      ("/jobs/search?in_iframe=1", 404, "<html>not a portal</html>"))
        self.assertEqual(check(ICIMS_DEAD, fetch=f).state, "uncertain")

    def test_a_200_that_only_lost_the_id_is_uncertain(self):
        def f(method, url, headers=None, body=None):
            return rl.Resp(200, fx("icims_search_listing.html"), ICIMS_HOST + "/jobs/search?in_iframe=1")
        lv = check(ICIMS, fetch=f)
        self.assertEqual((lv.state, lv.method), ("uncertain", "icims_frame"))
        self.assertIn("without it", lv.evidence)

    def test_a_200_with_no_posting_data_is_uncertain(self):
        f = FakeFetch(("/jobs/123456/job?in_iframe=1", 200, fx("icims_frame_410_redirect.html")))
        self.assertEqual(check(ICIMS, fetch=f).state, "uncertain")

    def test_posting_data_for_another_job_is_not_live(self):
        def f(method, url, headers=None, body=None):
            return rl.Resp(200, fx("icims_frame_live.html"), ICIMS_HOST + "/jobs/123456/job?in_iframe=1")
        self.assertEqual(check(ICIMS_DEAD + "/job", fetch=f).state, "uncertain")

    def test_when_the_frame_cannot_tell_a_page_410_still_counts(self):
        lv = check(ICIMS_DEAD, "", 410, page_gone="http_410", fetch=FakeFetch(("", 429, "slow down")))
        self.assertEqual((lv.state, lv.reason), ("gone", "http_410"))

    def test_an_icims_url_without_a_job_id_falls_to_the_page_rules(self):
        lv = check(ICIMS_HOST + "/jobs/search", fx("generic_shell.html"))
        self.assertEqual((lv.state, lv.method), ("uncertain", "no_req_id"))


class OnlyAnAuthoritativeSignalSaysGone(unittest.TestCase):
    """A timeout, 403, 429, 5xx or a body that does not parse is never gone."""

    URLS = (GH_DEAD, WD, SR, ORA_DEAD, ICIMS_DEAD)

    def test_api_failures_are_uncertain(self):
        for url in self.URLS:
            for status, body in ((403, "Forbidden"), (429, "Too Many Requests"), (500, "oops"), (502, "bad gateway"),
                                 (503, "<html>busy</html>"), (200, "not json"), (200, "[]"), (200, "{}")):
                lv = check(url, fetch=FakeFetch(("", status, body)))
                self.assertEqual(lv.state, "uncertain", (url, status, body, lv))
                self.assertIsNone(lv.reason, (url, status))

    def test_timeouts_are_uncertain_and_say_so(self):
        for url in self.URLS:
            lv = check(url, fetch=FakeFetch(("", 0, rl.FetchError("Timeout"))))
            self.assertEqual((lv.state, lv.reason), ("uncertain", None), url)
            self.assertIn("API request failed: Timeout", lv.evidence)

    def test_a_timeout_on_the_confirming_request_is_uncertain(self):
        f = FakeFetch(("/jobs/654321", 404, fx("greenhouse_job_404.json")),
                      ("/boards/examplehealth", 0, rl.FetchError("ConnectionError")))
        self.assertEqual(check(GH_DEAD, fetch=f).state, "uncertain")

    def test_every_gone_carries_a_reason_and_nothing_else_does(self):
        gone = check(UKG_DEAD, fx("ultipro_detail_unavailable.html"))
        self.assertTrue(gone.reason.startswith("req_gone:"))
        for lv in (check(JOB, READABLE), check("https://example.org", fx("generic_careers_home.html")),
                   check(JOB, "", 503, page_gone="http_503")):
            self.assertIsNone(lv.reason, lv)


class GenericPages(unittest.TestCase):
    def test_readable_posting_is_live_as_before(self):
        lv = check(JOB, READABLE)
        self.assertEqual((lv.state, lv.method), ("live", "page"))

    def test_jobposting_data_counts_as_a_posting(self):
        lv = check(JOB, fx("generic_jobposting_jsonld.html"))
        self.assertEqual(lv.state, "live")
        self.assertIn("Registered Nurse - Example Unit", lv.evidence)

    def test_gone_phrase_is_gone_with_the_same_reason_as_before(self):
        reason = r"marker:no\s+longer\s+accepting\s+applications"
        lv = check(JOB, READABLE.replace("</p>", " No longer accepting applications.</p>"), page_gone=reason)
        self.assertEqual((lv.state, lv.method, lv.reason), ("gone", "gone_phrase", reason))
        self.assertIn("no longer accepting applications", lv.evidence)

    def test_page_404_and_410_keep_their_reasons(self):
        self.assertEqual(check(JOB, "", 404, page_gone="http_404").reason, "http_404")
        lv = check(JOB, "", 410, page_gone="http_410")
        self.assertEqual((lv.state, lv.method, lv.reason), ("gone", "http_status", "http_410"))

    def test_page_5xx_is_uncertain_not_gone(self):
        lv = check(JOB, "", 503, page_gone="http_503")
        self.assertEqual((lv.state, lv.method), ("uncertain", "http_status"))

    def test_redirect_that_loses_the_job_id_is_uncertain(self):
        lv = check(JOB, READABLE, final="https://jobs.example.org/Recruiting/Jobs/JobNotFound")
        self.assertEqual((lv.state, lv.method), ("uncertain", "redirect_lost_id"))

    def test_redirect_that_keeps_the_job_id_is_live(self):
        lv = check(JOB, READABLE, final=JOB + "/registered-nurse-example-unit")
        self.assertEqual(lv.state, "live")

    def test_uuid_job_id_lost_is_uncertain(self):
        lv = check("https://jobs.example.org/acme/44444444-aaaa-bbbb-cccc-000000000004", READABLE,
                   final="https://jobs.example.org/acme")
        self.assertEqual(lv.method, "redirect_lost_id")

    def test_shell_with_almost_no_text_is_uncertain(self):
        url = ("https://apply.example.org/recruitment/recruitment.html"
               "?cid=55555555-aaaa-bbbb-cccc-000000000005&type=MP&lang=en_US")
        lv = check(url, fx("generic_shell.html"))
        self.assertEqual((lv.state, lv.method), ("uncertain", "shell_page"))

    def test_careers_home_and_search_pages_are_uncertain(self):
        home = fx("generic_careers_home.html")
        for url in ("https://example.org", "https://examplehealth.example/careers/",
                    "https://jobs.example.org/en/search-jobs/nurse",
                    "https://www.examplehealth.careers/residency", "https://www.example.gov/Anytown/jobs.html"):
            lv = check(url, home)
            self.assertEqual((lv.state, lv.method), ("uncertain", "no_req_id"), url)

    def test_other_pages_without_an_id_stay_live(self):
        self.assertEqual(check("https://www.examplehealth.example/willow-center", READABLE).state, "live")

    def test_403_and_bot_challenge_are_uncertain(self):
        lv = check("https://hr.example.edu/x/residency", fx("generic_bot_challenge.html"), 403)
        self.assertEqual((lv.state, lv.method), ("uncertain", "http_status"))
        self.assertIn("bot challenge", lv.evidence)
        lv = check(JOB, fx("generic_bot_challenge.html"), 200)
        self.assertEqual((lv.state, lv.method), ("uncertain", "bot_challenge"))
        self.assertEqual(check(JOB, "Too many requests", 429).state, "uncertain")


class AdapterAndPageEvidenceTogether(unittest.TestCase):
    def test_adapter_live_outranks_a_gone_phrase_in_page_furniture(self):
        lv = check(GH_LIVE, READABLE, page_gone="marker:page\\s+not\\s+found",
                   fetch=FakeFetch(("/jobs/123456", 200, fx("greenhouse_job_live.json"))))
        self.assertEqual(lv.state, "live")

    def test_when_the_adapter_cannot_tell_a_page_gone_still_counts(self):
        lv = check(GH_LIVE, "", 410, page_gone="http_410", fetch=FakeFetch(("", 429, "slow down")))
        self.assertEqual((lv.state, lv.reason), ("gone", "http_410"))

    def test_page_based_adapters_leave_a_failed_page_to_the_page_rules(self):
        lv = check(USA_CLOSED, "", 503, page_gone="http_503")
        self.assertEqual((lv.state, lv.method), ("uncertain", "http_status"))


class SourceRules(unittest.TestCase):
    def test_module_and_fixtures_are_plain_ascii(self):
        for path in [Path(rl.__file__), Path(__file__)] + sorted(FX.iterdir()):
            path.read_text(encoding="ascii")

    def test_the_module_imports_without_requests_and_reads_no_home_or_cwd(self):
        src = Path(rl.__file__).read_text(encoding="ascii")
        self.assertNotRegex(src, r"(?m)^import requests|^from requests")
        for banned in ("Path.home", "expanduser", "getcwd", "Path.cwd", "environ"):
            self.assertNotIn(banned, src, banned)


class _Page:
    """What requests.get returns, as far as verify_url.verify reads it."""

    def __init__(self, status, text, url):
        self.status_code, self.text, self.url = status, text, url


@unittest.skipIf(verify_url is None, "scripts/verify_url.py needs `requests` (use the kit's .venv python)")
class VerifyUrlWiring(unittest.TestCase):
    """verify() with the page fetch and the adapter fetch replaced: what the three new
    fields say, and that is_live and posting_gone_reason mean what they meant."""

    def setUp(self):
        self._get, self._fetch = verify_url.requests.get, rl.http_fetch
        rl.http_fetch = no_fetch
        self.addCleanup(lambda: (setattr(verify_url.requests, "get", self._get), setattr(rl, "http_fetch", self._fetch)))

    def page(self, text=READABLE, status=200, final=None):
        verify_url.requests.get = lambda url, **kw: _Page(status, text, final or url)

    def fields(self, url):
        rv = verify_url.verify(url)
        return rv.is_live, rv.posting_gone_reason, rv.liveness, rv.liveness_method

    def test_readable_page_is_live_as_before(self):
        self.page()
        self.assertEqual(self.fields(JOB), (True, None, "live", "page"))

    def test_gone_phrase_and_404_are_not_live_as_before(self):
        self.page(READABLE.replace("</p>", " This position has been filled.</p>"))
        live, reason, state, method = self.fields(JOB)
        self.assertEqual((live, state, method), (False, "gone", "gone_phrase"))
        self.assertTrue(reason.startswith("marker:"))
        self.page("", 404)
        self.assertEqual(self.fields(JOB), (False, "http_404", "gone", "http_status"))

    def test_page_5xx_is_not_live_as_before_and_reads_uncertain(self):
        self.page("busy", 503)
        self.assertEqual(self.fields(JOB), (False, "http_503", "uncertain", "http_status"))

    def test_page_that_does_not_answer_is_not_live_as_before_and_reads_uncertain(self):
        def down(url, **kw):
            raise verify_url.requests.ConnectionError("down")
        verify_url.requests.get = down
        self.assertEqual(self.fields(JOB), (False, "network_error:ConnectionError", "uncertain", "page_fetch"))

    def test_uncertain_stays_is_live_true_with_no_gone_reason(self):
        self.page(fx("generic_careers_home.html"))
        self.assertEqual(self.fields("https://examplehealth.example/careers/"), (True, None, "uncertain", "no_req_id"))

    def test_adapter_gone_is_not_live_though_the_page_reads_fine(self):
        self.page()
        rl.http_fetch = FakeFetch(("/jobs/654321", 404, fx("greenhouse_job_404.json")),
                                  ("/boards/examplehealth", 200, fx("greenhouse_board.json")))
        self.assertEqual(self.fields(GH_DEAD), (False, "req_gone:greenhouse_api", "gone", "greenhouse_api"))

    def test_adapter_timeout_is_uncertain_and_still_is_live(self):
        self.page()
        rl.http_fetch = FakeFetch(("", 0, rl.FetchError("Timeout")))
        self.assertEqual(self.fields(GH_LIVE), (True, None, "uncertain", "greenhouse_api"))

    def test_adapter_live_clears_a_gone_phrase_in_page_furniture(self):
        self.page(READABLE.replace("</p>", " <a>Page not found</a></p>"))
        rl.http_fetch = FakeFetch(("/jobs/123456", 200, fx("greenhouse_job_live.json")))
        self.assertEqual(self.fields(GH_LIVE), (True, None, "live", "greenhouse_api"))

    def test_if_the_check_breaks_the_old_answer_stands(self):
        self.page()
        real = rl.check
        self.addCleanup(lambda: setattr(rl, "check", real))

        def boom(*a, **k):
            raise RuntimeError("boom")
        rl.check = boom
        self.assertEqual(self.fields(JOB), (True, None, "uncertain", "liveness_check_failed"))
        self.page("", 410)
        self.assertEqual(self.fields(JOB)[:3], (False, "http_410", "gone"))

    def test_cli_keeps_its_lines_and_adds_one(self):
        self.page(fx("usajobs_closed.html"))
        argv, sys.argv = sys.argv, ["verify_url.py", USA_CLOSED]
        self.addCleanup(lambda: setattr(sys, "argv", argv))
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            runpy.run_path(str(KIT / "scripts" / "verify_url.py"), run_name="__main__")
        lines = out.getvalue().splitlines()
        self.assertEqual(lines[0], "== " + USA_CLOSED)
        self.assertEqual(lines[1], "   http 200  live=False  gone=req_gone:usajobs_closed")
        self.assertTrue(lines[2].startswith("   close_at="))
        self.assertTrue(lines[3].startswith("   snippet="))
        self.assertEqual(lines[4], "   liveness=gone  method=usajobs_closed  evidence=the page says "
                                   "'This job announcement has closed', status 'Reviewing applications'")
        self.assertEqual(len(lines), 5)


if __name__ == "__main__":
    unittest.main()
