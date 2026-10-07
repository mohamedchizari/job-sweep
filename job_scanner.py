#!/usr/bin/env python3
"""
job_scanner.py - enumerate employers' open roles by applicant tracking system (ATS), not by search.

Each employer is read from the list endpoint of its own ATS, and each row is then gated on what
the posting itself publishes: the pay band, the location and the clearance wording.

  Greenhouse  the list call has no salary; /jobs/{id}?pay_transparency=true returns it per job.
  Lever       `skip` + `limit` page the list. An unpaged call truncates it.
  Ashby       ?includeCompensation=true; the band is read from the structured components.
  Workday     POST only, at most 20 rows a page (a larger limit is refused with HTTP 400); the
              description is on the detail endpoint.
  iCIMS       {sub}.icims.com/sitemap.xml is public, and detail pages carry schema.org
              JobPosting JSON-LD.
  Eightfold   /api/pcsx/search, with the employer's registered domain; the description is on a
              detail endpoint.
  Phenom      the site's own search call, POST /widgets.
  Avature     HTML only, but enumerable: /careers/SearchJobs/?jobOffset=N
  JSON-LD     one extractor for any site that emits schema.org JobPosting.
  Liveness    the LIST endpoint is truth. A detail page that still renders is NOT evidence a
              requisition is open.

Settings (pay floor, home places, title lane, clearance choice, employers) are read from a JSON
file: see sweep_settings.py and config.example.json. Read-only: public endpoints, GET and the two
search POSTs the sites' own pages make. It never applies, submits or contacts anyone.

  pip install requests
  python3 job_scanner.py --config config.json --only name1,name2
  python3 job_scanner.py --config config.json --candidates --lane --cap 0
  python3 job_scanner.py --discover careers.example.com
"""

import argparse, csv, html, json, re, sys, time
from urllib.parse import unquote
from datetime import datetime, timezone, date

try:
    import requests
except ImportError:
    sys.exit("pip install requests")

import sweep_settings

UA = dict(sweep_settings.HEADERS)
TIMEOUT = 25
PAUSE = 0.4

# ---------------------------------------------------------------- SETTINGS
# The pay floor, the home places, the title lane, the clearance choice and the employers come from
# the settings file (sweep_settings.py). What stays in this file is how each ATS is read.

S = None   # the loaded sweep_settings.Settings; set by configure()

def configure(settings):
    """Install the settings every gate and adapter reads. main() calls it; the tests call it directly."""
    global S
    S = settings
    return settings

# ---------------------------------------------------------------- GATES


# Two readings of a posting's clearance wording. ACTIVE: it asks for a clearance already held.
# OBTAIN: it speaks of obtaining one, or of public trust, suitability or citizenship.
CLR_ACTIVE = re.compile(r"\b(active|current(ly)?\s+(hold|possess)|must\s+(currently\s+)?"
                        r"(hold|possess)|existing)\b[^.]{0,90}?\b(clearance|ts/sci|"
                        r"top secret|secret|polygraph)\b"
                        r"|\b(ts/sci|top secret)\b[^.]{0,50}?\bpolygraph\b", re.I)
CLR_OBTAIN = re.compile(r"\b(ability to obtain|able to obtain|eligib\w+ to obtain|"
                        r"obtain and maintain|public trust|suitability|clearance[^.]{0,20}"
                        r"preferred|u\.?s\.?\s+citizen)", re.I)

MONEY = re.compile(r"([^.$\n]{0,60}?)\$\s?([\d,]{5,12})(?:\.\d\d)?\s*(?:-|–|—|to)\s*"
                   r"\$?\s?([\d,]{5,12})(?:\.\d\d)?", re.I)

def strip_html(s):
    if not s: return ""
    # Greenhouse content=true arrives entity-escaped (&lt;p&gt;, &mdash;): unescape BEFORE stripping, or the
    # tags survive as text and "$210,000&mdash;$260,000" never reads as a band. Only when the whole string
    # is escaped (no raw "<"): in raw HTML a literal &lt; would otherwise open a fake tag that swallows
    # text up to the next ">".
    if "<" not in s and re.search(r"&(lt|gt|amp);", s):
        s = html.unescape(s)
    s = re.sub(r"<(script|style)[^>]*>.*?</\1>", " ", s, flags=re.S | re.I)
    s = re.sub(r"<[^>]+>", " ", s)
    s = html.unescape(s).replace("\xa0", " ")
    return re.sub(r"\s+", " ", s).strip()

# amazon.jobs prints "base pay ... ranges from $105,000/year in our lowest geographic market up to $195,000/year
# in our highest geographic market". That is not "$X - $Y", so it has its own pattern. The top is the HIGHEST
# market's, never one metro's, and the label says so.
FROMTO = re.compile(r"from\s+\$\s?([\d,]{5,12})(?:\.\d\d)?(?:\s*/\s*(?:year|yr))?[^$]{0,80}?up to\s+\$\s?([\d,]{5,12})", re.I)
FROMTO_LABEL = "lowest-to-highest market range, not a metro band"

# A dollar range is not a salary when the text before it says one of these ("Sign-on bonus $30,000 -
# $50,000"), or when the text after it begins "in equity" or the like.
NOT_SALARY = re.compile(r"\b(bonus|sign[- ]?on|equity|stock|rsus?|relocation|commission|incentive|stipend|allowance)\b", re.I)
NOT_SALARY_AFTER = re.compile(r"(?:in|for|at)\s+(?:an?\s+)?(bonus|equity|stock|rsus?|relocation|commission|incentives?)\b", re.I)
# The text after a range belongs to that range when it reads "in <place>" or "for <zone>":
# "$195,000 - $245,000 in New York, $170,000 - $210,000 in Denver".
TRAILING = re.compile(r"\s*(?:in|for|at)\b[^,;.$\n]{0,40}", re.I)

def bands(text):
    """Every salary range in the text as (label, low, high), highest top first. The label is the
    text just before the range, plus the "in <place>" that follows it when there is one."""
    text = text or ""
    out = []
    for lo, hi in FROMTO.findall(text):
        try:
            a, b = int(lo.replace(",", "")), int(hi.replace(",", ""))
        except ValueError:
            continue
        if 30_000 <= a <= b <= 2_000_000:
            out.append((FROMTO_LABEL, a, b))
    prev_end, prev_trail = None, 0
    for m in MONEY.finditer(text):
        ctx, lo, hi = m.groups()
        if prev_end == m.start(1):
            ctx = ctx[prev_trail:]            # the start of this gap was the previous range's "in <place>"
        t = TRAILING.match(text, m.end())
        trail = t.group(0).strip() if t else ""
        prev_end, prev_trail = m.end(), (len(t.group(0)) if t else 0)
        try:
            a, b = int(lo.replace(",", "")), int(hi.replace(",", ""))
        except ValueError:
            continue
        before = ctx.strip()[-45:]
        if NOT_SALARY.search(before) or NOT_SALARY_AFTER.match(trail):
            continue
        if 30_000 <= a <= b <= 2_000_000:
            out.append((" ".join(x for x in (before, trail) if x), a, b))
    return sorted(set(out), key=lambda t: -t[2])

def metro_band(bl):
    """The band labelled with a home place if there is one, else the one labelled remote (when
    remote counts as home), else any: and within each, the LOWEST top -- never the max. The
    maximum is usually the figure for the most expensive market, not for home."""
    low_first = sorted(bl, key=lambda t: t[2])
    for label in (S.places, S.metro):
        for ctx, lo, hi in low_first:
            if label.search(ctx): return ctx, lo, hi
    return low_first[0] if low_first else (None, None, None)

def pick_range(ranges):
    """ranges = [(label, lo, hi)], from a structured source. Same rule as metro_band."""
    return metro_band([r for r in ranges if r[1] and r[2]])

KMONEY = re.compile(r"\$\s?([\d.,]+)\s*([KkMm]?)\s*(?:-|–|—|to)\s*\$?\s?([\d.,]+)\s*([KkMm]?)")

def _kmoney(num, suf):
    v = float(num.replace(",", ""))
    return int(v * {"k": 1_000, "m": 1_000_000}.get(suf.lower(), 1))

def ashby_band(comp):
    """Ashby includeCompensation=true. Structured summaryComponents first (Salary, yearly);
    else parse compensationTierSummary ("$200K – $300K • Offers Equity"). The old path
    json.dumps'ed the whole object: the K suffix and the escaped dash meant no band was
    ever read, so the floor never applied to an Ashby board."""
    if not isinstance(comp, dict): return None
    ranges = []
    structured = [("summaryComponents", c) for c in comp.get("summaryComponents") or []]
    for tier in comp.get("compensationTiers") or []:
        structured += [(tier.get("title") or "tier", c) for c in tier.get("components") or []]
    for label, c in structured:
        if (c.get("compensationType") or "").lower() != "salary": continue
        if (c.get("currencyCode") or "USD") != "USD": continue
        mult = {"1 YEAR": 1, "6 MONTHS": 2, "1 MONTH": 12, "2 WEEKS": 26, "1 WEEK": 52, "1 DAY": 260,
                "1 HOUR": 2080}.get((c.get("interval") or "1 YEAR").upper(), 1)
        if c.get("minValue") and c.get("maxValue"):
            ranges.append((label, int(c["minValue"] * mult), int(c["maxValue"] * mult)))
    # The text summaries are parsed only when no structured component exists: a tier summary quoted per
    # hour would otherwise become the "lowest high" and drop the row.
    if not ranges:
        for tier in comp.get("compensationTiers") or []:
            m = KMONEY.search(tier.get("tierSummary") or "")
            if m:
                ranges.append((tier.get("title") or "tier", _kmoney(m[1], m[2]), _kmoney(m[3], m[4])))
    if not ranges:
        for key in ("compensationTierSummary", "scrapeableCompensationSalarySummary"):
            m = KMONEY.search(comp.get(key) or "")
            if m:
                ranges.append((key, _kmoney(m[1], m[2]), _kmoney(m[3], m[4]))); break
    ranges = [r for r in ranges if 30_000 <= r[1] <= r[2] <= 2_000_000]   # same sanity bound as bands()
    ctx, lo, hi = pick_range(ranges)
    return (ctx, lo, hi) if hi else None

def greenhouse_band(pay_input_ranges):
    """Greenhouse /jobs/{id}?pay_transparency=true. One range per zone; the title names the zone."""
    ranges = []
    for pr in pay_input_ranges or []:
        if (pr.get("currency_type") or "USD") != "USD": continue
        lo, hi = pr.get("min_cents"), pr.get("max_cents")
        if lo and hi:
            ranges.append((strip_html(pr.get("title") or "") or "pay_input_ranges", int(lo) // 100, int(hi) // 100))
    ranges = [r for r in ranges if 30_000 <= r[1] <= r[2] <= 2_000_000]   # an hourly zone is not a yearly band
    ctx, lo, hi = pick_range(ranges)
    return (ctx, lo, hi) if hi else None

def clearance_verdict(t):
    if CLR_ACTIVE.search(t or ""): return "ACTIVE REQUIRED"
    if CLR_OBTAIN.search(t or ""): return "OBTAINABLE"
    return "NONE STATED"

# ---------------------------------------------------------------- JSON-LD
# schema.org JobPosting, embedded in the detail page as application/ld+json. One parser for every
# site that emits it. baseSalary is read when it is there; Greenhouse boards are read through
# pay_transparency instead.

LD = re.compile(r'<script[^>]+type=["\']application/ld\+json["\'][^>]*>(.*?)</script>', re.S | re.I)

def _flatten(obj):
    if isinstance(obj, list):
        for o in obj: yield from _flatten(o)
    elif isinstance(obj, dict):
        if "@graph" in obj:
            yield from _flatten(obj["@graph"])
        else:
            yield obj

def jsonld_jobposting(html):
    """Return the first JobPosting dict, or None. Handles bare object,
    top-level array, and @graph. @type may itself be a list."""
    for blob in LD.findall(html or ""):
        try:
            data = json.loads(blob.strip())
        except Exception:
            continue
        for node in _flatten(data):
            t = node.get("@type")
            types = t if isinstance(t, list) else [t]
            if "JobPosting" in types:
                return node
    return None

LD_UNIT = {"HOUR": 2080, "HOURLY": 2080, "DAY": 260, "DAILY": 260, "WEEK": 52, "WEEKLY": 52,
           "MONTH": 12, "MONTHLY": 12, "YEAR": 1, "YEARLY": 1, "ANNUAL": 1, "ANNUALLY": 1}

def ld_salary(jp):
    """(low, high, currency), annualised. baseSalary.value is polymorphic: either `value` (a point)
    or minValue+maxValue (a range). The currency sits on baseSalary, not on value."""
    bs = (jp or {}).get("baseSalary") or {}
    if not isinstance(bs, dict): return (None, None, "")
    cur = str(bs.get("currency") or "").upper()
    v = bs.get("value") or {}
    if not isinstance(v, dict): return (None, None, cur)
    lo = v.get("minValue") or v.get("value")
    hi = v.get("maxValue") or v.get("value")
    unit = str(v.get("unitText") or "").upper()
    try:
        lo, hi = float(lo), float(hi)
    except (TypeError, ValueError):
        return (None, None, cur)
    mult = LD_UNIT.get(unit, 1)
    return (int(lo * mult), int(hi * mult), cur)

def ld_band(jp):
    """(low, high) when baseSalary is a US-dollar range inside the same bounds as bands(), else None.
    A posting in another currency is not read as dollars."""
    lo, hi, cur = ld_salary(jp)
    if lo and cur in ("", "USD") and 30_000 <= lo <= hi <= 2_000_000:
        return lo, hi
    return None

def ld_location(jp):
    """jobLocation is object or array; address is object or string. TELECOMMUTE adds Remote.
    Without it, rows read from a sitemap carry no location and fail the place gate, every one."""
    locs = (jp or {}).get("jobLocation") or []
    if isinstance(locs, str): locs = [{"address": locs}]
    if isinstance(locs, dict): locs = [locs]
    out = []
    for l in locs:
        a = (l or {}).get("address") if isinstance(l, dict) else None
        if isinstance(a, list): a = ", ".join(str(x) for x in a if x)
        if isinstance(a, str): out.append(a); continue
        if not isinstance(a, dict): continue
        c = a.get("addressCountry"); c = c.get("name") if isinstance(c, dict) else c
        out.append(", ".join(x for x in (a.get("addressLocality"), a.get("addressRegion"), c) if x))
    if str((jp or {}).get("jobLocationType", "")).upper() == "TELECOMMUTE": out.append("Remote")
    return "; ".join(x for x in out if x)

def ld_expired(jp):
    vt = (jp or {}).get("validThrough")
    if not vt: return False
    try:
        return datetime.fromisoformat(str(vt)[:19].replace("Z", "")).date() < date.today()
    except Exception:
        return False

def enrich_from_page(row, sess):
    """Fetch the detail page and read its JSON-LD; when the page has none, its text. For lists that
    carry no salary, place or text (iCIMS, Avature, sitemaps, feeds). row["_detail"] says how the
    read went, so the adapter's note can count the reads that failed."""
    try:
        r = sess.get(row["url"], headers=UA, timeout=TIMEOUT)
        if r.status_code != 200:
            row["_detail"] = f"HTTP {r.status_code}"
            return row
        row["_detail"] = "ok"
        jp = jsonld_jobposting(r.text)
        if jp:
            row["text"] = (row.get("text", "") + " " + strip_html(jp.get("description", "")))[:60000]
            row["posted"] = row.get("posted") or str(jp.get("datePosted") or "")[:10]
            row["location"] = row.get("location") or ld_location(jp)
            row["valid_through"] = str(jp.get("validThrough") or "")[:10]
            row["expired"] = "YES" if ld_expired(jp) else ""
            row["openings"] = jp.get("totalJobOpenings", "")
            band = ld_band(jp)
            if band: row["ld_low"], row["ld_high"] = band
            ident = jp.get("identifier") or {}
            if isinstance(ident, dict) and ident.get("value"):
                row["req"] = str(ident["value"])
        else:
            row["text"] = (row.get("text", "") + " " + strip_html(r.text))[:60000]
    except Exception as e:
        row["_detail"] = type(e).__name__
    return row

def failed_reads(rows):
    """A clause for an adapter's note: how many detail reads failed. Empty when none did."""
    n = sum(1 for r in rows if r.get("_detail") not in (None, "ok"))
    return f"; {n} detail reads FAILED" if n else ""

# ---------------------------------------------------------------- ADAPTERS

def greenhouse(token, sess, deep=False, **_):
    r = sess.get(f"https://boards-api.greenhouse.io/v1/boards/{token}/jobs?content=true",
                 headers=UA, timeout=TIMEOUT)
    if r.status_code != 200: return [], f"greenhouse {token}: HTTP {r.status_code}"
    jobs = r.json().get("jobs", [])
    rows = []
    for j in jobs:
        rows.append(dict(req=str(j.get("requisition_id") or j.get("id")),
                         title=j.get("title", ""),
                         # the job's own location, then its offices: an office can be named for a region
                         location="; ".join(dict.fromkeys(x for x in [(j.get("location") or {}).get("name")]
                                            + [(o or {}).get("name") for o in j.get("offices") or []] if x)),
                         text=strip_html(j.get("content", "")),
                         url=j.get("absolute_url", ""),
                         posted=(j.get("first_published") or "")[:10],
                         updated=(j.get("updated_at") or "")[:10],
                         deadline=(j.get("application_deadline") or "")[:10] if j.get("application_deadline") else ""))
        # Salary is NOT on the list call. It needs one request per job. The band is the level
        # gate, so fetch it for every row that names a home place or a remote word; --deep fetches it for all rows.
        if deep or S.metro.search(rows[-1]["location"]):
            try:
                d = sess.get(f"https://boards-api.greenhouse.io/v1/boards/{token}"
                             f"/jobs/{j['id']}?pay_transparency=true", headers=UA, timeout=TIMEOUT)
                rows[-1]["_detail"] = "ok" if d.status_code == 200 else f"HTTP {d.status_code}"
                b = greenhouse_band(d.json().get("pay_input_ranges")) if d.status_code == 200 else None
                if b:
                    rows[-1].update(pay_ctx=b[0], pay_low=b[1], pay_high=b[2], pay_src="pay_input_ranges")
            except Exception as e:
                rows[-1]["_detail"] = type(e).__name__
            time.sleep(PAUSE)
    return rows, f"greenhouse {token}: {len(jobs)} jobs (one call; the list is not paged){failed_reads(rows)}"

def lever(name, sess, **_):
    """skip + limit page the list. An unpaged call truncates it."""
    rows, skip = [], 0
    host = "api.lever.co"
    while True:
        r = sess.get(f"https://{host}/v0/postings/{name}?mode=json&limit=100&skip={skip}",
                     headers=UA, timeout=TIMEOUT)
        if r.status_code == 404 and host == "api.lever.co":
            host = "api.eu.lever.co"; continue          # EU tenants live elsewhere
        if r.status_code != 200:
            return rows, f"lever {name}: HTTP {r.status_code} after {len(rows)}"
        batch = r.json()
        if not batch: break
        for j in batch:
            sal = j.get("salaryRange") or {}
            # The structured range is added to the text only when it is US dollars per year; an hourly
            # or foreign-currency range would otherwise be read as a dollar salary.
            yearly = (str(sal.get("currency") or "USD").upper() == "USD"
                      and "year" in str(sal.get("interval") or "year").lower())
            whole = lambda v: int(v) if isinstance(v, (int, float)) and not isinstance(v, bool) else v
            rows.append(dict(req=j.get("id", "")[:8], title=j.get("text", ""),
                location=(j.get("categories") or {}).get("location") or "",
                text=strip_html(j.get("descriptionPlain") or j.get("description", ""))
                     + " " + strip_html(j.get("additionalPlain", ""))
                     + (f" ${whole(sal.get('min',''))} - ${whole(sal.get('max',''))}" if sal and yearly else "")
                     + " " + str(j.get("salaryDescription") or ""),
                url=j.get("hostedUrl", ""),
                posted=datetime.fromtimestamp(j.get("createdAt", 0)/1000, timezone.utc)
                       .strftime("%Y-%m-%d") if j.get("createdAt") else ""))
        skip += len(batch)
        if len(batch) < 100: break
        time.sleep(PAUSE)
    return rows, (f"lever {name}: {len(rows)} jobs, paged. NOTE: createdAt only -- "
                  f"no update timestamp exists, recency cannot be established here.")

def ashby(name, sess, **_):
    r = sess.get(f"https://api.ashbyhq.com/posting-api/job-board/{name}"
                 f"?includeCompensation=true", headers=UA, timeout=TIMEOUT)
    if r.status_code != 200: return [], f"ashby {name}: HTTP {r.status_code}"
    jobs = r.json().get("jobs", [])
    rows = []
    for j in jobs:
        # isListed=false means direct-link only. NOT the same as open.
        locs = [j.get("location", "")] + [s.get("location", "") for s in j.get("secondaryLocations") or []]
        rows.append(dict(req=str(j.get("id", ""))[:8], title=j.get("title", ""),
            location="; ".join(filter(None, locs)),
            text=strip_html(j.get("descriptionPlain") or j.get("descriptionHtml", "")),
            url=j.get("jobUrl", ""), posted=(j.get("publishedAt") or "")[:10],
            listed="" if j.get("isListed", True) else "UNLISTED"))
        b = ashby_band(j.get("compensation"))
        if b:
            rows[-1].update(pay_ctx=b[0], pay_low=b[1], pay_high=b[2], pay_src="ashby compensation")
    return rows, (f"ashby {name}: {len(jobs)} jobs. No pagination and no total field "
                  f"exists, so truncation cannot be detected from the response.")

def icims(sub, sess, cap=400, lane=None, **_):
    """No browser needed: sitemap.xml is public, and detail pages carry JobPosting JSON-LD.
    A large tenant lists far more URLs than the cap: with --lane the title slug is filtered BEFORE
    the detail fetch, so the cap is spent on lane titles only. --cap 0 means no cap."""
    r = sess.get(f"https://{sub}.icims.com/sitemap.xml", headers=UA, timeout=TIMEOUT)
    if r.status_code != 200:
        return [], f"icims {sub}: sitemap HTTP {r.status_code}"
    urls = [u for u in re.findall(r"<loc>([^<]+)</loc>", r.text) if "/jobs/" in u]
    n_all = len(urls)
    if lane:
        urls = [u for u in urls if lane.search(unquote(u.rstrip("/").split("/")[-2]).replace("-", " "))]
    rows = []
    for u in (urls[:cap] if cap else urls):
        m = re.search(r"/jobs/(\d+)/", u)
        rows.append(enrich_from_page(dict(
            req=m.group(1) if m else "", title=unquote(u.rstrip("/").split("/")[-2]).replace("-", " ").title(),  # unquote: slugs carry %2C
            location="", text="", url=u, posted=""), sess))
        time.sleep(PAUSE)
    note = (f"icims {sub}: {n_all} job URLs in sitemap, {len(urls)} after the lane slug filter, "
            f"{len(rows)} fetched" if lane else f"icims {sub}: {n_all} job URLs in sitemap, {len(rows)} fetched")
    if cap and len(urls) > cap: note += f"  <-- CAPPED at {cap}. Use --lane, or --cap 0."
    return rows, note + failed_reads(rows)

def eightfold(spec, sess, lane=None, **_):
    """Eightfold's search, /api/pcsx/search. The older /api/apply/v2/jobs returned 403 on the tenant
    tried and is not used. spec = 'host|domain.com': host is a bare sub (-> sub.eightfold.ai) or a
    full host (careers.example.com); domain is the employer's registered domain."""
    sub, domain = spec.split("|")
    host = sub if "." in sub else f"{sub}.eightfold.ai"
    H = {**UA, "Accept": "application/json, text/plain, */*"}
    rows, start, cnt, bound = [], 0, None, ""
    while True:
        r = sess.get(f"https://{host}/api/pcsx/search", params={"domain": domain, "query": "", "location": "",
                     "start": start, "sort_by": "timestamp"}, headers=H, timeout=TIMEOUT)
        if r.status_code != 200:
            waf = " (403 here is usually a client check: a wall)" if r.status_code == 403 else ""
            if not rows: return rows, f"eightfold {host}: HTTP {r.status_code} at start=0{waf}"
            bound = f"  <-- STOPPED: HTTP {r.status_code} at start={start}{waf}; the list is longer"; break
        d = (r.json() or {}).get("data") or {}
        pos = d.get("positions") or []
        if not pos: break
        for p in pos:   # field names per ats-scrapers 0.3.0, eightfold.py; the server fixes the page size at 10
            locs = p.get("standardizedLocations") or p.get("locations") or [p.get("location") or ""]
            pu = p.get("canonicalPositionUrl") or p.get("positionUrl") or f"/careers/job/{p.get('id')}"
            ts = p.get("postedTs") or p.get("t_create")
            if isinstance(ts, (int, float)):   # epoch, ms when > 1e10
                ts = datetime.fromtimestamp(ts / 1000 if ts > 1e10 else ts, timezone.utc).date().isoformat()
            rows.append(dict(req=str(p.get("displayJobId") or p.get("id", "")), title=p.get("name", ""),
                location="; ".join(l for l in locs if l), text="",
                url=pu if pu.startswith("http") else f"https://{host}{pu}",
                posted=str(ts or "")[:10], _pid=str(p.get("id") or "")))
        start += len(pos)
        cnt = d.get("count")   # absent -> page until empty, never "complete at page 1"
        if cnt is not None and start >= cnt: break
        if start >= 5000:
            bound = "  <-- STOPPED at the 5,000-row bound; the list is longer"; break
        time.sleep(PAUSE)
    # The list carries no description. /api/pcsx/position_details -> data.jobDescription, fetched for
    # rows that name a home place or a remote word (the same rule as the Greenhouse band fetch), and with --lane for lane
    # titles only: a large tenant needs more than a thousand detail reads otherwise.
    n = 0
    for row in rows:
        if not S.metro.search(row["location"]): continue      # fails the place gate whatever its text says
        row["unread"] = "YES"                                 # until its description has been read
        if not row.get("_pid") or (lane and not lane.search(row["title"])): continue
        try:
            dr = sess.get(f"https://{host}/api/pcsx/position_details",
                          params={"position_id": row["_pid"], "domain": domain, "hl": "en"}, headers=H, timeout=TIMEOUT)
            row["_detail"] = "ok" if dr.status_code == 200 else f"HTTP {dr.status_code}"
            if dr.status_code == 200:
                row["text"] = strip_html(((dr.json() or {}).get("data") or {}).get("jobDescription") or "")[:60000]
                row["unread"] = ""; n += 1
        except Exception as e:
            row["_detail"] = type(e).__name__
        time.sleep(PAUSE)
    if cnt is not None and len(rows) < cnt and not bound:
        bound = f"  <-- SHORT: the list ended at {len(rows)} of a reported {cnt}"
    of = "count missing, paged until empty" if cnt is None else f"of count {cnt}"
    return rows, (f"eightfold {host}: {len(rows)} jobs ({of}), {n} home or remote rows read from position_details"
                  + failed_reads(rows) + bound)

def workday(spec, sess, lane=None, cap=400, **_):
    """POST only: GET returns 400, and so does a limit above 20 (both measured on one tenant, 3 Oct 2026).
    spec = 'tenant|wd5|SiteName'. The list carries no description, so no band and no clearance: with --lane,
    lane-titled rows get GET {cxs}/{site}{externalPath} -> jobPostingInfo (description, location,
    additionalLocations). A row whose detail was not read is marked `unread` and never passes
    keep(): without that mark every unread row passed as "no band"."""
    tenant, shard, site = spec.split("|")
    url = f"https://{tenant}.{shard}.myworkdayjobs.com/wday/cxs/{tenant}/{site}/jobs"
    # A company map may list a site name in lower case while the tenant's real site is cased
    # (Careers_Site), and the lower-case name then answers non-JSON. One probe of the title-cased
    # form, reported in the wall either way.
    alt = "_".join(w[:1].upper() + w[1:] for w in site.split("_"))
    probe_note = ""
    def is_json(resp):
        try: resp.json(); return True
        except ValueError: return False
    first = sess.post(url, json={"appliedFacets": {}, "limit": 20, "offset": 0, "searchText": ""},
                      headers={**UA, "Content-Type": "application/json"}, timeout=TIMEOUT)
    if (first.status_code != 200 or not is_json(first)) and alt != site:
        url2 = url.replace(f"/{site}/jobs", f"/{alt}/jobs")
        second = sess.post(url2, json={"appliedFacets": {}, "limit": 20, "offset": 0, "searchText": ""},
                           headers={**UA, "Content-Type": "application/json"}, timeout=TIMEOUT)
        if second.status_code == 200 and is_json(second):
            url, site, probe_note = url2, alt, f" (site {spec.split('|')[2]!r} failed; {alt!r} answered)"
        else:
            return [], (f"workday {tenant}: site {site!r} HTTP {first.status_code} "
                        f"{'non-JSON' if first.status_code == 200 else ''} and {alt!r} HTTP {second.status_code}: "
                        f"read the real site name off the careers URL")
    elif first.status_code != 200 or not is_json(first):
        return [], f"workday {tenant}: site {site!r} HTTP {first.status_code}{' non-JSON' if first.status_code == 200 else ''}"
    rows, offset, total, stopped = [], 0, None, ""
    time.sleep(PAUSE)
    while True:
        r = sess.post(url, json={"appliedFacets": {}, "limit": 20, "offset": offset,
                                 "searchText": ""},
                      headers={**UA, "Content-Type": "application/json"}, timeout=TIMEOUT)
        if r.status_code != 200:   # keep what was listed, say so, and still read the details below
            stopped = f"  <-- STOPPED: HTTP {r.status_code} at offset={offset}; the list is longer"; break
        d = r.json()
        # `total` is reported only at offset 0; from offset 40 on it reads 0 with rows still present.
        # Trusting it on every page is why an earlier version stopped at 40 rows. A first page with
        # no total at all means: page until a page comes back empty.
        if offset == 0: total = d.get("total")
        posts = d.get("jobPostings", [])
        if not posts: break
        for p in posts:
            rows.append(dict(req=p.get("bulletFields", [""])[0] if p.get("bulletFields") else "",
                title=p.get("title", ""), location=p.get("locationsText", ""),
                text="", url=f"https://{tenant}.{shard}.myworkdayjobs.com"
                            f"/{site}{p.get('externalPath','')}",
                posted=p.get("postedOn", ""), _path=p.get("externalPath", "")))
        offset += 20
        if (total is not None and offset >= total) or offset >= 2000: break
        time.sleep(PAUSE)
    n = 0
    cxs = url[:-len("/jobs")]
    for row in rows:
        row["unread"] = "YES"                       # until its detail has been read
        if not lane or not lane.search(row["title"]) or (cap and n >= cap): continue
        try:
            dr = sess.get(cxs + row["_path"], headers={**UA, "Accept": "application/json"}, timeout=TIMEOUT)
            row["_detail"] = "ok" if dr.status_code == 200 else f"HTTP {dr.status_code}"
            if dr.status_code == 200:
                info = (dr.json() or {}).get("jobPostingInfo") or {}
                row["text"] = strip_html(info.get("jobDescription") or "")[:60000]
                locs = [info.get("location") or ""] + list(info.get("additionalLocations") or [])
                row["location"] = "; ".join(x for x in locs if x) or row["location"]
                row["req"] = info.get("jobReqId") or row["req"]
                row["unread"] = ""; n += 1
        except Exception as e:
            row["_detail"] = type(e).__name__
        time.sleep(PAUSE)
    note = (f"workday {tenant}: {len(rows)} of total {'not reported' if total is None else total}{probe_note}; "
            + (f"{n} lane rows read from the detail endpoint" + (f" (capped at {cap})" if cap and n >= cap else "")
               if lane else "no --lane, so no detail was read and no row can pass")
            + failed_reads(rows) + stopped)
    if total == 2000:      # a capped tenant reports exactly 2000 (ats-scrapers 0.3.0, workday.py)
        note += "  <-- CAPPED: a total of exactly 2,000 means the tenant caps a query; the list is longer."
    elif len(rows) >= 2000 and not stopped:
        note += "  <-- STOPPED at 2,000 rows: this tool pages no further; the list is longer."
    elif total is not None and len(rows) < total and not stopped:
        note += f"  <-- SHORT: the list ended at {len(rows)} of a reported {total}"
    return rows, note

def avature(co, sess, cap=400, lane=None, **_):
    """No JSON API exists. HTML pagination works.
    co is a slug ({co}.avature.net) or a full base URL for a site on its own domain, such as
    https://careers.example.com/portal. Many tenants answer 406 to plain HTTP clients
    (a client-fingerprint block): that is a wall, not an empty board, and it is not worked around."""
    base = co.rstrip("/") if co.startswith("http") else f"https://{co}.avature.net"
    origin = re.match(r"https?://[^/]+", base).group(0)
    rows, off, seen, more = [], 0, set(), False
    while (not cap or off < cap) and off < 12 * 200:   # cap 0 = no cap, as in icims; 200 pages is the hard bound
        r = sess.get(f"{base}/careers/SearchJobs/?jobRecordsPerPage=12&jobOffset={off}",
                     headers=UA, timeout=TIMEOUT)
        if r.status_code != 200:
            why = " (406 = Avature's client-fingerprint block; needs a browser-like client)" if r.status_code == 406 else ""
            return rows, f"avature {co}: HTTP {r.status_code} at offset={off}{why}"
        links = [h for h in dict.fromkeys(re.findall(r'href="([^"]*?/careers/JobDetail/[^"]+)"', r.text)) if h not in seen]
        more = bool(links)
        if not links: break   # an empty page, or a page that only repeats earlier links
        seen.update(links)
        time.sleep(PAUSE)
        for href in links:
            if cap and len(rows) >= cap: break   # the last page is cut at the cap
            u = href if href.startswith("http") else f"{origin}{href}"
            m = re.search(r"/(\d+)$", href)
            row = dict(req=m.group(1) if m else "", title=href.split("/")[-2].replace("-", " ").title(),
                       location="", text="", url=u, posted="")
            if lane and not lane.search(row["title"]):
                row["unread"] = "YES"   # no detail fetch outside the lane: a large tenant has more than a thousand
            else:
                enrich_from_page(row, sess); time.sleep(PAUSE)
            rows.append(row)
        off += 12
    n = sum(1 for r in rows if r.get("_detail") == "ok")
    stop = ""
    if more:   # the loop ended on a bound, not on an empty page
        stop = f"  <-- STOPPED at {'--cap ' + str(cap) if cap and off >= cap else 'the 200-page bound'}; the list may be longer"
    return rows, (f"avature {co}: {len(rows)} jobs listed, {n} job pages read" + (" (lane rows only)" if lane else "")
                  + failed_reads(rows) + stop)

# The request body and headers follow ats-scrapers 0.3.0, phenom.py (MIT; see THIRD_PARTY_NOTICES.md). The POST
# needs the csrf cookie the search-page GET seeds, echoed as x-csrf-token, plus Origin and Referer, or it 403s.
PHENOM_FIELDS = ["category", "jobFamilies", "country", "state", "city", "experienceLevel"]
_CSRF_RX = re.compile(r'"csrfToken"\s*:\s*"([^"]+)"')

def _phenom_post(sess, base, ref, frm, size, selected=None, csrf=None, referer=None, country="us"):
    body = {"lang": f"en_{country}", "deviceType": "desktop", "country": country, "pageName": "search-results",
            "ddoKey": "refineSearch", "sortBy": "", "subsearch": "", "from": frm, "jobs": True,
            "counts": True, "all_fields": PHENOM_FIELDS, "size": size, "clearAll": False,
            "jdsource": "facets", "isSliderEnable": False, "pageId": "page20", "siteType": "external",
            "keywords": "", "global": True, "selected_fields": selected or {}, "locationData": {}}
    if ref: body["refNum"] = ref
    h = {**UA, "Content-Type": "application/json", "Accept": "*/*", "Origin": base, "Referer": referer or base}
    if csrf: h["x-csrf-token"] = csrf
    r = sess.post(f"{base}/widgets", json=body, headers=h, timeout=TIMEOUT)
    if r.status_code != 200: return r.status_code, None
    try:
        return 200, (r.json() or {})
    except ValueError:   # a 200 HTML page: the site is not a Phenom tenant
        return f"200 non-JSON ({r.headers.get('Content-Type', '?')})", None

def _phenom_jobs(payload):
    rs = (payload or {}).get("refineSearch") or {}
    if isinstance(rs, dict):
        for cand in ((rs.get("data") or {}).get("jobs"), rs.get("jobs"), rs.get("hits")):
            if isinstance(cand, list): return cand
    return payload.get("jobs") if isinstance((payload or {}).get("jobs"), list) else []

def _phenom_total(payload):
    rs = (payload or {}).get("refineSearch") or {}
    if not isinstance(rs, dict): return 0
    for v in (rs.get("totalHits"), (rs.get("data") or {}).get("totalHits"), rs.get("hitsCount")):
        if isinstance(v, int): return v
    return 0

def phenom_widget(spec, sess, **_):
    """The site's own search call: POST {base}/widgets, ddoKey refineSearch. refNum is read off the
    search page (phApp), never guessed.
    Facet slicing: when paging returns fewer rows than totalHits, re-query per `category` facet
    value and union, so completeness is measured against totalHits. (An older GET {base}/api/jobs
    route returned no rows on any site tried and is not shipped.)
    spec = 'https://careers.example.com' or 'https://careers.example.com|REFNUM'."""
    base, _, ref = spec.partition("|")
    base = base.rstrip("/")
    tried, csrf, referer, seeded, country = [], None, None, False, "us"
    host = re.sub(r"^https?://", "", base).split("/")[0]
    for path in ("/us/en/search-results", "/global/en/search-results", "/search-results"):
        try:
            pg = sess.get(base + path, headers={**UA, "Accept": "text/html,application/xhtml+xml,*/*;q=0.8"},
                          timeout=TIMEOUT)
        except Exception as e:
            tried.append(f"{path}: {type(e).__name__}"); continue
        tried.append(f"{path}: HTTP {pg.status_code}")
        if pg.status_code != 200: continue
        seeded, referer = True, base + path
        if path.startswith("/global/"): country = "global"
        for c in getattr(sess, "cookies", []) or []:   # this tenant's cookie only: one Session serves every employer
            dom = (getattr(c, "domain", "") or "").lstrip(".")
            if "csrf" in c.name.lower() and (not dom or host.endswith(dom)): csrf = c.value
        m = _CSRF_RX.search(pg.text or "")
        if m and not csrf: csrf = m.group(1)
        m = re.search(r'"refNum"\s*:\s*"([A-Za-z0-9]+)"', pg.text or "")
        if m and not ref: ref = m.group(1)
        break
    if not seeded:
        # A fetch error is a wall, not evidence the site is not Phenom: say which it was.
        return [], f"phenom-widget {base}: search page not read ({'; '.join(tried)})"
    rows, seen = [], set()
    def take(jobs):
        n = 0
        for j in jobs or []:
            rid = str(j.get("jobSeqNo") or j.get("jobId") or j.get("reqId") or "")
            if not rid or rid in seen: continue
            seen.add(rid); n += 1
            u = j.get("jobUrl") or j.get("url") or j.get("applyUrl") or f"/job/{j.get('jobId', '')}"
            rows.append(dict(req=str(j.get("reqId") or rid), title=j.get("title") or j.get("jobTitle", ""),
                location=j.get("cityStateCountry") or j.get("location") or
                         "; ".join(filter(None, [j.get("city"), j.get("state")])),
                text=strip_html(j.get("description") or j.get("descriptionTeaser") or ""),   # the teaser is a fraction of the body
                url=u if u.startswith("http") else base + (u if u.startswith("/") else "/" + u),
                posted=str(j.get("postedDate", ""))[:10]))
        return n
    calls = [0]
    def post(frm, sel=None):
        if calls[0]: time.sleep(PAUSE)
        calls[0] += 1
        return _phenom_post(sess, base, ref, frm, 100, sel, csrf=csrf, referer=referer, country=country)
    status, first = post(0)
    if first is None:
        return [], f"phenom-widget {base}: POST /widgets HTTP {status} (csrf {'sent' if csrf else 'not found'}; refNum {ref or 'none'})"
    if not isinstance(first.get("refineSearch"), dict):
        return [], (f"phenom-widget {base}: POST /widgets answered 200 without refineSearch: "
                    f"{json.dumps(first)[:160]} (a wall, not an empty board)")
    total = _phenom_total(first)
    got = _phenom_jobs(first); take(got)
    frm = len(got)
    known = total > 0          # no total in the response: page until a page comes back empty
    while got and (frm < total or not known) and frm < 5000:   # advance by rows returned, not a fixed 100
        _, page = post(frm)
        got = _phenom_jobs(page) if page else []
        if not got or not take(got): break
        frm += len(got)
    sliced = 0
    if total and len(rows) < total:   # fallback only; ats-scrapers pages by `from` alone
        rs = first.get("refineSearch") or {}
        aggs = (rs.get("data") or {}).get("aggregations") or rs.get("aggregations") or []
        for agg in aggs:
            if agg.get("field") != "category": continue
            for val in (agg.get("value") or {}):
                frm = 0
                while True:
                    _, page = post(frm, {"category": [val]})
                    if not page: break
                    got = _phenom_jobs(page)
                    take(got); frm += len(got); sliced += 1
                    if not got or frm >= _phenom_total(page): break
    note = (f"phenom-widget {base}: {len(rows)} of totalHits {total if known else 'not reported'} (csrf {'sent' if csrf else 'none'}; "
            f"refNum {ref or 'none'}; {sliced} facet slices)")
    if total and len(rows) < total * 0.9:
        note += "  <-- INCOMPLETE"
    if (total > 5000 and len(rows) < total) or (not known and frm >= 5000):
        note += "  <-- STOPPED: paging stops at 5,000 rows; the list is longer"
    return rows, note

def amazon(spec, sess, **_):
    """amazon.jobs GET /en/search.json (public). Per ats-scrapers 0.3.0, amazon.py: business_category[]
    is honoured, 400 means past the 10,000-row cap, and `locations` is a list of JSON-encoded strings.
    The qualification fields may be lists. spec = 'category|query': business_category[]=category,
    base_query=query (whether base_query narrows is not established; the gates handle an unnarrowed
    category). The search is fixed to country=USA."""
    cat, _, query = spec.partition("|")
    base_params = {"country": "USA", "result_limit": 100, "sort": "recent"}
    if cat: base_params["business_category[]"] = cat
    if query: base_params["base_query"] = query
    rows, off, total, stop = [], 0, None, ""
    while True:
        r = sess.get("https://www.amazon.jobs/en/search.json", params={**base_params, "offset": off},
                     headers={**UA, "Accept": "application/json"}, timeout=TIMEOUT)
        if r.status_code == 400:                  # past the pagination cap; on the first page, a refusal
            if off == 0: return rows, f"amazon {spec!r}: HTTP 400 on the first page"
            stop = f"  <-- STOPPED: HTTP 400 at offset={off} (the search refuses an offset past its cap); the list may be longer"
            break
        if r.status_code != 200:
            return rows, f"amazon {spec!r}: HTTP {r.status_code} at offset={off}"
        d = r.json() or {}
        if total is None: total = d.get("hits")   # may be absent; then page until empty
        jobs = d.get("jobs") or []
        if not jobs: break
        for j in jobs:
            locs = []
            for e in j.get("locations") or []:
                try: e = json.loads(e) if isinstance(e, str) else e
                except ValueError: continue
                if isinstance(e, dict) and e.get("normalizedLocation"): locs.append(e["normalizedLocation"])
            loc = [j.get("normalized_location") or j.get("location") or ""] + locs
            sj = lambda v: " ".join(v) if isinstance(v, list) else (v or "")   # the qualification fields may be lists
            rows.append(dict(req=str(j.get("id_icims") or j.get("id", "")), title=j.get("title", ""),
                location="; ".join(dict.fromkeys(x for x in loc if x)),
                text=strip_html(sj(j.get("description"))) + " BASIC: " +
                     strip_html(sj(j.get("basic_qualifications"))) + " PREFERRED: " +
                     strip_html(sj(j.get("preferred_qualifications"))),
                url="https://www.amazon.jobs" + (j.get("job_path") or ""),
                posted=str(j.get("posted_date", ""))))
        off += len(jobs)
        if total and off >= total: break
        if off >= 10000:
            stop = "  <-- STOPPED at 10,000 rows, the most the search returns; the list may be longer"; break
        time.sleep(PAUSE)
    if not stop and total and len(rows) < total:
        stop = "  <-- STOPPED short of the reported hits"
    return rows, f"amazon {spec!r}: {len(rows)} rows (hits {total if total is not None else 'not reported'}){stop}"

def successfactors_rss(host, sess, **_):
    """SuccessFactors Recruiting Marketing sites publish RSS 2.0 at /sitemal.xml (the typo is the real
    path; ats-scrapers 0.3.0, successfactors.py). Credential-free and stateless, unlike the
    career{N}.successfactors.com search. host = 'careers.example.com'.
    Titles often end in '(City, State, Country)'; the detail page fills the rest for lane rows,
    with or without --lane: a feed holds thousands of items. The one site tried had no JSON-LD on
    its job pages, so the page text was what got read."""
    base = host.rstrip("/") if host.startswith("http") else f"https://{host}"
    r = sess.get(f"{base}/sitemal.xml", headers={**UA, "Accept": "application/rss+xml, application/xml, text/xml, */*"},
                 timeout=TIMEOUT)
    if r.status_code != 200: return [], f"successfactors-rss {host}: HTTP {r.status_code} on /sitemal.xml"
    rows = []
    def tag(item, t):
        m = re.search(rf"<{t}>\s*(?:<!\[CDATA\[)?(.*?)(?:\]\]>)?\s*</{t}>", item, re.S)
        return html.unescape(m.group(1).strip()) if m else ""
    for item in re.findall(r"<item>(.*?)</item>", r.text, re.S):
        title, link = tag(item, "title"), tag(item, "link")
        m = re.match(r"^(?P<t>.+?)\s*\((?P<loc>[^()]+)\)\s*$", title)
        if m and not ("," in m["loc"] or re.search(r"\b[A-Z]{2}\b", m["loc"])): m = None   # "(Excel)" is not a place
        rows.append(dict(req=(re.findall(r"/(\d{4,})(?=/|$)", link) or [""])[-1], title=m["t"] if m else title,
                         location=m["loc"] if m else "", text=strip_html(tag(item, "description")),
                         url=link, posted=tag(item, "pubDate")[:16]))
    n = 0
    for row in rows:   # the feed item is a teaser: JSON-LD on the page for lane rows
        if S.lane.search(row["title"]) and row["url"]:
            enrich_from_page(row, sess); time.sleep(PAUSE)
            if row.get("_detail") == "ok": n += 1; continue
        row["unread"] = "YES"
    return rows, f"successfactors-rss {host}: {len(rows)} items in /sitemal.xml, {n} lane rows read" + failed_reads(rows)

def sitemap(url, sess, cap=400, lane=None, **_):
    """A jobs sitemap whose URLs end .../<title-slug>/<id>/ : the title is read from the slug.
    Sitemap indexes and .gz files are not followed. A sitemap row has no location and no text, so
    it cannot pass the place gate until its page is read: with --lane, lane-titled rows get their
    JSON-LD; every other row is marked unread."""
    r = sess.get(url, headers=UA, timeout=TIMEOUT)
    if r.status_code != 200: return [], f"sitemap {url}: HTTP {r.status_code}"
    locs = re.findall(r"<loc>([^<]+)</loc>", r.text)
    rows = [dict(req=(re.findall(r"/(\d{5,})/?$", u) or [""])[0],
                 title=u.rstrip("/").split("/")[-2].replace("-", " ").title()
                       if len(u.split("/")) > 4 else u,
                 location="", text="", url=u, posted="", unread="YES") for u in locs]
    n = in_lane = 0
    if lane:
        for row in rows:
            if not lane.search(row["title"]): continue
            in_lane += 1
            if cap and in_lane > cap: continue
            enrich_from_page(row, sess); time.sleep(PAUSE)
            if row.get("_detail") == "ok": row["unread"] = ""; n += 1
    return rows, (f"sitemap {url}: {len(locs)} URLs, {n} lane rows read"
                  + ("" if lane else " (none: pass --lane, or no row can pass the place gate)") + failed_reads(rows)
                  + (f"  <-- CAPPED at {cap} of {in_lane} lane rows. Use --cap 0." if cap and in_lane > cap else ""))

# kind -> the parts of its spec when the spec is written a|b|c, else None.
KINDS = {"greenhouse": None, "lever": None, "ashby": None, "icims": None, "sitemap": None, "avature": None,
         "phenom_widget": None, "successfactors_rss": None,
         "amazon": None, "workday": ("tenant", "shard", "site"), "eightfold": ("host", "domain.com")}
ADAPTERS = {"greenhouse": greenhouse, "lever": lever, "ashby": ashby, "icims": icims, "sitemap": sitemap,
            "avature": avature, "phenom_widget": phenom_widget, "successfactors_rss": successfactors_rss,
            "workday": workday, "eightfold": eightfold, "amazon": amazon}


ATS_FINGERPRINTS = [
    ("workday",    r"https?://([a-z0-9-]+)\.(wd\d+)\.myworkdayjobs\.com/(?:[a-z]{2}-[A-Z]{2}/)?(?!wday\b)([A-Za-z0-9_-]+)"),
    ("phenom",     r'"refNum"\s*:\s*"([A-Za-z0-9]+)"'),
    ("eightfold",  r"([a-z0-9-]+)\.eightfold\.ai"),
    ("icims",      r"([a-z0-9-]+)\.icims\.com"),
    ("avature",    r"([a-z0-9-]+)\.avature\.net"),
    ("greenhouse", r"(?:boards(?:-api)?|job-boards)\.greenhouse\.io/(?:v1/boards/|embed/job_(?:board|app)(?:/js)?\?(?:[^\"'\s&]+&)*for=)?(?!embed\b)([A-Za-z0-9_]+)"),
    ("lever",      r"jobs\.lever\.co/([a-z0-9-]+)"),
    ("ashby",      r"jobs\.ashbyhq\.com/([A-Za-z0-9-]+)"),
    ("successfactors", r"(career\d*\.successfactors\.(?:com|eu)[^\"' ]*company=[A-Za-z0-9]+)"),
    ("oracle",     r"([a-z0-9-]+\.fa\.[a-z0-9-]+\.oraclecloud\.com)"),
    ("taleo",      r"([a-z0-9-]+)\.taleo\.net"),
    ("radancy",    r"(tbcdn\.talentbrew\.com|radancy)"),
]

def discover(domain, sess):
    """Read the careers page HTML and report every ATS fingerprint in it -- a route read off the
    real page instead of a guessed tenant. Workday matches print as tenant|shard|site."""
    u = domain if domain.startswith("http") else f"https://{domain}"
    try:
        r = sess.get(u, headers={**UA, "Accept": "text/html"}, timeout=TIMEOUT, allow_redirects=True)
    except Exception as e:
        print(f"discover {u}: {type(e).__name__} {e}"); return
    print(f"discover {u} -> HTTP {r.status_code} at {r.url}  ({len(r.text)} bytes)")
    found = False
    for kind, rx in ATS_FINGERPRINTS:
        hits = sorted(set("|".join(m) if isinstance(m, tuple) else m for m in re.findall(rx, r.text)))
        if hits:
            found = True; print(f"  {kind:<15} {', '.join(hits[:6])}")
    if not found:
        print("  no ATS fingerprint in the HTML (JS-rendered, or behind a bot check). A wall, not a zero.")

PROBE = [("icims", "https://{slug}.icims.com/sitemap.xml"),
         ("sitemap", "{base}/jobs_sitemap.xml"),
         ("greenhouse", "https://boards-api.greenhouse.io/v1/boards/{slug}/jobs"),
         ("ashby", "https://api.ashbyhq.com/posting-api/job-board/{slug}"),
         ("lever", "https://api.lever.co/v0/postings/{slug}?mode=json"),
         ("avature", "https://{slug}.avature.net/careers/SearchJobs/"),
         ("eightfold", "https://{slug}.eightfold.ai/api/pcsx/search?domain={dom}&query=&location=&start=0")]

def probe(domain, sess):
    host = re.sub(r"^https?://", "", domain).split("/")[0]      # a URL is accepted as well as a domain
    slug = re.sub(r"^(www\.|careers\.|jobs\.)", "", host).split(".")[0]
    dom = re.sub(r"^(www\.|careers\.|jobs\.)", "", host)
    base = domain if domain.startswith("http") else f"https://careers.{dom}"
    print(f"\nprobing {dom}   slug={slug}")
    print("  (a company-to-ATS map exists in ats-scrapers, MIT: github.com/kalil0321/ats-scrapers --")
    print("   use it instead of probing where you can, and verify what it says: such a map goes stale)")
    for kind, tmpl in PROBE:
        u = tmpl.format(base=base.rstrip("/"), slug=slug, dom=dom)
        try:
            r = sess.get(u, headers=UA, timeout=15)
            hit = "HIT " if r.status_code == 200 and len(r.content) > 400 else "    "
            print(f"  {hit}{r.status_code:>3}  {kind:<10} {u}")
        except Exception as e:
            print(f"       ERR  {kind:<10} {u}  {type(e).__name__}")
    print("  note: Workday is POST-only and Phenom needs its search page first; neither is probed here. Use --discover.")

# ---------------------------------------------------------------- GATE 2

def band_high(r):
    return int(r["band_high"]) if str(r.get("band_high", "")).isdigit() else None

NOT_REMOTE = re.compile(r"\b(?:not|non|no)[- ]?(?:remote|telework)\b", re.I)

def in_metro(where):
    """True when the location names a home place, or is remote and not tied to another country.
    "Remote" alone used to pass, so "Remote - United Kingdom" and "Bangalore - Remote" passed.
    A remote-only match now also needs no foreign place, or a home-country mark."""
    where = NOT_REMOTE.sub(" ", where)                             # "not remote", "non-remote", "no remote"
    if not S.metro.search(where): return False
    if S.metro.search(S.remote.sub("", where)): return True       # a home place matched on its own
    for part in re.split(r"[;|]", where):                          # remote-only: judge each listed location
        if S.remote.search(part) and (S.home.search(part) or not S.foreign.search(part)):
            return True
    return False

def clearance_blocks(r):
    """True when the settings say to drop postings that ask for an active clearance, and this one does."""
    return S.drop_active_clearance and r["clearance"] == "ACTIVE REQUIRED"

def place_ok(r):
    """The location passes in_metro, or the band read for this posting is labelled with a home place.
    A band label is tested against the places only: "the range for remote employees" must not put
    a posting in another city through the gate."""
    return in_metro(r.get("location") or "") or bool(r.get("band_ctx") and S.places.search(r["band_ctx"]))

def keep_but_for_band(r, clearance=True):
    """Every gate except the pay floor. clearance=False leaves the clearance choice out too."""
    if clearance and clearance_blocks(r): return False
    if r.get("expired") == "YES": return False
    if r.get("listed") == "UNLISTED": return False
    if r.get("unread") == "YES": return False   # listed but never read: no band, no clearance wording
    if S.junior.search(r.get("title") or ""): return False
    return place_ok(r)

def keep(r, floor, clearance=True):
    # The level gate is the published band, not words in the title: a title-word gate hides the
    # roles whose titles carry no level word. A board with no band passes every title through.
    if not keep_but_for_band(r, clearance): return False
    bh = band_high(r)
    return not (bh is not None and bh < floor)

def title_gate(r):
    """The title-word gate from the settings, used ONLY by --delta to show what such a gate hides.
    Never used to filter."""
    ok, no = S.title_gate
    t = r.get("title") or ""
    return bool(ok.search(t)) and not no.search(t)

def write_delta(path, uniq, floor, walls, employers):
    """The band gate against the title-word gate, on the same enumeration."""
    new = [r for r in uniq if keep(r, floor)]
    base = [r for r in uniq if keep_but_for_band(r)]
    surfaced = [r for r in new if not title_gate(r)]
    dropped = [r for r in base if title_gate(r) and not keep(r, floor)]
    kept_both = [r for r in new if title_gate(r)]
    def line(r):
        bh = band_high(r)
        band = (f"${int(r['band_low'] or 0):,} - ${bh:,} ({r['band_src']}: {r['band_ctx']})"
                if bh else "no band published")
        return f"| {r['employer']} | {r['title']} | {r['location']} | {band} | {r['clearance']} | {r['url']} |"
    hdr = "| employer | title | location | band read | clearance verdict | url |\n|---|---|---|---|---|---|"
    out = [f"# Gate delta, band floor ${floor:,}, {date.today().isoformat()}", "",
           f"Employers: {', '.join(employers)}. Enumerated {len(uniq)}; pass the band gate {len(new)}; "
           f"pass the title gate {len(kept_both) + len(dropped)}.", "",
           f"## Surfaced by the band gate, hidden by the title gate ({len(surfaced)})", hdr]
    out += [line(r) for r in sorted(surfaced, key=lambda r: (r["employer"], r["title"]))]
    out += ["", f"## Dropped by the band floor, passed by the title gate ({len(dropped)})", hdr]
    out += [line(r) for r in sorted(dropped, key=lambda r: (r["employer"], r["title"]))]
    out += ["", f"## Pass both gates ({len(kept_both)})", hdr]
    out += [line(r) for r in sorted(kept_both, key=lambda r: (r["employer"], r["title"]))]
    out += ["", "## Walls", ""] + [f"- {w}" for w in walls]
    out += ["", "Liveness: the list endpoint is truth. This file does not quote the qualifications or the "
            "clearance line of a role; posting_census.py reads those from the posting."]
    with open(path, "w", encoding="utf-8") as f:
        f.write("\n".join(out) + "\n")

# ---------------------------------------------------------------- MAIN

def main():
    ap = argparse.ArgumentParser(description="Enumerate employers' open roles by ATS and gate them on the published band, place and clearance wording.")
    ap.add_argument("--config", default="config.json", help="the settings file (see config.example.json)")
    ap.add_argument("--only", help="comma-separated names from the settings file")
    ap.add_argument("--probe", help="domain: try each ATS list endpoint with a guessed slug")
    ap.add_argument("--discover", help="careers URL/domain: print the ATS fingerprints in its HTML")
    ap.add_argument("--candidates", action="store_true", help="also run the `candidates` section of the settings")
    ap.add_argument("--lane", action="store_true",
                    help="read details for titles in the lane only (iCIMS, Avature, Eightfold); "
                         "Workday and sitemap details are read only with this flag")
    ap.add_argument("--floor", type=int, help="pay floor for this run; default: pay_floor in the settings")
    ap.add_argument("--out", default="roles.csv", help="the CSV of kept roles (default: roles.csv)")
    ap.add_argument("--deep", action="store_true",
                    help="per-job detail fetch (Greenhouse salary) for every row. Slow.")
    ap.add_argument("--cap", type=int, default=400,
                    help="most rows or detail pages read per employer by the adapters that take a cap "
                         "(iCIMS, Workday details, Avature, sitemap); 0 = no cap, though Avature still "
                         "stops at 200 pages (default: 400)")
    ap.add_argument("--delta", help="write a markdown delta: the band gate against the title gate in the settings")
    a = ap.parse_args()

    sess = requests.Session()
    if a.probe: probe(a.probe, sess); return          # these two need no settings: they are how a
    if a.discover: discover(a.discover, sess); return  # route is found before it is written down

    try:
        configure(sweep_settings.load(a.config, known_ats=KINDS))
    except sweep_settings.SettingsError as e:
        sys.exit(f"settings: {e}")
    if a.delta and not S.title_gate:
        sys.exit("settings: --delta needs a `title_gate` section (pass, fail) to compare the band gate with")
    floor = S.pay_floor if a.floor is None else a.floor

    targets = dict(S.employers)
    if a.candidates: targets.update(S.candidates)
    if a.only:
        wanted = [x for x in a.only.split(",") if x]
        missing = [x for x in wanted if x not in targets]
        if missing:   # say so: a name skipped without a word reads as an employer with no roles
            print(f"  --only names not defined (a candidate needs --candidates): {', '.join(missing)}")
        targets = {k: v for k, v in targets.items() if k in wanted}
    # An entry that is never fetched is a standing wall: it is listed on every run, whatever
    # --only and --candidates say, so that its absence from the results is never read as a result.
    for k, v in {**S.employers, **S.candidates}.items():
        if v[0] in sweep_settings.NOT_FETCHED: targets.setdefault(k, v)

    all_rows, walls = [], []
    for name, (kind, arg) in targets.items():
        if kind in sweep_settings.NOT_FETCHED:
            walls.append(f"{name}: {kind}: {arg}" + ("; run --discover" if kind == "unknown" else ""))
            print("  " + walls[-1]); continue
        try:
            rows, note = ADAPTERS[kind](arg, sess, deep=a.deep, cap=a.cap, lane=S.lane if a.lane else None)
        except Exception as e:
            rows, note = [], f"{name}: {type(e).__name__} {e}"
        walls.append(note); print("  " + note)
        for r in rows:
            for k in ("title", "location", "text", "req", "url"):   # an API's explicit null is not a string
                r[k] = r.get(k) or ""
            hay = f"{r['title']} {r['text']}"
            b = bands(hay)
            ctx, lo, hi = metro_band(b)
            src = "text" if hi else ""
            # JSON-LD baseSalary is the posting-wide range; a metro-labelled text band is the metro figure and wins.
            if r.get("ld_low") and not (ctx and S.metro.search(ctx)):
                lo, hi, ctx, src = r["ld_low"], r["ld_high"], "JSON-LD", "JSON-LD"
            if r.get("pay_high"): lo, hi, ctx, src = r["pay_low"], r["pay_high"], r["pay_ctx"], r["pay_src"]
            r.update(employer=name, clearance=clearance_verdict(hay),
                     band_ctx=ctx or "", band_low=lo or "", band_high=hi or "", band_src=src,
                     band_top_all=max([t[2] for t in b] + [int(hi or 0)]) or "")
            all_rows.append(r)

    best = {}
    for r in all_rows:                       # cross-posts collapse on employer+req; the URL when there is no req.
        k = (r["employer"], r["req"] or r["url"])
        # Of two rows with one req, the one that passes the gates is kept: a requisition posted
        # for another city first must not hide the same requisition posted for home.
        if k not in best or (not keep(best[k], floor) and keep(r, floor)): best[k] = r
    uniq = list(best.values())

    hits = sorted([r for r in uniq if keep(r, floor)],
                  key=lambda r: -(int(r["band_high"]) if str(r["band_high"]).isdigit() else 0))

    cols = ["employer", "req", "title", "location", "clearance", "band_low", "band_high",
            "band_ctx", "band_src", "band_top_all", "posted", "updated", "deadline", "valid_through",
            "openings", "listed", "url"]
    with open(a.out, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=cols, extrasaction="ignore")
        w.writeheader(); w.writerows(hits)

    if a.delta:
        write_delta(a.delta, uniq, floor, walls, sorted(targets))
        print(f"delta written: {a.delta}")

    over = [r for r in hits if str(r["band_high"]).isdigit() and int(r["band_high"]) >= floor]
    print(f"\n{len(uniq)} enumerated -> {len(hits)} pass the gates -> "
          f"{len(over)} clear ${floor:,}")
    if S.drop_active_clearance:
        n = sum(1 for r in uniq if keep(r, floor, clearance=False) and not keep(r, floor))
        print(f"left out by the clearance choice (\"drop\"): {n} that pass every other gate and ask for an active clearance")
    print(f"written: {a.out}\n\nWALLS (a wall is a finding, not an empty board):")
    for w_ in walls: print("  " + w_)
    print("\nLiveness: the LIST endpoint is truth. A detail page that still renders "
          "is NOT evidence a req is open.")

if __name__ == "__main__":
    main()
