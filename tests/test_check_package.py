#!/usr/bin/env python3
"""Tests for scripts/check_package.py. No network and nobody's real documents: every
docx and PDF is built here, in a temp dir, from the synthetic text below.

    python3 -m unittest discover -s tests        (from the kit root)

The two shapes it was built around, in synthetic form: a PDF that still carries a clause
the applicant deleted in Word, and stray text fused onto the letterhead's name line.

The text-shape and refusal tests need nothing but Python. The end-to-end class needs
soffice and poppler and is skipped without them.
"""
from __future__ import annotations

import contextlib
import hashlib
import io
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
import zipfile
from pathlib import Path
from xml.sax.saxutils import escape

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

import check_package as cp  # noqa: E402

HAVE_TOOLS = bool(cp._soffice()) and bool(cp._tool("pdftotext")) and bool(cp._tool("pdfinfo"))
EN_DASH = "\u2013"
# Words meant for another window, typed onto the name line.
FUSED = "The meeting notes are due on Friday as well"

# ------------------------------------------------------------------ builders

W_NS = ('xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main" '
        'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships"')


class Raw(str):
    """XML that goes into a paragraph as is."""


def deleted(text: str) -> Raw:
    return Raw('<w:del w:id="2" w:author="Example, Pat" w:date="2026-01-15T22:04:00Z"><w:r>'
               f'<w:delText xml:space="preserve">{escape(text)}</w:delText></w:r></w:del>')


def inserted(text: str) -> Raw:
    return Raw('<w:ins w:id="3" w:author="Example, Pat" w:date="2026-01-15T22:05:00Z"><w:r>'
               f'<w:t xml:space="preserve">{escape(text)}</w:t></w:r></w:ins>')


TAB = Raw("<w:r><w:tab/></w:r>")
# A deleted paragraph mark: the self-closing form, which holds no text.
DELETED_MARK = Raw('<w:pPr><w:rPr><w:del w:id="4" w:author="Example, Pat" '
                   'w:date="2026-01-15T22:06:00Z"/></w:rPr></w:pPr>')


def _paragraphs_xml(paragraphs: list) -> str:
    body = []
    for para in paragraphs:
        parts = para if isinstance(para, list) else [para]
        xml = "".join(p if isinstance(p, Raw)
                      else f'<w:r><w:t xml:space="preserve">{escape(p)}</w:t></w:r>' for p in parts)
        body.append(f"<w:p>{xml}</w:p>")
    return "".join(body)


def make_docx(path: Path, paragraphs: list, comment_authors: tuple = (), header: list | None = None) -> None:
    """A minimal docx. Each paragraph is a string, or a list of strings and Raw pieces
    for a paragraph that carries a tab or a tracked change. `header` puts those lines in
    a Word page header and a page number in the footer."""
    main = "application/vnd.openxmlformats-officedocument.wordprocessingml"
    rel = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
    overrides = f'<Override PartName="/word/document.xml" ContentType="{main}.document.main+xml"/>'
    sect = ""
    if header is not None:
        overrides += (f'<Override PartName="/word/header1.xml" ContentType="{main}.header+xml"/>'
                      f'<Override PartName="/word/footer1.xml" ContentType="{main}.footer+xml"/>')
        sect = ('<w:sectPr><w:headerReference w:type="default" r:id="rId10"/>'
                '<w:footerReference w:type="default" r:id="rId11"/></w:sectPr>')
    types = ('<?xml version="1.0" encoding="UTF-8"?>'
             '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
             '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
             f'<Default Extension="xml" ContentType="application/xml"/>{overrides}</Types>')
    rels = ('<?xml version="1.0" encoding="UTF-8"?>'
            '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
            f'<Relationship Id="rId1" Type="{rel}/officeDocument" Target="word/document.xml"/></Relationships>')
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("[Content_Types].xml", types)
        z.writestr("_rels/.rels", rels)
        z.writestr("word/document.xml",
                   f'<?xml version="1.0" encoding="UTF-8"?><w:document {W_NS}><w:body>'
                   f'{_paragraphs_xml(paragraphs)}{sect}</w:body></w:document>')
        if header is not None:
            z.writestr("word/_rels/document.xml.rels",
                       '<?xml version="1.0" encoding="UTF-8"?>'
                       '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
                       f'<Relationship Id="rId10" Type="{rel}/header" Target="header1.xml"/>'
                       f'<Relationship Id="rId11" Type="{rel}/footer" Target="footer1.xml"/></Relationships>')
            z.writestr("word/header1.xml", f'<?xml version="1.0" encoding="UTF-8"?><w:hdr {W_NS}>'
                                           f'{_paragraphs_xml(header)}</w:hdr>')
            z.writestr("word/footer1.xml",
                       f'<?xml version="1.0" encoding="UTF-8"?><w:ftr {W_NS}><w:p>'
                       '<w:r><w:t xml:space="preserve">Page </w:t></w:r>'
                       '<w:r><w:fldChar w:fldCharType="begin"/></w:r><w:r><w:instrText>PAGE</w:instrText></w:r>'
                       '<w:r><w:fldChar w:fldCharType="end"/></w:r></w:p></w:ftr>')
        if comment_authors:
            notes = "".join(f'<w:comment w:id="{n}" w:author="{a}"><w:p><w:r><w:t>note</w:t></w:r>'
                            '</w:p></w:comment>' for n, a in enumerate(comment_authors))
            z.writestr("word/comments.xml",
                       f'<?xml version="1.0" encoding="UTF-8"?><w:comments {W_NS}>{notes}</w:comments>')


def make_pdf(path: Path, pages: list[list[str]]) -> None:
    """A minimal text PDF, one list of lines per page, Helvetica in WinAnsi so a middle
    dot and an en dash reach the text layer as themselves."""
    def literal(line: str) -> str:
        out = []
        for byte in line.encode("cp1252"):
            ch = chr(byte)
            out.append("\\" + ch if ch in "\\()" else ch if 32 <= byte < 127 else f"\\{byte:03o}")
        return "".join(out)

    objects: list[bytes] = []
    kids = " ".join(f"{4 + 2 * n} 0 R" for n in range(len(pages)))
    objects.append(b"<< /Type /Catalog /Pages 2 0 R >>")
    objects.append(f"<< /Type /Pages /Kids [{kids}] /Count {len(pages)} >>".encode())
    objects.append(b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica /Encoding /WinAnsiEncoding >>")
    for n, lines in enumerate(pages):
        text = "BT /F1 9 Tf 40 750 Td 12 TL " + " ".join(f"({literal(ln)}) Tj T*" for ln in lines) + " ET"
        stream = text.encode("latin-1")
        objects.append(f"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Resources "
                       f"<< /Font << /F1 3 0 R >> >> /Contents {5 + 2 * n} 0 R >>".encode())
        objects.append(b"<< /Length " + str(len(stream)).encode() + b" >>\nstream\n" + stream
                       + b"\nendstream")
    out = bytearray(b"%PDF-1.4\n")
    offsets = []
    for num, obj in enumerate(objects, 1):
        offsets.append(len(out))
        out += f"{num} 0 obj\n".encode() + obj + b"\nendobj\n"
    xref = len(out)
    out += f"xref\n0 {len(objects) + 1}\n0000000000 65535 f \n".encode()
    for off in offsets:
        out += f"{off:010d} 00000 n \n".encode()
    out += f"trailer\n<< /Size {len(objects) + 1} /Root 1 0 R >>\nstartxref\n{xref}\n%%EOF\n".encode()
    path.write_bytes(bytes(out))


# ------------------------------------------------------------ synthetic text

NAME = "Pat Example"
CONTACT = "Anytown, CA \u00b7 pat@example.org \u00b7 (555) 555-0142"
EMPLOYER = "Larkmoor Health (Anytown)"
CLAUSE = ", night shifts included"
OPENING = "I am applying for the staff nurse position at Larkmoor."
BEFORE = "During my final rotation I managed my own multi-patient assignments"
AFTER = ". The team was steady and I learned to speak up early."
LETTER = "Synthetic-RN-Cover-Letter"
RESUME = "Synthetic-RN-Resume"


def letter_paragraphs(body: list | str, name: str | None = NAME) -> list:
    head = [] if name is None else [name, CONTACT]
    return head + ["January 15, 2026", "Larkmoor Health", "Hello,", body, "Thank you,", "Pat Example"]


def letter_pdf_lines(clause: str = "", name: str = NAME, extra: str = "") -> list[str]:
    """The same letter as a PDF prints it: wrapped, with "multi-patient" broken at its
    hyphen across a line end."""
    return [name, CONTACT, "", "January 15, 2026", "Larkmoor Health", "Hello,",
            OPENING + " During my final rotation I managed my own multi-",
            f"patient assignments{clause}. The team was steady and I",
            "learned to speak up early." + extra, "Thank you,", "Pat Example"]


BODY_NOW = OPENING + " " + BEFORE + AFTER                  # what the Word file says now
BODY_OLD = OPENING + " " + BEFORE + CLAUSE + AFTER         # what the stale PDF says


def resume_paragraphs(dash: str = "-") -> list:
    return [NAME, CONTACT, "Registered Nurse",
            ["Unit Clerk, Example Medical Center", TAB, f"Oct 2024{dash}Jun 2025"],
            "Answered call lights on a thirty-bed unit."]


def resume_pdf_lines(dash: str = "-") -> list[str]:
    # The right-aligned date reaches the text layer with no space before it.
    return [NAME, CONTACT, "Registered Nurse",
            f"Unit Clerk, Example Medical CenterOct 2024{dash}Jun 2025",
            "Answered call lights on a thirty-bed unit."]


def checks(found: list[tuple], level: str) -> list[str]:
    return [check for lv, check, _ in found if lv == level]


def message(found: list[tuple], check: str) -> str:
    return " || ".join(msg for _, c, msg in found if c == check)


class TempKit:
    """Point the module at a throwaway kit root, and put it back afterwards."""
    NAMES = ("KIT", "APPLICATIONS", "TRACKER", "LETTERHEAD_FILE")

    def __init__(self, letterhead: bool = True):
        self.root = Path(tempfile.mkdtemp(prefix="test_check_package_"))
        self.saved = {n: getattr(cp, n) for n in self.NAMES}
        cp.KIT, cp.APPLICATIONS = self.root, self.root / "Applications"
        cp.TRACKER = self.root / "tracker.json"
        cp.LETTERHEAD_FILE = self.root / "profile" / "letterhead.txt"
        cp.APPLICATIONS.mkdir()
        (self.root / "profile").mkdir()
        if letterhead:
            cp.LETTERHEAD_FILE.write_text(f"{NAME}\n{CONTACT}\n", encoding="utf-8")
        self.postings: dict = {}

    def package(self, name: str, status: str = "working", employer: str = EMPLOYER) -> Path:
        pkg = cp.APPLICATIONS / name
        pkg.mkdir(parents=True)
        self.postings[name] = {"id": name, "employer": employer, "status": status,
                               "status_at": "2026-01-16T05:00:00Z"}
        cp.TRACKER.write_text(json.dumps({"schema_version": 1, "postings": self.postings}))
        return pkg

    def close(self) -> None:
        for n, v in self.saved.items():
            setattr(cp, n, v)
        shutil.rmtree(self.root, ignore_errors=True)


def run_main(*argv: str) -> tuple[int, str]:
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        code = cp.main(list(argv))
    return code, buf.getvalue()


# ------------------------------------------------------------- text shape


class TextShape(unittest.TestCase):
    def test_word_and_pdf_spellings_compare_equal(self):
        word = "The \u201cfirst\u201d office \u2013 it\u2019s re\u00adopened \u2022 a multi-patient, well-run floor"
        pdf = "The \"\ufb01rst\" of\ufb01ce\u00a0- it's reopened a multi-\npatient, well-\nrun \ufb02oor"
        self.assertIsNone(cp.compare_text(word, pdf))

    def test_word_hyphenated_across_a_line_end(self):
        self.assertIsNone(cp.compare_text("carried my own assignments today",
                                          "carried my own assign-\n   ments today"))
        # A spaced dash at a line end is punctuation, not hyphenation.
        self.assertIsNone(cp.compare_text("the unit - a locked one", "the unit -\na locked one"))

    def test_squeezed_tab_is_not_a_difference(self):
        self.assertIsNone(cp.compare_text("General Hospital, Anytown\tSpring 2026",
                                          "General Hospital, AnytownSpring 2026"))

    def test_deleted_clause_is_reported_both_ways(self):
        diff = cp.compare_text(BODY_NOW, "\n".join(letter_pdf_lines(CLAUSE)[6:9]))
        self.assertEqual(diff["differences"], 1)
        self.assertIn("multi-patient assignments. The team", diff["word"])
        self.assertIn("assignments, night shifts included. The team", diff["pdf"])
        self.assertFalse(diff["same_words"])

    def test_one_changed_word_is_a_difference(self):
        diff = cp.compare_text("I led the huddle on nights.", "I joined the huddle on nights.")
        self.assertEqual((diff["word_only"], diff["pdf_only"]), ("led", "joined"))

    def test_moved_sentence_is_a_difference_and_says_same_words(self):
        diff = cp.compare_text("First point here. Second point there.",
                               "Second point there. First point here.")
        self.assertTrue(diff["same_words"])

    def test_long_first_sentence_is_cut_around_the_difference(self):
        filler = " ".join(f"w{n}" for n in range(200))
        diff = cp.compare_text(f"{filler} kept {filler}.", f"{filler} dropped {filler}.")
        self.assertIn("kept", diff["word"])
        self.assertIn("dropped", diff["pdf"])
        self.assertLess(len(diff["word"]), 500)

    def test_markers(self):
        for text, marker in (("on the [CONFIRM: unit] floor", "[CONFIRM"), ("on the [CONFIRM] floor", "[CONFIRM"),
                             ("dates [TODO] here", "[TODO"), ("unit [TBD]", "[TBD"),
                             ("carried [CHECK: how many] patients", "[CHECK"),
                             ("Yes [SESSION GUESS, ask]", "[SESSION GUESS"),
                             ("Supervisor: A. Person [APPLICANT 2026-01-15]", "[APPLICANT")):
            self.assertEqual([m for m, _ in cp.find_markers(text)], [marker], text)
        self.assertIn("unit name", cp.find_markers("the [CONFIRM: unit name] floor")[0][1])
        for clean in ("I confirm that the applicant can check a chart.", "Pat Example, RN"):
            self.assertEqual(cp.find_markers(clean), [], clean)

    def test_year_joined_to_a_non_ascii_dash(self):
        for text in (f"Oct 2025 {EN_DASH} Present", f"2013{EN_DASH}2017", f"Jan 2025{EN_DASH}Apr 2026",
                     "Oct 2025 \u2014 Jun 2026", f"Present {EN_DASH} 2026", "2019\u22122021"):
            self.assertTrue(cp.year_dash_hits(text), text)
        for text in ("Oct 2025-Present", "Oct 2025 - Jun 2026", "Expires 10/31/2027",
                     f"calm {EN_DASH} and it stayed calm", "June 2026"):
            self.assertEqual(cp.year_dash_hits(text), [], text)
        self.assertEqual(cp.year_dash_hits(f"2013{EN_DASH}2017")[0][1], "U+2013 en dash")

    def test_doctype_from_filename(self):
        for stem, doctype in (("Larkmoor-RN-Cover-Letter", "letter"),
                              ("Larkmoor-RN-Cover-Letter-Anytown", "letter"),
                              ("Larkmoor-RN-Resume", "resume"),
                              ("Example-Program-CV-Pat-Example", "resume"),
                              ("Larkmoor-RN-Reference-Letter-A-Person", "other"),
                              ("Cert-ACLS", "other"), ("Transcript-Example-University", "other")):
            self.assertEqual(cp.doctype_of(stem), doctype, stem)

    def test_word_lock_names(self):
        docxs = [Path("Larkmoor-Hollis-Unit-RN-Cover-Letter.docx"), Path("CV.docx")]
        self.assertEqual(cp.lock_owner(Path("~$rkmoor-Hollis-Unit-RN-Cover-Letter.docx"), docxs), docxs[0])
        self.assertEqual(cp.lock_owner(Path("~$CV.docx"), docxs), docxs[1])
        self.assertIsNone(cp.lock_owner(Path("~$Other-Resume.docx"), docxs))


class EmployerName(unittest.TestCase):
    def test_terms(self):
        self.assertEqual(cp.employer_terms("Larkmoor Corporation - Hollis CSU (Anytown)"),
                         ["Larkmoor", "Hollis", "CSU"])
        self.assertEqual(cp.employer_terms("Quillon Behavioral Health, Briar Care Center (Rivertown)"),
                         ["Quillon", "Briar"])
        self.assertEqual(cp.employer_terms("EX VMC (County of Example)"), ["EX", "VMC"])
        self.assertEqual(cp.employer_terms("(to be filled in)"), [])

    def test_loose_match(self):
        for employer, letter in (
            ("Larkmoor Corporation - Hollis CSU (Anytown)", "the role at Larkmoor's Hollis center"),
            ("EX VMC (County of Example)", "Example Valley Medical Center"),
            ("Quillon Health St. Briar (Rivertown)", "Quillon Health St. Briar\nHello,"),
            ("EXU School of Nursing", "I am applying to EXU."),
        ):
            self.assertTrue(cp.employer_named(employer, letter)[0], employer)

    def test_not_named(self):
        # The city in the parenthesis is not evidence: the letterhead names the same city.
        found, terms = cp.employer_named("Larkmoor Corporation - Hollis CSU (Anytown)",
                                         "Pat Example\nAnytown, CA\nI am applying to Quillon.")
        self.assertIs(found, False)
        self.assertEqual(terms, ["Larkmoor", "Hollis", "CSU"])
        # Two initials would match by chance ("Eastern ... Xavier").
        self.assertIs(cp.employer_named("EX VMC", "Eastern Xavier. Fall term.")[0], False)

    def test_nothing_to_look_for(self):
        self.assertIsNone(cp.employer_named("(to be filled in)", "anything")[0])


class DocxParts(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="test_check_package_"))
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)

    def test_counts_and_comment_authors(self):
        docx = self.tmp / "a.docx"
        make_docx(docx, [["kept", deleted(" gone"), inserted(" new")], [DELETED_MARK, "next"]],
                  comment_authors=("Claude", "Example, Pat", "Claude"))
        # delText is not a deletion tag; the deleted paragraph mark is.
        self.assertEqual(cp.tracked_changes(docx), {"ins": 1, "del": 2, "moveFrom": 0, "moveTo": 0})
        self.assertEqual(cp.comment_authors(docx), ["Claude", "Example, Pat", "Claude"])

    def test_clean_docx_counts_nothing(self):
        docx = self.tmp / "b.docx"
        make_docx(docx, ["plain"])
        self.assertFalse(any(cp.tracked_changes(docx).values()))
        self.assertEqual(cp.comment_authors(docx), [])

    def test_accepted_copy_cuts_deletion_blocks_only(self):
        docx, copy = self.tmp / "c.docx", self.tmp / "copy.docx"
        make_docx(docx, [["kept", deleted(" gone"), inserted(" new")], [DELETED_MARK, "next"]])
        before = docx.read_bytes()
        cp.write_accepted_copy(docx, copy)
        self.assertEqual(docx.read_bytes(), before)             # the source is untouched
        with zipfile.ZipFile(copy) as z:
            xml = z.read("word/document.xml").decode()
        self.assertNotIn("gone", xml)
        self.assertNotIn("delText", xml)
        for kept in ("kept", " new", "next", "<w:ins ", '<w:del w:id="4"'):
            self.assertIn(kept, xml, kept)


class Refusals(unittest.TestCase):
    """What stops the check before a single file is read. No soffice, no poppler."""

    def setUp(self):
        self.kit = TempKit()
        self.addCleanup(self.kit.close)
        self.kit.package("sent", status="submitted")
        self.kit.package("working")
        self.kit.package("heard-back", status="interview")
        (self.kit.package("marked") / "SUBMITTED.md").write_text("sent\n")
        self.reads = []
        saved = cp.read_docx_texts
        cp.read_docx_texts = lambda docxs: self.reads.append(docxs) or {}
        self.addCleanup(lambda: setattr(cp, "read_docx_texts", saved))

    def test_submitted_in_the_tracker_is_exit_2_and_names_the_date(self):
        code, out = run_main("sent", "--id", "sent")
        self.assertEqual(code, 2)
        self.assertTrue(out.startswith("REFUSED sent: tracker.json has sent as submitted (2026-01-16)"), out)
        self.assertIn("--force", out)
        self.assertEqual(self.reads, [])

    def test_every_status_after_submit_is_refused(self):
        code, out = run_main("Applications/heard-back", "--id", "heard-back")
        self.assertEqual((code, out.startswith("REFUSED heard-back")), (2, True))

    def test_a_submitted_marker_in_the_folder_is_refused_without_an_id(self):
        code, out = run_main("marked")
        self.assertEqual(code, 2)
        self.assertIn("SUBMITTED.md is in the folder", out)

    def test_unknown_folder_and_unknown_id_are_exit_2(self):
        code, out = run_main("no-such-package")
        self.assertEqual((code, out.startswith("STOP check_package: no folder")), (2, True))
        code, out = run_main("working", "--id", "nobody")
        self.assertEqual(code, 2)
        self.assertIn("no posting with id 'nobody'", out)

    def test_unreadable_tracker_is_exit_2_not_a_pass(self):
        cp.TRACKER.write_text("{ half a file")
        code, out = run_main("working", "--id", "working")
        self.assertEqual(code, 2)
        self.assertIn("tracker.json could not be read", out)

    def test_missing_tools_is_one_line_with_the_install_command(self):
        saved = (cp._tool, cp._soffice)
        self.addCleanup(lambda: (setattr(cp, "_tool", saved[0]), setattr(cp, "_soffice", saved[1])))
        cp._tool = lambda name: None
        code, out = run_main("working", "--id", "working")
        self.assertEqual(code, 2)
        self.assertEqual(len(out.strip().splitlines()), 1)
        self.assertIn("brew install poppler", out)
        self.assertNotIn("libreoffice", out)
        cp._soffice = lambda: None
        code, out = run_main("working", "--id", "working")
        self.assertEqual(code, 2)
        self.assertEqual(len(out.strip().splitlines()), 1)
        self.assertIn("brew install poppler && brew install --cask libreoffice", out)
        self.assertEqual(self.reads, [])

    def test_an_unexpected_error_is_exit_2_and_one_line(self):
        saved = cp.run
        self.addCleanup(lambda: setattr(cp, "run", saved))

        def boom(pkg, posting=None):
            raise ValueError("boom")
        cp.run = boom
        cp._tool, cp._soffice, tools = (lambda name: "/x"), (lambda: "/x"), (cp._tool, cp._soffice)
        self.addCleanup(lambda: (setattr(cp, "_tool", tools[0]), setattr(cp, "_soffice", tools[1])))
        code, out = run_main("working", "--id", "working")
        self.assertEqual(code, 2)
        self.assertEqual(out.strip().splitlines(), [
            "STOP check_package: ValueError: boom. Nothing was checked; do not upload on this result."])

    def test_hashes_need_no_tools_and_work_on_a_submitted_package(self):
        make_pdf(cp.APPLICATIONS / "sent" / f"{LETTER}.pdf", [["one"]])
        (cp.APPLICATIONS / "sent" / "Archive").mkdir()
        make_pdf(cp.APPLICATIONS / "sent" / "Archive" / "old.pdf", [["old"]])
        cp._tool, tool = (lambda name: None), cp._tool
        self.addCleanup(lambda: setattr(cp, "_tool", tool))
        code, out = run_main("sent", "--hashes")
        data = (cp.APPLICATIONS / "sent" / f"{LETTER}.pdf").read_bytes()
        self.assertEqual(code, 0)
        self.assertEqual(out, f"{hashlib.sha256(data).hexdigest()}  {len(data)}  {LETTER}.pdf\n")


class Letterhead(unittest.TestCase):
    """Where the expected two lines come from. No soffice: nothing here has an Archive letter."""

    def setUp(self):
        self.kit = TempKit(letterhead=False)
        self.addCleanup(self.kit.close)
        self.pkg = self.kit.package("p")

    def test_profile_file_wins(self):
        cp.LETTERHEAD_FILE.write_text(f"\ufeff  {NAME}  \n\n{CONTACT}\nthird line\n", encoding="utf-8")
        self.assertEqual(cp.expected_letterhead(self.pkg), ([NAME, cp.lines_of(CONTACT)[0]], "profile/letterhead.txt"))

    def test_missing_file_and_no_archive_says_how_to_enable(self):
        want, why = cp.expected_letterhead(self.pkg)
        self.assertIsNone(want)
        self.assertEqual(why, "profile/letterhead.txt is missing and Archive/ holds no earlier letter")

    def test_placeholder_or_short_file_is_not_a_letterhead(self):
        for text in (f"{NAME}\n", "[CONFIRM: name line]\n[CONFIRM: contact line]\n", ""):
            cp.LETTERHEAD_FILE.write_text(text, encoding="utf-8")
            want, why = cp.expected_letterhead(self.pkg)
            self.assertIsNone(want, text)
            self.assertIn("does not hold two filled lines", why)

    def test_mismatch_message_quotes_both(self):
        found = cp._letterhead_findings("L.docx", f"{FUSED}{NAME}\n{CONTACT}\nbody", [NAME, CONTACT],
                                        "profile/letterhead.txt")
        self.assertEqual(checks(found, "FAIL"), ["letterhead"])
        self.assertIn(f'L.docx opens "{FUSED}{NAME} / ', found[0][2])
        self.assertIn(f'expected "{NAME} / ', found[0][2])
        self.assertEqual(cp._letterhead_findings("L.docx", f"{NAME}\n\n  {CONTACT}\nbody", [NAME, CONTACT], "x"), [])


class SourceRules(unittest.TestCase):
    """Two rules a later edit could quietly break."""

    def test_paths_are_anchored_on_the_file(self):
        src = Path(cp.__file__).read_text(encoding="utf-8")
        code = "\n".join(line.split("#")[0] for line in src.split('"""')[2].splitlines())
        for banned in ("Path.home", "expanduser", "getcwd", "Path.cwd", 'environ["HOME"]'):
            self.assertNotIn(banned, code, banned)

    def test_both_files_are_plain_ascii(self):
        for path in (cp.__file__, __file__):
            Path(path).read_text(encoding="ascii")


# --------------------------------------------------------------- end to end


@unittest.skipUnless(HAVE_TOOLS, "needs soffice and poppler (pdftotext, pdfinfo)")
class EndToEnd(unittest.TestCase):
    """Real docx files through soffice, real PDFs through poppler."""

    @classmethod
    def setUpClass(cls):
        cls.kit = kit = TempKit()
        package = kit.package

        def letter(pkg: Path, body, pdf_pages, name: str = NAME, comments: tuple = ()) -> None:
            make_docx(pkg / f"{LETTER}.docx", letter_paragraphs(body, name=name), comment_authors=comments)
            make_pdf(pkg / f"{LETTER}.pdf", pdf_pages)

        # clean: a letter and a resume that match their PDFs, a supporting PDF, and a
        # wrecked letter in Archive/ that must never be read while the profile file exists.
        pkg = package("clean")
        letter(pkg, BODY_NOW, [letter_pdf_lines()])
        make_docx(pkg / f"{RESUME}.docx", resume_paragraphs())
        make_pdf(pkg / f"{RESUME}.pdf", [resume_pdf_lines()])
        make_pdf(pkg / "Cert-BLS.pdf", [["Basic Life Support"]])
        (pkg / "Archive").mkdir()
        make_docx(pkg / "Archive" / f"{LETTER}-v1.docx",
                  letter_paragraphs([BODY_OLD, deleted(" [CONFIRM: old]")], name=FUSED + NAME))
        make_pdf(pkg / "Archive" / f"{LETTER}-v1.pdf", [["page one"], ["page two"]])

        # stale: the clause was deleted in Word with tracking off; the PDF is the earlier
        # export, copied in afterwards so it is the NEWER file.
        pkg = package("stale")
        letter(pkg, BODY_NOW, [letter_pdf_lines(CLAUSE)])
        docx_time = (pkg / f"{LETTER}.docx").stat().st_mtime
        os.utime(pkg / f"{LETTER}.pdf", (docx_time + 3600, docx_time + 3600))

        # tracked: the same deletion left as a tracked change. One PDF is the export
        # after accepting it, the other still has the clause.
        pkg = package("tracked")
        letter(pkg, [OPENING + " " + BEFORE, deleted(CLAUSE), AFTER], [letter_pdf_lines()],
               comments=("Claude", "Example, Pat"))
        pkg = package("tracked-stale")
        letter(pkg, [OPENING + " " + BEFORE, deleted(CLAUSE), AFTER], [letter_pdf_lines(CLAUSE)])
        pkg = package("inserted")
        letter(pkg, [OPENING + " " + BEFORE, inserted(CLAUSE), AFTER], [letter_pdf_lines(CLAUSE)])

        pkg = package("marker")
        letter(pkg, BODY_NOW + " [CONFIRM: unit name]", [letter_pdf_lines(extra=" [CONFIRM: unit name]")])

        pkg = package("two-pages")
        lines = letter_pdf_lines()
        letter(pkg, BODY_NOW, [lines[:7], lines[7:]])

        # fused: stray text on the name line, and the round before it intact in Archive/.
        pkg = package("fused")
        letter(pkg, BODY_NOW, [letter_pdf_lines(name=FUSED + NAME)], name=FUSED + NAME)
        (pkg / "Archive").mkdir()
        make_docx(pkg / "Archive" / f"{LETTER}-v1.docx", letter_paragraphs(BODY_NOW))

        pkg = package("en-dash")
        make_docx(pkg / f"{RESUME}.docx", resume_paragraphs(f" {EN_DASH} "))
        make_pdf(pkg / f"{RESUME}.pdf", [resume_pdf_lines(f" {EN_DASH} ")])

        pkg = package("locked")
        letter(pkg, BODY_NOW, [letter_pdf_lines()])
        (pkg / "~$nthetic-RN-Cover-Letter.docx").write_bytes(b"\x00" * 162)

        pkg = package("unpaired")
        make_docx(pkg / f"{LETTER}.docx", letter_paragraphs(BODY_NOW))
        make_pdf(pkg / f"{RESUME}.pdf", [resume_pdf_lines()])

        pkg = package("other-employer", employer="Quillon Valley Hospital (Rivertown)")
        letter(pkg, BODY_NOW, [letter_pdf_lines()])

        pkg = package("sent", status="submitted")
        letter(pkg, BODY_NOW, [letter_pdf_lines(CLAUSE)])

        # headed: the letterhead sits in a Word page header and the footer numbers the
        # page. The PDF is a true LibreOffice export. In headed-edited the header was
        # changed after that export.
        exported = []
        for name in ("headed", "headed-edited"):
            pkg = package(name)
            make_docx(pkg / f"{LETTER}.docx", letter_paragraphs(BODY_NOW, name=None), header=[NAME, CONTACT])
            exported.append(pkg / f"{LETTER}.docx")
        for docx in exported:
            subprocess.run([cp._soffice(), f"-env:UserInstallation={(kit.root / 'lo-profile').as_uri()}",
                            "--headless", "--convert-to", "pdf", "--outdir", str(docx.parent), str(docx)],
                           capture_output=True, timeout=180, check=True)
        shutil.rmtree(kit.root / "lo-profile", ignore_errors=True)
        make_docx(exported[1], letter_paragraphs(BODY_NOW, name=None), header=[FUSED + NAME, CONTACT])

        cls.before = cls.snapshot()
        # One soffice start for every package, as run() does for one.
        cls.texts = cp.read_docx_texts([d for name in kit.postings
                                        for d in cp.scan(cp.APPLICATIONS / name)["docx"].values()])
        cls.found = {name: cp.check_package(cp.APPLICATIONS / name, posting, cls.texts)
                     for name, posting in kit.postings.items()}

    @classmethod
    def tearDownClass(cls):
        cls.kit.close()

    @classmethod
    def snapshot(cls) -> list:
        return sorted((str(p.relative_to(cls.kit.root)), p.stat().st_size, p.stat().st_mtime_ns)
                      for p in cls.kit.root.rglob("*"))

    def test_clean_package_passes_and_subfolders_are_not_read(self):
        found = self.found["clean"]
        self.assertEqual(checks(found, "FAIL"), [])
        self.assertEqual(checks(found, "WARN"), ["unpaired"])
        self.assertIn("1 supporting PDF(s)", message(found, "unpaired"))
        self.assertIn("Cert-BLS.pdf", message(found, "unpaired"))

    def test_stale_pdf_fails_on_content_though_it_is_the_newer_file(self):
        pkg = cp.APPLICATIONS / "stale"
        self.assertGreater((pkg / f"{LETTER}.pdf").stat().st_mtime, (pkg / f"{LETTER}.docx").stat().st_mtime)
        found = self.found["stale"]
        self.assertEqual(checks(found, "FAIL"), ["pdf-match"])
        msg = message(found, "pdf-match")
        self.assertIn('Word has "', msg)
        self.assertIn("multi-patient assignments. The team", msg.split("| PDF has")[0])
        self.assertIn("assignments, night shifts included. The team", msg.split("| PDF has")[1])

    def test_tracked_deletion_fails_with_counts_and_reads_as_deleted(self):
        found = self.found["tracked"]
        # The PDF without the clause matches: the comparison saw the deletion as made.
        self.assertEqual(checks(found, "FAIL"), ["tracked-changes"])
        self.assertIn("0 insertion(s), 1 deletion(s)", message(found, "tracked-changes"))
        self.assertIn("2 Word comment(s): Claude x1, Example, Pat x1", message(found, "comments"))

    def test_tracked_deletion_with_a_stale_pdf_fails_both_checks(self):
        found = self.found["tracked-stale"]
        self.assertEqual(sorted(checks(found, "FAIL")), ["pdf-match", "tracked-changes"])
        self.assertIn("night shifts included", message(found, "pdf-match").split("| PDF has")[1])

    def test_tracked_insertion_counts_and_reads_as_inserted(self):
        found = self.found["inserted"]
        self.assertEqual(checks(found, "FAIL"), ["tracked-changes"])
        self.assertIn("1 insertion(s), 0 deletion(s)", message(found, "tracked-changes"))

    def test_marker_fails_in_the_docx_and_in_the_pdf(self):
        found = self.found["marker"]
        self.assertEqual(checks(found, "FAIL"), ["marker", "marker"])
        msg = message(found, "marker")
        self.assertIn(f"{LETTER}.docx still has [CONFIRM", msg)
        self.assertIn(f"{LETTER}.pdf still has [CONFIRM", msg)
        self.assertIn("unit name", msg)

    def test_two_page_letter_fails_on_pages_only(self):
        found = self.found["two-pages"]
        self.assertEqual(checks(found, "FAIL"), ["pages"])
        self.assertIn("is 2 pages", message(found, "pages"))

    def test_fused_letterhead_fails_against_the_profile_file(self):
        found = self.found["fused"]
        self.assertEqual(checks(found, "FAIL"), ["letterhead", "letterhead"])
        msg = message(found, "letterhead")
        self.assertIn(f'{LETTER}.docx opens "{FUSED}{NAME} / ', msg)
        self.assertIn(f'{LETTER}.pdf opens "{FUSED}{NAME} / ', msg)
        self.assertIn("(from profile/letterhead.txt)", msg)

    def test_without_the_profile_file_the_newest_archived_letter_is_the_reference(self):
        saved = cp.LETTERHEAD_FILE
        cp.LETTERHEAD_FILE = self.kit.root / "profile" / "not-there.txt"
        try:
            fused = cp.check_package(cp.APPLICATIONS / "fused", None, self.texts)
            clean = cp.check_package(cp.APPLICATIONS / "clean", None, self.texts)
            stale = cp.check_package(cp.APPLICATIONS / "stale", None, self.texts)
        finally:
            cp.LETTERHEAD_FILE = saved
        msg = message(fused, "letterhead")
        self.assertEqual(checks(fused, "FAIL"), ["letterhead", "letterhead"])
        self.assertIn(f'expected "{NAME} / ', msg)
        self.assertIn(f"(from Archive/{LETTER}-v1.docx)", msg)
        self.assertIn("save them as profile/letterhead.txt", msg)
        # In clean it is the archived round that carries the stray text, so the good
        # letter fails against it: the Archive reference is the weaker one, and says how
        # to replace it.
        self.assertEqual(checks(clean, "FAIL"), ["letterhead", "letterhead"])
        # No Archive at all: one WARN, however many files the letter has, and no FAIL for it.
        self.assertEqual(checks(stale, "FAIL"), ["pdf-match"])
        self.assertEqual(checks(stale, "WARN"), ["letterhead"])
        self.assertIn("not checked: profile/letterhead.txt is missing and Archive/ holds no earlier letter",
                      message(stale, "letterhead"))
        self.assertIn("ask the applicant for the two lines", message(stale, "letterhead"))

    def test_letterhead_in_a_word_header_and_a_footer_compare_like_with_like(self):
        self.assertEqual(self.found["headed"], [])
        found = self.found["headed-edited"]
        self.assertEqual(checks(found, "FAIL"), ["pdf-match", "letterhead"])
        self.assertIn(f"{LETTER}.docx opens", message(found, "letterhead"))
        self.assertIn(FUSED, message(found, "pdf-match").split("| PDF has")[0])

    def test_en_dash_beside_a_year_warns_and_does_not_fail(self):
        found = self.found["en-dash"]
        self.assertEqual(checks(found, "FAIL"), [])
        self.assertEqual(checks(found, "WARN"), ["date-dash"])
        self.assertIn("U+2013 en dash", message(found, "date-dash"))
        self.assertEqual(checks(self.found["clean"], "WARN").count("date-dash"), 0)

    def test_word_lock_fails(self):
        found = self.found["locked"]
        self.assertEqual(checks(found, "FAIL"), ["word-lock"])
        self.assertIn(f"{LETTER}.docx is open in Word", message(found, "word-lock"))
        self.assertIn("closed in Word first", message(found, "word-lock"))

    def test_unpaired_files_warn_and_are_still_checked(self):
        found = self.found["unpaired"]
        self.assertEqual(checks(found, "FAIL"), [])
        self.assertEqual(checks(found, "WARN"), ["unpaired", "unpaired"])
        msg = message(found, "unpaired")
        self.assertIn(f"{LETTER}.docx has no PDF", msg)
        self.assertIn(f"{RESUME}.pdf has no Word file", msg)

    def test_employer_not_named_is_a_warning_and_needs_the_tracker_row(self):
        found = self.found["other-employer"]
        self.assertEqual(checks(found, "FAIL"), [])
        self.assertIn("names none of Quillon, Valley", message(found, "employer"))
        self.assertEqual(checks(self.found["clean"], "WARN").count("employer"), 0)
        no_row = cp.check_package(cp.APPLICATIONS / "other-employer", None, self.texts)
        self.assertEqual(checks(no_row, "WARN"), [])

    def test_nothing_is_written_into_a_package(self):
        self.assertEqual(self.snapshot(), self.before)

    def test_main_exit_codes_and_lines(self):
        code, out = run_main("Applications/clean", "--id", "clean")
        self.assertEqual(code, 0)
        self.assertIn(f"CHECKED cover letter: {LETTER}.docx + {LETTER}.pdf", out)
        self.assertTrue(out.rstrip().endswith("RESULT clean: safe to upload (0 FAIL, 1 WARN)"))
        code, out = run_main(str(cp.APPLICATIONS / "tracked-stale"))
        self.assertEqual(code, 1)
        fails = [ln for ln in out.splitlines() if ln.startswith("FAIL ")]
        self.assertEqual(len(fails), 2)
        for line in fails:
            self.assertRegex(line, r"^FAIL [a-z-]+: \S")
        self.assertIn("WARN status: no --id given", out)
        self.assertTrue(out.rstrip().endswith("DO NOT UPLOAD (2 FAIL, 1 WARN)"))
        self.assertEqual(self.snapshot(), self.before)

    def test_submitted_is_refused_then_checked_with_force(self):
        code, out = run_main("sent", "--id", "sent")
        self.assertEqual(code, 2)
        self.assertTrue(out.startswith("REFUSED sent"))
        self.assertNotIn("FAIL", out)
        code, out = run_main("sent", "--id", "sent", "--force")
        self.assertEqual(code, 1)
        self.assertIn("NOTE sent was submitted", out)
        self.assertIn("FAIL pdf-match", out)

    def test_hashes_prints_only_the_root_pdfs(self):
        code, out = run_main("clean", "--hashes")
        self.assertEqual(code, 0)
        rows = [ln.split("  ") for ln in out.splitlines()]
        self.assertEqual([r[2] for r in rows], ["Cert-BLS.pdf", f"{LETTER}.pdf", f"{RESUME}.pdf"])
        for digest, size, name in rows:
            data = (cp.APPLICATIONS / "clean" / name).read_bytes()
            self.assertEqual((digest, size), (hashlib.sha256(data).hexdigest(), str(len(data))))


if __name__ == "__main__":
    unittest.main()
