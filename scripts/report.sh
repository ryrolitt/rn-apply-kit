#!/bin/bash
# Send your colleague a question or a problem report by email. Claude writes the message;
# this opens it in your mail app, already addressed, and you click Send.
#   scripts/report.sh question "one-line summary" < message.txt
#   scripts/report.sh bug "one-line summary" < message.txt
# The address lives in ~/.config/rn-apply-kit/contact (set once in your first session).
set -u
KIT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
KIND="${1:-}"; SUMMARY="${2:-}"
case "$KIND" in question|bug) ;; *) echo "usage: scripts/report.sh question|bug \"summary\" < message.txt"; exit 2;; esac
[ -n "$SUMMARY" ] || { echo "a one-line summary is required"; exit 2; }
CONTACT_FILE="$HOME/.config/rn-apply-kit/contact"
[ -s "$CONTACT_FILE" ] || { echo "no contact address yet: ask your colleague for it, then: mkdir -p ~/.config/rn-apply-kit && echo ADDRESS > $CONTACT_FILE"; exit 1; }
TO="$(head -1 "$CONTACT_FILE" | tr -d '[:space:]')"
BODY="$(cat)"
BODY="$BODY

--
kit: $(git -C "$KIT" log -1 --format='%h %cs' 2>/dev/null) | macOS $(sw_vers -productVersion 2>/dev/null) | sent with scripts/report.sh"
SUBJECT="[rn-apply-kit] $KIND: $SUMMARY"
mkdir -p "$KIT/output"
OUT="$KIT/output/report-$(date +%Y%m%d-%H%M%S).txt"
printf 'To: %s\nSubject: %s\n\n%s\n' "$TO" "$SUBJECT" "$BODY" > "$OUT"
enc() { python3 -c 'import sys,urllib.parse;print(urllib.parse.quote(sys.stdin.read(),safe=""))'; }
URL="mailto:$TO?subject=$(printf '%s' "$SUBJECT" | enc)&body=$(printf '%s' "$BODY" | enc)"
printf '%s' "$BODY" | pbcopy 2>/dev/null
if open "$URL" 2>/dev/null; then echo "opened in your mail app, addressed to $TO: check it and click Send"
else echo "could not open a mail app"; fi
echo "if no draft appeared: email $TO with subject \"$SUBJECT\"; the message is on your clipboard and saved in ${OUT#$KIT/}"
