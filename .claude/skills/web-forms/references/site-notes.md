# Per-site notes

Hosts conquered, and what it cost. Append as you go: site, widget quirk, what worked. Generic
technique stays in SKILL.md. Dates are when the behavior was measured; portals change.

## Workday candidate portals (`*.myworkdayjobs.com`), measured 2026-09-30

- **Start with "Apply Manually"**, not "Autofill with Resume" (the parser writes claims in the
  applicant's name) or "Use My Last Application" (it carries only My Information; work history,
  education, uploads and questionnaires come up empty, measured on a second req the same night).
- Sign-in is a password: fill the email, leave the Sign In click to the applicant.
- **Date spinbuttons hide behind a display div**: clicking the `-input` ref times out. Click
  `#<section>--startDate-dateSectionMonth-display`, then type `MMYYYY` key by key into the
  `-input` id; it auto-advances to the year. Read values back with `.value` on both inputs.
- **Stable ids per row**: after "Add Another", list `[id^=workExperience-]` / `[id^=education-]`
  prefixes to get the new row's number, then address
  `#workExperience-NN--jobTitle|companyName|location|currentlyWorkHere|roleDescription`.
- **Dropdowns (`button[aria-haspopup=listbox]`)**: option labels can be long ("Yes - If you are
  a current employee..."), so an exact-text match misses. Open, list `[role=option]` id and
  text, click by `[id="..."]` (ids start with digits, so never `#id`). Escape closes a stuck
  popup that intercepts clicks.
- **Field of Study is a typeahead**: type, Enter; a single match auto-selects as a pill,
  otherwise click the `menuItem-...` id. Mirror the posting's education wording.
- **Checkbox grids** ("status of work", "shifts"): a ref click on "Any" silently failed once;
  verify `[checked]` in a snapshot and re-click via DOM if needed.
- **Uploads**: files under a cloud-synced symlink are refused ("outside allowed roots"); copy
  to `output/uploads/` first. The Resume/CV slot takes several files (resume plus letter).
- **The applicant's clicks**: Voluntary Disclosures, the Terms and Conditions checkbox, Self
  Identify (disability), and Submit on the Review page.

## UltiPro / UKG Recruiting (`recruiting2.ultipro.com`), measured 2026-09

1. **Uploading a document does not attach it.** Each row's include-checkbox stays OFF after
   upload, and the tree reports the control as `active`, never `checked`. Verify with
   `input.checked` keyed on `aria-labelledby="FileName<N>"` and toggle with a real `.click()`
   on that input. Set each row's Document Type; it defaults to "Resume" for every file.
2. **The resume parser fills skill LEVELS, not just names, by keyword prominence.** It rated
   one applicant's prior non-nursing career "Expert" and the nursing itself "Some Knowledge".
   The level `<select>` values are GUIDs; decode them from each select's own option map.
3. **After submitting, the application snapshot freezes but the candidate profile does not**
   (`/Candidate/ViewPresence` keeps Edit on every section). A missed field is fixable there.
4. **Skip the parser; hand entry is scriptable** (measured 2026-09-30). Leave the top "Upload
   Resume" alone and add the resume under Documents (its file input is the second
   `input[type=file]`; click its `label[for=...]`, then upload). Work Experience rows take a
   scripted fill (value plus input/change events, then Save) through `browser_evaluate`.
   School, Degree and License name are typeaheads that need real key presses, then a click on
   `.tt-suggestion`. School accepts free text; Degree and License come from a fixed list
   (`$root.licenseOptions`). Date boxes are three segments: click the `mm` box and type
   `MMDDYYYY`. Education dates are optional.

Knockout drives this app, so bulk programmatic edits are safe here, unlike React.

## CalCareers (`calcareers.ca.gov`, State of California STD 678), measured 2026-10-02

- ASP.NET WebForms: menu links and most selects are `__doPostBack`. Navigate by clicking
  `a[href*="ucAccountMenu$btn..."]` from `AccountOverview.aspx`, wait about 2.5 s; no deep links.
- The Application Template wizard (Questions, Education, Experience, Complete) saves server-side
  on every record Save, so nothing is lost if the tab closes.
- Dates and the supervisor phone are masked text: fill `07/20/2026` and `(415) 476-1000` as
  whole strings; bare digits typed key by key do not register.
- Degree select options are `AA/AS`, `BA/BS`, `MA/MS` (values 1, 2, 3) and it posts back on
  change: select it last, wait, then Save. License title is cut at 30 characters; the license
  number is required.
- Grid rows show the record name as an `input.linkButton`, so `innerText` looks empty; click it
  to reopen the record and read values back.
- Uploaded Documents: Add a Document, pick the type, Continue, then set the file on
  `#cphMainContent_fileUpload_AjaxFileUpload_Html5InputFile`; it uploads immediately.
