#!/bin/bash
# One-time setup for rn-apply-kit. Safe to re-run. Installs what is missing through Homebrew.
# Claude runs this; the applicant is asked only for a password when the Homebrew installer
# needs one, and for the GitHub sign-in click.
set -u
KIT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$KIT"
BLOCKED=0
ok()   { printf '  ok      %s\n' "$1"; }
inst() { printf '  installing %s\n' "$1"; brew install $2 >/dev/null 2>&1 && ok "$1" || { printf '  FAILED  %s (run: brew install %s)\n' "$1" "$2"; BLOCKED=1; }; }

echo "rn-apply-kit install in $KIT"
echo "1. Tools"
if ! command -v brew >/dev/null 2>&1; then
  for b in /opt/homebrew/bin/brew /usr/local/bin/brew; do [ -x "$b" ] && eval "$("$b" shellenv)"; done
fi
if ! command -v brew >/dev/null 2>&1; then
  echo "  MISSING Homebrew. Its installer needs the Mac login password, so it runs in the applicant's own Terminal:"
  echo '          /bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)"'
  echo "          then run ./install.sh again."
  exit 1
fi
ok "Homebrew"
command -v node >/dev/null 2>&1 && ok "node $(node --version)" || inst "node" "node"
if command -v python3 >/dev/null 2>&1 && [ "$(python3 -c 'import sys;print(sys.version_info[0]*100+sys.version_info[1])')" -ge 311 ]; then ok "python3 $(python3 --version | cut -d' ' -f2)"; else inst "python3" "python"; fi
command -v pdftotext >/dev/null 2>&1 && ok "poppler (pdftotext)" || inst "poppler" "poppler"
command -v gh >/dev/null 2>&1 && ok "GitHub CLI" || inst "GitHub CLI" "gh"
if command -v soffice >/dev/null 2>&1 || [ -x /Applications/LibreOffice.app/Contents/MacOS/soffice ]; then ok "LibreOffice"; else inst "LibreOffice" "--cask libreoffice"; fi
[ -d "/Applications/Google Chrome.app" ] && ok "Google Chrome" || inst "Google Chrome" "--cask google-chrome"
[ "$BLOCKED" = 1 ] && { echo "Fix the failed installs above, then run ./install.sh again."; exit 1; }

echo "2. GitHub sign-in (the kit and the feed are private repos you were invited to)"
if gh auth status >/dev/null 2>&1; then ok "signed in as $(gh api user -q .login 2>/dev/null)"; else
  echo "  NOT SIGNED IN. Run: gh auth login --web --git-protocol https"
  echo "          (opens the browser; the applicant signs in and approves. Claude never types the password.)"
  BLOCKED=1
fi
if git -C "$KIT" remote get-url origin >/dev/null 2>&1; then
  git -C "$KIT" ls-remote --exit-code origin HEAD >/dev/null 2>&1 && ok "kit repo reachable" || { echo "  cannot reach the kit repo: accept the GitHub invitation (github.com/notifications), then re-run"; BLOCKED=1; }
fi

echo "3. Python environment"
if [ ! -x .venv/bin/python3 ]; then python3 -m venv .venv || { echo "venv failed"; exit 1; }; fi
.venv/bin/python3 -m pip install -q --upgrade pip requests >/dev/null 2>&1 && ok ".venv with requests" || { echo "pip install failed"; exit 1; }
chmod +x scripts/*.sh scripts/*.py

echo "4. Playwright MCP (browser with a persistent profile)"
sed "s#__KIT__#$KIT#g" .mcp.json.template > .mcp.json && ok ".mcp.json written"
mkdir -p .playwright-profile output logs
if npx -y @playwright/mcp@latest --version >/dev/null 2>&1; then ok "@playwright/mcp $(npx -y @playwright/mcp@latest --version 2>/dev/null)"; else echo "  @playwright/mcp could not be fetched; check the network and re-run"; BLOCKED=1; fi

echo "5. Your files"
if [ ! -d profile ]; then cp -R templates/profile profile && ok "profile/ created from templates"; else ok "profile/ exists (left alone)"; fi
mkdir -p "Master Materials" Applications
[ -f preferences.toml ] || { cp preferences.example.toml preferences.toml && ok "preferences.toml created from the example (run /set-preferences to make it yours)"; }

echo "6. First pull and ranking"
if [ "$BLOCKED" = 0 ]; then
  .venv/bin/python3 scripts/fetch_feed.py && .venv/bin/python3 scripts/rank.py --top 5 || echo "  (feed pull or ranking failed; the daily job will retry)"
else echo "  skipped until the GitHub sign-in above is done"; fi

echo "7. Daily job (cron, 07:45)"
LINE="45 7 * * * $KIT/scripts/daily.sh >> $KIT/logs/daily.log 2>&1"
if crontab -l 2>/dev/null | grep -Fq "$KIT/scripts/daily.sh"; then ok "cron line present"; else
  (crontab -l 2>/dev/null; echo "$LINE") | crontab - && ok "cron line added" || echo "  could not edit crontab; run: (crontab -l; echo \"$LINE\") | crontab -"
fi

echo
if [ "$BLOCKED" = 1 ]; then echo "One step is still open (see above). Finish it and run ./install.sh again."; exit 1; fi
echo "Done. Next: in Claude Code, with this folder as the working directory, run /intake-profile."
exit 0
