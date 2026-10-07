# rn-apply-kit

A Claude Code workspace for a new-grad RN job hunt in the San Francisco Bay Area. It reads a
shared feed of openings, ranks them by your own preferences with a plain script, and gives
Claude the commands and rules to build each application (letter, resume, PDFs, portal data
entry) while you keep the Submit click.

Two setup sessions, then your Claude usage goes to applications. The daily pull and ranking
never touch Claude.

## Before you open Claude (5 minutes, once)

1. A free GitHub account (github.com/signup) if you do not have one; the kit and the feed are
   private repos you are invited to. Accept the invitation email.
2. The Claude desktop app, signed in with your Pro account, Code tab open.

That is all. Paste the kickoff prompt your colleague sent you. Claude installs the rest
(Homebrew tools, LibreOffice, Chrome, the Playwright browser) and asks you only for two
things it cannot do itself: your Mac password if Homebrew's installer needs it, and the
GitHub sign-in click in your browser.

## What is in here

| Path | What |
|---|---|
| `CLAUDE.md` | The rules Claude follows in this project. Read once; they explain the why. |
| `install.sh` | Checks tools, sets up the Playwright browser, pulls the feed, installs the daily cron job. |
| `scripts/fetch_feed.py` | Pulls the openings feed into `tracker.json`, keeping your statuses. |
| `scripts/rank.py` | Orders everything by `preferences.toml`, writes `ranked.html`. |
| `scripts/status.py` | The one way to change a posting's status. |
| `scripts/verify_url.py` | Checks a posting is still live and reads a close date from the page. |
| `scripts/export_pdf.sh` | docx to PDF with LibreOffice, and proves the PDF changed. |
| `.claude/commands/` | `/intake-profile`, `/set-preferences`, `/start-next-app`, `/close-out-app`. |
| `.claude/skills/web-forms/` | How to drive ATS portals (Workday, UltiPro, CalCareers) without wrong values. |
| `templates/profile/` | The files intake fills in: your facts, your anecdotes, your voice, your references. |
| `preferences.example.toml` | What a preferences file looks like. Yours is written by `/set-preferences`. |

Your data (`profile/`, `Master Materials/`, `Applications/`, `tracker.json`, `preferences.toml`,
the browser profile) is gitignored. `git pull` brings kit fixes and can never touch it.

## The sessions

1. **Intake** (`/intake-profile`): point Claude at your folder of past applications, CVs and
   letters; it does the first pass, then asks for what is missing in one list. Nothing is
   invented; gaps are marked `[CONFIRM]`.
2. **Preferences** (`/set-preferences`): a short interview, the first ranking, and a one-time
   login to each portal in the Playwright browser so later sessions are already signed in.
3. **Daily**: cron runs `scripts/daily.sh` at 07:45. Open `ranked.html`. New rows are marked.
4. **Per application** (`/start-next-app <id>`): verify the posting is live, letter and resume
   from your profile only, PDFs, portal pre-filled, and a short list of the clicks that are
   yours. `/close-out-app <id>` records the submission.

## Feed

`github.com/ryrolitt/rn-openings-feed` (private, you are a collaborator): postings only,
regenerated about hourly, read through the GitHub CLI.
A row is a pointer; every date and requirement is verified on the employer's page before
anything is built on it.

## Skills this relies on

The `docx` and `xlsx` skills for Word and Excel files, listed in Claude Code as
`anthropic-skills:docx` on the author's install (2026-10-07). If `/skills` does not list them,
install them from the official plugin marketplace before the first application session.
