#!/usr/bin/env python3
"""Offline check of job_scanner.py: the band readers, the gates, each adapter and a whole run.
No network: fake sessions serve fixtures in the response shapes the adapters expect. Everything
in the fixtures is made up (employers, titles, places, figures), except the from/up-to sentence
form, which is the one amazon.jobs prints. The settings are
config.example.json. A pass proves the code path, not that any role is open or that any route
answers today.

  python3 tests/test_gates.py
"""
import contextlib, csv, datetime, io, json, os, sys, tempfile
HERE = os.path.dirname(os.path.abspath(__file__)); ROOT = os.path.dirname(HERE); sys.path.insert(0, ROOT)
import job_scanner as js
import sweep_settings

EXAMPLE = os.path.join(ROOT, "config.example.json")
OK = True


def check(cond, msg):
    global OK
    print(("ok   " if cond else "FAIL ") + msg)
    OK = OK and bool(cond)
    return cond


def example():
    with open(EXAMPLE, encoding="utf-8") as fh:
        return json.load(fh)


def settings(**change):
    """The example settings, with whole top-level sections replaced for one test."""
    d = example(); d.update(change)
    return sweep_settings.Settings(d, known_ats=js.KINDS)


class Resp:
    def __init__(self, data=None, status=200, text=""):
        self.data, self.status_code, self.text = data if data is not None else {}, status, text
        self.headers, self.url = {}, ""
    def json(self):
        return self.data


class NotJSON(Resp):
    def json(self): raise ValueError("no json")


class Cookie:
    def __init__(self, name, value, domain=""): self.name, self.value, self.domain = name, value, domain


def ld_page(place="Boulder", extra="", description="Secret clearance preferred. $150,000 - $180,000"):
    return ('<html><script type="application/ld+json">{"@type":"JobPosting","title":"x","datePosted":"2026-09-01",'
            '"jobLocation":[{"@type":"Place","address":{"addressLocality":"%s","addressRegion":"CO","addressCountry":"US"}}],'
            '%s"description":"%s"}</script></html>' % (place, extra, description))


LD_PAGE = ld_page()


# ------------------------------------------------------------------ the band readers
def test_bands():
    check(js.bands(js.strip_html("&lt;p&gt;$210,000&amp;mdash;$260,000&lt;/p&gt;")) != [], "escaped Greenhouse content yields a band")
    check(js.strip_html("Pay: $210,000&amp;mdash;$260,000 USD") == "Pay: $210,000—$260,000 USD",
          "escaped content with no tag still unescapes")
    check(js.strip_html("<p>if a &lt; b then</p> keep") == "if a < b then keep", "raw HTML with a literal &lt; keeps the text after it")
    check(js.strip_html("<p>Pay</p><script>var a = '$150,000 - $190,000';</script><style>p{}</style> here") == "Pay here",
          "the bodies of script and style tags are not posting text")
    check([x[1:] for x in js.bands("Pay $150,000 to $190,000")] == [(150000, 190000)], "'to' joins a range as a dash does")
    words = ("bonus", "sign-on", "equity", "stock", "RSU", "relocation", "commission", "incentive", "stipend", "allowance")
    check(all([x[1:] for x in js.bands(f"Base $150,000 - $190,000. {w.capitalize()} $40,000 - $60,000.")] == [(150000, 190000)] for w in words),
          "a range introduced by any of ten words is not a salary: " + ", ".join(words))
    check([x[1:] for x in js.bands(js.strip_html("Pay Range: $120,000.00&nbsp;-&nbsp;$150,000.00"))] == [(120000, 150000)],
          "a band with cents and non-breaking spaces around the dash is read after strip_html")
    check(js.bands("Pay $20,000 - $28,000 a year") == [] and [x[1:] for x in js.bands("Pay $30,000 - $45,000 a year")] == [(30000, 45000)],
          "a range that starts under $30,000 is not a band; one that starts at $30,000 is")
    check(js.bands("Pay $1,500,000 - $2,500,000") == [], "a range that tops out over $2,000,000 is not a band")
    check([x[1:] for x in js.bands("Base $180,000 - $215,000. Sign-on bonus $30,000 - $50,000.")] == [(180000, 215000)],
          "a range labelled bonus is not a band, whatever its size")
    check([x[1:] for x in js.bands("Range $150,000 - $190,000 plus $40,000 - $60,000 in equity")] == [(150000, 190000)],
          "a range followed by 'in equity' is not a band")
    check([x[1:] for x in js.bands("The salary range is $150,000 - $190,000 in addition to a bonus.")] == [(150000, 190000)],
          "'in addition to a bonus' after a salary range does not remove it")
    b = js.bands("$195,000 - $245,000 in New York, $170,000 - $210,000 in Denver, and $150,000 - $190,000 elsewhere")
    check(js.metro_band(b)[1:] == (170000, 210000), f"'in <place>' after a range labels that range, not the next one ({js.metro_band(b)})")
    b = js.bands("$150,000 - $190,000 in Denver, $195,000 - $245,000 in New York")
    check(js.metro_band(b)[1:] == (150000, 190000), "trailing labels: the Denver range is the first one here")
    b = js.bands("New York: $195,000 - $245,000; Denver: $170,000 - $210,000; Other: $120,000 - $150,000")
    check(js.metro_band(b)[1:] == (170000, 210000), "'<place>:' before a range still labels it, and beats the lowest top")
    b = js.bands("Zone A $195,000 - $245,000 Zone B $120,000 - $150,000")
    check(js.metro_band(b)[1:] == (120000, 150000), "no home label: the lowest top, never the max")
    b = js.bands("Remote: $180,000 - $215,000; Denver: $100,000 - $130,000")
    check(js.metro_band(b)[1:] == (100000, 130000), "a place label beats a remote label, though the remote range is higher")
    b = js.bands("Remote: $100,000 - $130,000; Denver: $180,000 - $215,000")
    check(js.metro_band(b)[1:] == (180000, 215000), "a place label beats a remote label, though the remote range is lower")
    b = js.bands("Denver senior: $190,000 - $240,000; Denver: $150,000 - $190,000; Zone B: $100,000 - $120,000")
    check(js.metro_band(b)[1:] == (150000, 190000), "two ranges labelled with a home place: the lower top of the two")
    b = js.bands("Remote: $150,000 - $170,000; Zone B: $100,000 - $120,000")
    check(js.metro_band(b)[1:] == (150000, 170000), "no place label: a range labelled remote beats a lower range with no home label")
    b = js.bands("The base pay for this position ranges from $105,000/year in our lowest geographic market up to $195,000/year in our highest geographic market.")
    check(b and b[0][1:] == (105000, 195000) and "not a metro band" in b[0][0], f"the from/up-to form is read and labelled ({b})")
    check(js.bands("Pay ranges from $10,000 in our lowest market up to $20,000 in our highest market.") == [], "the from/up-to form keeps the $30,000 bound")

    check(js.ashby_band({"compensationTierSummary": "$195K – $300K • Offers Equity"})[1:] == (195000, 300000),
          "Ashby tier summary with K suffix and en dash")
    check(js.ashby_band({"summaryComponents": [{"compensationType": "Salary", "interval": "1 HOUR", "currencyCode": "USD",
                         "minValue": 90, "maxValue": 110}], "compensationTiers": [{"tierSummary": "$90 – $110 / hour"}]})[1:]
          == (187200, 228800), "Ashby hourly component annualised; the hourly tier text does not override it")
    check(js.ashby_band({"compensationTierSummary": "$45 – $60 per hour"}) is None, "Ashby sub-$30k text range ignored, not a $60 band")
    comp = lambda **c: {"summaryComponents": [dict({"compensationType": "Salary", "interval": "1 YEAR", "currencyCode": "USD",
                                                   "minValue": 100000, "maxValue": 150000}, **c)]}
    check(js.ashby_band(comp())[1:] == (100000, 150000) and js.ashby_band(comp(currencyCode="EUR")) is None
          and js.ashby_band(comp(compensationType="Equity")) is None, "Ashby: a component in another currency, or one that is not salary, is not read")
    check(js.ashby_band(comp(interval="1 WEEK", minValue=2000, maxValue=3000))[1:] == (104000, 156000)
          and js.ashby_band(comp(interval="2 WEEKS", minValue=4000, maxValue=6000))[1:] == (104000, 156000)
          and js.ashby_band(comp(interval="1 DAY", minValue=400, maxValue=600))[1:] == (104000, 156000),
          "Ashby: weekly, fortnightly and daily components annualised")
    check(js.ashby_band(comp(interval="6 MONTHS", minValue=70000, maxValue=90000))[1:] == (140000, 180000) and
          js.ashby_band({"compensationTierSummary": "$0.4M – $0.5M"})[1:] == (400000, 500000),
          "Ashby: a six-month component annualised; a summary in millions read")
    check(js.ashby_band({"compensationTiers": [{"title": "Tier 1", "components": [{"compensationType": "Salary", "interval": "1 MONTH",
                         "currencyCode": "USD", "minValue": 20000, "maxValue": 25000}], "tierSummary": "$20K – $25K"}]})[1:] == (240000, 300000),
          "Ashby tier components read structurally and annualised")
    check(js.ashby_band({"summaryComponents": [{"compensationType": "Salary", "interval": "1 YEAR", "currencyCode": "USD", "minValue": 150000, "maxValue": 190000}],
                         "compensationTiers": [{"title": "Tier 2", "tierSummary": "$100K – $120K"}]})[1:] == (150000, 190000),
          "Ashby: a tier's text summary is not read when a structured component exists")
    zones = [{"min_cents": 11000000, "max_cents": 13500000, "currency_type": "USD", "title": "Zone 1 (Coastal)"},
             {"min_cents": 15000000, "max_cents": 18000000, "currency_type": "USD", "title": "Zone 2 (Denver)"}]
    check(js.greenhouse_band(zones)[1:] == (150000, 180000), "Greenhouse picks the zone labelled with a home place, though another zone has the lowest top")
    check(js.greenhouse_band(zones[:1])[1:] == (110000, 135000) and js.greenhouse_band([dict(zones[0], currency_type="EUR")]) is None,
          "Greenhouse: one zone is that zone; a zone in another currency is not read")
    fl = js.greenhouse_band([{"min_cents": 15000000.0, "max_cents": 18000000.0, "title": "Zone 1"}])
    check(fl[1:] == (150000, 180000) and isinstance(fl[2], int), "Greenhouse: cents given as floats still give whole dollars")
    check(js.greenhouse_band([{"min_cents": 9000, "max_cents": 11000, "title": "Hourly"}]) is None,
          "Greenhouse: a zone outside $30,000 to $2,000,000 a year (an hourly rate) is no band, not a band under the floor")

    usd = lambda **v: {"baseSalary": {"currency": "USD", "value": v}}
    check(js.ld_band(usd(minValue=100000, maxValue=150000, unitText="YEAR")) == (100000, 150000), "JSON-LD yearly range")
    check(js.ld_band(usd(minValue=45, maxValue=60, unitText="HOUR")) == (93600, 124800)
          and js.ld_band(usd(minValue=45, maxValue=60, unitText="Hourly")) == (93600, 124800), "JSON-LD hourly range annualised, 'HOUR' or 'Hourly'")
    check(js.ld_band(usd(minValue=400, maxValue=600, unitText="DAY")) == (104000, 156000)
          and js.ld_band(usd(minValue=2000, maxValue=3000, unitText="WEEK")) == (104000, 156000)
          and js.ld_band(usd(minValue=10000, maxValue=12000, unitText="MONTH")) == (120000, 144000), "JSON-LD daily, weekly and monthly ranges annualised")
    check(js.ld_band(usd(minValue=400, maxValue=600, unitText="DAILY")) == (104000, 156000)
          and js.ld_band(usd(minValue=2000, maxValue=3000, unitText="WEEKLY")) == (104000, 156000)
          and js.ld_band(usd(minValue=10000, maxValue=12000, unitText="MONTHLY")) == (120000, 144000), "JSON-LD 'DAILY', 'WEEKLY' and 'MONTHLY' read the same way")
    today = datetime.date.today()
    check(not js.ld_expired({"validThrough": today.isoformat()}) and js.ld_expired({"validThrough": (today - datetime.timedelta(days=1)).isoformat()})
          and not js.ld_expired({}), "validThrough: yesterday is expired, today is not, none is not")
    class OnePage:
        def __init__(self, text): self.text = text
        def get(self, url, **_): return Resp(text=self.text)
    r = js.enrich_from_page(dict(url="u", req="1", text="", location=""), OnePage(ld_page(extra='"identifier":{"@type":"PropertyValue","value":"REQ-77"},')))
    check(r["req"] == "REQ-77" and r["_detail"] == "ok", "a job page's JSON-LD identifier replaces the req read from the list")
    r = js.enrich_from_page(dict(url="u", req="1", text="", location=""), OnePage('<script type="application/ld+json">{"@type":"JobPosting","datePosted":null,"validThrough":null,"description":"x"}</script>'))
    check(r["posted"] == "" and r["valid_through"] == "", "JSON-LD dates given as null are empty cells, not the word None")
    r = js.enrich_from_page(dict(url="u", req="1", text="", location=""), OnePage("<html><body><p>Pay $150,000 - $190,000 in Denver</p><script>x()</script></body></html>"))
    check(r["text"].strip() == "Pay $150,000 - $190,000 in Denver" and r["_detail"] == "ok", "a job page with no JSON-LD is read as its text")
    check(js.ld_band({"baseSalary": {"currency": "GBP", "value": {"minValue": 90000, "maxValue": 120000, "unitText": "YEAR"}}}) is None,
          "JSON-LD in another currency is not read as dollars")
    check(js.ld_band(usd(minValue=45, maxValue=60)) is None, "JSON-LD with no unit and a two-digit figure is out of bounds, not a $60 band")
    check(js.ld_band({"baseSalary": {"value": {"value": 150000, "unitText": "YEAR"}}}) == (150000, 150000), "JSON-LD single value, no currency stated")
    check(js.ld_location({"jobLocation": "Boulder, CO"}) == "Boulder, CO", "JSON-LD jobLocation as a plain string")
    check(js.ld_location({"jobLocation": {"address": {"addressLocality": "Boulder", "addressRegion": "CO"}},
                          "jobLocationType": "TELECOMMUTE"}) == "Boulder, CO; Remote", "JSON-LD jobLocation object + TELECOMMUTE")


# ------------------------------------------------------------------ the gates
def test_gates():
    for loc, want in (("Remote - United Kingdom", False), ("Bangalore - Remote", False), ("Ontario - Remote", False),
                      ("Remote - Spain", False), ("US - Remote", True), ("Remote - California", True), ("Remote - Denver", True),
                      ("Denver, CO; Seattle", True), ("Australia - Remote; Sydney, Australia", False),
                      ("London, UK; Remote - US", True), ("San Francisco, CA", False),
                      ("Remote, U.S. or Canada", True), ("Remote - Canada", False), ("", False),
                      ("Remote - Canada; Remote - US", True), ("Remote - Canada | Remote - Spain", False), ("Remote; Toronto, Canada", True),
                      ("San Francisco, CA (not remote)", False), ("Non-Remote; Austin, TX", False),
                      ("On-site only, no remote - Chicago", False), ("Denver, CO (not remote)", True),
                      ("Remote, London (join us)", False)):
        check(js.in_metro(loc) is want, f"place gate: {loc!r} -> {want}")
    row = lambda **kw: dict({"clearance": "NONE STATED", "title": "Controller", "location": "Denver, CO", "band_high": "", "band_ctx": ""}, **kw)
    check(js.keep(row(), 140000), "a home posting with no band passes")
    check(js.keep(row(band_high=140000), 140000) and not js.keep(row(band_high=139999), 140000), "the floor drops a band that tops out under it, and only that")
    check(not js.keep(row(title="Accounting Intern"), 140000) and not js.keep(row(title="Jr. Accountant"), 140000), "junior titles are dropped whatever the band")
    check(not js.keep(row(expired="YES"), 140000), "an expired posting is dropped")
    check(not js.keep(row(listed="UNLISTED"), 140000), "an unlisted posting is dropped")
    check(not js.keep(row(unread="YES"), 140000), "a row that was listed but never read is dropped")
    check(not js.keep(row(location="New York, NY", band_ctx="The range for remote employees is"), 140000),
          "a pay line about remote employees does not put a posting in another city through the place gate")
    check(js.keep(row(location="12 Locations", band_ctx="Zone 2 (Denver)"), 140000), "a band labelled with a home place does")
    check(not js.keep(row(location=None, title=None), 140000), "a row with no location and no title is dropped, not a crash")
    check(js.title_gate({"title": "Senior Controller"}) and not js.title_gate({"title": "Controller"}) and not js.title_gate({"title": "Senior Intern"}),
          "the title gate --delta compares with: a pass word passes, no pass word fails, a fail word fails whatever else the title says")

    hard = row(clearance="ACTIVE REQUIRED")
    check(js.clearance_verdict("Must hold an active TS/SCI clearance.") == "ACTIVE REQUIRED"
          and js.clearance_verdict("Ability to obtain a Secret clearance.") == "OBTAINABLE"
          and js.clearance_verdict("Close the books.") == "NONE STATED", "clearance wording read three ways")
    check(js.clearance_verdict("An existing Secret clearance is needed.") == "ACTIVE REQUIRED"
          and js.clearance_verdict("TS/SCI with full-scope polygraph.") == "ACTIVE REQUIRED", "ACTIVE REQUIRED: 'existing', and a level followed by 'polygraph'")
    check(js.clearance_verdict("A public trust position.") == "OBTAINABLE" and js.clearance_verdict("Must be a U.S. citizen.") == "OBTAINABLE"
          and js.clearance_verdict("A suitability review applies.") == "OBTAINABLE", "OBTAINABLE: public trust, suitability, citizenship")
    check(js.clearance_verdict("Ability to obtain a clearance. An active Secret clearance is a plus.") == "ACTIVE REQUIRED",
          "the sweep's one verdict: wording about an active clearance wins over wording about obtaining one")
    check(js.keep(hard, 140000), 'clearance "keep": a posting that asks for an active clearance stays, with its verdict')
    js.configure(settings(clearance={"when_active_required": "drop"}))
    check(not js.keep(hard, 140000), 'clearance "drop": the same posting is dropped')
    js.configure(settings(metro={"places": ["denver"], "accept_remote": False}))
    check(not js.in_metro("Remote - US") and js.in_metro("Denver, CO; Remote"), "accept_remote false: remote alone is not home, a home place still is")
    js.configure(settings())

    d0 = tempfile.mkdtemp(); p0 = os.path.join(d0, "d.md")
    rows = [row(employer="e", req="1", band_low="", band_high=185000, band_ctx="pay", band_src="text", url="u1"),
            row(employer="e", req="2", title="Senior Controller", unread="YES", band_low="", band_src="", url="u2"),
            row(employer="e", req="3", title="Senior Controller", location="Remote - United Kingdom", band_low="", band_src="", url="u3"),
            row(employer="e", req="4", title="Senior Controller", band_low=90000, band_high=120000, band_src="text", url="u4")]
    js.write_delta(p0, rows, 140000, [], ["e"])
    md = open(p0).read()
    check("$0 - $185,000" in md, "write_delta survives an empty band_low")
    check("## Dropped by the band floor, passed by the title gate (1)" in md and "| u4 |" in md and "| u2 |" not in md and "| u3 |" not in md,
          "the delta's dropped list holds only rows the floor dropped: not an unread row, not a row outside the place gate")


# ------------------------------------------------------------------ one adapter at a time
class RouteSession:
    """Phenom widget (csrf cookie + HTML token, 250 hits where paging stops at 100 so facet slicing runs),
    an iCIMS sitemap with JSON-LD locations, the Eightfold search with position_details, amazon.jobs with
    no `hits` key and a 400 past the cap, a Workday tenant that reports total only on page 0, a
    Avature site given by its base URL, and a SuccessFactors RSS feed."""
    def __init__(self):
        self.cookies = [Cookie("PHPPPE_CSRF", "COOKIETOK")]
        self.posts, self.gets, self.params = [], [], []
    def get(self, url, params=None, **kw):
        params = params or {}
        self.gets.append((url, kw.get("headers") or {})); self.params.append((url, params))
        if url.endswith("/us/en/search-results"):
            return Resp(text='<script>phApp = {"csrfToken":"HTMLTOK","refNum":"EXAMPLUS"}</script>')
        if "icims.com/sitemap.xml" in url:
            return Resp(text="".join(f"<loc>https://c.icims.com/jobs/{i}/{t}/job</loc>" for i, t in
                                     enumerate(["audit-team-manager", "janitor", "cpa-lead"])))
        if "icims.com/jobs/" in url:
            return Resp(text=LD_PAGE)
        if "/api/pcsx/search" in url:
            pos = [{"id": 7, "name": "Audit Manager", "standardizedLocations": ["Boulder, CO"], "displayJobId": "R-7",
                    "canonicalPositionUrl": "https://tenant.eightfold.ai/careers/job/7"},
                   {"id": 8, "name": "Cook", "standardizedLocations": ["Boulder, CO"], "displayJobId": "R-8"},
                   {"id": 9, "name": "Audit Lead", "standardizedLocations": ["Paris, France"], "displayJobId": "R-9"}]
            return Resp({"data": {"positions": pos if params["start"] == 0 else [], "count": 3}})
        if "/api/pcsx/position_details" in url:
            assert params["position_id"] == "7" and params["domain"] == "tenant.example", params
            return Resp({"data": {"jobDescription": "<p>Active TS/SCI required. $165,000 - $195,000</p>"}})
        if "amazon.jobs" in url:
            assert params.get("business_category[]") == "cat" and params.get("base_query") == "query words"
            off = params["offset"]
            if off >= 150: return Resp({}, 400)
            n = 100 if off == 0 else 50
            jobs = [{"id_icims": str(off + i), "title": "Controller", "normalized_location": "Seattle, WA",
                     "locations": ['{"normalizedLocation":"Denver, CO"}'], "basic_qualifications": "- 7+ years",
                     "job_path": f"/en/jobs/{off + i}"} for i in range(n)]
            return Resp({"jobs": jobs})          # no `hits` key on purpose
        if "careers.example.com/portal/careers/SearchJobs/" in url:
            off = int(url.split("jobOffset=")[1])
            return Resp(text='<a href="/portal/careers/JobDetail/Audit-Lead/123">x</a>' if off == 0 else "")
        if "careers.example.com/portal/careers/JobDetail/" in url:
            return Resp(text=LD_PAGE)
        if url.endswith("/sitemal.xml"):
            return Resp(text="<rss><channel><item><title>Audit Lead (Boulder, CO, US)</title><link>https://jobs.example.com/job/Boulder/Audit-Lead/39053/12345</link>"
                             "<description><![CDATA[<p>Teaser</p>]]></description><pubDate>Mon, 21 Sep 2026 00:00:00 GMT</pubDate></item>"
                             "<item><title>Tax Senior</title><link>https://jobs.example.com/job/x/Tax/1/9</link></item></channel></rss>")
        if "jobs.example.com/job/" in url:
            return Resp(text=LD_PAGE)
        return Resp({}, 404)
    def post(self, url, json=None, headers=None, **_):
        self.posts.append((url, json, headers or {}))
        if "myworkdayjobs.com" in url:
            off = json["offset"]
            rows = [{"title": f"Controller {off + i}", "externalPath": f"/job/Boulder-CO/x_{off + i}", "locationsText": "Boulder, CO",
                     "bulletFields": [f"R{off + i}"], "postedOn": "Posted Today"} for i in range(20)] if off < 60 else []
            return Resp({"total": 60 if off == 0 else 0, "jobPostings": rows})   # total only on page 0
        sel = (json.get("selected_fields") or {}).get("category")
        def jobs(prefix, n): return [{"jobSeqNo": f"{prefix}{i}", "title": f"Job {prefix}{i}", "jobUrl": f"/us/en/job/{prefix}{i}",
                                      "description": "Active TS/SCI required", "descriptionTeaser": "Join us"} for i in range(n)]
        if sel:
            n = {"Tax": 120, "Audit": 130}[sel[0]]
            chunk = jobs(sel[0], n)[json["from"]:json["from"] + 100]
            return Resp({"refineSearch": {"totalHits": n, "data": {"jobs": chunk}}})
        if json["from"] == 0:
            return Resp({"refineSearch": {"totalHits": 250, "data": {"jobs": jobs("Tax", 100),
                         "aggregations": [{"field": "category", "value": {"Tax": 120, "Audit": 130}}]}}})
        return Resp({"refineSearch": {"totalHits": 250, "data": {"jobs": []}}})


def test_adapters():
    lane = js.S.lane
    passes = lambda r: js.keep(dict({"clearance": "NONE STATED", "band_high": "", "band_ctx": ""}, **r), 140000)

    # ---- lever
    class LeverSession:
        def __init__(self): self.urls = []
        def get(self, url, **_):
            self.urls.append(url)
            if "api.lever.co" in url: return Resp({}, 404)          # an EU tenant: the first host does not know it
            skip = int(url.split("skip=")[1])
            if skip == 0:
                first = [{"id": "aaaaaaaa-1", "text": "Controller", "categories": {"location": "Denver, CO"}, "descriptionPlain": "x",
                          "salaryRange": {"min": 150000.0, "max": 190000.0, "currency": "USD", "interval": "per-year-salary"}, "createdAt": 1726000000 * 1000},
                         {"id": "bbbbbbbb-2", "text": "Clerk", "categories": {"location": None}, "descriptionPlain": "x",
                          "salaryRange": {"min": 45000, "max": 60000, "currency": "USD", "interval": "per-month-salary"}},
                         {"id": "cccccccc-3", "text": "Auditor", "categories": None, "descriptionPlain": "x",
                          "salaryRange": {"min": 90000, "max": 120000, "currency": "GBP", "interval": "per-year-salary"}}]
                return Resp(first + [{"id": f"{i:08d}", "text": "x"} for i in range(97)])
            return Resp([{"id": f"p{i:07d}", "text": "y"} for i in range(30)] if skip == 100 else [])
    ls = LeverSession(); rows, note = js.lever("slug", ls)
    check(len(rows) == 130 and "api.eu.lever.co" in ls.urls[-1] and ls.urls[-1].endswith("skip=100"), f"lever: pages by 100 until a short page; falls back to the EU host ({note})")
    check([x[1:] for x in js.bands(rows[0]["text"])] == [(150000, 190000)] and rows[0]["posted"] == "2024-09-10",
          "lever: a yearly dollar salaryRange is read as the band, also when its figures are floats; createdAt as the date")
    check(js.bands(rows[1]["text"]) == [] and js.bands(rows[2]["text"]) == [], "lever: a range that is not per year, and a range in another currency, are not read as yearly dollar salaries")
    check(rows[1]["location"] == "" and rows[2]["location"] == "", "lever: a null location or null categories is an empty string")

    # ---- greenhouse fingerprint
    check(js.re.findall(js.ATS_FINGERPRINTS[5][1], 'src="https://boards.greenhouse.io/embed/job_board/js?for=boardone" https://job-boards.greenhouse.io/boardtwo '
                        'https://boards.greenhouse.io/embed/job_app?token=123&for=Board_3')
          == ["boardone", "boardtwo", "Board_3"], "greenhouse fingerprint reads the embed forms, and a token with capitals or an underscore")
    check(js.re.findall(js.ATS_FINGERPRINTS[0][1], "https://acme.wd5.myworkdayjobs.com/wday/cxs/acme/External/jobs https://acme.wd5.myworkdayjobs.com/en-US/External") == [("acme", "wd5", "External")],
          "workday fingerprint: the API path is not read as a site name")
    check(js.re.findall(js.ATS_FINGERPRINTS[5][1], "https://boards.greenhouse.io/embed/job_board?x=1 https://boards.greenhouse.io/acme") == ["acme"],
          "greenhouse fingerprint: an embed URL that names no board gives no token, never the word 'embed'")

    # ---- eightfold
    class PX:
        def get(self, url, params=None, **_):
            if "/api/pcsx/search" in url:
                st = params["start"]; return Resp({"data": {"positions": [{"id": st + i, "name": "x"} for i in range(10)] if st < 30 else []}})
            return Resp({}, 404)
    rows, note = js.eightfold("t|t.example", PX())
    check(len(rows) == 30 and "count missing" in note, f"eightfold without count pages until empty ({note})")
    class PX2:
        def get(self, url, params=None, **_):
            if "/api/pcsx/search" in url and params["start"] == 0:
                return Resp({"data": {"count": 1, "positions": [{"id": 5, "name": "x", "positionUrl": "https://t.eightfold.ai/careers/job/5", "postedTs": 1726000000 * 1000}]}})   # epoch milliseconds
            return Resp({"data": {"positions": []}})
    rows, _ = js.eightfold("t|t.example", PX2())
    check(rows[0]["url"] == "https://t.eightfold.ai/careers/job/5" and rows[0]["posted"] == "2024-09-10", "eightfold: absolute positionUrl kept, epoch-ms posted as a date")
    class PXcount:
        def __init__(self): self.urls = []
        def get(self, url, params=None, **_):
            self.urls.append(url)
            return Resp({"data": {"count": 10, "positions": [{"id": 100 + params["start"] + i, "name": "x"} for i in range(10)]}})
    px = PXcount(); rows, note = js.eightfold("careers.example.com|example.com", px)
    check(len(rows) == 10 and "of count 10" in note and "SHORT" not in note, "eightfold: paging ends at the reported count, though the service would return more")
    check(px.urls[0] == "https://careers.example.com/api/pcsx/search", "eightfold: a host with a dot in it is used as given")
    class PXshort:
        def get(self, url, params=None, **_):
            return Resp({"data": {"count": 300, "positions": [{"id": 100 + i, "name": "x"} for i in range(10)] if params["start"] == 0 else []}})
    rows, note = js.eightfold("t|t.example", PXshort())
    check(len(rows) == 10 and "SHORT: the list ended at 10 of a reported 300" in note, f"eightfold: a list that ends short of its reported count is flagged ({note})")
    rs = RouteSession()
    rows, note = js.eightfold("tenant|tenant.example", rs, lane=lane)
    check(len(rows) == 3 and "TS/SCI" in rows[0]["text"] and rows[0]["req"] == "R-7" and not rows[0].get("unread") and "1 home or remote rows read" in note,
          f"eightfold: the lane row at home is read from position_details ({note})")
    check(rows[1].get("unread") == "YES" and not passes(rows[1]), "eightfold: a home row outside the lane is marked unread and cannot pass")
    check(not rows[2].get("unread") and not passes(rows[2]), "eightfold: a row elsewhere is not read and fails the place gate")
    class PXfail(RouteSession):
        def get(self, url, params=None, **kw):
            if "/api/pcsx/position_details" in url: return Resp({}, 500)
            return RouteSession.get(self, url, params=params, **kw)
    rows, note = js.eightfold("tenant|tenant.example", PXfail(), lane=lane)
    check("1 detail reads FAILED" in note and rows[0].get("unread") == "YES", f"eightfold: a failed detail read is counted and the row stays unread ({note})")

    # ---- phenom widget
    class PH(RouteSession):
        def post(self, url, json=None, headers=None, **_):
            if json["from"] == 0: return Resp({"refineSearch": {"totalHits": 120, "data": {"jobs": [{"jobId": str(i)} for i in range(50)]}}})
            if json["from"] == 50: return Resp({"refineSearch": {"totalHits": 120, "data": {"jobs": [{"jobId": str(50 + i)} for i in range(50)]}}})
            if json["from"] == 100: return Resp({"refineSearch": {"totalHits": 120, "data": {"jobs": [{"jobId": str(100 + i)} for i in range(20)]}}})
            return Resp({"refineSearch": {"totalHits": 120, "data": {"jobs": []}}})
    rows, note = js.phenom_widget("https://careers.example.org", PH())
    check(len(rows) == 120, f"phenom widget advances by rows returned when pages are short ({note})")
    class PE(RouteSession):
        def post(self, url, json=None, headers=None, **_): return Resp({"status": 400, "message": "invalid refNum"})
    rows, note = js.phenom_widget("https://careers.example.org", PE())
    check(rows == [] and "without refineSearch" in note, f"phenom widget: 200 without refineSearch is a wall ({note})")
    check(js._phenom_total({"refineSearch": "error"}) == 0, "phenom widget: the total survives a non-dict refineSearch")
    class PHhtml(RouteSession):
        def post(self, url, json=None, headers=None, **_):
            r = NotJSON(text="<html/>"); r.headers = {"Content-Type": "text/html"}; return r
    rows, note = js.phenom_widget("https://careers.example.org", PHhtml())
    check(rows == [] and "non-JSON" in note, f"phenom widget: a 200 HTML page is a wall, not a crash ({note})")
    rs = RouteSession()
    rows, note = js.phenom_widget("https://careers.example.org", rs)
    hdr = rs.posts[0][2]
    rs.cookies.append(Cookie("PHPPPE_CSRF", "OTHER")); rs.cookies[-1].domain = "careers.other.example"
    js.phenom_widget("https://careers.example.org", rs)
    check(rs.posts[-1][2].get("x-csrf-token") == "COOKIETOK", "phenom widget: another tenant's csrf cookie is not sent")
    check(len(rows) == 250 and "EXAMPLUS" in note, f"phenom widget: facet slicing closes 100 -> 250 ({note})")
    check(hdr.get("x-csrf-token") == "COOKIETOK" and hdr.get("Origin") == "https://careers.example.org"
          and hdr["Referer"].endswith("/us/en/search-results"), "phenom widget: csrf cookie echoed, Origin and Referer set")
    check(rows[0]["url"] == "https://careers.example.org/us/en/job/Tax0", "phenom widget: relative jobUrl prefixed")
    check("TS/SCI" in rows[0]["text"], "phenom widget: full description read, not the teaser")

    # ---- workday
    class WD2k:
        def post(self, url, json=None, **_): return Resp({"total": 2000 if json["offset"] == 0 else 0, "jobPostings": [{"title": "x", "externalPath": f"/job/{json['offset']+i}"} for i in range(20)]})
    rows, note = js.workday("t|wd1|S", WD2k())
    check(len(rows) == 2000 and "CAPPED" in note, "workday: exactly 2,000 reported is flagged as capped")
    rows, note = js.workday("x|wd1|Ext", RouteSession())
    check(len(rows) == 60, f"workday: total kept from page 0, not a stop at 40 rows ({note})")
    check(all(r.get("unread") == "YES" for r in rows) and not any(passes(r) for r in rows) and "no row can pass" in note,
          "workday without --lane: no detail is read, every row is unread, none passes")
    class WDdetail:
        def __init__(self, status=200): self.status = status
        def post(self, url, json=None, **_):
            if json["offset"] > 0: return Resp({"total": 0, "jobPostings": []})
            return Resp({"total": 2, "jobPostings": [
                {"title": "Audit Team Manager", "externalPath": "/job/Boulder-CO/Audit-Team-Manager_R1", "locationsText": "2 Locations"},
                {"title": "Janitor", "externalPath": "/job/Boulder-CO/Janitor_R2", "locationsText": "Boulder, CO"}]})
        def get(self, url, **_):
            assert url.endswith("/wday/cxs/t/Site/job/Boulder-CO/Audit-Team-Manager_R1"), url
            return Resp({"jobPostingInfo": {"jobDescription": "<p>Pay: $170,000 - $210,000. Active TS/SCI required.</p>",
                         "location": "Boulder, CO", "additionalLocations": ["Remote - US"], "jobReqId": "R1"}}, self.status)
    rows, note = js.workday("t|wd1|Site", WDdetail(), lane=lane)
    check(rows[0]["text"].startswith("Pay: $170,000") and rows[0]["location"] == "Boulder, CO; Remote - US" and not rows[0].get("unread")
          and rows[1].get("unread") == "YES" and "1 lane rows read" in note and "FAILED" not in note and rows[0]["req"] == "R1",
          f"workday: the lane row is read from the detail endpoint; the other is not fetched and is marked unread ({note})")
    rows, note = js.workday("t|wd1|Site", WDdetail(500), lane=lane)
    check(rows[0].get("unread") == "YES" and "1 detail reads FAILED" in note, f"workday: a failed detail read is counted and the row stays unread ({note})")
    class WDcase:
        def __init__(self): self.urls = []
        def post(self, url, json=None, **_):
            self.urls.append(url)
            if "/external/jobs" in url: return NotJSON(text="<html/>")
            return Resp({"total": 1 if json["offset"] == 0 else 0, "jobPostings": [{"title": "x", "externalPath": "/job/1"}] if json["offset"] == 0 else []})
    rows, note = js.workday("tenant|wd1|external", WDcase())
    check(len(rows) == 1 and "'External' answered" in note, f"workday: lowercase site fails, title-case probe answers and is named ({note})")
    class WDdead:
        def post(self, url, **_): return NotJSON(text="<html/>")
    rows, note = js.workday("t|wd1|external", WDdead())
    check(rows == [] and "read the real site name" in note, f"workday: both site forms fail -> a wall, no crash ({note})")

    # ---- avature
    class AVloop:
        def get(self, url, **_): return Resp(text='<a href="/careers/JobDetail/x/1">x</a>') if "SearchJobs" in url else Resp(text="")
    rows, note = js.avature("t", AVloop(), cap=0)
    check(len(rows) == 1 and "STOPPED" not in note, "avature: a repeating page ends the loop under --cap 0, and that is not a bound stop")
    class AVlane:
        def __init__(self): self.fetched = 0
        def get(self, url, **_):
            if "SearchJobs" in url:
                return Resp(text='<a href="/careers/JobDetail/Audit-Lead/1">x</a><a href="/careers/JobDetail/Tax-Senior/2">y</a>' if "jobOffset=0" in url else "")
            self.fetched += 1; return Resp(text=LD_PAGE)
    av = AVlane(); rows, note = js.avature("t", av, cap=0, lane=lane)
    check(av.fetched == 1 and rows[1].get("unread") == "YES", f"avature: only lane rows fetched ({note})")
    class AVmany:
        def get(self, url, **_):
            if "SearchJobs" in url:
                off = int(url.split("jobOffset=")[1])
                return Resp(text="".join(f'<a href="/careers/JobDetail/Clerk/{off + i}">x</a>' for i in range(12)))
            return Resp({}, 403)
    rows, note = js.avature("t", AVmany(), cap=24)
    check(len(rows) == 24 and "STOPPED at --cap 24" in note and "24 detail reads FAILED" in note and "0 job pages read" in note,
          f"avature: a stop at the cap and failed detail reads are both in the note; a failed read is not counted as read ({note})")
    rows, note = js.avature("t", AVmany(), cap=30)
    check(len(rows) == 30 and "STOPPED at --cap 30" in note, "avature: a cap that is not a multiple of the page size cuts the last page")
    rows, note = js.avature("t", AVmany(), cap=0)
    check(len(rows) == 2400 and "STOPPED at the 200-page bound" in note, "avature: without a cap the list stops at 200 pages, and the note says so")
    rows, note = js.avature("https://careers.example.com/portal", RouteSession(), cap=0)
    check(len(rows) == 1 and rows[0]["url"] == "https://careers.example.com/portal/careers/JobDetail/Audit-Lead/123"
          and rows[0]["location"] == "Boulder, CO, US", f"avature: a full base URL, JSON-LD location ({note})")

    # ---- amazon
    class AMZ:
        def get(self, url, params=None, **_):
            return Resp({"jobs": [{"id_icims": "1", "title": "x", "basic_qualifications": ["7+ years"], "description": None}]} if params["offset"] == 0 else {"jobs": []})
    rows, _ = js.amazon("cat|x", AMZ())
    check("BASIC: 7+ years" in rows[0]["text"], "amazon: list-valued qualifications joined")
    rows, note = js.amazon("cat|query words", RouteSession())
    check(len(rows) == 150 and rows[0]["location"] == "Seattle, WA; Denver, CO" and "BASIC: - 7+ years" in rows[0]["text"]
          and "150 rows (hits not reported)" in note and "STOPPED: HTTP 400 at offset=150" in note,
          f"amazon: pages without `hits`; a 400 after the first page keeps the rows and is flagged as a stop; multi-location decoded ({note})")
    class AMZbig:
        def get(self, url, params=None, **_):
            return Resp({"hits": 25000, "jobs": [{"id_icims": str(params["offset"] + i), "title": "x"} for i in range(100)]})
    rows, note = js.amazon("cat|x", AMZbig())
    check(len(rows) == 10000 and "hits 25000" in note and "STOPPED at 10,000 rows" in note, "amazon: the stop at 10,000 rows is flagged, with the reported hits beside it")
    class AMZnohits:
        def get(self, url, params=None, **_):
            return Resp({"jobs": [{"id_icims": str(params["offset"] + i), "title": "x"} for i in range(100)]})
    rows, note = js.amazon("cat|x", AMZnohits())
    check(len(rows) == 10000 and "STOPPED at 10,000 rows" in note, "amazon: the stop at 10,000 rows is flagged when no hits are reported too")
    class AMZshort:
        def get(self, url, params=None, **_):
            return Resp({"hits": 500, "jobs": [{"id_icims": str(i), "title": "x"} for i in range(100)] if params["offset"] == 0 else []})
    rows, note = js.amazon("cat|x", AMZshort())
    check(len(rows) == 100 and "STOPPED short of the reported hits" in note, "amazon: a list that ends short of the reported hits is flagged")
    class AMZwall:
        def get(self, url, params=None, **_): return Resp({}, 400)
    rows, note = js.amazon("cat|x", AMZwall())
    check(rows == [] and "HTTP 400 on the first page" in note, f"amazon: a 400 on the first page is a wall, not an empty board ({note})")

    # ---- successfactors feed
    one = type("S", (), {"get": lambda self, url, **_: Resp(text="<item><title>Controller &amp; Treasurer (Excel)</title><link>https://h/job/1/1234</link></item>")
                         if url.endswith("sitemal.xml") else Resp(text=LD_PAGE)})()
    check(js.successfactors_rss("h", one)[0][0]["title"] == "Controller & Treasurer (Excel)", "successfactors: '(Excel)' is not split off as a location")
    rows, note = js.successfactors_rss("jobs.example.com", RouteSession())
    check(len(rows) == 2 and rows[0]["title"] == "Audit Lead" and rows[0]["location"] == "Boulder, CO, US"
          and "$150,000" in rows[0]["text"] and rows[0]["req"] == "12345" and rows[1].get("unread") == "YES" and "2 items in /sitemal.xml, 1 lane rows read" in note,
          f"successfactors: title location split off, lane row read, the other marked unread ({note})")

    class SFrefused(RouteSession):
        def get(self, url, params=None, **kw):
            if "jobs.example.com/job/" in url: return Resp({}, 403)
            return RouteSession.get(self, url, params=params, **kw)
    rows, note = js.successfactors_rss("jobs.example.com", SFrefused())
    check(rows[0].get("unread") == "YES" and not passes(rows[0]) and "0 lane rows read; 1 detail reads FAILED" in note,
          f"successfactors: a lane row whose page is refused is unread, cannot pass on the feed teaser, and is not counted as read ({note})")

    # ---- sitemap and icims
    class SM:
        def get(self, url, **_):
            if url.endswith("sitemap.xml"): return Resp(text="<loc>https://x.example/jobs/audit-team-manager/12345/</loc><loc>https://x.example/jobs/cook/12346/</loc>")
            return Resp(text=LD_PAGE)
    rows, note = js.sitemap("https://x.example/jobs_sitemap.xml", SM(), lane=lane)
    check(len(rows) == 2 and rows[0]["location"] == "Boulder, CO, US" and not rows[0].get("unread") and rows[1].get("unread") == "YES"
          and "1 lane rows read" in note, f"sitemap: lane row read, the other marked unread ({note})")
    rows, note = js.sitemap("https://x.example/jobs_sitemap.xml", SM())
    check(all(r.get("unread") == "YES" for r in rows) and "no row can pass" in note, "sitemap without --lane: every row unread, and the note says so")
    rows, note = js.icims("c", RouteSession(), cap=0, lane=lane)
    check(len(rows) == 2 and rows[0]["location"] == "Boulder, CO, US" and rows[1]["title"] == "Cpa Lead", f"icims: lane filter before fetch, JSON-LD location read ({note})")
    rows, note = js.icims("c", RouteSession(), cap=2)
    check(len(rows) == 2 and "CAPPED at 2" in note, f"icims: the cap is named in the note ({note})")
    class ICmix:
        def get(self, url, **_):
            if url.endswith("sitemap.xml"): return Resp(text="<loc>https://c.icims.com/about-us</loc><loc>https://c.icims.com/jobs/7/controller/job</loc>")
            return Resp(text=LD_PAGE)
    rows, note = js.icims("c", ICmix(), cap=0)
    check(len(rows) == 1 and "1 job URLs in sitemap" in note, "icims: a sitemap URL that is not a job page is not fetched")
    class SM3:
        def get(self, url, **_):
            if url.endswith("sitemap.xml"):
                return Resp(text="".join(f"<loc>https://x.example/jobs/audit-lead/{n}/</loc>" for n in (10001, 10002, 10003, 10004)))
            return Resp(text=LD_PAGE) if url.endswith("/10001/") else Resp({}, 403)
    rows, note = js.sitemap("https://x.example/jobs_sitemap.xml", SM3(), lane=lane, cap=3)
    check([r.get("unread") for r in rows] == ["", "YES", "YES", "YES"] and "1 lane rows read" in note and "2 detail reads FAILED" in note
          and "CAPPED at 3 of 4 lane rows" in note, f"sitemap: the cap is flagged; a row whose page was refused stays unread and is not counted as read ({note})")

    # ---- workday: stops, a missing total, a failure part-way, the detail path
    class WDbig:
        def post(self, url, json=None, **_):
            return Resp({"total": 5000 if json["offset"] == 0 else 0,
                         "jobPostings": [{"title": "x", "externalPath": f"/job/{json['offset'] + i}"} for i in range(20)]})
    rows, note = js.workday("t|wd1|S", WDbig())
    check(len(rows) == 2000 and "2000 of total 5000" in note and "STOPPED at 2,000 rows" in note and "CAPPED" not in note,
          "workday: paging stops at 2,000 rows whatever the total, and the note says the list is longer")
    class WDnototal:
        def post(self, url, json=None, **_):
            return Resp({"jobPostings": [{"title": "x", "externalPath": f"/job/{json['offset'] + i}"} for i in range(20)] if json["offset"] < 60 else []})
    rows, note = js.workday("t|wd1|S", WDnototal())
    check(len(rows) == 60 and "60 of total not reported" in note, f"workday: a first page with no total is paged until a page comes back empty ({note})")
    class WDhalf:
        def post(self, url, json=None, **_):
            if json["offset"] >= 40: return Resp({}, 502)
            return Resp({"total": 100 if json["offset"] == 0 else 0, "jobPostings": [
                {"title": "Controller", "externalPath": f"/job/{json['offset'] + i}", "locationsText": "Boulder, CO"} for i in range(20)]})
        def get(self, url, **_):
            return Resp({"jobPostingInfo": {"jobDescription": "x", "location": "Boulder, CO"}})
    rows, note = js.workday("t|wd1|S", WDhalf())
    check(len(rows) == 40 and all(r.get("unread") == "YES" for r in rows) and not any(passes(r) for r in rows)
          and "40 of total 100" in note and "STOPPED: HTTP 502 at offset=40" in note,
          f"workday: a failure part-way keeps the rows already listed, marks them unread, and says where it stopped ({note})")
    rows, note = js.workday("t|wd1|S", WDhalf(), lane=lane, cap=0)
    check(len(rows) == 40 and not any(r.get("unread") for r in rows) and "40 lane rows read" in note and "STOPPED: HTTP 502" in note,
          "workday: with --lane the rows listed before the failure are still read")
    class WDsame:
        def __init__(self): self.got = []
        def post(self, url, json=None, **_):
            return Resp({"total": 1 if json["offset"] == 0 else 0,
                         "jobPostings": [{"title": "Controller", "externalPath": "/job/Denver/Controller_R1"}] if json["offset"] == 0 else []})
        def get(self, url, **_):
            self.got.append(url); return Resp({"jobPostingInfo": {"jobDescription": "x"}})
    rows, note = js.workday("t|wd1|S", WDhalf(), lane=lane, cap=5)
    check(sum(1 for r in rows if not r.get("unread")) == 5 and "5 lane rows read from the detail endpoint (capped at 5)" in note,
          "workday: --cap bounds the detail reads, and the note says so")
    class WDshort:
        def post(self, url, json=None, **_):
            return Resp({"total": 100 if json["offset"] == 0 else 0,
                         "jobPostings": [{"title": "x", "externalPath": f"/job/{i}"} for i in range(20)] if json["offset"] == 0 else []})
    rows, note = js.workday("t|wd1|S", WDshort())
    check(len(rows) == 20 and "SHORT: the list ended at 20 of a reported 100" in note, f"workday: a list that ends short of its reported total is flagged ({note})")
    ws = WDsame(); js.workday("acme|wd5|acme", ws, lane=lane)
    check(ws.got == ["https://acme.wd5.myworkdayjobs.com/wday/cxs/acme/acme/job/Denver/Controller_R1"],
          "workday: the detail URL is built from the row's own path, also when the site is named like the tenant")

    # ---- eightfold: the bound, and a failure part-way
    class PXbig:
        def get(self, url, params=None, **_):
            return Resp({"data": {"count": 99999, "positions": [{"id": params["start"] + i, "name": "x"} for i in range(10)]}})
    rows, note = js.eightfold("t|t.example", PXbig())
    check(len(rows) == 5000 and "of count 99999" in note and "STOPPED at the 5,000-row bound" in note,
          "eightfold: the list stops at 5,000 rows; the note gives the reported count and the stop")
    class PXhalf:
        def __init__(self, detail=200): self.detail = detail
        def get(self, url, params=None, **_):
            if "/api/pcsx/search" in url:
                if params["start"] >= 10: return Resp({}, 500)
                return Resp({"data": {"count": 50, "positions": [{"id": i, "name": "Audit Lead", "standardizedLocations": ["Boulder, CO"]} for i in range(1, 11)]}})
            return Resp({"data": {"jobDescription": "<p>Text</p>"}}, self.detail)
    rows, note = js.eightfold("t|t.example", PXhalf())
    check(len(rows) == 10 and "of count 50" in note and "STOPPED: HTTP 500 at start=10" in note and "10 home or remote rows read" in note
          and not any(r.get("unread") for r in rows), f"eightfold: a failure part-way is flagged, and the rows already listed are still read ({note})")
    rows, note = js.eightfold("t|t.example", PXhalf(detail=500))
    check(all(r.get("unread") == "YES" for r in rows) and not any(passes(r) for r in rows),
          "eightfold: after a failure part-way, rows whose description could not be read are unread and cannot pass")

    # ---- phenom: a list that falls short of its total
    class PHshort(RouteSession):
        def post(self, url, json=None, headers=None, **_):
            return Resp({"refineSearch": {"totalHits": 500, "data": {"jobs": [{"jobId": str(i)} for i in range(100)] if json["from"] == 0 else []}}})
    rows, note = js.phenom_widget("https://careers.example.org", PHshort())
    check(len(rows) == 100 and "100 of totalHits 500" in note and "INCOMPLETE" in note and "5,000" not in note,
          f"phenom widget: a list under 90 percent of its total is marked INCOMPLETE ({note})")
    class PHnototal(RouteSession):
        def post(self, url, json=None, headers=None, **_):
            return Resp({"refineSearch": {"data": {"jobs": [{"jobId": str(json["from"] + i)} for i in range(100)] if json["from"] < 300 else []}}})
    rows, note = js.phenom_widget("https://careers.example.org", PHnototal())
    check(len(rows) == 300 and "300 of totalHits not reported" in note, f"phenom widget: with no total in the response, paging goes on until a page is empty ({note[:80]})")
    class PHhuge(RouteSession):
        total = 6000
        def post(self, url, json=None, headers=None, **_):
            return Resp({"refineSearch": {"totalHits": self.total, "data": {"jobs": [{"jobId": str(json["from"] + i)} for i in range(100)]}}})
    rows, note = js.phenom_widget("https://careers.example.org", PHhuge())
    check(len(rows) == 5000 and "INCOMPLETE" in note and "STOPPED: paging stops at 5,000 rows" in note, "phenom widget: paging stops at 5,000 rows, and the note says so")
    PHhuge.total = 5300
    rows, note = js.phenom_widget("https://careers.example.org", PHhuge())
    check(len(rows) == 5000 and "INCOMPLETE" not in note and "STOPPED: paging stops at 5,000 rows" in note,
          "phenom widget: the stop at 5,000 rows is flagged also when the list is over 90 percent of its total")

    # ---- a refused list call is a wall, for every adapter
    class Down:
        cookies = []
        def get(self, url, **_): return Resp({}, 503)
        def post(self, url, **_): return Resp({}, 503)
    for kind, spec in (("greenhouse", "b"), ("lever", "b"), ("ashby", "b"), ("icims", "b"), ("sitemap", "https://x.example/jobs_sitemap.xml"),
                       ("successfactors_rss", "jobs.example.com"), ("avature", "b"), ("eightfold", "t|t.example"), ("amazon", "cat|q"),
                       ("workday", "t|wd1|S"), ("phenom_widget", "https://careers.example.org")):
        rows, note = js.ADAPTERS[kind](spec, Down(), cap=0, lane=None, deep=False)
        check(rows == [] and "503" in note, f"{kind}: a refused list call returns no rows and a note with the status ({note[:70]})")

    # ---- phenom: the token in the page, a /global/ site; amazon: the country
    rs = RouteSession(); rs.cookies = []
    js.phenom_widget("https://careers.example.org", rs)
    check(rs.posts[0][2].get("x-csrf-token") == "HTMLTOK", "phenom widget: with no csrf cookie, the token in the search page is sent")
    class PHglobal(RouteSession):
        def get(self, url, params=None, **kw):
            if url.endswith("/us/en/search-results"): return Resp({}, 404)
            if url.endswith("/global/en/search-results"): return Resp(text='<script>phApp = {"refNum":"EXAMPLGLOBAL"}</script>')
            return RouteSession.get(self, url, params=params, **kw)
    rs = PHglobal(); js.phenom_widget("https://careers.example.org", rs)
    check(rs.posts[0][1]["country"] == "global" and rs.posts[0][1]["lang"] == "en_global" and rs.posts[0][1]["refNum"] == "EXAMPLGLOBAL"
          and rs.posts[0][2]["Referer"].endswith("/global/en/search-results"), "phenom widget: a site that answers only under /global/ is searched as 'global'")
    rs = RouteSession(); js.amazon("cat|query words", rs)
    check(all(p.get("country") == "USA" for u, p in rs.params) and len(rs.params) == 3, "amazon: every page of the search is fixed to the United States")

    # ---- spacing and headers
    sleeps, clock = [], js.time
    js.time = type("Clock", (), {"sleep": staticmethod(sleeps.append)})
    try:
        rs = RouteSession(); js.phenom_widget("https://careers.example.org", rs); phenom_gaps, phenom_posts = len(sleeps), len(rs.posts)
        del sleeps[:]; js.lever("slug", LeverSession()); lever_gaps = len(sleeps)
        class GHraise:
            def get(self, url, **_):
                if "pay_transparency" in url: raise RuntimeError("dropped")
                return Resp({"jobs": [{"id": i, "title": "Controller", "offices": [{"name": "Denver, CO"}], "content": ""} for i in (1, 2, 3)]})
        del sleeps[:]; rows, gh_note = js.greenhouse("b", GHraise()); gh_gaps = len(sleeps)
    finally:
        js.time = clock
    check(phenom_posts > 3 and phenom_gaps == phenom_posts - 1, f"phenom widget: a pause before every POST after the first, facet slices included ({phenom_posts} POSTs)")
    check(lever_gaps == 1, "lever: a pause between two pages of the list")
    check(gh_gaps == 3 and "3 detail reads FAILED" in gh_note, "greenhouse: a pay call that raises is counted, and is still followed by a pause")
    rs = RouteSession()
    js.eightfold("tenant|tenant.example", rs, lane=lane); js.icims("c", rs, cap=0, lane=lane)
    js.avature("https://careers.example.com/portal", rs, cap=0); js.successfactors_rss("jobs.example.com", rs)
    js.amazon("cat|query words", rs); js.workday("x|wd1|Ext", rs); js.phenom_widget("https://careers.example.org", rs)
    heads = [h for _, h in rs.gets] + [h for _, _, h in rs.posts]
    check(len(heads) > 20 and all("job_scanner/" in h.get("User-Agent", "") and h.get("Accept") for h in heads),
          f"every adapter request names the tool in its User-Agent and sends an Accept header ({len(heads)} requests)")


# ------------------------------------------------------------------ a whole run
GH_LIST = {"jobs": [
    {"id": 1, "title": "Revenue Cycle Manager", "offices": [{"name": "Denver, CO"}],
     "content": "&lt;p&gt;Pay range: $150,000&amp;mdash;$190,000 USD&lt;/p&gt;", "absolute_url": "u1"},
    {"id": 2, "title": "Billing Specialist", "offices": [{"name": "Boulder, CO"}],
     "content": "&lt;p&gt;Build.&lt;/p&gt;", "absolute_url": "u2"},
    {"id": 3, "title": "Senior Collections Manager", "offices": [{"name": "Aurora, CO"}],
     "content": "", "absolute_url": "u3"},
    {"id": 4, "title": "Staff Accountant", "offices": [{"name": "San Francisco, CA"}],
     "content": "", "absolute_url": "u4"},
    {"id": 5, "title": "Accounting Intern", "location": {"name": "Denver, CO"}, "content": "", "absolute_url": "u5"},
    {"id": 6, "title": "Payments Analyst", "offices": [{"name": "Denver, CO"}], "content": "", "absolute_url": "u6"},
    {"id": 7, "title": "Ledger Analyst", "location": {"name": "Denver, CO"}, "offices": [{"name": "Regional HQ"}, {"name": None}],
     "content": "", "absolute_url": "u7"},
    {"id": 8, "requisition_id": "REQ-9", "title": "Close Manager", "offices": [{"name": "London"}], "content": "", "absolute_url": "u8"},
    {"id": 9, "requisition_id": "REQ-9", "title": "Close Manager", "offices": [{"name": "Denver, CO"}], "content": "", "absolute_url": "u9"},
    {"id": 10, "title": "Vault Custodian", "offices": [{"name": "Denver, CO"}], "content": "Must hold an active TS/SCI clearance.", "absolute_url": "u10"},
    {"id": 11, "title": "Vault Custodian", "offices": [{"name": "London"}], "content": "Must hold an active TS/SCI clearance.", "absolute_url": "u11"},
    {"id": 12, "title": "Ledger Lead (active TS/SCI)", "offices": [{"name": "Denver, CO"}], "content": "", "absolute_url": "u12"},
]}
GH_THREE = {"jobs": [{"id": 31, "title": "Candidate Board Role", "offices": [{"name": "Denver, CO"}], "content": "", "absolute_url": "u31"}]}
GH_PAY = {
    2: {"pay_input_ranges": [{"min_cents": 11000000, "max_cents": 13500000, "currency_type": "USD", "title": "Zone 1 (Coastal)"},
                             {"min_cents": 15000000, "max_cents": 18000000, "currency_type": "USD", "title": "Zone 2 (Denver)"}]},
    3: {"pay_input_ranges": [{"min_cents": 10000000, "max_cents": 13000000, "currency_type": "USD", "title": "US"}]},
}
ASHBY = {"jobs": [
    {"id": "a1", "title": "Payroll Partner", "location": "Denver, CO", "isListed": True,
     "descriptionPlain": "x", "jobUrl": "o1",
     "compensation": {"compensationTierSummary": "$165K – $215K • Offers Equity"}},
    {"id": "a2", "title": "Payroll Specialist", "location": "Denver, CO", "isListed": True,
     "descriptionPlain": "x", "jobUrl": "o2",
     "compensation": {"summaryComponents": [{"compensationType": "Salary", "interval": "1 YEAR",
                                             "currencyCode": "USD", "minValue": 100000, "maxValue": 130000}]}},
    {"id": "a3", "title": "Tax Partner", "location": "Remote - US", "isListed": True,
     "descriptionPlain": "x", "jobUrl": "o3", "compensation": {}},
    {"id": "a4", "title": "Unlisted Role", "location": "Denver, CO", "isListed": False, "descriptionPlain": "x", "jobUrl": "o4"},
    {"id": "a1", "title": "Payroll Partner (cross-post)", "location": "Boulder, CO", "isListed": True, "descriptionPlain": "x", "jobUrl": "o5"},
    {"id": "a6", "title": None, "location": "Denver, CO", "isListed": True, "descriptionPlain": "x", "jobUrl": "o6"},
]}
IC_PAGES = {
    "21": ld_page("Denver", '"baseSalary":{"currency":"USD","value":{"minValue":100000,"maxValue":195000,"unitText":"YEAR"}},',
                  "Denver: $150,000 - $170,000. Elsewhere: $180,000 - $195,000."),
    "22": ld_page("Boulder", '"baseSalary":{"currency":"USD","value":{"minValue":145000,"maxValue":175000,"unitText":"YEAR"}},',
                  "Sign-on bonus $30,000 - $50,000."),
    "23": ld_page("Denver", '"validThrough":"2020-01-01",', "An old posting."),
}


class FakeSession:
    """Five employers: a Greenhouse board (one pay call fails), an Ashby board (one unlisted job, one
    cross-post), an iCIMS sitemap (one page refused, one posting expired), a jobs sitemap whose
    URLs carry no id, and a Lever board whose connection drops. One candidate Greenhouse board."""
    seen = []
    def get(self, url, headers=None, **_):
        FakeSession.seen.append((url, headers or {}))
        if "api.lever.co" in url:
            raise RuntimeError("the connection dropped")
        if "boards-api.greenhouse.io" in url and "/jobs/" in url:
            jid = int(url.split("/jobs/")[1].split("?")[0])
            if jid == 6: return Resp({}, 500)
            return Resp(GH_PAY.get(jid, {"pay_input_ranges": []}))
        if "boards-api.greenhouse.io" in url:
            return Resp(GH_THREE if "/boardthree/" in url else GH_LIST)
        if "api.ashbyhq.com" in url:
            return Resp(ASHBY)
        if "icims.com/sitemap.xml" in url:
            return Resp(text="".join(f"<loc>https://c.icims.com/jobs/{i}/{t}/job</loc>" for i, t in
                                     (("21", "controller"), ("22", "treasury-analyst"), ("23", "auditor"), ("24", "senior-accountant"))))
        if "icims.com/jobs/" in url:
            jid = url.split("/jobs/")[1].split("/")[0]
            return Resp(text=IC_PAGES[jid]) if jid in IC_PAGES else Resp({}, 403)
        if url == "https://x.example/jobs_sitemap.xml":
            return Resp(text="<loc>https://x.example/jobs/controller/a/</loc><loc>https://x.example/jobs/audit-manager/b/</loc>")
        if url.startswith("https://x.example/jobs/"):
            return Resp(text=LD_PAGE)
        return Resp({}, 404)


def test_whole_run():
    js.requests.Session = FakeSession
    cfg = example()
    cfg["employers"] = {"gh": {"ats": "greenhouse", "spec": "boardone"}, "ab": {"ats": "ashby", "spec": "boardtwo"},
                        "ic": {"ats": "icims", "spec": "c"}, "sm": {"ats": "sitemap", "spec": "https://x.example/jobs_sitemap.xml"},
                        "boom": {"ats": "lever", "spec": "explode"}}
    cfg["candidates"] = {"blocked": {"ats": "offlimits", "spec": "robots"}, "q": {"ats": "unknown", "spec": "x.example"},
                         "cand": {"ats": "greenhouse", "spec": "boardthree"}}
    cfg["weekly"] = {}
    d = tempfile.mkdtemp()
    cfg_p, csv_p, md_p = os.path.join(d, "config.json"), os.path.join(d, "r.csv"), os.path.join(d, "delta.md")
    def write_cfg():
        with open(cfg_p, "w", encoding="utf-8") as fh:
            json.dump(cfg, fh)
    def run(*args):
        sys.argv = ["x", "--config", cfg_p, "--out", csv_p] + list(args)
        buf = io.StringIO()
        try:
            with contextlib.redirect_stdout(buf):
                js.main()
            return buf.getvalue(), ""
        except SystemExit as e:
            return buf.getvalue(), str(e)
    write_cfg()
    out, _ = run("--delta", md_p, "--lane")
    with open(csv_p, newline="", encoding="utf-8") as fh:
        rows = list(csv.DictReader(fh))
    got = {r["title"]: r for r in rows if r["employer"] != "sm"}
    sm = {r["title"]: r for r in rows if r["employer"] == "sm"}
    md = open(md_p).read()
    check("22 enumerated -> 14 pass the gates -> 7 clear $140,000" in out, "the run's summary line: " + [l for l in out.split("\n") if "enumerated" in l][0])
    for t in ("Revenue Cycle Manager", "Billing Specialist", "Payroll Partner", "Tax Partner"):
        check(t in got, f"passes the band gate: {t}")
        check(not js.title_gate({"title": t}), f"a title-word gate would have hidden it: {t}")
    check(got["Billing Specialist"]["band_high"] == "180000" and got["Billing Specialist"]["band_ctx"] == "Zone 2 (Denver)",
          "the band kept is the home zone's, though another zone tops out lower and under the floor")
    check("Payroll Specialist" not in got, "dropped: Ashby band top $130,000 is under the floor")
    check("Senior Collections Manager" not in got, "dropped: Greenhouse band top $130,000 is under the floor")
    check("Staff Accountant" not in got, "dropped: San Francisco fails the place gate")
    check(got.get("Ledger Analyst", {}).get("location") == "Denver, CO; Regional HQ",
          "Greenhouse: the job's own location is read with its offices, so an office named for a region does not hide it; a null office name is skipped")
    check(got.get("Close Manager", {}).get("location") == "Denver, CO",
          "of two rows with one req, the one that passes the gates is kept, though the other was listed first")
    check(got.get("Vault Custodian", {}).get("clearance") == "ACTIVE REQUIRED" and "left out by the clearance choice" not in out,
          'clearance "keep": the posting is in the output with its verdict')
    check(got.get("Ledger Lead (active TS/SCI)", {}).get("clearance") == "ACTIVE REQUIRED", "the clearance verdict reads the title as well as the text")
    check("" in got and "| ab |  | Denver, CO |" in md, "a job whose title is an explicit null is a row with an empty title, in the CSV and in the delta, not a crash")
    check(got.get("Controller", {}).get("band_top_all") == "195000", "band_top_all keeps the highest top among the text ranges, beside the band chosen")
    tops = [int(r["band_high"] or 0) for r in rows]
    check(tops == sorted(tops, reverse=True) and tops[0] > tops[-1], "the CSV is sorted by the top of the band, highest first")
    check("Enumerated 22; pass the band gate 14; pass the title gate 2." in md and "hidden by the title gate (13)" in md and "## Pass both gates (1)" in md,
          "the delta's three counts: " + md.split("\n")[2])
    check("boom: RuntimeError the connection dropped" in out and "Candidate Board Role" not in got,
          "an adapter that raises becomes a wall and the run goes on; a candidate does not run without --candidates")
    check(len(FakeSession.seen) > 10 and all("json" in h.get("Accept", "") and "job_scanner/" in h.get("User-Agent", "") for u, h in FakeSession.seen),
          f"every request of the run named the tool and sent an Accept header that includes JSON ({len(FakeSession.seen)} requests)")
    check("Accounting Intern" not in got, "dropped: a junior title")
    check("Unlisted Role" not in got, "dropped: an unlisted Ashby job")
    check("Payroll Partner (cross-post)" not in got, "a second row with the same employer and req collapses into the first")
    check("Payments Analyst" in got and "greenhouse boardone: 12 jobs (one call; the list is not paged); 1 detail reads FAILED" in out,
          "a failed Greenhouse pay call is counted in the note; the row keeps the text the list gave it")
    check(got.get("Controller", {}).get("band_src") == "text" and got.get("Controller", {}).get("band_high") == "170000",
          "a text band labelled with a home place beats the posting-wide JSON-LD range")
    check(got.get("Treasury Analyst", {}).get("band_src") == "JSON-LD" and got.get("Treasury Analyst", {}).get("band_high") == "175000",
          "JSON-LD range used when the text holds only a bonus range; the bonus is not read as the band")
    check("Auditor" not in got, "dropped: validThrough is in the past")
    check("Senior Accountant" not in got and "icims c: 4 job URLs in sitemap, 4 after the lane slug filter, 4 fetched; 1 detail reads FAILED" in out,
          "a refused detail page is counted in the note, and its row cannot pass")
    check(sorted(sm) == ["Audit Manager", "Controller"], "two sitemap rows with no req do not collapse into one")
    check("## Dropped by the band floor, passed by the title gate (1)" in md, "the delta counts the one row the floor dropped that a title gate passes")
    check("- blocked: offlimits: robots" in md and "- q: unknown: x.example; run --discover" in md, "never-fetched entries are written as walls")

    out, _ = run("--lane", "--candidates", "--floor", "175000")
    with open(csv_p, newline="", encoding="utf-8") as fh:
        hi = {(r["employer"], r["title"]) for r in csv.DictReader(fh)}
    check(("cand", "Candidate Board Role") in hi and ("gh", "Billing Specialist") in hi and ("gh", "Revenue Cycle Manager") in hi and ("ic", "Controller") not in hi,
          "--candidates adds the candidate board; --floor 175000 drops the $170,000 band and keeps $180,000 and $190,000")
    cfg["clearance"] = {"when_active_required": "drop"}; write_cfg()
    out, _ = run("--lane")
    with open(csv_p, newline="", encoding="utf-8") as fh:
        kept = {r["title"] for r in csv.DictReader(fh)}
    check("Vault Custodian" not in kept and 'left out by the clearance choice ("drop"): 2 that pass every other gate' in out,
          'clearance "drop": the postings are left out, and the run counts the two that passed every other gate, not the one in another city')
    cfg["clearance"] = {"when_active_required": "keep"}; write_cfg()

    out, _ = run("--only", "ab")
    check("blocked: offlimits: robots" in out and "q: unknown: x.example" in out and "greenhouse" not in out,
          "never-fetched entries are listed even with --only and without --candidates; nothing else runs")
    out, _ = run("--only", "ab,nosuch")
    check("--only names not defined (a candidate needs --candidates): nosuch" in out, "--only with an undefined name says so")

    del cfg["title_gate"]; write_cfg()
    _, stopped = run("--delta", md_p)
    check("--delta needs a `title_gate` section" in stopped, "--delta without a title gate in the settings stops with the reason")
    cfg["employers"]["wd"] = {"ats": "workday", "spec": "tenant|wd5"}; write_cfg()
    _, stopped = run()
    check("employers.wd: a workday spec is tenant|shard|site; got 'tenant|wd5'" in stopped, "a Workday spec with a part missing stops the run at load")

    class DiscoverSession:
        def get(self, url, **_):
            r = Resp(text='<a href="https://tenant.wd5.myworkdayjobs.com/en-US/Careers_Site">jobs</a> '
                          '<script src="https://boards.greenhouse.io/embed/job_board/js?for=boardone"></script> '
                          '<a href="https://jobs.lever.co/slugone">x</a> <a href="https://jobs.ashbyhq.com/Board-Two">y</a>' if "careers" in url else "<html></html>")
            r.url = url
            return r
    js.requests.Session = DiscoverSession
    sys.argv = ["x", "--config", os.path.join(d, "absent.json"), "--discover", "careers.example.com"]
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        js.main()
    check("tenant|wd5|Careers_Site" in buf.getvalue() and "boardone" in buf.getvalue(),
          "--discover prints the Workday tenant|shard|site and the Greenhouse token, and needs no settings file")
    check("lever           slugone" in buf.getvalue() and "ashby           Board-Two" in buf.getvalue(), "--discover prints the Lever slug and the Ashby board name")
    sys.argv = ["x", "--discover", "blank.example.com"]
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        js.main()
    check("no ATS fingerprint in the HTML" in buf.getvalue(), "--discover on a page with no fingerprint says so, and calls it a wall")
    class ProbeSession:
        def get(self, url, **_):
            r = Resp({}, 200 if "icims.com" in url else 404); r.content = b"x" * (500 if "icims.com" in url else 0)
            return r
    js.requests.Session = ProbeSession
    sys.argv = ["x", "--probe", "https://careers.acme.example/jobs"]
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        js.main()
    check("HIT 200  icims      https://acme.icims.com/sitemap.xml" in buf.getvalue() and buf.getvalue().count("HIT ") == 1
          and "404  greenhouse" in buf.getvalue(), "--probe takes a URL or a domain, marks the one endpoint that answered with content, and prints the status of the others")
    sys.argv = ["x", "--config", os.path.join(d, "absent.json")]
    try:
        js.main(); stopped = ""
    except SystemExit as e:
        stopped = str(e)
    check("not found. Copy config.example.json" in stopped, "a sweep without a settings file stops and says what to copy")


def main():
    js.configure(settings())
    js.PAUSE = 0   # the adapters pause between requests; a fake session needs none
    test_bands()
    test_gates()
    test_adapters()
    test_whole_run()
    print("\nALL PASS" if OK else "\nFAILURES ABOVE")
    return 0 if OK else 1


if __name__ == "__main__":
    sys.exit(main())
