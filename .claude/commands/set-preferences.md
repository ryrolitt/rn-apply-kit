# /set-preferences: write preferences.toml, rank, sign in to the portals once

Session 2. Output: `preferences.toml`, `ranked.html`, portal logins saved in the Playwright
browser profile. Re-run any time to change the ranking.

## 1. Interview, one batched list
Ask these in one message, numbered; they answer in any order:
1. Home city and the longest commute they will accept in minutes.
2. Cities or areas they prefer, will accept, and will not consider.
3. Specialties in order of preference (psych, emergency, telemetry, med-surg, ICU, OR, peds,
   NICU, L&D, oncology, cardiac, home health, public health), and any to exclude.
4. Inpatient, outpatient, or either.
5. Schedule preferences and what to avoid (nights, days, full-time, part-time, per diem).
6. Employers to favor; employers to exclude.
7. Residency programs versus direct-hire staff roles: which matters more.
8. Years of RN experience they have (0 for a new grad) and license state.

## 2. Write the file
Start from `preferences.example.toml`, keep its comments, fill every section from the answers,
leave weights at their defaults unless they asked for something specific. Save as
`preferences.toml`. Read it back to them in six lines, plain words, no TOML.

## 3. Rank and show
```bash
.venv/bin/python3 scripts/fetch_feed.py && .venv/bin/python3 scripts/rank.py --top 10
```
Open `ranked.html` (`open ranked.html`). Ask if the top ten look right; adjust the lists or
weights once if not, re-run, stop there. Do not iterate more than twice; they can re-run the
command any day.

## 4. One-time portal logins
From the top ten, list the distinct portals (Workday tenants, UltiPro, iCIMS, Oracle, the
employer's own site). For each: `browser_navigate` to the posting's apply page in the
`playwright` MCP, take a snapshot, and tell them to sign in or create an account in that
window. Claude never types a password or a code. After they say done, snapshot once to confirm
the signed-in state, then move to the next. The profile keeps these logins.

## 5. Finish
Confirm the cron line exists (`crontab -l | grep daily.sh`); if not, run `./install.sh` again.
Tell them: open `ranked.html` each morning, pick a row, run `/start-next-app <id>`.
