"""Sibling and portal labels in scripts/rank.py. No network, no tracker.json.

    python3 -m unittest discover -s tests        (from the kit root)

Every employer, title, requisition id and URL tenant below is invented.
"""
import contextlib
import io
import json
import shutil
import sys
import tempfile
import unittest
import warnings
from pathlib import Path

if sys.version_info < (3, 11):
    raise unittest.SkipTest("scripts/rank.py needs Python 3.11 (tomllib)")

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

import rank  # noqa: E402

ULT = "https://recruiting2.ultipro.com/LRK1000/JobBoard/0000aaaa/OpportunityDetail?opportunityId="


SENT_TITLE = "Staff Nurse (On Call) - Recovery Unit 204 (Rivertown, CA)"


def p(pid, employer, title, status, url="", status_at="2026-01-05T00:00:00Z", location=""):
    return {"id": pid, "employer": employer, "title": title, "status": status, "url": url,
            "status_at": status_at, "location": location}


def postings():
    rows = [
        # already sent
        p("lark-oncall", "Larkmoor Behavioral Health",
          SENT_TITLE,
          "submitted", ULT + "a", "2026-01-10T05:53:00Z", "Rivertown, CA"),
        p("lark-crisis", "Larkmoor Behavioral Health",
          "Acute RN (On Call) - Recovery Unit 311, Bayside Crisis House (Bayside, CA)",
          "rejected", ULT + "b", "2026-01-11T06:14:00Z", "Bayside, CA"),
        p("mill-sent", "Millbrook Hospital (MHS)", "RN - Adult Inpatient (FT req 100234 + PT req 100567)",
          "submitted", "https://careers-mhsexample.icims.com/jobs/100234", "2025-11-18T00:00:00Z"),
        p("county-train", "Example County Health (County of Example)",
          "Registered Nurse, New Graduate Track (9901) - Countywide - X00123",
          "submitted", "https://jobs.smartrecruiters.com/ExampleCounty1/1", "2025-12-20T00:00:00Z"),
        p("quillon-sent", "Quillon Behavioral Health (Harbor Street)", "Registered Nurse | RN (posted 3/2)",
          "submitted", "https://job-boards.greenhouse.io/quilloncareers/jobs/7000000001", "2025-12-09T00:00:00Z"),
        # the ranked list
        p("lark-noc", "Larkmoor Behavioral Health - Hollis Center (Rivertown)",
          "Staff Nurse (NOC shift) - Recovery Unit 204, Full-Time (RN0012345, posted 2/14)",
          "new", ULT + "c", location="Rivertown, CA"),
        p("lark-other-unit", "Larkmoor Behavioral Health - Garnet Center",
          "RN Supervisor (On Call) - Recovery Unit 205 (req SUP0012346)", "new", ULT + "d"),
        p("lark-other-city", "Larkmoor Behavioral Health",
          "Staff Nurse (NOC shift) - Recovery Unit 204, Full-Time", "new", ULT + "e",
          location="Lakeside, CA"),
        p("mill-new", "Millbrook Hospital (MHS)",
          "Registered Nurse (RN) - Full Time, adult inpatient, PM/NOC (req 100890)",
          "working", "https://careers-mhsexample.icims.com/jobs/100890/job"),
        p("county-perdiem", "Example County Health", "Per Diem RN All Specialties (Q77)", "working",
          "https://jobs.smartrecruiters.com/ExampleCounty1/2"),
        p("quillon-other", "Quillon Behavioral Health, Briar Care Center (Lakeside)",
          "Licensed Vocational Nurse (LVN) | Registered Nurse (RN), RN on-call",
          "new", "https://job-boards.greenhouse.io/quilloncareers/jobs/7000000002"),
        p("ridge", "Ridgeview Health Lakeside", "RN, Part Time, Evening Shift, medical surgical",
          "new", "https://abcd.fa.us2.oraclecloud.com/hcmUI/CandidateExperience/en/sites/CX/job/501"),
    ]
    return {row["id"]: row for row in rows}


def ranked_rows(by_id):
    return [{"p": row, "score": 0, "reasons": []} for row in by_id.values()
            if row["status"] in ("new", "working")]


class Siblings(unittest.TestCase):
    def setUp(self):
        self.postings = postings()
        self.rows = ranked_rows(self.postings)
        rank.label_siblings(self.rows, self.postings)
        self.by = {r["p"]["id"]: r for r in self.rows}

    def test_same_unit_different_shift_is_a_sibling(self):
        self.assertEqual(self.by["lark-noc"].get("sibling_of"), "lark-oncall")
        self.assertEqual(self.by["mill-new"].get("sibling_of"), "mill-sent")
        self.assertEqual(self.by["lark-noc"]["label"],
                         f"sibling of {SENT_TITLE[:40]}, sent 2026-01-10: short send")

    def test_other_unit_number_is_only_the_same_portal(self):
        row = self.by["lark-other-unit"]
        self.assertIsNone(row.get("sibling_of"))
        self.assertIn(row.get("same_portal_as"), ("lark-oncall", "lark-crisis"))
        self.assertEqual(row["label"], "portal account exists (Larkmoor Behavioral Heal)")

    def test_same_title_in_another_city_is_only_the_same_portal(self):
        row = self.by["lark-other-city"]
        self.assertIsNone(row.get("sibling_of"))
        self.assertIsNotNone(row.get("same_portal_as"))

    def test_other_job_class_at_the_same_employer_is_only_the_same_portal(self):
        row = self.by["county-perdiem"]
        self.assertIsNone(row.get("sibling_of"))
        self.assertEqual(row.get("same_portal_as"), "county-train")

    def test_other_facility_and_a_board_with_no_account_gets_nothing(self):
        row = self.by["quillon-other"]
        self.assertNotIn("sibling_of", row)
        self.assertNotIn("same_portal_as", row)     # a hosted board with no login
        self.assertNotIn("label", row)

    def test_nothing_sent_there_gets_nothing(self):
        self.assertNotIn("label", self.by["ridge"])

    def test_labels_do_not_move_rows_and_stale_labels_clear(self):
        order = [r["p"]["id"] for r in self.rows]
        self.postings["lark-oncall"]["status"] = "skip"
        self.postings["lark-crisis"]["status"] = "skip"
        rank.label_siblings(self.rows, self.postings)
        self.assertEqual([r["p"]["id"] for r in self.rows], order)
        for pid in ("lark-noc", "lark-other-unit", "lark-other-city"):
            self.assertNotIn("label", self.by[pid], pid)
            self.assertNotIn("sibling_of", self.by[pid], pid)

    def test_a_rejection_and_a_later_status_are_said_in_the_label(self):
        self.postings["lark-oncall"]["status"] = "rejected"
        rank.label_siblings(self.rows, self.postings)
        self.assertEqual(self.by["lark-noc"]["label"],
                         f"sibling of {SENT_TITLE[:40]}, REJECTED there 2026-01-10")
        self.postings["lark-oncall"]["status"] = "interview"
        rank.label_siblings(self.rows, self.postings)
        self.assertIn("interview since 2026-01-10: short send", self.by["lark-noc"]["label"])

    def test_req_ids_dates_hours_and_fte_do_not_count_as_title_words(self):
        self.assertEqual(
            rank._core_tokens("Staff Nurse (NOC shift) - Recovery Unit 204, Full-Time (RN0012345, posted 2/14)"),
            {"staff", "nurse", "recovery", "unit", "204"})
        self.assertEqual(
            rank._core_tokens("Clinical Nurse (RN), ICU (B2) - 12HR Nights .90, 7a-7p, 0.9 FTE, 8-hour"),
            {"clinical", "nurse", "registered", "icu", "b2"})

    def test_a_longer_title_naming_another_unit_is_not_a_sibling(self):
        sent = p("s", "Tarn Valley Medical", "Clinical Nurse (RN), ICU Medicine (B2) - 12HR Nights .90", "submitted")
        for title, expected in (("Clinical Nurse (RN), ICU Medicine (B2) - 12HR Days .75", True),
                                ("Clinical Nurse (RN), ICU Cardiac Surgery (C3) - 12HR Nights .90", False),
                                ("Clinical Nurse (RN), ICU Float Pool - 12hr Nights .90", False),
                                ("Clinical Nurse II", False)):
            self.assertIs(rank.is_sibling(p("n", "Tarn Valley Medical", title, "new"), sent), expected, title)

    def test_portal_key(self):
        self.assertEqual(rank.portal_key(ULT + "a"), "recruiting2.ultipro.com/lrk1000")
        self.assertEqual(rank.portal_key("https://www.usajobs.gov:443/job/1"), "usajobs.gov")
        self.assertEqual(rank.portal_key("https://tenant.wd5.myworkdayjobs.com/en-US/x/job/1"),
                         "tenant.wd5.myworkdayjobs.com")
        self.assertIsNone(rank.portal_key("https://job-boards.greenhouse.io/x/jobs/1"))
        self.assertIsNone(rank.portal_key(""))


class RankedOutput(unittest.TestCase):
    """main() on a throwaway kit: the label reaches ranked.html, ranked.json and the console."""

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="test_rank_"))
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        names = ("TRACKER", "PREFS", "OUT_HTML", "OUT_JSON")
        saved = {n: getattr(rank, n) for n in names}
        self.addCleanup(lambda: [setattr(rank, n, v) for n, v in saved.items()])
        rank.TRACKER, rank.PREFS = str(self.tmp / "tracker.json"), str(self.tmp / "preferences.toml")
        rank.OUT_HTML, rank.OUT_JSON = str(self.tmp / "ranked.html"), str(self.tmp / "ranked.json")
        (self.tmp / "preferences.toml").write_text("")
        (self.tmp / "tracker.json").write_text(json.dumps({"schema_version": 1, "postings": postings()}))

    def test_label_is_in_every_output_and_the_order_is_the_score(self):
        argv, sys.argv = sys.argv, ["rank.py"]
        self.addCleanup(lambda: setattr(sys, "argv", argv))
        out = io.StringIO()
        with contextlib.redirect_stdout(out), warnings.catch_warnings():
            warnings.simplefilter("ignore", ResourceWarning)    # rank.py leaves its files to the collector
            self.assertEqual(rank.main(), 0)
        ranked = json.loads((self.tmp / "ranked.json").read_text())["ranked"]
        by = {r["id"]: r for r in ranked}
        self.assertEqual(by["lark-noc"]["sibling_of"], "lark-oncall")
        self.assertTrue(by["lark-noc"]["label"].startswith("sibling of Staff Nurse (On Call)"))
        self.assertEqual(by["county-perdiem"]["same_portal_as"], "county-train")
        self.assertNotIn("label", by["ridge"])
        self.assertEqual([r["score"] for r in ranked], sorted((r["score"] for r in ranked), reverse=True))
        html = (self.tmp / "ranked.html").read_text()
        self.assertIn(f"<b>sibling of {SENT_TITLE[:40]}, sent 2026-01-10: short send</b>", html)
        self.assertIn("<b>portal account exists (Example County Health (C)</b>", html)
        self.assertIn("| sibling of Staff Nurse (On Call)", out.getvalue())


if __name__ == "__main__":
    unittest.main()
