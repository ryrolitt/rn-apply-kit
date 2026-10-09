#!/usr/bin/env python3
"""The sentences in the commands, the skill and CLAUDE.md that must not erode. No network.

    python3 -m unittest discover -s tests        (from the kit root)

The command files are edited often, because fixing the command is how the next session
inherits a lesson. Every edit is also a chance to drop a rule nobody was looking at. This
pins the few whose loss would send something out wrong. It proves the text is still
there; it cannot prove a session obeys it.

A fragment is matched with whitespace collapsed, so re-wrapping a paragraph is free.
Rewording a pinned sentence on purpose: change it here in the same commit.
"""
import re
import unittest
from pathlib import Path

KIT = Path(__file__).resolve().parents[1]
RULES = "CLAUDE.md"
START = ".claude/commands/start-next-app.md"
CLOSE = ".claude/commands/close-out-app.md"
PREFS = ".claude/commands/set-preferences.md"
FORMS = ".claude/skills/web-forms/SKILL.md"

# (file, fragment, what breaks if it goes)
PINNED = [
    (RULES, "## Claude never submits",
     "the Submit click stops being the applicant's"),
    (RULES, "stops before the attestation checkbox and the Submit button",
     "a session certifies or submits in the applicant's name"),
    (RULES, "A close date comes only from the employer's own page",
     "a date from a feed, an email or memory gets counted down to"),
    (RULES, 'say "act by D-1"',
     "a deadline is relayed as its own date and missed by a day"),
    (RULES, "Status changes go through `scripts/status.py`",
     "tracker.json gets hand-edited and the daily pull overwrites or corrupts it"),
    (RULES, "Never hand-edit `tracker.json`",
     "tracker.json gets hand-edited and the daily pull overwrites or corrupts it"),
    (RULES, "A submitted package is the record of what was sent. Never edit its letter or resume.",
     "a later session edits the only evidence of what the employer read"),
    (RULES, "exit 1 means do not upload",
     "the pre-upload gate stops being run"),
    (START, '.venv/bin/python3 scripts/check_package.py "Applications/<slug>" --id <id>',
     "the pre-upload gate stops being run"),
    (START, "Exit 1 is a stop",
     "a PDF that does not match its Word file gets uploaded anyway"),
    (START, "Missing fact: `[CONFIRM: ...]`, never a filler",
     "invented detail fills a gap in a letter"),
    (START, "only when the question text and options match exactly and it has not expired",
     "an old answer is entered for a question that only looks the same"),
    (START, "read every pre-loaded row against the current resume",
     "a stale stored profile goes out under a new application"),
    (START, "the attestation checkbox, voluntary disclosures, Submit",
     "the applicant is not told which clicks are theirs"),
    (CLOSE, 'No evidence, no "submitted"',
     "a submission gets recorded on say-so alone"),
    (CLOSE, "status.py <id> submitted",
     "the submission is recorded somewhere other than the tracker"),
    (CLOSE, "never edit them again",
     "a later session edits the only evidence of what the employer read"),
    (PREFS, "Claude never types a password or a code.",
     "a session handles a credential"),
    (FORMS, "never press Enter in a field",
     "Enter is the implicit submit on a single-page form"),
    (FORMS, "## What is never Claude's click",
     "the list of controls a session must leave alone is gone"),
]


def squash(text):
    return re.sub(r"\s+", " ", text)


class PinnedSentences(unittest.TestCase):
    def test_every_pinned_sentence_is_still_there(self):
        cache, missing = {}, []
        for rel, fragment, why in PINNED:
            if rel not in cache:
                cache[rel] = squash((KIT / rel).read_text(encoding="utf-8"))
            if squash(fragment) not in cache[rel]:
                missing.append(f"\n  {rel}\n    gone: {fragment!r}\n    risk: {why}")
        self.assertFalse(missing, "pinned rule text is missing:" + "".join(missing))

    def test_the_pin_list_names_real_files(self):
        for rel in {p[0] for p in PINNED}:
            self.assertTrue((KIT / rel).is_file(), rel)


if __name__ == "__main__":
    unittest.main()
