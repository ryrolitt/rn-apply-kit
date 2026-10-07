#!/bin/bash
# Store the read-only access token your colleague sent you, so git pull and the feed keep
# working after the repos go private. Run once: scripts/set-token.sh <token>
# The token is read-only on two repositories and nothing else. It lives in
# ~/.config/rn-apply-kit/token (mode 600) and never in this repo.
set -eu
KIT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
TOKEN="${1:-}"
[ -n "$TOKEN" ] || { echo "usage: scripts/set-token.sh <token>"; exit 2; }
case "$TOKEN" in github_pat_*|ghp_*) ;; *) echo "that does not look like a GitHub token (expected github_pat_... )"; exit 2;; esac
mkdir -p "$HOME/.config/rn-apply-kit"
umask 077
printf '%s\n' "$TOKEN" > "$HOME/.config/rn-apply-kit/token"
# A credential helper local to this clone: git asks it for a password and gets the token.
git -C "$KIT" config --local credential.helper '!f(){ echo username=x-access-token; echo "password=$(cat "$HOME/.config/rn-apply-kit/token")"; }; f'
if git -C "$KIT" ls-remote --exit-code origin HEAD >/dev/null 2>&1; then echo "ok: git can reach the kit repo with the token"; else echo "FAILED: git cannot reach the kit repo with this token"; exit 1; fi
if "$KIT/.venv/bin/python3" "$KIT/scripts/fetch_feed.py" >/dev/null 2>&1; then echo "ok: the feed is readable with the token"; else echo "FAILED: the feed is not readable with this token"; exit 1; fi
echo "stored in ~/.config/rn-apply-kit/token"
