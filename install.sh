#!/bin/bash
# One-time setup for rn-apply-kit. Safe to re-run. No Claude tokens involved.
set -u
KIT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$KIT"
MISSING=0
ok()   { printf '  ok      %s\n' "$1"; }
miss() { printf '  MISSING %s\n          install: %s\n' "$1" "$2"; MISSING=1; }

echo "rn-apply-kit install in $KIT"
echo "1. Tools"
command -v brew    >/dev/null 2>&1 && ok "Homebrew" || miss "Homebrew" '/bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)"'
command -v node    >/dev/null 2>&1 && ok "node $(node --version)" || miss "node" "brew install node"
command -v npx     >/dev/null 2>&1 && ok "npx" || miss "npx (comes with node)" "brew install node"
if command -v python3 >/dev/null 2>&1; then
  PYV=$(python3 -c 'import sys;print(sys.version_info[0]*100+sys.version_info[1])')
  [ "$PYV" -ge 311 ] && ok "python3 $(python3 --version | cut -d' ' -f2)" || miss "python3 >= 3.11 (have $(python3 --version))" "brew install python"
else miss "python3" "brew install python"; fi
SOFFICE="$(command -v soffice || true)"; [ -n "$SOFFICE" ] || [ -x /Applications/LibreOffice.app/Contents/MacOS/soffice ] && ok "LibreOffice" || miss "LibreOffice (soffice)" "brew install --cask libreoffice"
command -v pdftotext >/dev/null 2>&1 && ok "poppler (pdftotext)" || miss "poppler" "brew install poppler"
[ -d "/Applications/Google Chrome.app" ] && ok "Google Chrome" || miss "Google Chrome" "brew install --cask google-chrome"
if [ "$MISSING" = 1 ]; then echo; echo "Install the missing tools above, then run ./install.sh again."; exit 1; fi

echo "2. Python environment"
if [ ! -x .venv/bin/python3 ]; then python3 -m venv .venv || { echo "venv failed"; exit 1; }; fi
.venv/bin/python3 -m pip install -q --upgrade pip requests >/dev/null 2>&1 && ok ".venv with requests" || { echo "pip install failed"; exit 1; }
chmod +x scripts/*.sh scripts/*.py

echo "3. Playwright MCP (browser with a persistent profile)"
sed "s#__KIT__#$KIT#g" .mcp.json.template > .mcp.json && ok ".mcp.json written"
mkdir -p .playwright-profile output logs
if npx -y @playwright/mcp@latest --version >/dev/null 2>&1; then ok "@playwright/mcp $(npx -y @playwright/mcp@latest --version 2>/dev/null)"; else miss "@playwright/mcp (npx could not fetch it; check the network)" "npx -y @playwright/mcp@latest --version"; fi

echo "4. Your files"
if [ ! -d profile ]; then cp -R templates/profile profile && ok "profile/ created from templates"; else ok "profile/ exists (left alone)"; fi
mkdir -p "Master Materials" Applications
[ -f preferences.toml ] || { cp preferences.example.toml preferences.toml && ok "preferences.toml created from the example (run /set-preferences to make it yours)"; }

echo "5. First pull and ranking"
.venv/bin/python3 scripts/fetch_feed.py && .venv/bin/python3 scripts/rank.py --top 5 || echo "  (feed pull or ranking failed; the daily job will retry)"

echo "6. Daily job (cron, 07:45)"
LINE="45 7 * * * $KIT/scripts/daily.sh >> $KIT/logs/daily.log 2>&1"
if crontab -l 2>/dev/null | grep -Fq "$KIT/scripts/daily.sh"; then ok "cron line present"; else
  (crontab -l 2>/dev/null; echo "$LINE") | crontab - && ok "cron line added" || echo "  could not edit crontab; run: (crontab -l; echo \"$LINE\") | crontab -"
fi

echo
echo "Done. Next: in Claude Code, with this folder as the working directory, run /intake-profile."
[ "$MISSING" = 1 ] && exit 1 || exit 0
