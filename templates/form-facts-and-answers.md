# Form facts and answers

A lookup for sessions pre-filling portals: each job and school in the shape a form asks for, and
every screening answer the applicant has given, word for word. It is not a source for letters or
resumes. It lives in `profile/`, which is local only.

**Rule.** A banked answer is shown to the applicant as a proposal when a form asks the same or a
near question. It is entered without asking only when the question text and the options match
exactly and the entry has not expired.

Further limits on that rule:
- An entry marked `text: not verbatim` can never match exactly. Proposal only.
- A `[SUBMITTED ...]` entry marked `no read-back recorded` is a proposal only.
- A `[SESSION GUESS, ask]` value is never presented as the applicant's answer. Ask.
- Attestations, signatures, initials and Submit are the applicant's, every time.

## Source tags

Every value and every answer ends with one tag.
- `[APPLICANT <date>]` the applicant typed, said, chose or corrected it in a session that day.
- `[SUBMITTED <date>, <portal>]` it was on a form the applicant then submitted, and it was read
  back from the form.
- `[RECORD <file>]` it comes from a document: the resume in `Master Materials/`, a transcript, a
  license, a certificate.
- `[SESSION GUESS, ask]` a session chose or proposed it; nothing shows the applicant confirmed it.

Facts tagged `[APPLICANT]`, `[SUBMITTED]` or `[RECORD]` are typed without asking. A
`[SESSION GUESS, ask]`, a `[CONFIRM]`, or two values that disagree are asked, once, in one list.

## Not stored here, on purpose

Veteran status, disability, accommodation answers, gender, race or ethnicity, sexual orientation,
any other voluntary self-identification answer; attestations, initials and e-signatures;
passwords, security answers, one-time codes; driver license number; Social Security number;
birthdate. Where a portal asked, the line reads "self-identification: the applicant's, not stored".

# Part 1. Form facts

Licenses, certifications and contact details stay in `profile/fact-base.md` and
`profile/contact.md`; references in `profile/references.md`. Copy a block per job and per school,
newest first.

## Jobs

### J1. [CONFIRM: employer] ([CONFIRM: current, or the end month])

- Employer as entered: [CONFIRM]
- Title: [CONFIRM]
- Setting (unit or program, and what it is): [CONFIRM]
- Location (city and state, or "Remote" when there was no office): [CONFIRM]
- Start (month and year; the day if a form wants it): [CONFIRM]
- End (month and year, or "current"): [CONFIRM]
- Supervisor (name, title, phone or email): [CONFIRM]
- May the employer be contacted: [CONFIRM]
- Hours per week: [CONFIRM]
- Reason for leaving: [CONFIRM]
- Duties text, as pasted into forms: [CONFIRM]

## Schools

### S1. [CONFIRM: school] ([CONFIRM: degree])

- Degree as entered: [CONFIRM]
- Field or major as entered, by portal list: [CONFIRM]
- Attended (start to end, month and year): [CONFIRM]
- Conferred: [CONFIRM]
- GPA (only as the transcript states it): [CONFIRM]
- City and state: [CONFIRM]

# Part 2. Answers given

Only answers the applicant gave. Format: the question word for word, the options where the form
showed them, the answer with its tag, where it was asked, and an `expires:` line. An answer
expires when it depends on something that changes: months of experience, current employment,
availability, license or certification status.

### A1. "<the question, word for word>" (<option> / <option>)

- Answer: <the choice> [APPLICANT <date>]
- Asked by: <employer>, <portal>
- expires: <a date, the event that makes it stale, or never>
