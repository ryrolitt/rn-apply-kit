# /start-next-app <id>: build and pre-fill one application, leave the Submit click

Argument: a posting `id` from `ranked.html` (or none: take rank 1 whose status is `new`).
One application per session. Say at the start which NOT SENT packages exist
(`python3 scripts/status.py --list working`).

## 1. Verify the posting (before any writing)
- `.venv/bin/python3 scripts/verify_url.py <url>`. Not live: `status.py <id> skip "posting gone <date>"`, stop.
- Open it in the `playwright` MCP, `browser_snapshot`, read the full description. Record in
  `Applications/<slug>/INTAKE.md`: the verbatim experience requirement, license and
  certification requirements, "open to" or internal-only language, the close date exactly
  as the page states it (or "none stated"), shift and hours, pay if posted, the apply URL, and
  what the portal is. Slug: `<Employer>-<Role>` in ASCII with hyphens.
- Eligibility against `profile/fact-base.md`: a stated years floor above theirs, a license they
  do not hold, or internal-only means stop: `status.py <id> skip "<the employer's sentence>"`.
- `status.py <id> working "started <date>"`.

## 2. Cover letter
- Read `profile/voice-samples.md`, `profile/anecdotes.md`, `profile/fact-base.md` and the
  description. Only these are sources. Missing fact: `[CONFIRM: ...]`, never a filler.
- Draft one page: why this unit and employer (from the posting's own words), one concrete
  moment from the anecdotes that proves the thing this reader needs proved, what they bring,
  a plain close. Hyphens, no em dashes, acronyms spelled out, nothing that volunteers a gap.
- One self-review pass, in order: every sentence traceable to a source; does it read as the
  applicant against the voice samples; cut any sentence that only praises; one page in Calibri.
  Fix, do not re-draft.
- Write `Applications/<slug>/<Employer-Role>-Cover-Letter.docx` through the `docx` skill.
  Show the text in chat for approval before any PDF.

## 3. Resume
- Copy `Master Materials/<Name>-Resume-Master.docx` to `Applications/<slug>/<Employer-Role>-Resume.docx`
  and edit it in place through the `docx` skill: reorder or trim so the relevant placements and
  skills are first; add nothing the master does not carry. No objective line naming the job.
- `scripts/export_pdf.sh` on both files. Check the page count it prints.

## 4. Portal
- Load `.claude/skills/web-forms/SKILL.md` and its `references/site-notes.md` first.
- Before any upload: `.venv/bin/python3 scripts/check_package.py "Applications/<slug>" --id <id>`.
  Exit 1 is a stop: fix each FAIL (it prints the differing sentence), export again, re-run.
  Exit 2 means nothing was checked: do what its one line says. Read the WARN lines. It cannot
  see a wrong fact or a weak sentence.
- In the `playwright` MCP: start the application, prefer "apply manually" over resume parsing,
  fill every field from `profile/`, open optional sections and decide each, upload the PDFs,
  answer screening questions from the fact base (unknown answer: ask, do not guess).
- Walk every page once more before handing over. Then say exactly what is left for them:
  the attestation checkbox, voluntary disclosures, Submit. Keep the browser window open.

## 5. Finish
`status.py <id> working "pre-filled, awaiting their Submit"`; commit nothing under
`Applications/` (gitignored). Remind them: run `/close-out-app <id>` after they click Submit.
