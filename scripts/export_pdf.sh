#!/bin/bash
# Export a .docx to PDF next to it with LibreOffice, then prove the PDF is fresh.
# Usage: scripts/export_pdf.sh "Applications/<slug>/<Employer-Role>-Cover-Letter.docx"
set -eu
SRC="$1"
DIR="$(cd "$(dirname "$SRC")" && pwd)"
SOFFICE="$(command -v soffice || true)"
[ -n "$SOFFICE" ] || SOFFICE="/Applications/LibreOffice.app/Contents/MacOS/soffice"
[ -x "$SOFFICE" ] || { echo "soffice not found: brew install --cask libreoffice"; exit 1; }
PDF="$DIR/$(basename "${SRC%.*}").pdf"
BEFORE=$(stat -f %m "$PDF" 2>/dev/null || echo 0)
"$SOFFICE" --headless --convert-to pdf "$SRC" --outdir "$DIR" >/dev/null 2>&1
AFTER=$(stat -f %m "$PDF" 2>/dev/null || echo 0)
if [ "$AFTER" -le "$BEFORE" ]; then echo "PDF did not change: $PDF"; exit 1; fi
PAGES=$(command -v pdfinfo >/dev/null && pdfinfo "$PDF" | awk '/^Pages:/{print $2}' || echo "?")
echo "ok: $PDF ($PAGES pages)"
