#!/usr/bin/env python3
"""Rank tracker.json by preferences.toml and write ranked.html + ranked.json. No LLM.

One list, everything on it, most important first. Postings you have finished with (submitted,
skip, rejected, ...) and postings excluded by your preferences are still on the page, below
the fold, with the reason. Nothing is silently dropped.

A ranked row is labeled, never moved, when it is a sibling of an application already sent
(same employer and unit, only the shift or hours differ: a short send) or when its portal
already holds an account from an earlier application.

Usage: python3 scripts/rank.py [--top N]
Change preferences by re-running /set-preferences, not by editing the file by hand.
"""
import datetime
import functools
import html
import json
import os
import re
import sys
import tomllib

KIT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TRACKER = os.path.join(KIT, "tracker.json")
PREFS = os.path.join(KIT, "preferences.toml")
OUT_HTML = os.path.join(KIT, "ranked.html")
OUT_JSON = os.path.join(KIT, "ranked.json")

DONE = {"submitted", "skip", "rejected", "withdrawn", "interview", "offer"}
SYNONYMS = {
    "psych": ["psych", "behavioral health", "mental health", "bhu", "crisis", "psychiatric"],
    "emergency": ["emergency", " ed ", " ed,", "trauma", " er "],
    "med-surg": ["med-surg", "med/surg", "medical surgical", "medical-surgical", "medsurg", "med surg"],
    "telemetry": ["telemetry", " tele", "progressive care", "step-down", "stepdown", "pcu"],
    "icu": ["icu", "intensive care", "critical care"],
    "or": ["operating room", " or ", "perioperative", "surgical services", "periop"],
    "pediatrics": ["pediatric", "peds", "children"],
    "nicu": ["nicu", "neonatal"],
    "l&d": ["labor and delivery", "labor & delivery", "l&d", "perinatal", "maternity", "postpartum", "mother"],
    "oncology": ["oncology", "infusion"],
    "cardiac": ["cardiac", "cardiology", "cath lab"],
    "home health": ["home health", "hospice"],
    "public health": ["public health", "community health"],
    "residency": ["residency", "new grad", "new graduate", "nurse resident", "transition to practice"],
    "outpatient": ["clinic", "ambulatory", "outpatient"],
    "inpatient": ["inpatient", "hospital", "unit"],
    "nights": ["night", "noc"],
    "days": ["day shift", "days"],
    "full-time": ["full time", "full-time", "ft "],
    "part-time": ["part time", "part-time", "pt "],
    "per diem": ["per diem", "prn", "casual", "relief", "limited term"],
}


def has(term, text):
    t = term.lower()
    for s in SYNONYMS.get(t, [t]):
        if s in text:
            return True
    return False


def text_of(p):
    sc = p.get("screen") or {}
    return " " + " ".join(str(x) for x in (
        p.get("title"), p.get("location"), sc.get("population"), sc.get("employment_type"),
        sc.get("work_city"))).lower() + " "


def score(p, prefs, today):
    w = prefs.get("weights", {})
    sc = p.get("screen") or {}
    text = text_of(p)
    employer = (p.get("employer") or "").lower()
    loc = ((p.get("location") or "") + " " + (sc.get("work_city") or "")).lower()
    reasons, excl = [], []
    s = 0

    for e in prefs.get("employers", {}).get("excluded", []):
        if e.lower() in employer:
            excl.append(f"employer excluded: {e}")
    for l in prefs.get("locations", {}).get("excluded", []):
        if l.lower() in loc:
            excl.append(f"location excluded: {l}")
    for sp in prefs.get("specialties", {}).get("excluded", []):
        if has(sp, text):
            excl.append(f"specialty excluded: {sp}")
    if sc.get("restricted_to_internal"):
        excl.append("posting restricted to internal applicants")
    elig = prefs.get("eligibility", {})
    yrs = sc.get("experience_years_required")
    if isinstance(yrs, (int, float)) and yrs > elig.get("years_experience", 0) and elig.get(
            "hard_exclude_over_experience", True):
        excl.append(f"requires {yrs:g} yr experience: \"{(sc.get('experience_quote') or '')[:90]}\"")
    if excl:
        return None, excl

    ranked = prefs.get("specialties", {}).get("ranked", [])
    top = w.get("specialty_first", 40)
    for i, sp in enumerate(ranked):
        if has(sp, text):
            pts = max(top - i * (top // max(len(ranked), 1)), 5)
            s += pts
            reasons.append(f"specialty {sp} +{pts}")
            break
    for l in prefs.get("locations", {}).get("preferred", []):
        if l.lower() in loc:
            s += w.get("location_preferred", 20)
            reasons.append(f"location {l} +{w.get('location_preferred', 20)}")
            break
    else:
        for l in prefs.get("locations", {}).get("acceptable", []):
            if l.lower() in loc:
                s += w.get("location_acceptable", 5)
                reasons.append(f"location ok +{w.get('location_acceptable', 5)}")
                break
    for e in prefs.get("employers", {}).get("preferred", []):
        if e.lower() in employer:
            s += w.get("employer_preferred", 15)
            reasons.append(f"employer {e} +{w.get('employer_preferred', 15)}")
            break
    if sc.get("new_grad_ok") is True:
        s += w.get("new_grad_ok", 25)
        reasons.append(f"posting says new grad ok +{w.get('new_grad_ok', 25)}")
    setting = prefs.get("setting", {}).get("prefer", "any")
    if setting != "any" and has(setting, text):
        s += w.get("setting", 10)
        reasons.append(f"{setting} +{w.get('setting', 10)}")
    for sch in prefs.get("schedule", {}).get("prefer", []):
        if has(sch, text):
            s += w.get("schedule", 5)
            reasons.append(f"{sch} +{w.get('schedule', 5)}")
    for sch in prefs.get("schedule", {}).get("avoid", []):
        if has(sch, text):
            s -= w.get("schedule", 5)
            reasons.append(f"{sch} -{w.get('schedule', 5)}")
    rt = prefs.get("role_type", {})
    if p.get("kind") == "residency_window" or has("residency", text):
        s += rt.get("residency_weight", 20)
        reasons.append(f"residency +{rt.get('residency_weight', 20)}")
        if p.get("window_state") == "open":
            s += 40
            reasons.append("WINDOW OPEN +40")
    else:
        s += rt.get("direct_hire_weight", 10)
    if p.get("tracked"):
        s += w.get("tracked_verified", 10)
        reasons.append(f"verified entry +{w.get('tracked_verified', 10)}")
    ca = p.get("close_at")
    if ca:
        try:
            days = (datetime.date.fromisoformat(ca[:10]) - today).days
            if 0 <= days <= 14:
                s += w.get("closing_soon", 20)
                reasons.append(f"closes in {days}d +{w.get('closing_soon', 20)}")
            elif days < 0:
                return None, [f"close date passed ({ca[:10]})"]
        except ValueError:
            pass
    fa = p.get("found_at") or p.get("first_seen_at")
    if fa:
        try:
            age = (today - datetime.date.fromisoformat(fa[:10])).days
            if age <= 7:
                s += w.get("recency", 10)
                reasons.append(f"found {age}d ago +{w.get('recency', 10)}")
        except ValueError:
            pass
    if p.get("bh_tag") and w.get("bh_tag", 0):
        s += w["bh_tag"]
        reasons.append(f"behavioral health +{w['bh_tag']}")
    return s, reasons


# --- Sibling labels ---------------------------------------------------------------------
# A sibling is a posting at the same employer and unit as an application that already went
# out, where only the shift or hours differ. Those are the short sends: the letter and the
# portal profile exist. A different job on a portal where an account already exists is a
# shorter form but still a new letter. This only LABELS a row; the order stays the score.
SENT = ("submitted", "interview", "offer", "rejected")
_SCHEDULE_WORDS = set("""
full time part per diem on call noc night nights day days evening evenings pm am
shift shifts dayshift nightshift variable regular rotating hour hours hr hrs fte ft pt prn
pool weekend weekends limited term temporary benefited onsite
the and of a an at in for to req job posted ca
""".split())
_GENERIC_TITLE = {"registered", "nurse", "staff", "clinical", "ii", "iii", "iv"}
_PLACE_WORDS = {"united", "states", "america", "usa", "california"}
# Hosts where one login covers every requisition, so a second application starts from a
# stored profile. Value: how many leading path segments name the tenant.
_ACCOUNT_HOSTS = (
    ("ultipro.com", 1), ("myworkdayjobs.com", 0), ("icims.com", 0),
    ("smartrecruiters.com", 1), ("avature.net", 0), ("usajobs.gov", 0),
    ("governmentjobs.com", 0), ("calcareers.ca.gov", 0), ("oraclecloud.com", 0),
)


@functools.lru_cache(maxsize=None)
def _core_tokens(text):
    """Lowercase word set with schedule words, hours, FTE, requisition ids and dates
    removed. Two and three digit numbers stay: some employers write the unit into the
    title as a number, and 204 against 205 is then the whole difference between two sites."""
    text = re.sub(r"\brn\b", " registered nurse ", (text or "").lower())
    text = re.sub(r"\b\d{1,2}/\d{1,2}(/\d{2,4})?\b", " ", text)              # 'posted 2/14'
    text = re.sub(r"\d*\.\d+", " ", text)                                    # 0.9 FTE, .90
    text = re.sub(r"\b\d{1,2}\s*-?\s*(?:hrs?|hours?|am|pm|a|p)\b", " ", text)  # 12-hour, 8am, 7a-7p
    text = re.sub(r"\b\w*\d{4,}\w*\b", " ", text)                            # RN0012345, JR0001234
    out = set()
    for w in re.findall(r"[a-z0-9]+", text):
        if w.isdigit():
            if 2 <= len(w) <= 3:
                out.add(w)
            continue
        if len(w) > 1 and w not in _SCHEDULE_WORDS:
            out.add(w)
    return frozenset(out)


def _overlap(a, b):
    return len(a & b) / min(len(a), len(b)) if a and b else 0.0


def portal_key(url):
    """Tenant-level key for account-based portals, else None."""
    m = re.match(r"https?://([^/:?#]+)(?::\d+)?(/[^?#]*)?", url or "")
    if not m:
        return None
    host, path = m.group(1).lower().removeprefix("www."), (m.group(2) or "")
    for suffix, nseg in _ACCOUNT_HOSTS:
        if host == suffix or host.endswith("." + suffix):
            segs = [x for x in path.split("/") if x][:nseg]
            return "/".join([host] + [x.lower() for x in segs])
    return None


def _same_place(a, b):
    """False only when both postings name a city and the cities differ."""
    for get in (lambda p: (p.get("screen") or {}).get("work_city"),
                lambda p: (p.get("location") or "").split(",")[0]):
        x, y = (get(a) or "").strip().lower(), (get(b) or "").strip().lower()
        if x and y:
            return x == y
    return True


def _unit_tokens(p):
    """What a title says beyond 'Registered Nurse' and the posting's own city: the unit,
    the specialty, the role."""
    place = _core_tokens(p.get("location")) | _core_tokens((p.get("screen") or {}).get("work_city"))
    return _core_tokens(p.get("title")) - place - _PLACE_WORDS - _GENERIC_TITLE


def is_sibling(p, sent):
    """Same employer, same unit, same role; only the schedule differs."""
    if _overlap(_core_tokens(p.get("employer")), _core_tokens(sent.get("employer"))) < 0.8:
        return False
    if not _same_place(p, sent):
        return False
    a, b = _unit_tokens(p), _unit_tokens(sent)
    if not a & b:
        return False           # 'Registered Nurse' alone proves nothing
    na, nb = {w for w in a if w.isdigit()}, {w for w in b if w.isdigit()}
    if na and nb and not (na & nb):
        return False           # both name a unit number and they differ
    # Nearly all of the shorter title is in the longer one, and the longer one does not
    # add much: 'ICU' against 'ICU Cardiac Surgery' is another unit, not another shift.
    return _overlap(a, b) >= 0.8 and len(a & b) / max(len(a), len(b)) >= 0.6


def label_siblings(rows, postings):
    """Set or clear `sibling_of` / `same_portal_as` (a posting id) and `label` (the text
    shown) on every ranked row. `postings` is tracker.json's id -> posting map. A rejected
    sibling is labeled too: being turned down for the same unit is worth seeing before
    building. Nothing is written to tracker.json and no row moves."""
    sent = sorted((s for s in postings.values() if s.get("status") in SENT),
                  key=lambda s: str(s.get("status_at") or ""), reverse=True)
    for r in rows:
        p = r["p"]
        for field in ("sibling_of", "same_portal_as", "label"):
            r.pop(field, None)
        sib = next((s for s in sent if is_sibling(p, s)), None)
        if sib:
            r["sibling_of"], r["label"] = sib.get("id"), sibling_note(sib)
            continue
        key = portal_key(p.get("url"))
        portal = next((s for s in sent if portal_key(s.get("url")) == key), None) if key else None
        if portal:
            r["same_portal_as"] = portal.get("id")
            r["label"] = f"portal account exists ({(portal.get('employer') or '')[:24]})"


def sibling_note(sent):
    """The label for a sibling of the already-sent posting `sent`."""
    title, when = (sent.get("title") or "")[:40], str(sent.get("status_at") or "")[:10]
    status = sent.get("status")
    if status == "rejected":
        return f"sibling of {title}, REJECTED there {when}"
    if status == "submitted":
        return f"sibling of {title}, sent {when}: short send"
    return f"sibling of {title}, {status} since {when}: short send"


def render(rows, working, excluded, done, gone, prefs, today):
    def esc(x):
        return html.escape(str(x if x is not None else ""))

    def tr(r, show_score=True):
        p = r["p"]
        sc = p.get("screen") or {}
        new = p.get("first_seen_at") and (today - datetime.date.fromisoformat(p["first_seen_at"][:10])).days <= 2
        badge = '<span class="new">NEW</span> ' if new else ""
        label = f"<b>{esc(r['label'])}</b>; " if r.get("label") else ""
        return (f"<tr><td>{r.get('rank', '')}</td><td>{r.get('score', '') if show_score else ''}</td>"
                f"<td>{esc(p.get('employer'))}</td><td>{badge}<a href=\"{esc(p.get('url'))}\">{esc(p.get('title'))}</a></td>"
                f"<td>{esc(p.get('location') or sc.get('work_city'))}</td>"
                f"<td>{'' if sc.get('new_grad_ok') is None else ('yes' if sc.get('new_grad_ok') else 'no')}</td>"
                f"<td>{esc((p.get('close_at') or '')[:10])}</td><td>{esc(p.get('status'))}</td>"
                f"<td class=q>{label}{esc('; '.join(r.get('reasons', [])))}</td><td class=id>{esc(p.get('id'))}</td></tr>")

    head = ("<tr><th>#</th><th>Score</th><th>Employer</th><th>Title</th><th>Location</th><th>New grad</th>"
            "<th>Closes</th><th>Status</th><th>Why</th><th>id</th></tr>")
    wk = "".join(f"<li><b>NOT SENT {r['age']}d</b>: {esc(r['p'].get('employer'))}, {esc(r['p'].get('title'))} "
                 f"<code>{esc(r['p']['id'])}</code></li>" for r in working)
    return f"""<!doctype html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1"><title>Ranked RN openings</title>
<style>:root{{--bg:#fafaf8;--fg:#1a1a1a;--muted:#6b6b6b;--line:#e3e1dc;--accent:#0a6e5c;--warn:#9a5b00;--warnbg:#fff4e0;--newbg:#e3f3ee}}
@media (prefers-color-scheme: dark){{:root{{--bg:#141416;--fg:#e8e6e3;--muted:#9a9893;--line:#33333a;--accent:#4fc3ab;--warn:#e0a84a;--warnbg:#2a2214;--newbg:#1b2f29}}}}
body{{margin:0;padding:0 16px 40px;background:var(--bg);color:var(--fg);font:15px/1.5 -apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,sans-serif}}
h1{{font-size:1.4rem;margin:24px 0 4px}} h2{{font-size:1.1rem;margin:28px 0 8px}} p{{color:var(--muted);margin:0 0 12px}} a{{color:var(--accent)}}
.w{{overflow-x:auto}} table{{border-collapse:collapse;width:100%;font-size:.88rem}} th,td{{text-align:left;vertical-align:top;padding:6px 8px;border-bottom:1px solid var(--line)}}
th{{color:var(--muted);position:sticky;top:0;background:var(--bg)}} td.q{{color:var(--muted);max-width:300px}} td.id{{color:var(--muted);font:.78rem ui-monospace,Menlo,monospace}}
.new{{background:var(--newbg);color:var(--accent);font-size:.75rem;padding:1px 5px;border-radius:4px}}
.warn{{background:var(--warnbg);border:1px solid var(--warn);border-radius:8px;padding:10px 14px;margin:12px 0}} .warn ul{{margin:4px 0 0;padding-left:18px}}
input{{width:100%;max-width:420px;padding:7px 10px;margin:0 0 12px;border:1px solid var(--line);border-radius:6px;background:var(--bg);color:var(--fg)}}
details{{margin:10px 0}} summary{{cursor:pointer;color:var(--accent)}} code{{font:.85rem ui-monospace,Menlo,monospace}}</style></head>
<body><h1>Ranked RN openings</h1>
<p>{len(rows)} ranked, {len(excluded)} excluded by your preferences, {len(done)} done, {len(gone)} left the feed. Ranked {today.isoformat()}.
To work one: <code>/start-next-app &lt;id&gt;</code>. To change the ranking: <code>/set-preferences</code>.</p>
{f'<div class="warn"><b>Packages built or in progress and not submitted.</b> A posting goes stale after a couple of days.<ul>{wk}</ul></div>' if working else ''}
<input id="f" placeholder="filter: employer, title, city, reason" oninput="flt()">
<div class="w"><table><thead>{head}</thead><tbody id="b">{''.join(tr(r) for r in rows)}</tbody></table></div>
<details><summary>Excluded by preferences ({len(excluded)})</summary><div class="w"><table><thead>{head}</thead><tbody>{''.join(tr(r, False) for r in excluded)}</tbody></table></div></details>
<details><summary>Done ({len(done)})</summary><div class="w"><table><thead>{head}</thead><tbody>{''.join(tr(r, False) for r in done)}</tbody></table></div></details>
<details><summary>Left the feed ({len(gone)})</summary><div class="w"><table><thead>{head}</thead><tbody>{''.join(tr(r, False) for r in gone)}</tbody></table></div></details>
<script>function flt(){{var q=document.getElementById('f').value.toLowerCase();for(const r of document.querySelectorAll('#b tr'))r.style.display=r.innerText.toLowerCase().includes(q)?'':'none'}}</script>
</body></html>"""


def main():
    top_n = 15
    if "--top" in sys.argv:
        top_n = int(sys.argv[sys.argv.index("--top") + 1])
    if not os.path.exists(PREFS):
        print("rank: preferences.toml missing; run /set-preferences (or copy preferences.example.toml)")
        return 2
    prefs = tomllib.load(open(PREFS, "rb"))
    t = json.load(open(TRACKER))
    today = datetime.date.today()
    rows, working, excluded, done, gone = [], [], [], [], []
    for pid, p in t["postings"].items():
        st = p.get("status", "new")
        if not p.get("in_feed", True) and st in ("new", "skip"):
            gone.append({"p": p, "reasons": ["no longer in the feed"]})
            continue
        if st in DONE:
            done.append({"p": p, "reasons": [st]})
            continue
        s, reasons = score(p, prefs, today)
        if s is None:
            excluded.append({"p": p, "reasons": reasons})
            continue
        row = {"p": p, "score": s, "reasons": reasons}
        rows.append(row)
        if st == "working":
            age = (today - datetime.date.fromisoformat(p.get("status_at", today.isoformat())[:10])).days
            working.append({"p": p, "age": age})
    rows.sort(key=lambda r: (-r["score"], r["p"].get("employer") or ""))
    for i, r in enumerate(rows, 1):
        r["rank"] = i
    working.sort(key=lambda r: -r["age"])
    label_siblings(rows, t["postings"])
    open(OUT_HTML, "w").write(render(rows, working, excluded, done, gone, prefs, today))
    json.dump({"ranked_at": today.isoformat(),
               "ranked": [{"rank": r["rank"], "score": r["score"], "id": r["p"]["id"], "employer": r["p"].get("employer"),
                           "title": r["p"].get("title"), "url": r["p"].get("url"), "status": r["p"].get("status"),
                           "reasons": r["reasons"],
                           **{k: r[k] for k in ("label", "sibling_of", "same_portal_as") if r.get(k)}}
                          for r in rows],
               "working_not_sent": [{"id": r["p"]["id"], "age_days": r["age"], "title": r["p"].get("title")} for r in working],
               "excluded": [{"id": r["p"]["id"], "reasons": r["reasons"]} for r in excluded]},
              open(OUT_JSON, "w"), indent=1)
    print(f"rank: {len(rows)} ranked, {len(excluded)} excluded, {len(done)} done, {len(gone)} gone -> ranked.html")
    for r in working:
        print(f"  NOT SENT {r['age']}d: {r['p'].get('employer')} | {r['p'].get('title')} | {r['p']['id']}")
    for r in rows[:top_n]:
        print(f"  {r['rank']:>3}. {r['score']:>3}  {r['p'].get('employer')} | {r['p'].get('title')} | {r['p']['id']}"
              + (f" | {r['label']}" if r.get("label") else ""))
    return 0


if __name__ == "__main__":
    sys.exit(main())
