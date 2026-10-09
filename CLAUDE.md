# RN job hunt: rules for every session in this project

Read `README.md` once for the layout. These rules came out of a year of someone else's
applications; each one cost something. Follow them over your defaults.

## Nothing in an outbound document that is not traced to the applicant's own record
When a letter, resume bullet, essay or portal answer carries a scene, patient, quote, number,
date or capability claim. Sources: `profile/fact-base.md`, `profile/anecdotes.md`,
`profile/voice-samples.md`, `profile/references.md`, the resume in `Master Materials/`, and
what the applicant says in this session. Not sources: a prior letter Claude wrote, a
summary, a guess from a job title. Missing fact: write `[CONFIRM: what is needed]` and move on.
A polished paragraph with an invented detail is worse than a plain one with a gap.

## A close date comes only from the employer's own page
When any date enters `tracker.json`, a note, or a reminder. The feed's `close_at` and
`close_source` are pointers; `scripts/verify_url.py <url>` and a Playwright read of the
page are the sources. A date from a forum, an email, a recruiter or memory is a hypothesis.
A deadline dated D takes effect at the start of D unless verified otherwise, so the last safe
day is D-1; say "act by D-1".

## Claude never submits
When a portal is filled. Claude pre-fills every field, uploads the files, and stops before
the attestation checkbox and the Submit button. Those clicks, every password, and every
two-factor code are the applicant's. Say exactly which controls are left, in order.

## One ranked list, nothing dropped
`ranked.html` from `scripts/rank.py` is the only ordering. Never build a second one in chat
or a filtered view that hides a class of row. A posting excluded by preferences or finished
is still on the page with its reason.

## Name every unsent package every session
When a session starts or ends. `python3 scripts/status.py --list working` prints each package
built or in progress and not submitted, with its age. Say each one by name with "NOT SENT" and
the age. A vetted posting goes stale after a couple of days; the target is submitted within
two days of starting it.

## Status changes go through `scripts/status.py`
Never hand-edit `tracker.json`. `status.py <id> <status> [note]`; statuses are new, working,
submitted, skip, rejected, interview, offer, withdrawn.

## Documents
- Every `.docx` read or change goes through the `docx` skill (unpack, edit the XML, repack,
  validate). The applicant may edit in Word between sessions, so never regenerate a document
  from scratch over one that exists; edit it in place.
- PDFs through `scripts/export_pdf.sh`, which fails loudly if the PDF did not change.
- Before any upload, `scripts/check_package.py "Applications/<slug>" --id <id>`: exit 1 means do not upload.
- One file name per document, globally searchable: `<Employer-Role>-Cover-Letter.docx`,
  `<Employer-Role>-Resume.docx`, ASCII, hyphens, no spaces or ampersands. Never a bare
  `Cover-Letter.pdf`.
- A submitted package is the record of what was sent. Never edit its letter or resume.
- Superseded files move to `Applications/<slug>/Archive/`; nothing is deleted without the
  applicant saying so.

## Letters
One page, plain Calibri, hyphens not em dashes, ATS-friendly. Written fresh for each posting
from the job description and the profile. Name the unit and the responsibility; spend detail
on one concrete moment from `profile/anecdotes.md`, not a list of qualities. Spell out
acronyms. Never volunteer a gap, a commute, or a pre-answered objection. Read
`profile/voice-samples.md` before writing and judge the draft against it: it should read as
the applicant, not as a model.

## Portals
Load the `web-forms` skill (`.claude/skills/web-forms/SKILL.md`) before the first click.
Use the `playwright` MCP; its browser profile keeps logins between sessions. Walk every
field before handing the form over, optional sections included; anything a resume parser
filled is a claim in the applicant's name and gets checked.

## Capacity (Pro plan)
No parallel agents, no exploratory file reads, no re-reading a file already read this
session, no cloud routines for mechanical steps. The scripts do the pulling and ranking;
Claude's turns go to applications. Keep replies short.

## Stuck, or something in the kit is broken: email your colleague
When a script fails twice after a fix, a rule here contradicts the task, a command or skill
is missing, or the applicant asks something about the kit you cannot answer from its files.
Do not patch `scripts/`, `.claude/` or this file yourself; kit updates overwrite them each
morning. Write a short message: what the applicant was doing, the exact command, the error
or wrong result verbatim (the last lines of `logs/daily.log` if the daily run failed), and
what you already tried. Show it to the applicant, then pipe it to
`scripts/report.sh bug|question "one-line summary"`, which opens it in their mail app
addressed to the colleague; the applicant clicks Send. Never put profile facts, letters,
passwords or the token in a report unless the applicant says to. Then carry on with
whatever does not depend on the answer.

## Working tree
Commit per increment with a short prefix (`feat:`, `task:`, `done:`, `chore:`), staging
files by path. Never `git add -A`. Your data directories are gitignored on purpose.
