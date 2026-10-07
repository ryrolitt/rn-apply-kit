#!/bin/bash
# Pull kit updates (commands, rules, scripts, skills). Your data is gitignored and untouched.
# Run by daily.sh; safe to run by hand. Uses the stored token when the repos are private.
set -u
KIT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$KIT"
BEFORE=$(git rev-parse HEAD 2>/dev/null)
if git pull -q --ff-only origin main 2>/tmp/rn-apply-kit-pull.err; then
  AFTER=$(git rev-parse HEAD)
  if [ "$BEFORE" != "$AFTER" ]; then
    echo "kit updated: $(git log --oneline "$BEFORE..$AFTER" | wc -l | tr -d ' ') commits"
    git log --oneline "$BEFORE..$AFTER" | sed 's/^/  /'
    [ -f .mcp.json.template ] && sed "s#__KIT__#$KIT#g" .mcp.json.template > .mcp.json
  else echo "kit up to date"; fi
else
  echo "kit update failed: $(head -c 200 /tmp/rn-apply-kit-pull.err)"
  echo "  if the repos went private: ask your colleague for the token, then scripts/set-token.sh <token>"
fi
