#!/usr/bin/env python3
"""Offline check of posting_census.py: the clearance reader, the band reader, the fetch routes and
one whole run. No network. Every fixture is made up: titles, employers, figures, and the wording
of the clearance lines, which was written for these tests and is not quoted from any posting.

  python3 tests/test_census.py
"""
import contextlib, csv, io, os, sys, tempfile
HERE = os.path.dirname(os.path.abspath(__file__)); ROOT = os.path.dirname(HERE); sys.path.insert(0, ROOT)
import posting_census as pc

T = 'Analyst'
CASES = [
 ('ACTIVE_REQUIRED', T, "Qualifications\n- Clearance: Top Secret, SCI and polygraph, at the time of application, to be considered."),
 ('ACTIVE_REQUIRED', T, "Clearance level:\n\nTop Secret/SCI with polygraph"),
 ('ACTIVE_REQUIRED', T, "Clearance level: TS/SCI"),
 ('ACTIVE_REQUIRED', T, "Clearance required:\nActive Top Secret with polygraph"),
 ('ACTIVE_REQUIRED', T, "Required clearance\nTop Secret/SCI"),
 ('ACTIVE_REQUIRED', T, "Clearance required: Yes"),
 ('ACTIVE_REQUIRED', T, "Basic qualifications:\n- Secret clearance\n- Bachelor's degree"),
 ('ACTIVE_REQUIRED', T, "Clearance: U.S. citizenship with an active Secret clearance and ability to obtain Top Secret clearance."),
 ('ACTIVE_REQUIRED', 'Engineer - TS/SCI w/poly', "Any text"),
 ('ACTIVE_REQUIRED', T, "Must have a TS/SCI level government clearance with a willingness to sit for a polygraph"),
 ('ACTIVE_REQUIRED', T, "Must have an active secret clearance."),
 ('ACTIVE_REQUIRED', T, "An active top secret clearance is required."),
 ('ACTIVE_PUBLIC_TRUST', T, "Clearance required:\nActive Public Trust"),
 ('ACTIVE_PUBLIC_TRUST', T, "- An active Public Trust, or an active Top Secret clearance."),
 ('PUBLIC_TRUST', T, "- You can obtain and keep a Public Trust determination"),
 ('PUBLIC_TRUST', T, "Clearance required: Ability to obtain Public Trust"),
 ('NONE_FOUND', T, "- Eligible to obtain and maintain a U.S. Secret security clearance"),
 ('NONE_FOUND', T, "\u00b7 Must be eligible to obtain and maintain a Secret clearance"),
 ('NONE_FOUND', T, "- Ability to obtain and maintain an active Secret security clearance (U.S. citizenship required)."),
 ('NONE_FOUND', T, "- Active clearance preferred but not required."),
 ('NONE_FOUND', T, "Clearance level:\nNone"),
 ('NONE_FOUND', T, "Clearance the role can sponsor: Top Secret/SCI"),
 ('NONE_FOUND', T, "Clearance required: No"),
 ('NONE_FOUND', T, "Clearance required:\nStart date:\nJanuary"),
 ('NONE_FOUND', T, "Applicants must meet the requirements; a facility clearance is required."),
 ('NONE_FOUND', 'Senior Polymer Scientist', "Polymer chemistry."),
 ('NONE_FOUND', T, "- At least 12 years of experience in general ledger accounting"),
 # wording about obtaining, after "must": not a requirement to hold one today
 ('NONE_FOUND', T, "Must have the ability to obtain a Secret clearance."),
 ('NONE_FOUND', T, "- Must hold or be able to obtain a Secret clearance"),
 ('NONE_FOUND', T, "Must have experience with financial statements; ability to obtain a Secret clearance is a plus."),
 ('ACTIVE_REQUIRED', T, "Must hold a secret clearance."),
 ('ACTIVE_REQUIRED', T, "Requires TS/SCI clearance."),
 ('ACTIVE_REQUIRED', T, "Applicants need a Secret clearance at the time of application."),
 ('ACTIVE_REQUIRED', T, "A Top Secret clearance is needed to be considered."),
 # a wish is not a requirement, wherever the word sits; a wish beside a requirement does not undo it
 ('NONE_FOUND', T, "Active Secret clearance preferred."),
 ('NONE_FOUND', T, "A current Secret clearance is a plus."),
 ('ACTIVE_REQUIRED', T, "Active Secret clearance required; polygraph preferred."),
 # a paragraph, not a line: too long to be read as a requirement line
 ('NONE_FOUND', T, "We value people who " + "plan, review and report " * 20 + "and some of them must have an active secret clearance."),
 # a posting that says none is needed
 ('NONE_FOUND', T, "Security clearance: Not needed"),
 ('NONE_FOUND', T, "Security clearance: This position does not require a clearance"),
 ('NONE_FOUND', T, "No Secret clearance is required for this role."),
 ('NONE_FOUND', T, "A Secret clearance is not required."),
 # a sentence about the vetting process names levels without asking for one, unless it says so
 ('NONE_FOUND', T, "Everyone hired is subject to a background investigation, as required of all staff near Secret clearance work."),
 ('ACTIVE_REQUIRED', T, "This role is subject to a background investigation; a Secret clearance is required."),
 # titles
 ('NONE_FOUND', 'Uncleared Margin Analyst', "Any text"),
 ('NONE_FOUND', 'Analyst (TS/SCI eligible)', "Any text"),
 ('NONE_FOUND', 'Analyst - Ability to obtain Top Secret', "Any text"),
 ('ACTIVE_REQUIRED', 'Cleared Derivatives Analyst', "Any text"),   # a known misread: see Limits in the README
]


class Resp:
    def __init__(self, data=None, status=200, text=""):
        self.data, self.status_code, self.text = data if data is not None else {}, status, text
    def json(self):
        return self.data


class Sess:
    """Answers each ATS route posting_census.get() can take, and counts the calls."""
    def __init__(self): self.calls, self.accept = [], set()
    def get(self, url, headers=None, **_):
        self.calls.append(url); self.accept.add((headers or {}).get("Accept", ""))
        if url == "https://boards-api.greenhouse.io/v1/boards/boardone/jobs/11?pay_transparency=true":
            return Resp({"title": "Cost Accountant", "location": {"name": "Denver, CO"}, "updated_at": "2026-09-01",
                         "pay_input_ranges": [{"title": "Zone A:", "min_cents": 15000000, "max_cents": 19000000}],
                         "content": "&lt;p&gt;Clearance Required: Active Top Secret&lt;/p&gt;&lt;p&gt;Pay: $150,000 - $190,000&lt;/p&gt;"})
        if url == "https://boards-api.greenhouse.io/v1/boards/boardone/jobs/12?pay_transparency=true":
            return Resp({"error": "Clearance required: Top Secret"}, 404)
        if url == "https://tenant.wd5.myworkdayjobs.com/wday/cxs/tenant/Site/job/Denver-CO/Analyst_R2":
            return Resp({"jobPostingInfo": {"title": "Analyst", "location": "Denver, CO",
                         "jobDescription": "<ul><li>5+ years of experience</li><li>U.S. citizenship is required</li></ul>"}})
        if url == "https://api.lever.co/v0/postings/slug/aaaa-1111":
            return Resp({"text": "Tax Analyst", "categories": {"location": "Remote"}, "descriptionPlain": "Prepare returns.",
                         "lists": [{"text": "Requirements", "content": "<li>Ability to obtain a Secret clearance</li>"}]})
        if url == "https://api.ashbyhq.com/posting-api/job-board/boardtwo?includeCompensation=true":
            return Resp({"jobs": [{"id": "bbbb-2222", "title": "Audit Lead", "location": "Denver",
                                   "descriptionHtml": "<p>Public Trust eligibility.</p>"}]})
        if url == "https://careers.example.com/job/9":
            return Resp(text='<html><script type="application/ld+json">{"@graph":[{"@type":"JobPosting","title":"Treasury Analyst",'
                             '"description":"&lt;p&gt;Salary $120,000 - $165,000&lt;/p&gt;"}]}</script></html>')
        if url == "https://careers.example.com/plain":
            return Resp(text="<html><style>p{}</style><p>Plain page</p><script>x()</script></html>")
        return Resp({}, 404)


def check(cond, msg):
    print(("ok   " if cond else "FAIL ") + msg)
    return cond


def main():
    ok = True
    for want, title, text in CASES:
        got, line = pc.clearance(text, title)
        ok &= check(got == want, f"{want} <- {title}" + ("" if got == want else f" (got {got}: {line[:70]})"))

    ok &= check(pc.band("Base pay: $150,000 - $195,000") == (150000, 195000, "Base pay: $150,000 - $195,000"), "band: a range on one line, quoted with its line")
    ok &= check(pc.band("Base pay: $30,000 - $39,000") is None and pc.band("Base pay: $40,000 - $55,000")[:2] == (40000, 55000),
                "band: a range that starts under $40,000 is not quoted; one that starts at $40,000 is")
    ok &= check(pc.band("Bonus up to $50,000; relocation $45,000") is None and pc.band("Pay between $90,000 and $110,000")[:2] == (90000, 110000),
                "band: two figures on a line are a range only when a dash, 'to' or 'and' joins them")
    ok &= check(pc.band("Zone A $120,000.00 to $150,000.00\nZone B $140,000 to $185,000")[:2] == (140000, 185000),
                "band: the line with the highest top wins, cents accepted")
    ok &= check(pc.band("Salary up to $150,000") is None, "band: one figure is not a band")
    ok &= check(pc.band("Pay: $850,000 - $900,000")[:2] == (850000, 900000) and pc.band("Pay: $850,000 - $950,000") is None,
                "band: a range that tops out over $900,000 is not quoted")
    ok &= check(pc.band("x" * 700 + " $150,000 - $190,000") is None, "band: a line of more than 700 characters is not read as a pay line")
    ok &= check(pc.clearance("Clearance required:\nPublic trust status:\nNone", T) == ("PUBLIC_TRUST", "Public trust status:"),
                "a line that ends in a colon is the next label, not this label's value")
    ok &= check(pc.strip("<p>a&nbsp;b</p><ul><li>c</li></ul>") == "a b\n- c", "strip keeps line breaks and list marks")

    s = Sess()
    code, text = pc.get("https://job-boards.greenhouse.io/boardone/jobs/11", s)
    ok &= check(code == 200 and "PAY: Zone A: $150,000 - $190,000" in text and pc.clearance(text, "x")[0] == "ACTIVE_REQUIRED"
                and pc.band("PAY: Zone A: $150,000 - $190,000")[:2] == (150000, 190000),
                "greenhouse: read through the board API with pay_transparency; escaped content unescaped; the PAY line is one band() can read")
    ok &= check(pc.get("https://job-boards.greenhouse.io/boardone/jobs/12", s) == (404, ""), "greenhouse: a refused call returns its status and no text")
    code, text = pc.get("https://tenant.wd5.myworkdayjobs.com/Site/job/Denver-CO/Analyst_R2", s)
    ok &= check(code == 200 and "- 5+ years of experience" in text and "LOCATION: Denver, CO" in text, "workday: read from the cxs detail endpoint")
    code, text = pc.get("https://jobs.lever.co/slug/aaaa-1111", s)
    ok &= check(code == 200 and "Ability to obtain a Secret clearance" in text and pc.clearance(text, "x")[0] == "NONE_FOUND",
                "lever: lists joined into the text; 'ability to obtain' is not a requirement")
    code, text = pc.get("https://jobs.ashbyhq.com/boardtwo/bbbb-2222", s)
    ok &= check(code == 200 and pc.clearance(text, "x")[0] == "PUBLIC_TRUST", "ashby: found in the board list")
    code, text = pc.get("https://jobs.ashbyhq.com/boardtwo/cccc-3333", s)
    ok &= check(code == "ABSENT FROM LIST" and text == "", "ashby: a job that is not in the list is reported as absent")
    code, text = pc.get("https://careers.example.com/job/9", s)
    ok &= check(code == 200 and text.startswith("TITLE: Treasury Analyst") and pc.band(text)[:2] == (120000, 165000), "other sites: JSON-LD inside @graph")
    code, text = pc.get("https://careers.example.com/plain", s)
    ok &= check((code, text) == (200, "Plain page"), "no JSON-LD: page text without script or style")
    code, text = pc.get("https://careers.example.com/gone", s)
    ok &= check((code, text) == (404, ""), "a refused page returns its status and no text")
    ok &= check(s.accept <= {"application/json, text/html;q=0.9,*/*;q=0.8", "application/json"} and "" not in s.accept,
                "every fetch sends an Accept header that includes JSON (a job page can depend on it)")

    d = tempfile.mkdtemp(); out = os.path.join(d, "census.csv"); save = os.path.join(d, "postings")
    rows = [{"employer": "gh", "req": "11", "title": "Cost Accountant", "location": "Denver, CO", "url": "https://job-boards.greenhouse.io/boardone/jobs/11", "band_low": "", "band_high": ""},
            {"employer": "w/d", "req": "../R2", "title": "Analyst", "location": "Denver, CO", "url": "https://tenant.wd5.myworkdayjobs.com/Site/job/Denver-CO/Analyst_R2", "band_low": "100000", "band_high": "130000"},
            {"employer": "sm", "req": "", "title": "Treasury Analyst", "location": "", "url": "https://careers.example.com/job/9", "band_low": "", "band_high": ""},
            {"employer": "sm", "req": "", "title": "Plain", "location": "", "url": "https://careers.example.com/plain", "band_low": "", "band_high": ""},
            {"employer": "sm", "req": "", "title": "Gone", "location": "", "url": "https://careers.example.com/gone", "band_low": "", "band_high": ""}]
    s = Sess(); pc.census(rows, s, save, out, today="2026-01-01", pause=0)
    def read():
        with open(out, newline="", encoding="utf-8") as fh:
            return list(csv.DictReader(fh))
    got = read()
    ok &= check(got[0]["clearance_verdict"] == "ACTIVE_REQUIRED" and got[0]["band_high"] == "190000" and got[0]["clearance_line"] == "Clearance Required: Active Top Secret",
                "run: verdict, the line it rests on and the band written for a read posting")
    ok &= check(got[1]["citizenship"] == "Y" and "5+ years" in got[1]["years_lines"] and got[1]["band_line"] == "from the sweep row",
                "run: citizenship and years lines quoted; the sweep's band is used when the text has none")
    ok &= check(got[4]["clearance_verdict"] == "UNREAD" and got[4]["http"] == "404", "run: a posting that could not be read is UNREAD, not NONE_FOUND")
    names = sorted(os.listdir(save))
    ok &= check(len(names) == 4 and all(pc.re.fullmatch(r"[A-Za-z0-9_-]+\.txt", n) for n in names) and any(n.startswith("wd_R2_") for n in names),
                f"run: saved under names built from letters, digits, hyphens and a hash, whatever the row holds ({names})")
    ok &= check(got[2]["band_high"] == "165000" and got[3]["chars"] == "10" and got[3]["band_high"] == "",
                "run: two rows with no req are saved and read separately")
    with open(os.path.join(save, [n for n in names if n.startswith("gh_11_")][0]), encoding="utf-8") as fh:
        ok &= check(fh.read().startswith("URL: https://job-boards.greenhouse.io/boardone/jobs/11\nFETCHED: 2026-01-01\n"), "run: the saved text carries its URL and fetch date")
    n = len(s.calls); pc.census(rows, s, save, out, pause=0); again = read()
    ok &= check(len(s.calls) == n + 1 and s.calls[-1].endswith("/gone"), "run: a saved posting is not fetched again; the unread one is tried again")
    ok &= check([r["chars"] for r in again] == [r["chars"] for r in got] and [r["clearance_verdict"] for r in again] == [r["clearance_verdict"] for r in got]
                and again[0]["http"] == "saved", "run: a re-read gives the same text and verdicts, and says the text came from the save")

    # the command line: --only, --skip-employers, a file without the columns it needs
    import requests
    requests.Session = Sess
    roles_p = os.path.join(d, "roles.csv")
    with open(roles_p, "w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=list(rows[0])); w.writeheader(); w.writerows(rows)
    def cli(*args, roles=roles_p):
        sys.argv = ["x", roles, "--out", out, "--save-dir", os.path.join(d, "postings2")] + list(args)
        buf = io.StringIO()
        try:
            with contextlib.redirect_stdout(buf):
                pc.main()
            return buf.getvalue()
        except SystemExit as e:
            return "EXIT " + str(e)
    said = cli()
    ok &= check(len(read()) == 5 and "DONE 5 postings: ACTIVE_REQUIRED 1, NONE_FOUND 3, UNREAD 1" in said, "command line: every row of the roles file is read, and the verdicts are counted")
    cli("--only", "gh:11,w/d:../R2")
    ok &= check([r["employer"] for r in read()] == ["gh", "w/d"], "command line: --only keeps the named employer:req pairs")
    cli("--skip-employers", "sm,gh")
    ok &= check([r["employer"] for r in read()] == ["w/d"], "command line: --skip-employers leaves those employers out")
    bad = os.path.join(d, "bad.csv")
    with open(bad, "w", encoding="utf-8") as fh: fh.write("employer,title\ngh,Controller\n")
    ok &= check("missing column(s) req, url" in cli(roles=bad), "command line: a roles file without the columns it needs stops with their names")

    print("\nALL PASS" if ok else "\nFAILURES ABOVE")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
