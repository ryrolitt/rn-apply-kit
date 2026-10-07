#!/bin/bash
# Daily pull and rank. No Claude, no tokens. Installed into cron by install.sh.
set -u
export PATH="/opt/homebrew/bin:/usr/local/bin:$PATH"   # cron has no Homebrew on PATH; gh lives there
KIT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PY="$KIT/.venv/bin/python3"
[ -x "$PY" ] || PY="$(command -v python3)"
mkdir -p "$KIT/logs"
echo "[$(date '+%Y-%m-%d %H:%M')] daily start"
"$KIT/scripts/update.sh"
"$PY" "$KIT/scripts/fetch_feed.py" || echo "fetch failed; ranking the last tracker"
"$PY" "$KIT/scripts/rank.py" --top 10
echo "[$(date '+%Y-%m-%d %H:%M')] daily end"
