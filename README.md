# Job sweep: open roles, read from employers' own applicant tracking systems

Command-line tools that list an employer's open roles from the list endpoint of its applicant
tracking system (ATS), then keep the roles whose own text passes three checks: the published pay
band, the location and the clearance wording. Read-only. Nothing here applies, submits or contacts
anyone.

It was built for one job search and is published with that search taken out. The pay floor, the
home places, the title lane, the clearance choice and the employers are settings, and the settings
file in this repository holds made-up values.

## Three rules the code keeps

1. **The list endpoint is the truth about what is open.** A detail page can keep rendering after a
   requisition closes. A row exists only because the employer's list returned it in this run.
2. **The published band is the level gate, not the title.** A filter on level words in the title
   hides every role whose title carries none. `--delta` shows the difference on your own run, and
   `docs/DESIGN.md` has a measured case.
3. **A wall is a finding.** A refused list call, a bot check, a list that stops short of its own
   total, detail pages that fail, a site whose robots.txt rules it out: each is written under WALLS
   in the run's output, with a count where there is one. `docs/DESIGN.md` lists what the notes
   cover and what they cannot see.

## Quick start

```
pip install requests
cp config.example.json config.json
python3 job_scanner.py --discover careers.example.com
python3 job_scanner.py --config config.json --lane --out roles.csv
python3 posting_census.py roles.csv --out census.csv --save-dir postings
```

`config.example.json` names no real employer, so copying it is not enough: replace every value in
`config.json`. Run unedited, the copy sends requests to the placeholder names. `--discover` reads a careers page and prints the ATS fingerprints it finds in the HTML; for
Greenhouse, Lever, Ashby, Workday, iCIMS and Avature the fingerprint is the value to enter as
`spec`. `config.json` is git-ignored, and so are `results/`, `postings/` and every `.csv`.

The tests need no settings of your own and no route to any job site:

```
bash tests/run_all.sh
python3 tests/mutate.py      # optional, about ten minutes: are the tests able to fail?
```

## Settings

One JSON file. A required key that is missing, an unknown key at any level, or a value of the
wrong type in a key the tools read stops the run and names the key. The optional keys have the
defaults given here, and an optional key set to `null` counts as left out. `about` is free text
and is not read.

| key | what it sets |
|---|---|
| `pay_floor` | Dollars per year. A posting whose band tops out under it is dropped. A posting with no band passes. |
| `metro.places` | The places that count as home. Each entry is a regular-expression fragment matched as a whole word, case-insensitive. |
| `metro.accept_remote` | Optional, default `true`: a remote posting counts as home unless it names a place on the foreign list and no home-country mark. `false`: only a listed place counts. |
| `metro.home_country`, `metro.foreign_places` | Optional. They replace the built-in word lists used to judge a remote posting. Home-country marks are matched with case as written ("US" is a mark, the word "us" is not); the foreign list in any case. |
| `lane_titles` | Title fragments. They decide which detail pages are read (see `--lane` below). |
| `junior_titles` | Optional. Replaces the built-in list of titles dropped whatever the band says. |
| `clearance.when_active_required` | `"drop"` or `"keep"` for a posting that asks for a clearance already held. `"keep"` writes it to the output with its verdict. `"drop"` leaves it out of every output file, and the run prints how many passed every other gate and were left out. |
| `title_gate` | Optional `pass` and `fail` word lists. Used only by `--delta`, never to filter. |
| `employers` | Name to `{"ats": kind, "spec": text}`. The kinds are listed below. |
| `candidates` | Optional. The same shape. Run only with `--candidates`: routes you have not yet seen answer. |
| `weekly` | Optional `canary_url` and `second_pass_only` for `weekly_run.py`. The first pass runs without `--lane`, so a Workday or sitemap employer yields rows only if it is named in `second_pass_only`. |

A two-letter state code in `metro.places` also matches ordinary words in a pay line: "or" and "in"
are state codes. Add one only if you accept that.

`--lane`: some lists carry no description, so the band and the clearance wording need one more
request per posting. Workday and plain sitemaps are read that far only with `--lane`, and only for
titles in the lane; without it their rows are counted in the enumeration and cannot pass. iCIMS and
Avature read every row's detail without `--lane`, and Eightfold the detail of every row that names
a home place or a remote word; with it they read lane titles only. The SuccessFactors feed reads lane titles only, with or without the
flag.

## Files

| file | what it does |
|---|---|
| `job_scanner.py` | The sweep: one adapter per ATS, the gates, `roles.csv`, the WALLS list, `--delta`, `--discover`, `--probe`. |
| `sweep_settings.py` | Loads and checks the settings file. |
| `posting_census.py` | Second pass. Fetches each kept posting, saves its text, and quotes the clearance line, the pay line and the years-of-experience lines. |
| `weekly_run.py` | Canary, sweep, and a delta against the previous run: walls, new roles, closed roles. |
| `config.example.json` | Made-up settings to copy. |
| `tests/` | Four offline test files and `run_all.sh`. `mutate.py` breaks rules of the code one at a time and expects the tests to fail. |
| `docs/DESIGN.md` | How each gate decides, what each adapter cannot see, and how this version was checked. |

## ATS kinds

`spec` is what the adapter needs to find the board.

| kind | spec | how it reads |
|---|---|---|
| `greenhouse` | board token | One list call. Pay comes from one more call per job, made for rows that name a home place or a remote word. |
| `lever` | company slug | Paged list. |
| `ashby` | board name | One list call with compensation. |
| `workday` | `tenant\|wd5\|SiteName` | Paged POST, 20 rows a page. The description is on a detail endpoint. |
| `icims` | subdomain | The public sitemap, then JSON-LD on each job page. |
| `eightfold` | `host\|domain.com` | The search API, then a detail call for rows that name a home place or a remote word. |
| `phenom_widget` | careers base URL | The site's own search POST. |
| `avature` | slug or base URL | HTML result pages, then each job page: its JSON-LD, or its text when it has none. |
| `successfactors_rss` | careers host | The site's RSS feed, then the job page for lane titles. |
| `amazon` | `category\|query` | amazon.jobs search JSON, United States, up to 10,000 rows. |
| `sitemap` | sitemap URL | A jobs sitemap whose URLs end `/<title-slug>/<id>/`, then the job page for lane titles. |
| `unknown`, `unsupported`, `offlimits` | a note | Never fetched. The note is written under WALLS on every run, whatever `--only` and `--candidates` say. |

## Before you add an employer

The scanner does not read robots.txt or a site's terms for you. Read both. If the careers pages
are disallowed, enter the employer as `offlimits` with the reason: the run then records the wall
and never sends a request. When a site answers with a bot check or a client-fingerprint block, the
adapter reports the status as a wall and stops. It does not try to get around it.

Every request carries one User-Agent, a browser-style token followed by the tool's name
(`job_scanner/2.0`), and an Accept header. Four calls send an Accept header with no JSON type:
the HTML pages read by `--discover` and by the Phenom route, the Phenom search call, and the
SuccessFactors feed. Every other list call and job-page read sends one that includes JSON: iCIMS served
the job page to that header and a wrapper page without it, when this was written.

Inside a paged list, and inside a run of detail reads, requests are at least 0.4 seconds apart.
There is no pause between a list call and the first detail read, between one employer and the
next, or before three retries: the Workday site-name probe, the Lever second host, and the Phenom
search-page paths. The
only POSTs are the Workday list call and the Phenom search call, which are the calls those sites'
own pages make.

## Limits

- The gates read text with patterns. They miss phrasings they were not written for. The sweep's
  clearance verdict reads "Top Secret clearance required" as `NONE STATED` and "No active clearance
  is required" as `ACTIVE REQUIRED`; `posting_census.py` exists because one verdict per posting is
  not enough to act on. The census misreads too: it takes the title "Cleared Derivatives Analyst"
  for a clearance requirement.
- A posting with no published band passes the pay gate. On boards that print no bands the sweep is
  a list to read, not a shortlist.
- A range is skipped as "not a salary" when the words just before it say bonus, equity, relocation
  and the like. A real salary introduced as "salary plus bonus: $X - $Y" is skipped too, and the
  posting then counts as having no band.
- The scanner reads a text range in two forms: `$150,000 - $180,000` (a dash or "to" between two
  full figures; the second dollar sign may be missing), and "from $X ... up to $Y". "$150K -
  $180K", "$150,000/yr - $180,000/yr", "$150,000 USD - $180,000 USD"
  and "between $150,000 and $180,000" are not read, and such a posting counts as having no band.
- Bands are read in US dollars, and the place logic assumes a United States home. The built-in
  word lists are blunt: "mexico" rejects "Remote - New Mexico", "assistant" drops "Assistant
  Controller", and the foreign list is short, so "Remote - Portugal" passes as a home posting.
- Workday paging stops at 2,000 rows for every tenant: a reported total of exactly 2,000 is flagged
  as capped, and a longer list as stopped. Avature stops at 200 pages, Eightfold at 5,000 rows,
  amazon.jobs at 10,000, and Phenom's main paging at 5,000 (its per-category fallback has no
  bound). Each of these stops is flagged in that employer's note, and so is a
  Workday, Eightfold or amazon.jobs list that ends short of the total the service reported.
- Routes change. An adapter that answered when this was written can be refused tomorrow, and the
  run will say so.

## Credits

Several routes were written against the source of
[ats-scrapers](https://github.com/kalil0321/ats-scrapers) 0.3.0 (MIT), and the Phenom request body
follows it closely. `THIRD_PARTY_NOTICES.md` lists the parts and carries its license.

## License

MIT. See `LICENSE`. Written by Mohamed Chizari, Seven Sky Consulting.
