#!/usr/bin/env python3
"""Pull the openings feed and merge it into tracker.json. No LLM, no tokens.

The feed (rn-openings-feed/openings.json) is regenerated about hourly by its owner's tooling.
The repo is private: the feed is read through the GitHub CLI (`gh auth login` once, done in
session 1). The raw URL is only a fallback for a public mirror.
This script keeps YOUR state: a posting's `status`, `status_at`, `notes` and `first_seen_at`
survive every pull. Feed fields are refreshed in place. Ids that leave the feed are kept with
`in_feed: false` so your history is never lost.

Usage: python3 scripts/fetch_feed.py            (uses FEED_URL below, or env RN_FEED_URL)
       python3 scripts/fetch_feed.py --file openings.json   (offline, for tests)
"""
import datetime
import json
import os
import sys

KIT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TRACKER = os.path.join(KIT, "tracker.json")
FEED_REPO = os.environ.get("RN_FEED_REPO", "ryrolitt/rn-openings-feed")
FEED_URL = os.environ.get(
    "RN_FEED_URL",
    f"https://raw.githubusercontent.com/{FEED_REPO}/main/openings.json",
)
FEED_FIELDS_KEPT_LOCAL = ("status", "status_at", "notes", "first_seen_at", "package_dir")


def now():
    return datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def load_feed(path=None):
    if path:
        return json.load(open(path))
    import shutil
    import subprocess
    if shutil.which("gh"):
        r = subprocess.run(["gh", "api", "-H", "Accept: application/vnd.github.raw",
                            f"/repos/{FEED_REPO}/contents/openings.json"],
                           capture_output=True, text=True, timeout=90)
        if r.returncode == 0 and r.stdout.strip():
            return json.loads(r.stdout)
        print(f"fetch_feed: gh api failed ({r.stderr.strip()[:160]}); trying the raw URL", file=sys.stderr)
    import urllib.request
    req = urllib.request.Request(FEED_URL, headers={"User-Agent": "rn-apply-kit fetch_feed"})
    with urllib.request.urlopen(req, timeout=60) as r:
        return json.load(r)


def load_tracker():
    if os.path.exists(TRACKER):
        return json.load(open(TRACKER))
    return {"schema_version": 1, "updated_at": None, "feed_generated_at": None, "postings": {}}


def main():
    path = None
    if len(sys.argv) > 2 and sys.argv[1] == "--file":
        path = sys.argv[2]
    try:
        feed = load_feed(path)
    except Exception as e:  # network down, raw URL moved: keep the last tracker untouched
        print(f"fetch_feed: could not load feed ({e}); tracker unchanged", file=sys.stderr)
        return 1
    if feed.get("schema_version") != 1:
        print(f"fetch_feed: feed schema_version {feed.get('schema_version')} is newer than this "
              f"script understands; run `git pull` in the kit", file=sys.stderr)
        return 2

    t = load_tracker()
    postings = t["postings"]
    seen = set()
    added = updated = 0
    ts = now()
    for p in feed.get("postings", []):
        pid = p["id"]
        seen.add(pid)
        if pid in postings:
            local = {k: postings[pid].get(k) for k in FEED_FIELDS_KEPT_LOCAL}
            if any(postings[pid].get(k) != v for k, v in p.items()):
                updated += 1
            postings[pid].update(p)
            for k, v in local.items():
                if v is not None:
                    postings[pid][k] = v
        else:
            postings[pid] = dict(p, status="new", status_at=ts, notes="", first_seen_at=ts)
            added += 1
        postings[pid]["in_feed"] = True
        postings[pid]["last_seen_in_feed_at"] = ts
    dropped = 0
    for pid, p in postings.items():
        if pid not in seen and p.get("in_feed", True):
            p["in_feed"] = False
            dropped += 1
    t["updated_at"] = ts
    t["feed_generated_at"] = feed.get("generated_at")
    json.dump(t, open(TRACKER, "w"), indent=1, ensure_ascii=False)
    print(f"fetch_feed: {len(seen)} in feed (generated {feed.get('generated_at')}), "
          f"{added} new, {updated} refreshed, {dropped} left the feed; tracker has {len(postings)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
