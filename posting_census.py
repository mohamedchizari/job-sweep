#!/usr/bin/env python3
"""posting_census.py - second pass: read each posting the sweep kept, and quote what it says.

job_scanner.py gives one verdict per posting. This pass fetches the text of each posting in a
roles CSV, saves it, and reports per posting:

  clearance   the line that states it, and how it reads: ACTIVE_REQUIRED (it asks for one already
              held), ACTIVE_PUBLIC_TRUST, PUBLIC_TRUST, NONE_FOUND, or UNREAD when the posting
              could not be fetched
  band        the pay line with the highest top, as printed. This is a quotation, not the sweep's
              band rule (which takes the home-labelled range or the lowest top)
  citizenship whether the text mentions U.S. citizenship
  years       the lines that state years of experience

It reads only what a script can read, and it does not judge fit: its output is a set of quoted
lines for a person to check. Read-only: public endpoints, GET only; it contacts no one.

  python3 posting_census.py roles.csv --out census.csv --save-dir postings
  python3 posting_census.py roles.csv --only name:REQ123,name:REQ456 --show
"""
import argparse, csv, datetime, hashlib, html, json, os, re, sys, time

import sweep_settings

UA = dict(sweep_settings.HEADERS)
PAUSE = 0.4


def strip(h):
    """HTML to text that keeps line breaks, because the readers below work line by line."""
    h = html.unescape(h or '')
    h = re.sub(r'(?i)<(br|/p|/li|/h\d|/div|/tr)\s*/?>', '\n', h); h = re.sub(r'(?i)<li[^>]*>', '- ', h)
    h = re.sub(r'<[^>]+>', '', h); h = html.unescape(h)
    return re.sub(r'\n\s*\n+', '\n', re.sub(r'[ \t\xa0]+', ' ', h)).strip()


def jsonld(page):
    """The first schema.org JobPosting in the page's application/ld+json blocks, or None."""
    for m in re.finditer(r'<script[^>]+application/ld\+json[^>]*>(.*?)</script>', page, re.S):
        try: d = json.loads(m.group(1).strip())
        except Exception: continue
        st = [d]
        while st:
            x = st.pop()
            if isinstance(x, list): st += x
            elif isinstance(x, dict):
                t = x.get('@type'); t = t if isinstance(t, list) else [t]
                if 'JobPosting' in t: return x
                st += list(x.get('@graph', []) if isinstance(x.get('@graph'), list) else [])
    return None


def get(url, sess):
    """(status, text) for one posting. The ATS's own JSON where the URL shows which ATS it is
    (Greenhouse, Workday, Lever, Ashby); otherwise the page's JSON-LD; otherwise the page text."""
    m = re.search(r'greenhouse\.io/([A-Za-z0-9_]+)/jobs/(\d+)', url)
    if m:
        r = sess.get(f'https://boards-api.greenhouse.io/v1/boards/{m.group(1)}/jobs/{m.group(2)}?pay_transparency=true', headers=UA, timeout=30)
        if r.status_code != 200: return r.status_code, ''
        d = r.json(); pay = '; '.join(f"{(p.get('title') or '').strip().rstrip(':')}: ${(p.get('min_cents') or 0)//100:,} - ${(p.get('max_cents') or 0)//100:,}" for p in d.get('pay_input_ranges') or [])
        return 200, f"TITLE: {d.get('title')}\nLOCATION: {(d.get('location') or {}).get('name')}\nUPDATED: {d.get('updated_at')}\nPAY: {pay}\n" + strip(d.get('content'))
    m = re.match(r'https://([a-z0-9-]+)\.(wd\d+)\.myworkdayjobs\.com/([^/]+)(/job/.*)', url)
    if m:
        r = sess.get(f'https://{m.group(1)}.{m.group(2)}.myworkdayjobs.com/wday/cxs/{m.group(1)}/{m.group(3)}{m.group(4)}', headers={**UA, 'Accept': 'application/json'}, timeout=30)
        if r.status_code != 200: return r.status_code, ''
        j = r.json().get('jobPostingInfo', {})
        return 200, f"TITLE: {j.get('title')}\nLOCATION: {j.get('location')} | additional: {j.get('additionalLocations')}\nPOSTED: {j.get('postedOn')} start {j.get('startDate')} | {j.get('timeType')} | remote: {j.get('remoteType')}\n" + strip(j.get('jobDescription'))
    m = re.search(r'jobs\.lever\.co/([a-z0-9-]+)/([0-9a-f-]+)', url)
    if m:
        r = sess.get(f'https://api.lever.co/v0/postings/{m.group(1)}/{m.group(2)}', headers=UA, timeout=30)
        if r.status_code != 200: return r.status_code, ''
        d = r.json(); body = d.get('descriptionPlain', '') + '\n' + '\n'.join((l.get('text', '') + '\n' + strip(l.get('content', ''))) for l in d.get('lists', [])) + '\n' + (d.get('additionalPlain') or '')
        return 200, f"TITLE: {d.get('text')}\nLOCATION: {d.get('categories')}\nPAY: {d.get('salaryRange')} {d.get('salaryDescriptionPlain','')}\n" + body
    m = re.search(r'jobs\.ashbyhq\.com/([A-Za-z0-9-]+)/([0-9a-f-]+)', url)
    if m:
        r = sess.get(f'https://api.ashbyhq.com/posting-api/job-board/{m.group(1)}?includeCompensation=true', headers=UA, timeout=30)
        if r.status_code != 200: return r.status_code, ''
        for d in r.json().get('jobs', []):
            if d.get('id') == m.group(2):
                return 200, f"TITLE: {d.get('title')}\nLOCATION: {d.get('location')} remote={d.get('isRemote')} listed={d.get('isListed')}\nPAY: {(d.get('compensation') or {}).get('compensationTierSummary')}\nPUBLISHED: {d.get('publishedAt')}\n" + strip(d.get('descriptionHtml'))
        return 'ABSENT FROM LIST', ''   # read from the board list: a job that is not in it is not open on the board
    r = sess.get(url, headers=UA, timeout=30)
    if r.status_code != 200: return r.status_code, ''
    jp = jsonld(r.text)
    if jp: return 200, f"TITLE: {jp.get('title')}\nPOSTED: {jp.get('datePosted')} validThrough {jp.get('validThrough')}\nPAY: {json.dumps(jp.get('baseSalary'))}\n" + strip(jp.get('description'))
    return 200, strip(re.sub(r'(?is)<(script|style)[^>]*>.*?</\1>', '', r.text))


# ---------------------------------------------------------------- the clearance line
# A level, as a posting names it. "TS" counts only in capitals and as a word of its own (in lower
# case it is the end of "requirements"); the other words count in any case.
LEVEL = r"(?:TS/SCI|\bTS\b|(?i:top[- ]secret|secret|q clearance|polygraph|ci poly|fs poly))"
NAMES_LEVEL = re.compile(LEVEL)
SOFT = re.compile(r"(obtain|eligib|preferred|desired|a plus|ability to|able to|willing|sponsor|interim|nice to have|may be required|or higher is a plus)", re.I)
WISH = re.compile(r"(preferred|desired|a plus|nice to have)", re.I)   # a wish, wherever it sits in the line
HARD = re.compile(r"(active|current|currently|must (have|hold|possess)|required|\brequires\b|maintain|at the time of application|to be considered)", re.I)
# "No clearance is required", "a Secret clearance is not required", "does not require a clearance".
NOT_NEEDED = re.compile(r"\bno\b[^.;]{0,40}\bclearance\b[^.;]{0,30}\b(required|needed|necessary)"
                        r"|clearance[^.;]{0,30}\b(is |are )?not\s+(required|needed|necessary)|does not require|not needed", re.I)
# A labelled field: "Clearance required: Top Secret", "Security clearance level: None". The value may sit on the
# next line, and some postings print the label with no colon at all.
FIELD = re.compile(r"^[-·•*\s]*((?:[A-Za-z][A-Za-z /&()-]{0,60}?)?\bclearance\b[A-Za-z /&()-]{0,60}?)\s*(:\s*(.*))?$", re.I)
NO_VALUE = re.compile(r"(none|no\b|n/a|not applicable|not required)", re.I)
TRUST = re.compile(r"public trust|naci|suitab", re.I)
YES_VALUE = re.compile(r"(yes|active|current)\b", re.I)
TITLE = re.compile(r"(?:TS/SCI|\bTS\b|(?i:\bpoly(?:graph)?\b|top secret|secret clearance required|security clearance requi|\bcleared\b))")
PROCESS = re.compile(r"subject to[^.]{0,40}investigation", re.I)        # a sentence about the vetting process
MUST = re.compile(r"(?i:must (?:have|hold|possess))([^.]{0,40})" + LEVEL)
BARE = re.compile(r"^[-·•*\s]*(?i:an? )?(?i:active |current )?" + LEVEL + r"(?i:[A-Za-z/ ,()-]{0,60}clearance[^.]{0,40})$")
IS_REQUIRED = re.compile(LEVEL + r"(?i:[^.;]{0,30}clearance[^.;]{0,20}is required)")


def clearance(text, title):
    """(verdict, the line it rests on). Reads, in order: the title; a labelled field
    ("Clearance required: ..."); any line that names a clearance level; public trust."""
    if TITLE.search(title) and not re.search(r"sponsorship|desired|eligible|obtain", title, re.I):
        return 'ACTIVE_REQUIRED', 'title: ' + title
    lines = [l.strip() for l in text.split('\n')]
    for i, l in enumerate(lines):
        m = FIELD.match(l)
        if not m or SOFT.search(m.group(1)):            # a field about what can be obtained is not a requirement
            continue
        colon, v, quote = bool(m.group(2)), (m.group(3) or '').strip(), l
        if not colon and NAMES_LEVEL.search(l):         # "Secret clearance required" is a sentence, not a label
            continue
        if not v:                                       # the value is on a following line, if that line looks like a value
            v = next((x for x in lines[i+1:i+3] if x), '')
            if v.endswith(':') or not (NAMES_LEVEL.search(v) or TRUST.search(v) or NO_VALUE.match(v) or YES_VALUE.match(v)):
                v = ''
            quote = l + ' ' + v
        if not v or NO_VALUE.match(v) or NOT_NEEDED.search(v):
            continue
        if TRUST.search(v): return ('ACTIVE_PUBLIC_TRUST' if re.search(r'\bactive\b', v, re.I) else 'PUBLIC_TRUST'), quote[:200]
        if SOFT.search(v) and not re.search(r"\bactive\b", v, re.I): continue
        return 'ACTIVE_REQUIRED', quote[:200]
    for l in lines:
        if len(l) > 400 or not NAMES_LEVEL.search(l) or not re.search(r"clearance|poly|TS/SCI", l, re.I): continue
        if NOT_NEEDED.search(l): continue
        if PROCESS.search(l):
            if IS_REQUIRED.search(l): return 'ACTIVE_REQUIRED', l[:200]
            continue
        if re.search(r"public trust[^.]{0,60}\bor\b|\bor\b[^.]{0,60}public trust", l, re.I):
            continue                                    # public trust is offered as an alternative: read below
        m = MUST.search(l)                              # "must have a TS/SCI ...", but not "must have the ability to obtain ..."
        if m and not re.search(r"abilit|able to|eligib|obtain", m.group(1), re.I): return 'ACTIVE_REQUIRED', l[:200]
        soft, held = SOFT.search(l), re.search(r"\b(active|current)\b", l, re.I)
        if soft and (not held or soft.start() < held.start()): continue   # "ability to obtain and maintain an active ..." is about obtaining
        if WISH.search(l) and not re.search(r"required|must", l, re.I): continue   # "an active clearance is preferred"
        if BARE.match(l) or HARD.search(l): return 'ACTIVE_REQUIRED', l[:200]
    for l in lines:
        if re.search(r"\bactive\b[^.]{0,40}public trust", l, re.I) and len(l) < 300: return 'ACTIVE_PUBLIC_TRUST', l[:160]
        if re.search(r"public trust", l, re.I) and len(l) < 300: return 'PUBLIC_TRUST', l[:160]
    return 'NONE_FOUND', ''


RANGE = re.compile(r"\$\s?(\d{2,3},\d{3})(?:\.\d\d)?\s*(?:-|\u2013|\u2014|to|and)\s*\$\s?(\d{2,3},\d{3})(?:\.\d\d)?")


def band(text):
    """(low, high, the line) for the pay range with the highest top, or None. A range is two dollar
    figures joined by a dash, "to" or "and", each between $40,000 and $900,000."""
    best = None
    for l in text.split('\n'):
        if '$' not in l or len(l) > 700: continue
        for a, b in RANGE.findall(l):
            lo, hi = sorted((int(a.replace(',', '')), int(b.replace(',', ''))))
            if 40000 <= lo and hi <= 900000 and (best is None or hi > best[1]): best = (lo, hi, l.strip()[:140])
    return best


# ---------------------------------------------------------------- the run
KEY = re.compile(r'(clearance|TS/SCI|top secret|\bsecret\b|public trust|polygraph|citizen|suitability|\d+\+? ?(?:or more )?years|bachelor|master|ph\.?d|degree|\$ ?\d{2,3},\d{3}|salary|remote|hybrid|onsite|on-site|travel)', re.I)
COLUMNS = ['employer', 'req', 'title', 'location', 'http', 'chars', 'clearance_verdict', 'clearance_line',
           'band_low', 'band_high', 'band_line', 'citizenship', 'years_lines', 'url']


def safe(s):
    return re.sub(r'[^A-Za-z0-9-]', '', s or '')


def saved_name(r):
    """The file a posting's text is saved under: employer and req for the eye, a hash of the URL
    so that two postings never share a file."""
    h = hashlib.sha1((r.get('url') or '').encode('utf-8')).hexdigest()[:10]
    return f"{safe(r.get('employer'))}_{safe(r.get('req'))}_{h}.txt"


def census(rows, sess, save_dir, out_path, show=False, today=None, pause=PAUSE):
    """Fetch (or re-read from save_dir), classify and write one CSV line per row. Returns the lines."""
    today = today or datetime.date.today().isoformat()
    os.makedirs(save_dir, exist_ok=True)
    done = []
    with open(out_path, 'w', newline='', encoding='utf-8') as fh:
        out = csv.writer(fh); out.writerow(COLUMNS)
        for n, r in enumerate(rows, 1):
            fn = os.path.join(save_dir, saved_name(r))
            code, text = 'saved', ''
            if os.path.exists(fn):
                with open(fn, encoding='utf-8') as f: text = f.read().split('\n', 2)[-1]   # without the URL and FETCHED lines
            else:
                try: code, text = get(r['url'], sess)
                except Exception as e: code, text = 'ERR ' + e.__class__.__name__, ''
                if text:
                    text = text.strip()
                    with open(fn, 'w', encoding='utf-8') as f: f.write(f"URL: {r['url']}\nFETCHED: {today}\n{text}")
                time.sleep(pause)
            v, line = clearance(text, r.get('title', '')) if text else ('UNREAD', '')
            b = band(text) if text else None
            if not b and str(r.get('band_high', '')).isdigit(): b = (int(r.get('band_low') or 0), int(r['band_high']), 'from the sweep row')
            cit = 'Y' if re.search(r"U\.?S\.? citizen", text, re.I) else ''
            yrs = ' / '.join(l.strip()[:110] for l in text.split('\n') if re.search(r"\d+\+? ?(or more )?years", l) and len(l) < 300)[:330]
            row = [r.get('employer', ''), r.get('req', ''), r.get('title', ''), r.get('location', ''), code, len(text), v, line,
                   b[0] if b else '', b[1] if b else '', b[2] if b else '', cit, yrs, r.get('url', '')]
            out.writerow(row); done.append(row)
            if show:
                print(f"\n=== {r.get('employer')}:{r.get('req')} | {r.get('title')} | http {code} | {len(text)} chars | {v}")
                seen = 0
                for ln in text.split('\n'):
                    if ln.startswith(('TITLE', 'LOCATION', 'PAY', 'POSTED', 'UPDATED')) or (KEY.search(ln) and len(ln) < 420):
                        print('  ' + ln.strip()[:300]); seen += 1
                        if seen > 16: break
            elif n % 25 == 0:
                print(n, 'of', len(rows), flush=True)
    return done


def main():
    ap = argparse.ArgumentParser(description="Read each posting in a roles CSV and quote its clearance, pay and years lines.")
    ap.add_argument("roles", help="a CSV written by job_scanner.py (needs the columns employer, req, title, url)")
    ap.add_argument("--out", default="census.csv")
    ap.add_argument("--save-dir", default="postings",
                    help="where each posting's text is saved; a saved posting is not fetched again (its http column then reads 'saved')")
    ap.add_argument("--only", help="comma-separated employer:req pairs")
    ap.add_argument("--skip-employers", help="comma-separated employer names to leave out")
    ap.add_argument("--show", action="store_true", help="print each posting's key lines")
    a = ap.parse_args()
    try:
        import requests
    except ImportError:
        sys.exit("pip install requests")
    with open(a.roles, newline='', encoding='utf-8') as fh:
        rows = list(csv.DictReader(fh))
    missing = [c for c in ('employer', 'req', 'title', 'url') if rows and c not in rows[0]]
    if missing:
        sys.exit(f"{a.roles}: missing column(s) {', '.join(missing)}")
    if a.only:
        want = set(x for x in a.only.split(',') if x)
        rows = [r for r in rows if f"{r['employer']}:{r['req']}" in want]
    if a.skip_employers:
        skip = set(x for x in a.skip_employers.split(',') if x)
        rows = [r for r in rows if r['employer'] not in skip]
    done = census(rows, requests.Session(), a.save_dir, a.out, show=a.show)
    counts = {}
    for row in done: counts[row[6]] = counts.get(row[6], 0) + 1
    print('DONE', len(done), 'postings:', ', '.join(f"{k} {v}" for k, v in sorted(counts.items())) or 'none')
    print('written:', a.out)


if __name__ == '__main__':
    main()
