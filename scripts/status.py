#!/usr/bin/env python3
"""Set a posting's status in tracker.json. The only sanctioned way to change one.

Usage: python3 scripts/status.py <id> <status> [note]
       python3 scripts/status.py --list [status]

Statuses: new | working | submitted | skip | rejected | interview | offer | withdrawn
`working` means a package is being built or is built and NOT SENT. Those are listed every
session with their age, because a vetted posting goes stale after a couple of days.
"""
import datetime
import json
import os
import sys

KIT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TRACKER = os.path.join(KIT, "tracker.json")
STATUSES = ("new", "working", "submitted", "skip", "rejected", "interview", "offer", "withdrawn")


def main():
    t = json.load(open(TRACKER))
    if len(sys.argv) >= 2 and sys.argv[1] == "--list":
        want = sys.argv[2] if len(sys.argv) > 2 else None
        today = datetime.date.today()
        rows = []
        for pid, p in t["postings"].items():
            if want and p.get("status") != want:
                continue
            if not want and p.get("status") in ("new", "skip"):
                continue
            age = ""
            if p.get("status_at"):
                age = f"{(today - datetime.date.fromisoformat(p['status_at'][:10])).days}d"
            rows.append((p.get("status"), age, pid, p.get("employer"), p.get("title")))
        rows.sort()
        for r in rows:
            print(" | ".join(str(x) for x in r))
        print(f"{len(rows)} rows")
        return 0
    if len(sys.argv) < 3 or sys.argv[2] not in STATUSES:
        print(__doc__)
        return 2
    pid, status = sys.argv[1], sys.argv[2]
    note = " ".join(sys.argv[3:])
    p = t["postings"].get(pid)
    if p is None:
        print(f"status: no posting with id {pid!r}")
        return 1
    ts = datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    p["status"], p["status_at"] = status, ts
    if note:
        p["notes"] = (p.get("notes") or "").rstrip()
        p["notes"] = (p["notes"] + "\n" if p["notes"] else "") + f"{ts[:10]} {note}"
    json.dump(t, open(TRACKER, "w"), indent=1, ensure_ascii=False)
    print(f"status: {pid} -> {status}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
