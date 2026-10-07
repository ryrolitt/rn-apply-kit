# /intake-profile: build the applicant's profile from their own materials

Session 1. Output: `profile/` filled in, the current resume copied into `Master Materials/`,
one commit. Nothing invented. The applicant is on a Pro plan: one batched ask, no exploring.

## 1. Ask for the folder first
Ask one question: "Do you have a folder with past applications, CVs, cover letters, transcripts
or certificates? Paste its path (or drag the folder into this chat). If not, say no."

## 2. First pass from the folder (if given)
- `find "<path>" -type f \( -iname '*.docx' -o -iname '*.pdf' -o -iname '*.txt' -o -iname '*.md' \)`.
  List what you found in one short table (file, kind, modified date). No file is opened twice.
- Read them: `.docx` through the `docx` skill (or `soffice --headless --convert-to txt` for a
  quick read), `.pdf` with `pdftotext -layout file.pdf -`. Read each in full.
- Extract into `profile/`, every fact with its source file in brackets, e.g.
  `RN license 12345678, exp 2028-01-31 [from Resume-2026.pdf]`:
  - `profile/fact-base.md`: name as it appears on documents, degrees with school and year,
    GPA only if a transcript or the resume states it, license numbers and expiry, certifications
    with expiry, clinical placements (unit, site, hours if stated), employment with dates,
    research or volunteer roles, languages, skills the documents list.
  - `profile/anecdotes.md`: concrete moments from THEIR OWN letters and essays, quoted or closely
    paraphrased, each with the source file. A moment that appears only in a model-looking letter
    with no detail is listed under "unverified" for them to confirm.
  - `profile/voice-samples.md`: two or three verbatim passages (80 to 200 words each) from things
    they clearly wrote themselves (an essay, a personal statement, an email). Not a template letter.
  - `profile/references.md`: names, titles, relationship, contact details found.
  - `profile/contact.md`: address, phone, email, LinkedIn as found.
- Copy the most recent resume to `Master Materials/<Name>-Resume-Master.<ext>` (keep the original
  untouched in their folder).
- Mark every field you could not fill `[CONFIRM: ...]`. Where two documents disagree, write both
  with their sources and `[CONFIRM: which]`.

## 3. One batched ask for the gaps
Present a single numbered list of everything still `[CONFIRM]` plus these if absent: license
state and number, certifications with expiry, GPA per school, placements, two or three things
they wrote themselves, references with contact details, home address and phone, the
preferred name on applications. Say they can answer in any order and skip what they do not
have. Write the answers in exactly as given.

## 4. Finish
- `python3 scripts/status.py --list` is empty at this point; skip it.
- Commit: `git add -A profile` is NOT allowed because profile is gitignored on purpose; commit
  only kit files you changed, if any. Say in one line where the profile lives and that it is
  local only.
- Tell them, in five lines or fewer, what `/set-preferences` will ask next session: home city
  and commute tolerance, specialties in order, inpatient or outpatient, schedule, employers to
  prefer or avoid, residency versus direct hire, years of experience, license state.
