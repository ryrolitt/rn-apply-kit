#!/usr/bin/env python3
"""The gate a session runs right before it uploads a package's PDFs. No LLM, no network.

Why: the applicant edits the Word files in Word between sessions, so the PDF beside a
letter can be an export of an earlier version, and text typed into the wrong window can
land in the letterhead. Neither shows in a file date or a page count.

Exit 0: safe to upload. Exit 1: at least one FAIL, each printed as one line
`FAIL <check>: <what, with the offending text>`. WARN lines never change the exit code.
Exit 2: nothing was checked (a refusal, a missing tool, a usage error); one line says why.

What it checks, per `X.docx` + `X.pdf` pair in the package root (subfolders are not read):
  pdf-match        the PDF's text equals the Word file's CURRENT text (tracked insertions
                   in, tracked deletions out). Content, never file age: a stale PDF copied
                   into place has a fresh date.
  tracked-changes  tracked insertions or deletions left in the docx: FAIL with counts.
  comments         Word comments present: WARN.
  marker           `[CONFIRM` and similar unresolved markers in the docx or PDF text.
  pages            a cover letter longer than one page.
  letterhead       the cover letter's first two lines differ from `profile/letterhead.txt`
                   (two lines, the applicant's own). Without that file: from the newest
                   letter in the package's `Archive/`. Without either: one WARN.
  employer         with --id: the letter names no distinctive word of the employer in
                   tracker.json: WARN (a loose match).
  date-dash        the resume PDF joins a year to a non-ASCII dash: WARN.
  word-lock        a `~$` lock file: Word has the docx open, so the file on disk may not
                   be what the applicant sees.
  unpaired         a docx with no PDF, or the reverse: WARN.

How the Word text is read: a temp copy of the docx has its tracked-deletion blocks cut
out, LibreOffice exports that copy to PDF in a temp folder, and poppler reads the text
layer. Both sides of the comparison are then PDF text, so headers, footers and tables
compare like with like. Nothing is written into the package.

Usage (from the kit root):
  python3 scripts/check_package.py "Applications/<slug>" --id <posting id>
  python3 scripts/check_package.py "Applications/<slug>" --hashes
        sha256, size and name of every PDF in the package root; nothing else
  --force   check a package that was already submitted (read only)

A submitted package is the record of what was sent, so it is refused without --force.
"Submitted" is the posting's status in tracker.json (the file scripts/status.py writes)
when --id is given, or a SUBMITTED.md in the folder.

Python 3 stdlib, plus poppler (pdftotext, pdfinfo) and LibreOffice (soffice).
Tests: `python3 -m unittest discover -s tests` from the kit root.
"""
from __future__ import annotations

import argparse
import difflib
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import unicodedata
import zipfile
from pathlib import Path

# Anchored on this file, never the home directory or the working directory.
KIT = Path(__file__).resolve().parents[1]
APPLICATIONS = KIT / "Applications"
TRACKER = KIT / "tracker.json"
LETTERHEAD_FILE = KIT / "profile" / "letterhead.txt"

SOFFICE_PATHS = ("/opt/homebrew/bin/soffice", "/usr/local/bin/soffice",
                 "/Applications/LibreOffice.app/Contents/MacOS/soffice")
POPPLER_DIRS = ("/opt/homebrew/bin", "/usr/local/bin", "/usr/bin")
SOFFICE_TIMEOUT_S = 180
POPPLER_TIMEOUT_S = 60

# Statuses that mean the package went out. Its files are then a record, not a draft.
SENT_STATUSES = ("submitted", "interview", "offer", "rejected", "withdrawn")

MARKERS = (
    ("[CONFIRM", re.compile(r"\[\s*CONFIRM", re.I)),
    ("[TODO", re.compile(r"\[\s*TODO", re.I)),
    ("[TBD", re.compile(r"\[\s*TBD", re.I)),
    ("[CHECK", re.compile(r"\[\s*CHECK\b")),
    ("[SESSION GUESS", re.compile(r"\[\s*SESSION GUESS")),
    ("[APPLICANT", re.compile(r"\[\s*APPLICANT\b")),
)

# Non-ASCII dashes and hyphens: hyphen, non-breaking hyphen, figure dash, en dash, em
# dash, horizontal bar, minus sign. Escapes on purpose, so no such character is in this file.
DASHES = "\u2010\u2011\u2012\u2013\u2014\u2015\u2212"
DASH_NAMES = {"\u2010": "U+2010 hyphen", "\u2011": "U+2011 non-breaking hyphen",
              "\u2012": "U+2012 figure dash", "\u2013": "U+2013 en dash",
              "\u2014": "U+2014 em dash", "\u2015": "U+2015 horizontal bar",
              "\u2212": "U+2212 minus sign"}
_YEAR = r"(?:19|20)\d{2}"
# A year followed by the dash ("2025 [en dash] Present"), or the dash followed by a
# year, with or without a month name ("[en dash] Jun 2026").
YEAR_DASH_RE = re.compile(
    rf"\b{_YEAR}\s?[{DASHES}]\s?\w*|\w*\s?[{DASHES}]\s?(?:[A-Z][a-z]{{2,8}}\.?\s)?{_YEAR}\b")

# ---------------------------------------------------------------- text shape

_TRANSLATE = {
    0x2018: "'", 0x2019: "'", 0x201A: "'", 0x201B: "'", 0x2032: "'",
    0x201C: '"', 0x201D: '"', 0x201E: '"', 0x201F: '"', 0x2033: '"',
    0x00AD: None,                                   # soft hyphen
    0x200B: None, 0x200C: None, 0x200D: None, 0x2060: None, 0xFEFF: None,
    0x000C: "\n",                                   # pdftotext page break
    # List bullets: a symbol-font bullet reaches a PDF text layer as a private-use
    # glyph or as U+2022 depending on who exported it. Neither is content.
    0x2022: " ", 0x25E6: " ", 0x25AA: " ", 0x25CF: " ", 0x25CB: " ",
    0x2023: " ", 0x2043: " ", 0x2219: " ", 0x25A0: " ", 0x27A2: " ",
}
for _c in DASHES:
    _TRANSLATE[ord(_c)] = "-"


def clean(text: str) -> str:
    """One spelling for the things two exporters spell differently: ligatures and
    non-breaking spaces (NFKC), curly quotes, dashes, bullets."""
    text = unicodedata.normalize("NFKC", text).translate(_TRANSLATE)
    return "".join(ch for ch in text if unicodedata.category(ch) != "Co")


def lines_of(text: str) -> list[str]:
    """Non-empty lines, cleaned, inner whitespace collapsed."""
    out = []
    for raw in clean(text).splitlines():
        line = " ".join(raw.split())
        if line:
            out.append(line)
    return out


def stream(text: str) -> str:
    """The whole text as one line. A word hyphenated across a PDF line end is joined
    first ("assign-" + "ments", "multi-" + "patient")."""
    text = re.sub(r"(?<=\w)-[ \t]*\n\s*(?=\w)", "-", clean(text))
    return " ".join(text.split())


def token_key(token: str) -> str:
    """Comparison key for one word: hyphens between letters dropped, so "assign-ments"
    (a line break) equals "assignments". Cost, accepted: an edit that only adds or
    removes a hyphen inside a word, or only a space, is not seen."""
    return re.sub(r"(?<=\w)-(?=\w)", "", token)


def tokens(text: str) -> list[str]:
    return stream(text).split()


def _sentence_window(toks: list[str], lo: int, hi: int, pad: int = 28) -> str:
    """The sentence around toks[lo:hi], cut to `pad` words each side."""
    start = lo
    while start > 0 and lo - start < pad and not re.search(r"[.!?][\"')\]]*$", toks[start - 1]):
        start -= 1
    end = max(hi, lo)
    while end < len(toks) and end - hi < pad:
        end += 1
        if re.search(r"[.!?][\"')\]]*$", toks[end - 1]) and end > hi:
            break
    text = " ".join(toks[start:end])
    return ("... " if start > 0 else "") + text + (" ..." if end < len(toks) else "")


def compare_text(word_text: str, pdf_text_: str) -> dict | None:
    """None when the two texts are the same words in the same order. Otherwise the
    first difference, shown as the sentence around it on each side.

    A difference that is only a missing or extra space is not one: a right-aligned tab
    with no room left ("General Hospital<tab>Spring 2026") can reach a PDF text layer
    with no space at all, from a PDF that is a true export."""
    d, p = tokens(word_text), tokens(pdf_text_)
    dk, pk = [token_key(t) for t in d], [token_key(t) for t in p]
    if "".join(dk) == "".join(pk):
        return None
    ops = [op for op in difflib.SequenceMatcher(None, dk, pk, autojunk=False).get_opcodes()
           if op[0] != "equal" and "".join(dk[op[1]:op[2]]) != "".join(pk[op[3]:op[4]])]
    _tag, i1, i2, j1, j2 = ops[0]
    return {
        "differences": len(ops),
        "word": _sentence_window(d, i1, i2),
        "pdf": _sentence_window(p, j1, j2),
        "word_only": " ".join(d[i1:i2]),
        "pdf_only": " ".join(p[j1:j2]),
        "same_words": sorted(dk) == sorted(pk),
    }


def find_markers(text: str) -> list[tuple[str, str]]:
    """(marker, text around it) for every unresolved marker."""
    flat = stream(text)
    hits = []
    for name, rx in MARKERS:
        for m in rx.finditer(flat):
            lo, hi = max(0, m.start() - 40), min(len(flat), m.end() + 60)
            hits.append((name, flat[lo:hi]))
    return hits


def year_dash_hits(pdf_text_: str) -> list[tuple[str, str]]:
    """(matched text, dash name) wherever a year touches a non-ASCII dash. Run on the
    raw PDF text layer: that is what an ATS parser reads, and some parsers do not take
    an en dash as a range separator and drop the end date."""
    hits = []
    for m in YEAR_DASH_RE.finditer(unicodedata.normalize("NFC", pdf_text_)):
        dash = next(ch for ch in m.group(0) if ch in DASHES)
        hits.append((" ".join(m.group(0).split()), DASH_NAMES[dash]))
    return hits


# ------------------------------------------------------------- employer name

_GENERIC = {
    "the", "of", "and", "for", "at", "in", "a", "an", "health", "healthcare", "hospital",
    "hospitals", "medical", "center", "centre", "corporation", "corp", "inc", "llc", "system",
    "systems", "services", "service", "county", "city", "behavioral", "care", "clinic",
    "clinics", "university", "school", "nursing", "department", "group", "family", "agencies",
    "solutions", "regional", "community", "program", "programs", "st", "san", "santa",
}


def employer_terms(employer: str) -> list[str]:
    """The words of an employer string worth looking for: everything before the first
    parenthesis, minus words any employer could carry. The parenthesis is dropped
    because it is usually a city, and the applicant's own letterhead may name that city."""
    head = employer.split("(", 1)[0]
    terms = []
    for word in re.findall(r"[A-Za-z0-9][A-Za-z0-9&'.]*", head):
        word = word.strip(".'")
        if len(word) >= 2 and word.lower() not in _GENERIC and word not in terms:
            terms.append(word)
    return terms


def employer_named(employer: str, letter_text: str) -> tuple[bool | None, list[str]]:
    """(found, terms looked for). Loose on purpose: one distinctive word of the employer
    is enough, and an acronym also matches the initials of the capitalised words ("VMC"
    in "Valley Medical Center"). None when nothing distinctive can be looked for."""
    terms = employer_terms(employer)
    if not terms:
        return None, terms
    flat = stream(letter_text)
    initials = "".join(w[0] for w in re.findall(r"[A-Za-z][A-Za-z'.&-]*", flat) if w[0].isupper())
    for term in terms:
        acronym = term.isupper() and term.isalpha() and len(term) <= 6
        if len(term) >= 3 or acronym:
            flags = 0 if acronym else re.I
            if re.search(rf"(?<![A-Za-z0-9]){re.escape(term)}(?![A-Za-z0-9])", flat, flags):
                return True, terms
        if acronym and len(term) >= 3 and term in initials:    # two initials match by chance
            return True, terms
    return False, terms


# -------------------------------------------------------------- tracker.json

def load_posting(pid: str) -> tuple[dict | None, str | None]:
    """(posting, None) from tracker.json, or (None, why not). Read only."""
    try:
        with open(TRACKER, encoding="utf-8") as f:
            postings = json.load(f).get("postings", {})
    except (OSError, ValueError) as e:
        return None, f"tracker.json could not be read ({e})"
    posting = postings.get(pid)
    if not isinstance(posting, dict):
        return None, f"tracker.json has no posting with id {pid!r}"
    return posting, None


def refusal(pkg: Path, pid: str | None, posting: dict | None) -> str | None:
    """Why this package is not checked, or None."""
    why = None
    if posting and posting.get("status") in SENT_STATUSES:
        when = str(posting.get("status_at") or "date not recorded")[:10]
        why = f"tracker.json has {pid} as {posting.get('status')} ({when})"
    elif (pkg / "SUBMITTED.md").is_file():
        why = "SUBMITTED.md is in the folder"
    if why is None:
        return None
    return (f"REFUSED {pkg.name}: {why}. Its documents are the record of what was sent, so "
            "nothing in it is fixed, re-exported or uploaded again. Pass --force to check it "
            "anyway (read only).")


# ------------------------------------------------------------------ the docx

_TRACK_RE = re.compile(rb"<w:(ins|del|moveFrom|moveTo)[\s/>]")
_BODY_PARTS_RE = re.compile(r"word/(document|header\d*|footer\d*|footnotes|endnotes)\.xml$")
# A tracked deletion with content. The self-closing form (a deleted paragraph mark
# inside <w:rPr>) holds no text and is left alone.
_DEL_BLOCK_RE = re.compile(rb"<w:(del|moveFrom)(?=[\s>])(?:[^>]*[^/>])?>.*?</w:\1>", re.S)


def tracked_changes(docx: Path) -> dict[str, int]:
    """Counts of tracked-change tags over the body parts (document, headers, footers,
    notes). A count of tags, not a reading of the text."""
    counts = {"ins": 0, "del": 0, "moveFrom": 0, "moveTo": 0}
    with zipfile.ZipFile(docx) as z:
        for name in z.namelist():
            if _BODY_PARTS_RE.match(name):
                for m in _TRACK_RE.finditer(z.read(name)):
                    counts[m.group(1).decode()] += 1
    return counts


def comment_authors(docx: Path) -> list[str]:
    """One author name per Word comment, in file order."""
    with zipfile.ZipFile(docx) as z:
        if "word/comments.xml" not in z.namelist():
            return []
        xml = z.read("word/comments.xml").decode("utf-8", "replace")
    authors = []
    for tag in re.findall(r"<w:comment\s[^>]*>", xml):
        m = re.search(r'w:author="([^"]*)"', tag)
        authors.append(m.group(1) if m else "unknown")
    return authors


def write_accepted_copy(docx: Path, dst: Path) -> None:
    """Copy `docx` to `dst` with every tracked-deletion block cut out, so the export
    reads as the text will once the changes are accepted (LibreOffice prints a tracked
    deletion as if it were still there). Whole `<w:del>` containers are removed; no
    text is read out of the XML."""
    with zipfile.ZipFile(docx) as zin, zipfile.ZipFile(dst, "w", zipfile.ZIP_DEFLATED) as zout:
        for item in zin.infolist():
            data = zin.read(item.filename)
            if _BODY_PARTS_RE.match(item.filename):
                data = _DEL_BLOCK_RE.sub(b"", data)
            zout.writestr(item, data)


def _tool(name: str) -> str | None:
    for d in POPPLER_DIRS:
        path = os.path.join(d, name)
        if os.path.exists(path):
            return path
    return shutil.which(name)


def _soffice() -> str | None:
    for path in SOFFICE_PATHS:
        if os.path.exists(path):
            return path
    return shutil.which("soffice")


def missing_tools() -> str | None:
    """One line naming what to install, or None when everything is there."""
    need = []
    if not (_tool("pdftotext") and _tool("pdfinfo")):
        need.append(("pdftotext and pdfinfo (poppler)", "brew install poppler"))
    if not _soffice():
        need.append(("soffice (LibreOffice)", "brew install --cask libreoffice"))
    if not need:
        return None
    return (f"STOP check_package: {' and '.join(n for n, _ in need)} not found. Run: "
            f"{' && '.join(c for _, c in need)}. Nothing was checked; do not upload until "
            "this check has run.")


def read_docx_texts(docxs: list[Path]) -> dict[Path, dict | Exception]:
    """What each docx prints NOW (tracked insertions in, deletions out), as the text
    layer of a fresh PDF export: {"plain": ..., "layout": ...} in pdftotext's two reading
    orders. ONE soffice run over temp copies, with a throwaway profile in the temp dir,
    so it neither collides with an open LibreOffice nor opens a file in the package."""
    out: dict[Path, dict | Exception] = {}
    if not docxs:
        return out
    soffice = _soffice()
    if not soffice:
        return {d: RuntimeError("soffice not found") for d in docxs}
    tmp = Path(tempfile.mkdtemp(prefix="check_package_"))
    try:
        src, dst = tmp / "in", tmp / "out"
        src.mkdir()
        dst.mkdir()
        copies: dict[Path, Path] = {}
        for n, docx in enumerate(docxs):
            copy = src / f"d{n:03d}.docx"
            try:
                write_accepted_copy(docx, copy)
                copies[docx] = copy
            except (OSError, zipfile.BadZipFile, KeyError) as e:
                out[docx] = e
        if copies:
            cmd = [soffice, f"-env:UserInstallation={(tmp / 'profile').as_uri()}", "--headless",
                   "--convert-to", "pdf", "--outdir", str(dst)]
            cmd += [str(c) for c in copies.values()]
            note = ""
            try:
                proc = subprocess.run(cmd, capture_output=True, text=True,
                                      timeout=SOFFICE_TIMEOUT_S, cwd=str(tmp))
                note = (proc.stderr or proc.stdout or "").strip()[-200:]
            except (OSError, subprocess.TimeoutExpired) as e:
                note = str(e)
            for docx, copy in copies.items():
                pdf = dst / (copy.stem + ".pdf")
                if not pdf.exists():
                    out[docx] = RuntimeError(f"soffice produced no export ({note or 'no message'})")
                    continue
                try:
                    out[docx] = {"plain": pdf_text(pdf), "layout": pdf_text(pdf, layout=True)}
                except RuntimeError as e:
                    out[docx] = e
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    return out


# ------------------------------------------------------------------- the PDF

def pdf_text(pdf: Path, layout: bool = False) -> str:
    """The PDF's text layer. Raises RuntimeError when it cannot be read."""
    tool = _tool("pdftotext")
    if not tool:
        raise RuntimeError("pdftotext (poppler) not found")
    cmd = [tool, "-enc", "UTF-8"] + (["-layout"] if layout else []) + [str(pdf), "-"]
    try:
        proc = subprocess.run(cmd, capture_output=True, timeout=POPPLER_TIMEOUT_S)
    except (OSError, subprocess.TimeoutExpired) as e:
        raise RuntimeError(f"pdftotext: {e}") from e
    if proc.returncode != 0:
        raise RuntimeError("pdftotext: " + proc.stderr.decode("utf-8", "replace").strip()[:200])
    return proc.stdout.decode("utf-8", "replace")


def pdf_pages(pdf: Path) -> int:
    tool = _tool("pdfinfo")
    if not tool:
        raise RuntimeError("pdfinfo (poppler) not found")
    try:
        proc = subprocess.run([tool, str(pdf)], capture_output=True, timeout=POPPLER_TIMEOUT_S)
    except (OSError, subprocess.TimeoutExpired) as e:
        raise RuntimeError(f"pdfinfo: {e}") from e
    m = re.search(rb"^Pages:\s+(\d+)", proc.stdout, re.M)
    if proc.returncode != 0 or not m:
        raise RuntimeError("pdfinfo: " + proc.stderr.decode("utf-8", "replace").strip()[:200])
    return int(m.group(1))


# --------------------------------------------------------------- the package

def doctype_of(stem: str) -> str:
    """letter, resume or other, from the filename (the kit's naming rule:
    <Employer-Role>-Cover-Letter, <Employer-Role>-Resume)."""
    if re.search(r"cover[-_ ]?letter", stem, re.I):
        return "letter"
    if re.search(r"resume|(?:^|[-_ ])cv(?:[-_ ]|$)", stem, re.I):
        return "resume"
    return "other"


DOCTYPE_LABEL = {"letter": "cover letter", "resume": "resume", "other": "document"}


def scan(pkg: Path) -> dict:
    """What is in the package ROOT. Subfolders are never entered, which is how
    Archive/ stays out of every check."""
    docx: dict[str, Path] = {}
    pdf: dict[str, Path] = {}
    word_locks, office_locks = [], []
    for p in sorted(pkg.iterdir()):
        if not p.is_file():
            continue
        name = p.name
        if name.startswith("~$"):
            word_locks.append(p)
        elif name.startswith(".~lock."):
            office_locks.append(p)
        elif name.startswith("."):
            continue
        elif name.lower().endswith(".docx"):
            docx[p.stem] = p
        elif name.lower().endswith(".pdf"):
            pdf[p.stem] = p
    return {"docx": docx, "pdf": pdf, "word_locks": word_locks, "office_locks": office_locks}


def lock_owner(lock: Path, docxs: list[Path]) -> Path | None:
    """The docx a Word `~$` lock belongs to. Word writes `~$` plus the name, or for a
    long name drops its first one or two characters to make room."""
    tail = lock.name[2:]
    for docx in docxs:
        if docx.name.endswith(tail) and len(docx.name) - len(tail) in (0, 1, 2):
            return docx
    return None


def _quote(text: str, limit: int = 420) -> str:
    text = " ".join(text.split())
    return '"' + (text if len(text) <= limit else text[:limit] + " ...") + '"'


LETTERHEAD_HOWTO = ("To turn the check on, ask the applicant for the two lines that open every "
                    "letter (name line, contact line) and save them as profile/letterhead.txt")


def expected_letterhead(pkg: Path) -> tuple[list[str] | None, str]:
    """(the two lines a letter must open with, where they came from), or (None, why
    there is nothing to compare with). profile/letterhead.txt first; without it, the
    newest cover letter in the package's Archive/."""
    if LETTERHEAD_FILE.is_file():
        try:
            lines = lines_of(LETTERHEAD_FILE.read_text(encoding="utf-8-sig", errors="replace"))
        except OSError:
            lines = []
        if len(lines) >= 2 and not find_markers("\n".join(lines[:2])):
            return lines[:2], "profile/letterhead.txt"
        why = "profile/letterhead.txt does not hold two filled lines"
    else:
        why = "profile/letterhead.txt is missing"
    archive = pkg / "Archive"
    letters = []
    if archive.is_dir():
        letters = [p for p in archive.iterdir()
                   if p.is_file() and p.suffix.lower() == ".docx" and not p.name.startswith("~$")
                   and doctype_of(p.stem) == "letter"]
    if letters:
        newest = max(letters, key=lambda p: p.stat().st_mtime)
        got = read_docx_texts([newest]).get(newest)
        if isinstance(got, dict) and len(lines_of(got["plain"])) >= 2:
            return lines_of(got["plain"])[:2], f"Archive/{newest.name}"
        why += f" and Archive/{newest.name} could not be read"
    else:
        why += " and Archive/ holds no earlier letter"
    return None, why


def _letterhead_findings(label: str, text: str, want: list[str], source: str) -> list[tuple]:
    got = lines_of(text)[:2]
    if got == want:
        return []
    shown = " / ".join(got) if got else "(no text)"
    hint = "" if source == "profile/letterhead.txt" else f". If the new opening is right: {LETTERHEAD_HOWTO}"
    return [("FAIL", "letterhead",
             f"{label} opens {_quote(shown)}, expected {_quote(' / '.join(want))} "
             f"(from {source}){hint}")]


def check_package(pkg: Path, posting: dict | None, docx_texts: dict) -> list[tuple]:
    """Every finding for one package, as (level, check, message). `posting` is the
    tracker.json row when --id was given. `docx_texts` comes from read_docx_texts over
    this package's root docx files."""
    found: list[tuple] = []
    s = scan(pkg)
    docxs, pdfs = s["docx"], s["pdf"]
    letterhead: tuple | None = None        # looked up once, and only if there is a letter

    for lock in s["word_locks"]:
        owner = lock_owner(lock, list(docxs.values()))
        if owner:
            found.append(("FAIL", "word-lock",
                          f"{owner.name} is open in Word ({lock.name} is beside it): have it "
                          "closed in Word first, then re-run, so the file on disk is the one "
                          "the applicant sees"))
        else:
            found.append(("WARN", "word-lock",
                          f"{lock.name} is a Word lock with no matching docx in the folder"))
    for lock in s["office_locks"]:
        found.append(("WARN", "word-lock", f"{lock.name}: LibreOffice has a document open here"))

    supporting = []
    for stem in sorted(set(docxs) | set(pdfs)):
        docx, pdf = docxs.get(stem), pdfs.get(stem)
        doctype = doctype_of(stem)
        if docx is None and doctype == "other":
            supporting.append(pdf.name)      # certificates, transcripts: nothing to compare
            continue
        if pdf is None:
            found.append(("WARN", "unpaired",
                          f"{docx.name} has no PDF of the same name (nothing exported yet, "
                          "or the PDF was renamed)"))
        elif docx is None:
            found.append(("WARN", "unpaired",
                          f"{pdf.name} has no Word file of the same name, so it cannot be "
                          "compared with its source"))

        dtext = dlayout = ptext = playout = None
        if docx is not None:
            got = docx_texts.get(docx)
            if isinstance(got, dict):
                dtext, dlayout = got["plain"], got["layout"]
            else:
                found.append(("FAIL", "read", f"{docx.name} could not be read: {got}"))
            try:
                tc = tracked_changes(docx)
                if any(tc.values()):
                    parts = [f"{tc['ins']} insertion(s)", f"{tc['del']} deletion(s)"]
                    if tc["moveFrom"] or tc["moveTo"]:
                        parts.append(f"{max(tc['moveFrom'], tc['moveTo'])} move(s)")
                    found.append(("FAIL", "tracked-changes",
                                  f"{docx.name} still holds tracked changes: {', '.join(parts)}. "
                                  "Read them, accept or reject each, then export again"))
                authors = comment_authors(docx)
                if authors:
                    by = ", ".join(f"{a} x{authors.count(a)}" for a in dict.fromkeys(authors))
                    found.append(("WARN", "comments",
                                  f"{docx.name} carries {len(authors)} Word comment(s): {by}"))
            except (OSError, zipfile.BadZipFile) as e:
                found.append(("FAIL", "read", f"{docx.name} is not a readable docx: {e}"))
        if pdf is not None:
            try:
                ptext = pdf_text(pdf)
                playout = pdf_text(pdf, layout=True)
            except RuntimeError as e:
                found.append(("FAIL", "read", f"{pdf.name} could not be read: {e}"))

        # The PDF equals the Word file's current text, in either reading order.
        if dtext is not None and ptext is not None:
            diffs = [compare_text(dtext, ptext), compare_text(dlayout, playout)]
            if all(diffs):
                # On a tie show the -layout reading: it keeps a hyphen at a line end, where
                # the plain reading joins "multi-" + "patient" into one unhyphenated word.
                diff = min(reversed(diffs), key=lambda d: d["differences"])
                if not stream(ptext):
                    found.append(("FAIL", "pdf-match",
                                  f"{pdf.name} has no text layer, so it cannot be compared "
                                  f"with {docx.name}"))
                else:
                    order = (" (same words, different order: a moved passage, or a layout "
                             "that reads out of order)" if diff["same_words"] else "")
                    found.append(("FAIL", "pdf-match",
                                  f"{pdf.name} is not an export of the current {docx.name}: "
                                  f"{diff['differences']} difference(s){order}. First one, Word has "
                                  f"{_quote(diff['word'])} | PDF has {_quote(diff['pdf'])}"))

        for label, text in ((docx.name if docx else "", dtext), (pdf.name if pdf else "", ptext)):
            if text:
                for marker, context in find_markers(text):
                    found.append(("FAIL", "marker",
                                  f"{label} still has {marker}: {_quote(context)}"))

        if doctype == "letter":
            if pdf is not None:
                try:
                    pages = pdf_pages(pdf)
                    if pages > 1:
                        found.append(("FAIL", "pages",
                                      f"{pdf.name} is {pages} pages; a cover letter is one"))
                except RuntimeError as e:
                    found.append(("FAIL", "read", f"{pdf.name} page count unreadable: {e}"))
            letter_text = ptext if ptext is not None else dtext
            employer = (posting or {}).get("employer")
            if letter_text is not None and employer:
                named, looked = employer_named(employer, letter_text)
                if named is False:
                    found.append(("WARN", "employer",
                                  f"{stem} names none of {', '.join(looked)} (employer in "
                                  f"tracker.json: {employer})"))
            if dtext is not None or ptext is not None:
                if letterhead is None:
                    letterhead = expected_letterhead(pkg)
                    if letterhead[0] is None:
                        found.append(("WARN", "letterhead",
                                      f"not checked: {letterhead[1]}. {LETTERHEAD_HOWTO}"))
                want, source = letterhead
                if want is not None:
                    if dtext is not None:
                        found += _letterhead_findings(docx.name, dtext, want, source)
                    if ptext is not None:
                        found += _letterhead_findings(pdf.name, ptext, want, source)

        if doctype == "resume" and ptext is not None:
            hits = year_dash_hits(ptext)
            if hits:
                names = ", ".join(sorted({h[1] for h in hits}))
                sample = "; ".join(dict.fromkeys(
                    _quote(re.sub(f"[{DASHES}]", lambda m: f"[{DASH_NAMES[m.group(0)][:6]}]", h[0]))
                    for h in hits[:3]))
                found.append(("WARN", "date-dash",
                              f"{pdf.name} joins a year to a non-ASCII dash in {len(hits)} "
                              f"place(s) ({names}), which some ATS parsers read as no end date: "
                              f"{sample}. An ASCII hyphen parses everywhere"))

    if supporting:
        found.append(("WARN", "unpaired",
                      f"{len(supporting)} supporting PDF(s) with no Word file beside them, not "
                      f"compared: {', '.join(supporting)}"))
    return found


def run(pkg: Path, posting: dict | None = None) -> list[tuple]:
    """Check one package with a single soffice start for its root docx files."""
    return check_package(pkg, posting, read_docx_texts(list(scan(pkg)["docx"].values())))


def hashes(pkg: Path) -> list[str]:
    """`sha256  size  filename` for every PDF in the package root: the close-out
    record of exactly which bytes were uploaded."""
    rows = []
    for pdf in scan(pkg)["pdf"].values():
        data = pdf.read_bytes()
        rows.append(f"{hashlib.sha256(data).hexdigest()}  {len(data)}  {pdf.name}")
    return rows


# ----------------------------------------------------------------------- CLI

def resolve_package(arg: str) -> Path | None:
    """An absolute path, a path from the kit root, or a folder name under Applications/.
    Never the working directory."""
    given = Path(arg)
    candidates = [given] if given.is_absolute() else [KIT / given, APPLICATIONS / given]
    for c in candidates:
        if c.is_dir():
            return c
    return None


def _counts(found: list[tuple]) -> tuple[int, int]:
    return (sum(1 for f in found if f[0] == "FAIL"), sum(1 for f in found if f[0] == "WARN"))


def _main(argv: list[str] | None) -> int:
    ap = argparse.ArgumentParser(
        description="Gate before upload: PDF matches its Word file, no tracked changes, no "
                    "markers, letterhead intact. Exit 0 safe, 1 FAIL, 2 nothing checked.")
    ap.add_argument("package_dir", help="package folder: a path, or a folder name under Applications/")
    ap.add_argument("--id", dest="pid", help="the posting id in tracker.json (status and employer)")
    ap.add_argument("--hashes", action="store_true",
                    help="print sha256, size and filename of every PDF in the root; nothing else")
    ap.add_argument("--force", action="store_true",
                    help="check a package that was already submitted (read only)")
    args = ap.parse_args(argv)

    pkg = resolve_package(args.package_dir)
    if pkg is None:
        print(f"STOP check_package: no folder {args.package_dir!r} (tried it as an absolute path, "
              f"under {KIT} and under {APPLICATIONS}). Nothing was checked.")
        return 2
    if args.hashes:
        for row in hashes(pkg):
            print(row)
        return 0

    posting = None
    if args.pid:
        posting, problem = load_posting(args.pid)
        if posting is None:
            print(f"STOP check_package: {problem}. Nothing was checked.")
            return 2
    why = refusal(pkg, args.pid, posting)
    if why and not args.force:
        print(why)
        return 2
    stop = missing_tools()
    if stop:
        print(stop)
        return 2

    found = run(pkg, posting)
    if why:
        print(f"NOTE {pkg.name} was submitted; checked because of --force. Change nothing in it.")
    if not args.pid:
        found.append(("WARN", "status",
                      "no --id given, so tracker.json was not read: the submitted check used "
                      "SUBMITTED.md only and the employer name was not checked"))
    s = scan(pkg)
    for stem in sorted(set(s["docx"]) | set(s["pdf"])):
        if stem in s["docx"] or doctype_of(stem) != "other":
            have = " + ".join(p.name for p in (s["docx"].get(stem), s["pdf"].get(stem)) if p)
            print(f"CHECKED {DOCTYPE_LABEL[doctype_of(stem)]}: {have}")
    for level in ("FAIL", "WARN"):
        for lv, check, msg in found:
            if lv == level:
                print(f"{lv} {check}: {msg}")
    fails, warns = _counts(found)
    if fails:
        print(f"RESULT {pkg.name}: DO NOT UPLOAD ({fails} FAIL, {warns} WARN)")
        return 1
    print(f"RESULT {pkg.name}: safe to upload (0 FAIL, {warns} WARN)")
    return 0


def main(argv: list[str] | None = None) -> int:
    """Never a stack trace and never a silent pass: anything unexpected is exit 2."""
    try:
        return _main(argv)
    except Exception as e:      # noqa: BLE001
        print(f"STOP check_package: {type(e).__name__}: {e}. Nothing was checked; do not "
              "upload on this result.")
        return 2


if __name__ == "__main__":
    sys.exit(main())
