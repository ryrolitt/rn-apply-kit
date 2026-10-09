# /close-out-app <id>: record a submission

Run when the applicant says they clicked Submit.

1. Ask for one piece of evidence: the confirmation page text, a screenshot, or the
   confirmation email subject and time. If the portal is still open in the `playwright` MCP,
   `browser_snapshot` the confirmation page yourself. No evidence, no "submitted": record
   `working` with the note "says submitted <date>, unconfirmed" and say so.
2. `python3 scripts/status.py <id> submitted "<date> via <portal>, confirmation <what you saw>"`.
3. In `Applications/<slug>/`, write `SUBMITTED.md`: date, portal, which files went, the
   confirmation detail, any recruiter or contact named on the confirmation. For the files, keep
   the lines `.venv/bin/python3 scripts/check_package.py "Applications/<slug>" --hashes` prints
   (sha256, size, name) for the PDFs actually uploaded. The letter and
   resume in that folder are now the record of what was sent; never edit them again.
4. Follow-up: if the posting named a timeline, put it in the note. Suggest a calendar check
   for two weeks out; do not create one unless asked.
5. Re-rank: `.venv/bin/python3 scripts/rank.py --top 5`. Print the remaining NOT SENT list
   with ages, then the next three ranked rows. Stop.
