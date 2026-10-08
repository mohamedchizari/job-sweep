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
   highest" form. A range may carry "USD" between its first figure and the dash, and then after
   its second figure too ("$150,000 USD - $180,000 USD"); in that form the second figure needs
   its dollar sign, and no other currency code is read. Such a range is read as the same words
   without "USD" would be; a comma right after the closing "USD" is taken into the range when
   the second figure has no cents, as a plain figure without cents takes its own comma in. A
   text that holds no "$figure USD" followed by a dash or "to" is read as it always was.

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
figure for the most expensive market. The home places are tried one at a time, in the order
`metro.places` lists them, and "the lowest top" then means the lowest among the ranges the first
such place labels. A pay table can hold a row for a listed city and a row for another city in a
listed state; the place listed first is the one read, even when the other row has the lower
top. So the nearest places are listed first and a whole state last. The same order decides among
the zones of a structured source. `band_top_all` in the output keeps the highest top among the
text ranges and the chosen band (not among the zones of a structured source), so the difference
is visible where the ranges are in the text.

The label of a text range is the text just before it, plus the "in <place>" or "for <zone>" that
follows it. Both forms occur: "Denver: $170,000 - $210,000" and "$170,000 - $210,000 in Denver".
When a phrase beginning in, for or at sits between two ranges, it is given to the range before
it, up to the next comma, semicolon or full stop, and at most 40 characters. One case is
excepted, the row of a pay table: "Denver, CO: $170,000 - $210,000 for Analyst Pueblo, CO:
$150,000 - $190,000". Three things must hold. The range has a label of its own that ends in a
colon. The phrase after it begins with "for" and does not go on with a home place or, when
remote counts as home, a remote word: "for Denver" and "for the Denver office" are place labels,
not grades. And the words up to the next range end in a colon, hold no semicolon, full stop or
dollar sign, run to at most 60 characters, do not name a home place directly after "in" or "at",
and do not go on after the last home place they name ("for staff in Denver, CO:" and "for our
Denver office Range:" are about the range before them; "for Analyst Denver, CO:" ends in the
next row's label). Then all of those words label the next range (their last 45 characters) and
none of them the range before. The words bonus, equity, stock, RSU, relocation, commission and
incentive right after "for" ("for Equity Analyst", "for equity") still remove that row's own
range, as they do outside a table, and are not held against the next row. A page's line breaks
are gone by then, and nothing else separates the grade from the next city. This is a heuristic. A sentence built another way can still attach a
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
| `workday` | Paged to the total reported on the first page, or until an empty page when none is reported, and never past 2,000 rows a query. A total of exactly 2,000 is flagged CAPPED. Unless a page of that first list failed, the query is then asked again once per value of one facet, leaving out values counted zero. The facet is flat, is not a place facet (its parameter name holds none of location, distance, country, region, state, city), has two values or more (a value counted zero included) and counts that add up to 2,000 or more; of those, the one whose counts add up to the most, and of two with the same sum the one with the smaller largest value. A value that comes back capped is split once more by a second facet, and no deeper. Once the split's queries have returned 6,000 postings it asks no further query. The flag gives the distinct postings held beside the facet's count. It cannot show a posting that has no value for the facet and was outside the first 2,000. It says the list is longer when no facet qualifies, and that it may still be longer when the two numbers differ, another usable facet counts more, a slice is still capped, or the bound is reached. A slice that is refused or fails is named in the flag and ends the split: no further query is sent. A reported total above 2,000, or 2,000 rows with no total, is flagged STOPPED and not split; so is a page that fails part-way. A list that ends short of its total is flagged SHORT. | No description without `--lane`: every row is then unread. |
| `icims` | Every URL in the sitemap, up to `--cap`; the cap is flagged. | Titles come from URL slugs. A refused job page is counted, and its row has no place. |
| `eightfold` | Paged to the reported count, which the note prints, or until empty when none is reported. Stops at 5,000 rows, or on a page that fails part-way; both are flagged, and so is a list that ends short of the count. | Descriptions are read only for rows that name a home place or a remote word. |
| `phenom_widget` | Measured against `totalHits`; sliced by category when paging under-delivers. Paging stops at 5,000 rows, flagged. | Marked INCOMPLETE under 90 percent of the total. |
| `avature` | Result pages until one repeats or is empty. Stops at `--cap` rows or at 200 pages, flagged. A board is read as a `FolderDetail` board when its first result page links no `JobDetail` page, links a `FolderDetail` page, and holds `folderOffset=` or `folderRecordsPerPage=` anywhere in it; the note then says "FolderDetail links", also when a later result page is refused. It is paged with `folderOffset`. The step is the first of these that is above zero and no more than the jobs the first page links: the smallest `folderOffset` on that page, the smallest `folderRecordsPerPage` on it; failing both, the number of those jobs. When the first page prints "N results" and the rows listed come to another number, that is flagged; a list that reaches `--cap` with exactly that number of rows is not flagged as stopped. | Many tenants refuse plain HTTP clients with 406. That is a wall. On a `FolderDetail` board a job is the number its address ends in, before a closing "/" and anything from "?" or "#" on (the whole address when it ends in none); its title is the text of its first link that has words. The title comes from the address instead (the part before the number) when no link has words, or when two or more jobs on one result page carry the same words, on that page or an earlier one: such a text is taken for a button. Its location is the job page's City, State and Country fields when the page prints a city or a state and its JSON-LD names neither (it can hold a country and a postcode only). |
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

**Offline tests.** `bash tests/run_all.sh` runs four files, 512 checks, with no route to any job
site. Fake sessions serve fixtures in each adapter's response shape. The part of `weekly_run.py`
that starts the sweep is tested with stand-ins for the canary call and the scanner process.
`python3 tests/mutate.py` then breaks 406 chosen rules on purpose, one at a time, in a copy of the
code: the gates, the band readers, each bound and flag named in section 7, a refused list call
for nine of the adapters, the settings checks, the census readings, the weekly delta. The tests
fail every time, once by not finishing (without the Avature page bound its test never ends).

The list was chosen by hand, and a rule outside it can still be untested. Gaps that are known:
the census's `--show` printing, the wording of most notes beyond the flags, and everything only a
live service can show, which is all of what sections 7 and 9 say about how the services answer.
For the split of a capped Workday list, section 12 names rules that no test pins.

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
Lever, Workday (two tenants), a JSON-LD page and a plain page. The split of a capped Workday list
(section 7) was added after publication. The code as committed was run live, without `--lane`, on
two tenants that reported exactly 2,000 postings. On one the split ran, and the scanner then held
exactly the number of postings the facet counted. On the other a page of the first list was
refused (HTTP 502) in each of two runs, so the scanner reported that tenant as stopped and did
not split it. An earlier build of the split, run the same day, had held exactly the facet's count
on both tenants.

**A FolderDetail board, live.** The reading of Avature boards that link `FolderDetail` pages
(section 7) was added after publication. The code as committed was run live once on one such
board, with a title lane: the rows listed came to the number the board's first page printed,
the note carried no flag, and every job page read gave a location with a city or a state.

**After the replay.** Six small fixes from the last review pass were made after the recordings
were replayed, and the replay was not run again: Phenom paging when no total is reported, the
Avature cap cutting its last page, a null JSON-LD date, `--probe` given a URL, the Workday
fingerprint, and the weekly run's handling of a failed second pass. The offline tests cover each.

**A full sweep, live.** At publication no full sweep had been run with the published code on a
live network: the live sweeps above were the refactor's. One has been run since, with private
settings: both passes of `weekly_run.py`, each exiting 0. Its row counts depend on those settings
and are not given here.

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
- A place more than 45 characters before its range, or in an earlier sentence, does not label
  it: "Staff in Denver and in some other cities are paid, for this role, a base range of
  $150,000 - $190,000" is read as a range with no place.
- The order of `metro.places` decides between two home places in one posting (section 2). A
  list that puts a state before its cities reads the lowest top among the rows that spell the
  state as listed. A stray home-place word before a range ("our Denver-founded firm pays") now
  also beats a range rightly labelled with a place listed later.
- The table-row rule of section 2 covers one form. When the words between two ranges run past
  60 characters, hold a full stop ("Colo.:") or do not end in a colon, the ranges are read as
  before, and a range can still take the next row's city. A list written "Range: $150,000 -
  $190,000 for greater Denver, Range: ..." is taken for a table, and "Denver" then labels the
  second range: after a comma, one word before the colon reads like a state. Only the last home
  place in those words is looked at, and "in" or "at" only directly before a place: "... for
  staff in greater Denver, CO: ..." and "... for our Denver team Boulder, CO: ..." are taken for
  table rows.
- A grade that begins with bonus, equity, stock, RSU, relocation, commission or incentive
  directly after "for" removes its own range ("$150,000 - $190,000 for Equity Analyst"), in a
  table as elsewhere. In a table, any not-salary word later in a grade ("for Senior Equity
  Analyst") removes the row after it. When a row is removed, the range read can be another
  city's.
- "USD" in a text range. A range with "USD" after its first figure was not read before; the
  posting then kept the band it had from elsewhere, or none. It is now read as the same words
  without "USD", so every limit of the plain form applies to it, and a reading that was right
  can turn wrong:
  - A dollar range that is not pay is taken for a band ("We manage budgets of $50,000 USD -
    $90,000 USD"). So is a bonus line that the not-a-salary rule of section 2 does not catch:
    "New hires also get $30,000 USD - $50,000 USD as a bonus" and "$30,000 USD - $50,000 USD
    bonus at target" are both read as bands.
  - Such a range can be picked over the salary range in the same text ("Typical deal sizes run
    $50,000 USD - $90,000 USD. The salary range is $150,000 - $190,000." gives $50,000 to
    $90,000, the lower top), and over a JSON-LD band when its words name a home place or
    remote ("Remote teams manage budgets of ..."). A lower range for another market does the
    same to a salary range that names no place: "The base range is $150,000 - $190,000. Zone
    B: $120,000 USD - $135,000 USD" gives $120,000 to $135,000.
  - The words behind a range, up to 40 characters, are its place: in "$120,000 USD - $135,000
    USD in Tucson and in Denver $150,000 - $190,000" the first range is read as Denver's.
  - Three figures chained with "USD" after the first are read as the first two ("Starts at
    $95,000 USD - $150,000 - $190,000" gives $95,000 to $150,000). When the words before the
    first say relocation, bonus or the like, that range is skipped and nothing is read at all
    ("Relocation of $20,000 USD - $150,000 - $190,000 base").
  - A comma right after a figure with cents is not taken into the range, with "USD" or
    without. In "$150,000.00 USD - $190,000.00 USD, in Denver; $195,000.00 USD - $245,000.00
    USD, in New York" the first range has no place and ", in Denver;" labels the second.
  - On malformed input a range can read differently from its plain form. With two commas in
    a row after the closing "USD", "$150,000 USD - $180,000 USD,, in Denver" has no place,
    and the same words without "USD" have one. "USD" written twice after the first figure is
    not read at all.
  With no "USD" after the first figure, the words behind "USD" after the second are still not
  read as that range's place or grade: "$150,000 - $180,000 USD in Denver" has no place. A
  range followed by another currency code ("$150,000 - $180,000 CAD") is read as US dollars.
  `posting_census.py` does not read "USD" after the first figure.
- Two ranges with the same top. Which of them is reported can differ from one run to the next
  ("Zone A: $100,000 - $150,000; Zone B: $120,000 - $150,000"): their order comes from a set.
- A `FolderDetail` Avature board. A first result page that links even one `JobDetail` page makes
  the board a `JobDetail` board, and its `FolderDetail` jobs are then not listed. A board whose
  first page holds neither `folderOffset=` nor `folderRecordsPerPage=` is read as empty. Any
  `FolderDetail` link on a result page is taken for a job, so a link that is page furniture
  becomes a row. When the first page gives no `folderOffset` above zero and no
  `folderRecordsPerPage` that is at most the number of jobs it links (none at all, or only
  larger ones, such as a link to the last page), such a link also makes the step one too long,
  and one job on every page is then never listed; the count check of section 7 misses that
  when the extra row and the missed job cancel out. The count check reads the first "N results"
  on the first page, in those words: a line such as "Showing 3 results" above the total, or a
  count of something else, gives a false flag, and a board that prints no such line is not
  checked. A board that answers every `folderOffset` with its first page is read as that one
  page, with no flag when it prints no count. A button text is known only once two jobs on one
  result page have carried it: on a board that shows one job to a page, "View job" stays every
  job's title. Two real jobs with the same title on one page lose it to the address, and so does
  any later job with that title. An address that ends in no number gives a row with an empty
  `req`. A result page refused part-way ends the list there; the note gives the status and how
  many jobs were listed before it. The City, State and Country fields are found by their English
  labels in Avature's own markup. A city field that says "Remote" is read as it stands. A job
  page that prints its pay only in labelled fields of its own, not as a range in its text or in
  its JSON-LD, shows no band. When a job page prints several City or State fields, the first of
  each that is not empty is the one read.
- A `FolderDetail` Avature board and `--cap`. A list cut by `--cap` part-way through a result
  page is not flagged as stopped when a further page is then read and holds only jobs already
  seen (five jobs on one page, a step of three and `--cap 4`). A list that reaches `--cap` with
  exactly the printed number of rows is taken for complete even when one of those rows is a
  link that is not a job and a job is missing. A board that prints no "N results" line is
  flagged as stopped, although it is complete, whenever it still has jobs at the last offset
  read below `--cap` (380 jobs, a step of 25 and `--cap 400`).
- More on a `FolderDetail` Avature board. When the first result page links `FolderDetail`
  pages and a later one links `JobDetail` pages, the later pages' jobs are not listed. A job
  whose addresses end in no number is listed once for each address it is linked under; when
  the step is taken from the number of jobs on the first page, it is then too long and jobs
  are missed. An address that is a number and nothing else, with no words in
  its link, gets the title "Folderdetail". A result page with tens of thousands of links takes
  seconds to read, and a first result page with tens of thousands of script tags that never
  close can take about a minute.
- The census quotes "$50,000 and $60,000" as a range whatever the words around it say.
- robots.txt and site terms are not read by the code. `offlimits` entries are how a person records
  that a site is ruled out.
- The Phenom search call sends the csrf token the site's own search page issues, as that page
  does. A site that refuses the call is reported as a wall.
- The split of a capped Workday list (section 7), added after publication:
  - A slice that ends short of its own total is not flagged by itself. It shows only when the
    postings held then differ from the facet's count, and a posting the facet leaves out can
    cancel that difference.
  - The place test is a match on the facet's parameter name, so a facet named for something else
    that holds one of those words is passed over.
  - A facet count too large to read as a number, or a `jobPostings` that is not a list, raises
    inside the split. The run then reports that employer as a wall with no rows, where the first
    2,000 had been listed.
  - Among the rules no test pins: the figure 6,000; the bound inside the second level; the count
    being of distinct postings; the reason given for a capped slice that has no second facet; the
    stop for a slice body that is not a JSON object; and that a total above 2,000, or 2,000 rows
    with no total, is flagged STOPPED and not split.
