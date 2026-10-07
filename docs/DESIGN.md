# Design notes

What each gate decides and why, what each adapter cannot see, and how this version was checked.
"The private version" below is the unpublished code this was derived from.

## 1. Why the list endpoint

A job detail page is a poor witness. It can render for days after the requisition closes, and a
search engine will still link to it. So the sweep starts from each employer's own list call and
treats a posting as open only because the list returned it in this run. `posting_census.py` reads
detail pages only for rows the list already returned.

The same reasoning gives the WALLS list. A list call can fail, stop early or be refused, and each
of those looks like "this employer has no roles" unless the run says otherwise. Each adapter
returns its rows together with a one-line note. The note says how many rows were listed, against
the total when the service reports one, how many detail reads failed, and whether the adapter
stopped at a cap, at a bound, or on a failed page part-way through a list. The notes are printed
under WALLS and written into the delta file.

What the notes cannot see: a service that silently returns a shorter list than it holds and
reports no total (Ashby, Lever, a sitemap) looks complete. Section 7 says which adapters can
measure completeness and which cannot.

Entries of kind `unknown`, `unsupported` and `offlimits` are walls by definition. They are never
fetched, and they are listed on every run, whatever `--only` and `--candidates` select, so that
nobody reads their absence from the results as a result.

## 2. The pay band

The band is read from the most structured source the posting offers. In order of precedence:

1. Greenhouse `pay_input_ranges` and Ashby `compensation` components: fields, per zone or tier.
2. JSON-LD `baseSalary` on the detail page, unless the posting text carries a band labelled with a
   home place (or with a remote word, when remote counts as home), which is the more specific
   figure.
3. Text: `$X - $Y` ranges, and the "from $X in our lowest geographic market up to $Y in our
   highest" form.

Ashby and JSON-LD figures given per hour, day, week or month are annualised. A range from any
source is accepted only between $30,000 and $2,000,000 a year: outside that it counts as no band,
not as a band under the floor. A structured figure in
another currency is left out (a Greenhouse zone, an Ashby component, a JSON-LD salary, a Lever
salary range), and so is a Lever range that is not per year. A dollar sign in text is taken to
mean US dollars.

A text range is not a salary when the words just before it say bonus, sign-on, equity, stock,
RSU, relocation, commission, incentive, stipend or allowance, or when it is followed by "in
equity" or the like. Without that rule, "Base $180,000 - $220,000. Sign-on bonus $30,000 - $50,000." reads as
two ranges and the lower one wins.

A posting often prints several ranges, one per pay zone. The rule is: **the range labelled with a
home place if there is one; otherwise, when remote counts as home, the range labelled remote;
otherwise any range. Within each, the lowest top. Never the maximum.** The maximum is usually the
figure for the most expensive market. `band_top_all` in the output keeps the highest top among the
text ranges and the chosen band (not among the zones of a structured source), so the difference
is visible where the ranges are in the text.

The label of a text range is the text just before it, plus the "in <place>" or "for <zone>" that
follows it. Both forms occur: "Denver: $170,000 - $210,000" and "$170,000 - $210,000 in Denver".
When a phrase beginning in, for or at sits between two ranges, it is given to the range before
it, up to the next comma, semicolon or full stop, and at most 40 characters. This is a heuristic. A sentence built another way can still attach a
place to the wrong range, and the lowest-top rule is what limits the damage when no label is read.

## 3. The level gate is the band, not the title

The first version filtered titles on level words. It hid every role whose title carries no level
word, and many titles carry none.

The gate is now the pay floor. A posting passes unless its band tops out under `pay_floor`, or its
title matches `junior_titles`. `--delta` writes both gates over the same enumeration so the
difference can be read. In one run over four boards, 2,276 postings: the title gate passed 26; the
band gate passed 337, and 312 of those had been hidden by the title gate; one posting passed the
title gate and fell under the floor.

Read that count with its limit. A posting with no published band passes the pay gate, and some
boards publish none. On those boards the band gate passes every title that is not junior, so the
312 are postings to read, not a shortlist. The gate trades a filter that hides good rows for one
that keeps too many, on purpose: a hidden row cannot be recovered by reading, a kept row can be
dropped by reading.

## 4. The place gate

`in_metro` passes a location when it names a place in `metro.places`. When `metro.accept_remote`
is true, a remote posting also passes, with one check. "Remote" alone used to pass, which let
"Remote - United Kingdom" and "Bangalore - Remote" through. A remote-only location is now judged
part by part (parts are separated by `;` or `|`): a part passes when it says remote and either
carries a home-country mark or names no place on the foreign list. "Not remote", "non-remote" and
"no remote" are taken out before the test. Home-country marks keep their case, so that "US" is a
mark and "join us" is not. The foreign list is a short word list, not a gazetteer: a country that
is not on it passes.

The band's own label is part of the place test, against the places only. A posting whose location
field lists many cities, but whose pay table has a row labelled with a home place, passes. A pay
line about "remote employees" does not put a posting in another city through the gate. It did,
in the version this was derived from.

Rows that an adapter listed but did not read are marked `unread` and never pass. Without the mark
an unread row passes as "no band", and on a large Workday tenant that is every row.

## 5. Clearance wording

`job_scanner.py` gives one verdict per posting:

- `ACTIVE REQUIRED`: the title or the text asks for a clearance already held ("active",
  "existing", "must hold", a level followed by "polygraph").
- `OBTAINABLE`: the text speaks of ability to obtain one, of public trust or suitability, or of
  citizenship.
- `NONE STATED`.

`clearance.when_active_required` decides whether an `ACTIVE REQUIRED` posting is dropped or kept.
Kept, it is written with its verdict. Dropped, it is in no output file; the run prints how many
postings passed every other gate and were left out for this reason.

One verdict over a whole posting is coarse: a posting can say "ability to obtain" in one line and
"must have an active clearance" in another. `posting_census.py` reads the posting line by line. It
looks first at the title, then at labelled fields ("Clearance required: ..."), then at any line
that names a level, then at public trust, and it returns the line it relied on, so a person can
check the verdict at a glance. Within a line, wording about obtaining counts when it comes before
"active": "ability to obtain and maintain an active clearance" is about obtaining. Its test file
holds forty-eight phrasings and titles, written for the tests, and the reading each must get. One of
them is a known misread, kept as such: the title "Cleared Derivatives Analyst".

## 6. The lane

`lane_titles` exists to limit which detail pages are fetched. Some lists carry no description
(Workday, iCIMS sitemaps, Avature result pages, Eightfold search), so the band and the clearance
wording need one more request per posting, and a large tenant has more than a thousand postings.
With `--lane`, details are read for lane titles only; the other rows are left out before the fetch
(iCIMS) or marked `unread`.

## 7. What each adapter can and cannot see

| kind | completeness | blind spots |
|---|---|---|
| `greenhouse` | The whole board in one call. | The place is the job's own location together with its offices. Pay needs one call per job. Without `--deep` it is fetched only for rows that name a home place or a remote word. A failed pay call is counted. |
| `lever` | Paged until a short page. No total to check against. | Only a creation date: recency cannot be established. The sweep reads the description and not the posting's `lists`, where requirements often sit; the census reads both. |
| `ashby` | One call, no total field. | Truncation cannot be detected from the response. Unlisted jobs are marked and dropped. |
| `workday` | Paged to the total reported on the first page, or until an empty page when none is reported, and never past 2,000 rows. A total of exactly 2,000 is flagged CAPPED; a longer list, or a page that fails part-way, is flagged STOPPED; a list that ends short of its total is flagged SHORT. | No description without `--lane`: every row is then unread. |
| `icims` | Every URL in the sitemap, up to `--cap`; the cap is flagged. | Titles come from URL slugs. A refused job page is counted, and its row has no place. |
| `eightfold` | Paged to the reported count, which the note prints, or until empty when none is reported. Stops at 5,000 rows, or on a page that fails part-way; both are flagged, and so is a list that ends short of the count. | Descriptions are read only for rows that name a home place or a remote word. |
| `phenom_widget` | Measured against `totalHits`; sliced by category when paging under-delivers. Paging stops at 5,000 rows, flagged. | Marked INCOMPLETE under 90 percent of the total. |
| `avature` | Result pages until one repeats or is empty. Stops at `--cap` rows or at 200 pages, flagged. | Many tenants refuse plain HTTP clients with 406. That is a wall. |
| `successfactors_rss` | The feed. No total to check against. | Feed items are teasers; job pages are read for lane titles, and on the site tried they carried no JSON-LD, so the place comes from the title. |
| `amazon` | Paged until empty or the reported hits. A stop at 10,000 rows, on HTTP 400 after the first page, or short of the reported hits is flagged. | The pay range is the lowest-to-highest market range, not a metro band, and is labelled so. |
| `sitemap` | Every URL in the file. Sitemap indexes and `.gz` files are not followed. | No location or text without `--lane`: every row is then unread. With it, lane rows are read up to `--cap`, flagged; a row whose page is refused stays unread. |

## 8. The weekly delta

`weekly_run.py` compares today's roles with the newest earlier day's. The first request is a
canary to an address you choose; if it does not answer 200, nothing else runs and the delta says
STOPPED. It exists because on a blocked network every employer fails the same way, and a run that
reports that as a column of zeros looks like a result.

The delta opens with the walls: each note the scanner printed under WALLS in this run, and each
employer that had rows last time and has none now. The roles of such an employer are not listed
as closed, because a wall is not evidence that anything closed. "Closed" otherwise means a role
that was in the previous file and is not in this one, which a gate or a cap can also cause. A
posting that both passes of a day wrote is counted once. A sweep that fails or times out stops the
run with a STOPPED delta, even when a roles file for the day is already on disk.

## 9. What answered

The private version these adapters come from was run against live sites in the weeks before this
was published. In its last full run, each kind in section 7 answered on at least one site.
Refusals in that run: one Greenhouse token returned 404, one Workday tenant returned 502 part-way,
one Phenom site returned 404 to the search call, and one Avature site returned 202 with no rows.
Eightfold's older apply API returned 403 on the tenant tried, and a Phenom `GET /api/jobs` route
returned no rows on any site tried, so neither is in this code.

These are dated observations of other people's services, not promises.

## 10. How this version was checked

**Offline tests.** `bash tests/run_all.sh` runs four files, 371 checks, with no route to any job
site. Fake sessions serve fixtures in each adapter's response shape. The part of `weekly_run.py`
that starts the sweep is tested with stand-ins for the canary call and the scanner process.
`python3 tests/mutate.py` then breaks 277 chosen rules on purpose, one at a time, in a copy of the
code: the gates, the band readers, each bound and flag named in section 7, a refused list call
for nine of the adapters, the settings checks, the census readings, the weekly delta. The tests
fail every time, once by not finishing (without the Avature page bound its test never ends).

The list was chosen by hand, and a rule outside it can still be untested. Gaps that are known:
the census's `--show` printing, the wording of most notes beyond the flags, and everything only a
live service can show, which is all of what sections 7 and 9 say about how the services answer.

**Against the private version, on recorded responses.** Two live runs minutes apart can differ
because the lists move. To take the network out of the comparison, the private version was run
against the live sites while every response was recorded (two recordings: 2,426 responses, 17,533
postings), and this code was then run against the recordings with the private settings in a
settings file.

- First, this code as a pure refactor, with the settings moved out and nothing else changed. It
  made the same 2,426 requests and wrote the same 990 rows, cell for cell and in the same order.
- Then this code as published, with the fixes in section 11. Of the private version's 990 rows it
  kept 988. In 627 of them every cell is identical. In 361 the band figures and the clearance
  verdict are identical and a label differs: 298 Greenhouse rows now show the job's own location
  with its offices, and 94 rows carry another label for the same range (two zones or components
  with equal figures); 31 rows have both. It dropped 2: postings in other cities whose pay tier
  was labelled "Remote", which the private version had passed through the place gate (section 4).
  It added 94: 92 Greenhouse postings whose own location passes the place gate while their
  offices do not; one posting that an earlier row with the same requisition id, in another city,
  had hidden; and one posting whose pay zone held a placeholder of one to two dollars, which the
  private version had read as a band under the floor.
- What the replay cannot show: this code asks for the pay of every Greenhouse row that names a
  home place or a remote word, and with the job's own location read, more rows do. That made 124
  pay calls the recordings do not hold, so in the replay the bands of those rows came from the
  posting text. It also left 54 recorded responses unused: the calls of the two routes that were
  taken out (section 9).

**Against the private version, live.** Before that, the refactor and the private version were
run back to back on live sites three times. Each pair kept the same rows: 387, 222 and 33.

**The clearance reader.** `posting_census.py` and the private reader gave the same verdict, and
quoted the same band, on each of 316 saved postings. That shows the fixes in section 11 changed
no reading there; it does not test them, because none of the 316 holds the phrasings they are
about. The offline cases do that.

**This code, live.** `weekly_run.py` was run end to end twice on two small Greenhouse boards and
one Workday tenant: canary, both passes, and a delta that showed a planted wall and a planted new
role. `posting_census.py` fetched and read seven postings over six routes: Greenhouse, Ashby,
Lever, Workday (two tenants), a JSON-LD page and a plain page.

**After the replay.** Six small fixes from the last review pass were made after the recordings
were replayed, and the replay was not run again: Phenom paging when no total is reported, the
Avature cap cutting its last page, a null JSON-LD date, `--probe` given a URL, the Workday
fingerprint, and the weekly run's handling of a failed second pass. The offline tests cover each.

**Not checked live in this version:** a full sweep with the published code on a live network. The
live sweeps above were the refactor's; the published code has run against the recordings and, live,
on the small set just described.

## 11. What was fixed after independent review

Before publication the tree was read line by line in independent review passes, each starting
from the files alone, and the findings of one pass were fixed before the next. Most of these
defects were in the private version too; a few came in while the settings were moved out. All are
fixed here:

- a bonus range read as the salary band; a place after one range labelling the next range;
- a pay line about remote employees passing the place gate for a posting in another city;
- among several ranges, a range labelled remote chosen over one labelled with a home place, and
  the highest of two home-labelled ranges chosen over the lowest;
- "not remote" passing as remote, and the word "us" passing as a home-country mark;
- rows with no requisition id collapsing into one row per employer; of two rows with one
  requisition id, a row in another city hiding the row at home;
- a Greenhouse job's offices read in place of its own location;
- the delta's comparison list built with a looser place test than the gate itself;
- "U.S." not recognised as a home-country mark before a space;
- JSON-LD salaries in another currency read as dollars, and hourly ones not annualised;
- Workday and sitemap rows passing unread when `--lane` was not given; Workday and Eightfold
  rows passing unread after a list failed part-way; a SuccessFactors row passing on its feed
  teaser after its page was refused;
- a Greenhouse pay zone outside any yearly salary (an hourly rate, a placeholder) read as a band
  under the floor;
- a Workday first page with no total read as an empty tenant;
- failed detail reads and stops at a bound not reported; a 400 on the first amazon.jobs page read
  as an empty result;
- never-fetched entries missing from WALLS under `--only`;
- a settings file whose patterns compile one by one but not together ending in a traceback;
- in the census: "Poly" matching inside a word, "TS" matching the end of a word, level words
  matched in capitals only, "Clearance required: No" and "a clearance is not required" read as a
  requirement, "must have the ability to obtain" and "an active clearance is preferred" read as
  requirements, two postings sharing one saved file, a job page fetched without the Accept header
  its site needs;
- in the weekly delta: a walled employer's roles listed as closed, a posting written by both
  passes counted twice, and a failed sweep compared from a roles file an earlier run had left.

## 12. Known limits

- Pattern reading, everywhere. Section 2 and the README give examples that are read wrongly.
- A posting with no band passes the pay gate (section 3).
- US dollars and a United States home are assumed.
- A two-letter place fragment matches ordinary words in a pay line, and any home-place word in
  the 45 characters before a range labels that range ("our Denver-founded firm pays").
- The census quotes "$50,000 and $60,000" as a range whatever the words around it say.
- robots.txt and site terms are not read by the code. `offlimits` entries are how a person records
  that a site is ruled out.
- The Phenom search call sends the csrf token the site's own search page issues, as that page
  does. A site that refuses the call is reported as a wall.
