# Third-party notices

## ats-scrapers 0.3.0

https://github.com/kalil0321/ats-scrapers (MIT)

Parts of `job_scanner.py` were written with that project's source open and match or follow it:

- `_phenom_post` and `phenom_widget`: the body of the Phenom search request and its headers; the
  seed GET of the search page with the same Accept string; the csrf token taken from the cookie
  first and from the page (the same pattern) second; a relative job URL prefixed with the site,
  and the full description preferred to the teaser (`scrapers/phenom.py`). `_phenom_jobs` and
  `_phenom_total`: the response paths tried, in the same order.
- `eightfold`: the search and detail routes, the field names read from them, and the rule that a
  timestamp above 1e10 is in milliseconds (`scrapers/eightfold.py`).
- `amazon`: the `business_category[]` parameter, the 400 past the row cap, and the reading of
  `locations` as JSON-encoded strings (`scrapers/amazon.py`).
- `successfactors_rss`: the feed path, the pattern that splits "(City, State, Country)" off a
  title, and the test that the bracket holds a place (`scrapers/successfactors.py`).
- `avature`: a full base URL for a custom domain, the page size of 12 and the bound of 200 pages
  (`scrapers/avature.py`).
- `workday`: the detail route, and reading a reported total of exactly 2,000 as a cap
  (`scrapers/workday.py`).

Its license:

```
MIT License

Copyright (c) 2026 Kalil Bouzigues

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE.
```
