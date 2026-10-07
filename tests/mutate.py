#!/usr/bin/env python3
"""Mutation check of the offline tests: break one rule at a time in a copy of the code and expect
`tests/run_all.sh` to fail. A rule that can be broken with every test still passing is reported
as SURVIVED. The list below was chosen by hand: it covers the gates, the band readers, each
adapter's bounds and flags, the settings checks, the census readings and the weekly delta, and a
rule outside it can still be untested. Each entry is (what is broken, file, the code as it is,
the code as broken); an entry whose "as it is" text no longer occurs exactly once is reported as
SKIP, so the list has to be kept in step with the code.

Takes about ten minutes. One entry (the Avature page bound) is caught by its test not finishing, so
each run has a time limit and, where the system supports it, a memory limit.

  python3 tests/mutate.py            (six at a time)
  python3 tests/mutate.py 2          (two at a time)
"""
import os, shutil, subprocess, sys, tempfile
from concurrent.futures import ThreadPoolExecutor
try:
    import resource
except ImportError:          # not on every system; the time limit still applies
    resource = None
SRC = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
WORKERS = int(sys.argv[1]) if len(sys.argv) > 1 else 6
J, C, W, S = "job_scanner.py", "posting_census.py", "weekly_run.py", "sweep_settings.py"
BAND = '        if 30_000 <= a <= b <= 2_000_000:\n            out.append((" ".join'
FT = '        if 30_000 <= a <= b <= 2_000_000:\n            out.append((FROMTO_LABEL, a, b))'
NS = "        if NOT_SALARY.search(before) or NOT_SALARY_AFTER.match(trail):"
LDB = '    if lo and cur in ("", "USD") and 30_000 <= lo <= hi <= 2_000_000:'
PART = "        if S.remote.search(part) and (S.home.search(part) or not S.foreign.search(part)):"
CB = '    return S.drop_active_clearance and r["clearance"] == "ACTIVE REQUIRED"'
FL = "    return not (bh is not None and bh < floor)"
LDW = '            if r.get("ld_low") and not (ctx and S.metro.search(ctx)):'
DD = "        if k not in best or (not keep(best[k], floor) and keep(r, floor)): best[k] = r"
LY = ('            yearly = (str(sal.get("currency") or "USD").upper() == "USD"\n'
      '                      and "year" in str(sal.get("interval") or "year").lower())')
TG = "    return bool(ok.search(t)) and not no.search(t)"
LEVEL = r'''LEVEL = r"(?:TS/SCI|\bTS\b|(?i:top[- ]secret|secret|q clearance|polygraph|ci poly|fs poly))"'''
M = [
 # ---------------- bands
 ("text band: lower bound off", J, BAND, BAND.replace("30_000", "3_000")),
 ("text band: upper bound off", J, BAND, BAND.replace("2_000_000", "2_000_000_000")),
 ("from/up-to form: bounds off", J, FT, FT.replace("30_000 <= a <= b <= 2_000_000", "True")),
 ("bonus-before rule off", J, NS, "        if NOT_SALARY_AFTER.match(trail):"),
 ("equity-after rule off", J, NS, "        if NOT_SALARY.search(before):"),
 ("trailing label not taken off the next range", J, "            ctx = ctx[prev_trail:]", "            pass"),
 ("no trailing labels", J, "        t = TRAILING.match(text, m.end())\n", "        t = None\n"),
 ("metro_band: remote label as good as a place label", J, "    for label in (S.places, S.metro):", "    for label in (S.metro,):"),
 ("metro_band: highest top first", J, "    low_first = sorted(bl, key=lambda t: t[2])", "    low_first = sorted(bl, key=lambda t: -t[2])"),
 ("metro_band: home label ignored", J, "            if label.search(ctx): return ctx, lo, hi", "            if False: return ctx, lo, hi"),
 ("ashby: currency ignored", J, '        if (c.get("currencyCode") or "USD") != "USD": continue\n', ""),
 ("ashby: non-salary component read", J, '        if (c.get("compensationType") or "").lower() != "salary": continue\n', ""),
 ("ashby: bounds off", J, "    ranges = [r for r in ranges if 30_000 <= r[1] <= r[2] <= 2_000_000]   # same sanity bound as bands()\n", ""),
 ("ashby: weekly not annualised", J, '"1 WEEK": 52,', '"1 WEEK": 1,'),
 ("ashby: fortnightly not annualised", J, '"2 WEEKS": 26,', '"2 WEEKS": 1,'),
 ("ashby: daily not annualised", J, '"1 DAY": 260,', '"1 DAY": 1,'),
 ("ashby: monthly not annualised", J, '"1 MONTH": 12,', '"1 MONTH": 1,'),
 ("ashby: hourly not annualised", J, '"1 HOUR": 2080}', '"1 HOUR": 1}'),
 ("ashby: tier text read beside components", J, '    if not ranges:\n        for tier in comp.get("compensationTiers") or []:', '    if True:\n        for tier in comp.get("compensationTiers") or []:'),
 ("greenhouse: currency ignored", J, '        if (pr.get("currency_type") or "USD") != "USD": continue\n', ""),
 ("greenhouse: float cents kept as floats", J, "int(lo) // 100, int(hi) // 100", "lo / 100, hi / 100"),
 ("JSON-LD: currency ignored", J, LDB, "    if lo and 30_000 <= lo <= hi <= 2_000_000:"),
 ("JSON-LD: bounds off", J, LDB, '    if lo and cur in ("", "USD"):'),
 ("JSON-LD: hourly not annualised", J, 'LD_UNIT = {"HOUR": 2080,', 'LD_UNIT = {"HOUR": 1,'),
 ("JSON-LD: 'Hourly' not annualised", J, '"HOURLY": 2080,', '"HOURLY": 1,'),
 ("JSON-LD: daily not annualised", J, '"DAY": 260,', '"DAY": 1,'),
 ("JSON-LD: weekly not annualised", J, '"WEEK": 52,', '"WEEK": 1,'),
 ("JSON-LD: monthly not annualised", J, '"MONTH": 12,', '"MONTH": 1,'),
 ("JSON-LD: TELECOMMUTE ignored", J, '    if str((jp or {}).get("jobLocationType", "")).upper() == "TELECOMMUTE": out.append("Remote")\n', ""),
 ("JSON-LD: validThrough ignored", J, '        return datetime.fromisoformat(str(vt)[:19].replace("Z", "")).date() < date.today()', "        return False"),
 ("JSON-LD always wins over a home text band", J, LDW, '            if r.get("ld_low"):'),
 ("JSON-LD never used", J, LDW, "            if False:"),
 ("structured pay not preferred", J, '            if r.get("pay_high"): lo, hi, ctx, src', '            if False: lo, hi, ctx, src'),
 # ---------------- gates
 ("place: 'not remote' read as remote", J, '    where = NOT_REMOTE.sub(" ", where)', "    pass"),
 ("place: foreign check off", J, PART, "        if S.remote.search(part):"),
 ("place: home-country mark off", J, PART, "        if S.remote.search(part) and not S.foreign.search(part):"),
 ("place: locations judged together", J, '    for part in re.split(r"[;|]", where):', "    for part in [where]:"),
 ("place: a home place beside a remote word not enough", J, '    if S.metro.search(S.remote.sub("", where)): return True       # a home place matched on its own\n', ""),
 ("place: band label tested with remote words", J, 'S.places.search(r["band_ctx"])', 'S.metro.search(r["band_ctx"])'),
 ("clearance never blocks", J, CB, "    return False"),
 ("clearance always blocks", J, CB, '    return r["clearance"] == "ACTIVE REQUIRED"'),
 ("expired kept", J, '    if r.get("expired") == "YES": return False\n', ""),
 ("unlisted kept", J, '    if r.get("listed") == "UNLISTED": return False\n', ""),
 ("unread kept", J, '    if r.get("unread") == "YES": return False   # listed but never read: no band, no clearance wording\n', ""),
 ("junior kept", J, '    if S.junior.search(r.get("title") or ""): return False\n', ""),
 ("floor is <=", J, FL, FL.replace("bh < floor", "bh <= floor")),
 ("no floor", J, FL, "    return True"),
 ("title gate: fail list ignored", J, TG, "    return bool(ok.search(t))"),
 ("title gate: pass list ignored", J, TG, "    return not no.search(t)"),
 ("delta: base is everything", J, "    base = [r for r in uniq if keep_but_for_band(r)]", "    base = list(uniq)"),
 # ---------------- the run
 ("--floor ignored", J, "    floor = S.pay_floor if a.floor is None else a.floor", "    floor = S.pay_floor"),
 ("--candidates ignored", J, "    if a.candidates: targets.update(S.candidates)\n", ""),
 ("candidates always run", J, "    if a.candidates: targets.update(S.candidates)\n", "    targets.update(S.candidates)\n"),
 ("--only ignored", J, "        targets = {k: v for k, v in targets.items() if k in wanted}\n", ""),
 ("standing walls off", J, "        if v[0] in sweep_settings.NOT_FETCHED: targets.setdefault(k, v)\n", ""),
 ("adapter exception not caught", J, '        except Exception as e:\n            rows, note = [], f"{name}: {type(e).__name__} {e}"', '        except ZeroDivisionError as e:\n            rows, note = [], f"{name}: {type(e).__name__} {e}"'),
 ("dedupe on req alone", J, '        k = (r["employer"], r["req"] or r["url"])', '        k = (r["employer"], r["req"])'),
 ("dedupe: first row wins", J, DD, "        if k not in best: best[k] = r"),
 ("dedupe: last row wins", J, DD, "        best[k] = r"),
 ("no dedupe", J, '        k = (r["employer"], r["req"] or r["url"])', "        k = id(r)"),
 ("clearance-drop count takes every active row", J, "        n = sum(1 for r in uniq if keep(r, floor, clearance=False) and not keep(r, floor))", '        n = sum(1 for r in uniq if r["clearance"] == "ACTIVE REQUIRED")'),
 ("scanner: no Accept header", J, "UA = dict(sweep_settings.HEADERS)", 'UA = {"User-Agent": sweep_settings.USER_AGENT}'),
 ("failed reads not counted", J, '    return f"; {n} detail reads FAILED" if n else ""', '    return ""'),
 # ---------------- adapters
 ("greenhouse: offices replace the location", J, 'x for x in [(j.get("location") or {}).get("name")]', "x for x in []"),
 ("greenhouse: pay fetched only with --deep", J, '        if deep or S.metro.search(rows[-1]["location"]):', "        if deep:"),
 ("lever: non-yearly range read", J, LY, '            yearly = (str(sal.get("currency") or "USD").upper() == "USD")'),
 ("lever: other currency read", J, LY, '            yearly = ("year" in str(sal.get("interval") or "year").lower())'),
 ("lever: EU fallback off", J, '            host = "api.eu.lever.co"; continue          # EU tenants live elsewhere\n', "            pass\n"),
 ("lever: stops after one page", J, "        if len(batch) < 100: break\n        time.sleep(PAUSE)\n    return rows, (f\"lever", "        break\n    return rows, (f\"lever"),
 ("lever: no pause between pages", J, "        if len(batch) < 100: break\n        time.sleep(PAUSE)\n    return rows, (f\"lever", "        if len(batch) < 100: break\n    return rows, (f\"lever"),
 ("ashby: unlisted not marked", J, 'listed="" if j.get("isListed", True) else "UNLISTED"', 'listed=""'),
 ("icims: cap not flagged", J, "    if cap and len(urls) > cap: note +=", "    if False: note +="),
 ("icims: lane filter off", J, "    if lane:\n        urls = [u for u in urls if lane.search(", "    if False:\n        urls = [u for u in urls if lane.search("),
 ("eightfold: unread mark off", J, '        row["unread"] = "YES"                                 # until its description has been read\n', ""),
 ("eightfold: 5,000 bound off", J, '        if start >= 5000:\n            bound = "  <-- STOPPED at the 5,000-row bound; the list is longer"; break\n', ""),
 ("eightfold: 5,000 bound not flagged", J, '            bound = "  <-- STOPPED at the 5,000-row bound; the list is longer"; break', '            break'),
 ("eightfold: rows elsewhere marked", J, '        if not S.metro.search(row["location"]): continue      # fails the place gate whatever its text says\n', ""),
 ("eightfold: ms rule off", J, "ts / 1000 if ts > 1e10 else ts", "ts"),
 ("eightfold: failure part-way not flagged", J, '            bound = f"  <-- STOPPED: HTTP {r.status_code} at start={start}{waf}; the list is longer"; break', '            break'),
 ("eightfold: count not printed", J, 'of = "count missing, paged until empty" if cnt is None else f"of count {cnt}"', 'of = "count missing, paged until empty" if cnt is None else "paged"'),
 ("eightfold: lane filter off", J, '        if not row.get("_pid") or (lane and not lane.search(row["title"])): continue', '        if not row.get("_pid"): continue'),
 ("eightfold: failed detail clears unread", J, '            if dr.status_code == 200:\n                row["text"] = strip_html(((dr.json()', '            if True:\n                row["text"] = strip_html(((dr.json()'),
 ("workday: unread mark off", J, '        row["unread"] = "YES"                       # until its detail has been read\n', ""),
 ("workday: 2,000-row stop off", J, "        if (total is not None and offset >= total) or offset >= 2000: break", "        if (total is not None and offset >= total): break"),
 ("workday: total re-read on every page", J, '        if offset == 0: total = d.get("total")', '        total = d.get("total")'),
 ("workday: missing total read as zero", J, '        if offset == 0: total = d.get("total")', '        if offset == 0: total = d.get("total", 0)'),
 ("workday: CAPPED flag off", J, "    if total == 2000:      # a capped tenant", "    if False:      # a capped tenant"),
 ("workday: 2,000-row stop not flagged", J, "    elif len(rows) >= 2000 and not stopped:", "    elif False:"),
 ("workday: failure part-way not flagged", J, '            stopped = f"  <-- STOPPED: HTTP {r.status_code} at offset={offset}; the list is longer"; break', '            break'),
 ("workday: split of a capped list off", J, "    if total == 2000 and not stopped:", "    if False:"),
 ("workday: a capped list split after a page failed", J, "    if total == 2000 and not stopped:", "    if total == 2000:"),
 ("workday split: a place facet used", J, "        if not isinstance(name, str) or not name or name in applied or WD_PLACE_FACET.search(name): continue", "        if not isinstance(name, str) or not name or name in applied: continue"),
 ("workday split: the applied facet used again", J, "        if not isinstance(name, str) or not name or name in applied or WD_PLACE_FACET.search(name): continue", "        if not isinstance(name, str) or not name or WD_PLACE_FACET.search(name): continue"),
 ("workday split: counts that add up to under 2,000 used", J, "        if len(vals) < 2 or total < 2000: continue", "        if len(vals) < 2: continue"),
 ("workday split: a one-value facet used", J, "        if len(vals) < 2 or total < 2000: continue", "        if total < 2000: continue"),
 ("workday split: the smaller sum preferred", J, "        key = (-total, max(c for _, c in vals))", "        key = (total, max(c for _, c in vals))"),
 ("workday split: tie decided by the larger largest value", J, "        key = (-total, max(c for _, c in vals))", "        key = (-total, -max(c for _, c in vals))"),
 ("workday split: a nested facet read as flat", J, '        if not isinstance(v, dict) or "values" in v or not v.get("id"): return []', '        if not isinstance(v, dict) or not v.get("id"): return []'),
 ("workday split: facets that are not a list crash it", J, "    for f in facets if isinstance(facets, list) else []:", "    for f in facets:"),
 ("workday split: a value counted zero queried", J, "        if not count: continue\n", ""),
 ("workday split: second level off", J, "            if depth == 0:\n                more, deeper", "            if False:\n                more, deeper"),
 ("workday split: a third level", J, "            if depth == 0:\n                more, deeper", "            if True:\n                more, deeper"),
 ("workday split: bound off", J, '        if state["listed"] >= WD_SPLIT_ROWS:', "        if False:"),
 ("workday split: postings listed twice kept twice", J, "            if path and path not in seen:", "            if path:"),
 ("workday split: a failed slice not reported", J, '        if stop: info["problems"].append(f"a slice stopped: {stop}")\n', ""),
 ("workday split: queries go on after a slice is refused", J, '        if stop: state["halted"] = True', '        if False: state["halted"] = True'),
 ("workday split: the level above goes on after a slice below is refused", J, '        if state.get("halted"): break', '        if stop: break'),
 ("workday split: a dropped connection in a slice not caught", J, '        except Exception as e:\n            return posts, total, facets, f"{type(e).__name__} at offset={offset}"', '        except ZeroDivisionError as e:\n            return posts, total, facets, f"{type(e).__name__} at offset={offset}"'),
 ("workday split: a slice paged past 2,000", J, "        if offset >= 2000 or (isinstance(total, int) and offset >= total): break", "        if isinstance(total, int) and offset >= total: break"),
 ("workday split: no pause before a slice", J, "        time.sleep(PAUSE)\n        sub = dict(applied, **{name: [vid]})", "        sub = dict(applied, **{name: [vid]})"),
 ("workday split: no pause between a slice's pages", J, '        time.sleep(PAUSE)\n    return posts, total, facets, ""', '    return posts, total, facets, ""'),
 ("workday split: another facet counting more not said", J, '    if most > info["expected"]:', "    if False:"),
 ("workday split: fewer postings than counted not said", J, '    if n < split["expected"]: why.append("fewer postings than the facet counts")\n', ""),
 ("workday split: more postings than counted not said", J, '    if n > split["expected"]: why.append("more postings than the facet counts, so it does not cover the list")\n', ""),
 ("workday split: an unfinished split reported plainly", J, '    if why: return base + said + "; the list may still be longer (" + "; ".join(why) + ")."\n', ""),
 ("workday split: no facet, no reason given", J, '''        why = f" ({split['problems'][0]})" if split and split["problems"] else ""''', '''        why = ""'''),
 ("workday: site-case probe off", J, "    if (first.status_code != 200 or not is_json(first)) and alt != site:", "    if False:"),
 ("workday: failed detail clears unread", J, "            if dr.status_code == 200:\n                info", "            if True:\n                info"),
 ("workday: lane filter off", J, '        if not lane or not lane.search(row["title"]) or (cap and n >= cap): continue', "        if not lane or (cap and n >= cap): continue"),
 ("workday: detail read without --lane", J, '        if not lane or not lane.search(row["title"]) or (cap and n >= cap): continue', '        if (lane and not lane.search(row["title"])) or (cap and n >= cap): continue'),
 ("avature: 200-page bound off", J, "    while (not cap or off < cap) and off < 12 * 200:", "    while (not cap or off < cap):"),
 ("avature: stop not flagged", J, "    if more:   # the loop ended on a bound, not on an empty page", "    if False:"),
 ("avature: lane skip off", J, '            if lane and not lane.search(row["title"]):', "            if False:"),
 ("avature: failed reads counted as read", J, '    n = sum(1 for r in rows if r.get("_detail") == "ok")\n    stop = ""', '    n = len(rows)\n    stop = ""'),
 ("phenom: no pause between POSTs", J, "        if calls[0]: time.sleep(PAUSE)\n", ""),
 ("phenom: INCOMPLETE flag off", J, "    if total and len(rows) < total * 0.9:", "    if False:"),
 ("phenom: 5,000 stop not flagged", J, "    if (total > 5000 and len(rows) < total) or (not known and frm >= 5000):", "    if False:"),
 ("phenom: 5,000 stop flagged only when under 90 percent", J, "    if (total > 5000 and len(rows) < total) or (not known and frm >= 5000):", "    if (total > 5000 and len(rows) < total * 0.9) or (not known and frm >= 5000):"),
 ("phenom: 5,000 bound off", J, "    while got and (frm < total or not known) and frm < 5000:", "    while got and (frm < total or not known):"),
 ("phenom: facet slicing off", J, "    if total and len(rows) < total:   # fallback only", "    if False:   # fallback only"),
 ("phenom: another tenant's csrf cookie sent", J, '            if "csrf" in c.name.lower() and (not dom or host.endswith(dom)): csrf = c.value', '            if "csrf" in c.name.lower(): csrf = c.value'),
 ("phenom: a 200 without refineSearch read as empty", J, '    if not isinstance(first.get("refineSearch"), dict):', "    if False:"),
 ("amazon: 400 on the first page read as empty", J, '''            if off == 0: return rows, f"amazon {spec!r}: HTTP 400 on the first page"\n''', ""),
 ("amazon: 400 after the first page an error", J, "        if r.status_code == 400:                  # past", "        if r.status_code == 400 and off == 0:                  # past"),
 ("amazon: 400 after the first page not flagged", J, '            stop = f"  <-- STOPPED: HTTP 400 at offset={off} (the search refuses an offset past its cap); the list may be longer"\n            break', '            break'),
 ("amazon: 10,000 stop not flagged", J, '            stop = "  <-- STOPPED at 10,000 rows, the most the search returns; the list may be longer"; break', '            break'),
 ("amazon: 10,000 bound off", J, "        if off >= 10000:\n", "        if False:\n"),
 ("amazon: short list not flagged", J, "    if not stop and total and len(rows) < total:", "    if False:"),
 ("successfactors: any bracket is a place", J, '''        if m and not ("," in m["loc"] or re.search(r"\\b[A-Z]{2}\\b", m["loc"])): m = None   # "(Excel)" is not a place\n''', ""),
 ("successfactors: every item read", J, '        if S.lane.search(row["title"]) and row["url"]:', '        if row["url"]:'),
 ("sitemap: rows not marked unread", J, 'location="", text="", url=u, posted="", unread="YES") for u in locs]', 'location="", text="", url=u, posted="") for u in locs]'),
 ("sitemap: cap off", J, "            if cap and in_lane > cap: continue\n", ""),
 ("sitemap: failed read clears unread", J, '            if row.get("_detail") == "ok": row["unread"] = ""; n += 1', '            row["unread"] = ""; n += 1'),
 ("sitemap: cap not flagged", J, 'lane rows. Use --cap 0." if cap and in_lane > cap else ""))', 'lane rows. Use --cap 0." if False else ""))'),
 # ---------------- settings
 ("settings: unknown keys accepted", S, "    stray = sorted(set(value) - KEYS[known])", "    stray = []"),
 ("settings: spec parts not checked", S, '            if parts and (len(spec.split("|")) != len(parts) or not all(p.strip() for p in spec.split("|"))):', "            if False:"),
 ("settings: unknown ats accepted", S, "            if kind not in known_ats and kind not in NOT_FETCHED:", "            if False:"),
 ("settings: blank spec accepted", S, '                or not entry["spec"].strip()):', "                or False):"),
 ("settings: words matched with \\b", S, 'return _compile(r"(?<![A-Za-z0-9_])(?:" + "|".join(frags) + r")(?![A-Za-z0-9_])"', 'return _compile(r"\\b(?:" + "|".join(frags) + r")\\b"'),
 ("settings: home marks in any case", S, '"metro.home_country", ignore_case=False)', '"metro.home_country")'),
 ("settings: accept_remote ignored", S, 'self.metro = _words(places + (REMOTE_WORDS if accept_remote else []), "metro.places")', 'self.metro = _words(places + REMOTE_WORDS, "metro.places")'),
 ("settings: joined-pattern error not caught", S, '    except re.error as e:\n        raise SettingsError(f"{key}: the patterns do not combine', '    except ZeroDivisionError as e:\n        raise SettingsError(f"{key}: the patterns do not combine'),
 ("settings: a null section is an error", S, "    if value is None and not required:\n        return None\n    if not isinstance(value, dict):", "    if not isinstance(value, dict):"),
 ("settings: a null list is an error", S, "    if value is None and not required:\n        return None\n    if not isinstance(value, list) or not value:", "    if not isinstance(value, list) or not value:"),
 ("settings: unreadable file not caught", S, "    except (OSError, UnicodeDecodeError) as e:", "    except ZeroDivisionError as e:"),
 ("settings: one name in both sections accepted", S, "        if both:\n", "        if False:\n"),
 ("settings: true accepted as a floor", S, "if isinstance(floor, bool) or not isinstance(floor, int) or floor < 0:", "if not isinstance(floor, int) or floor < 0:"),
 ("settings: any canary accepted", S, 'if canary is not None and not (isinstance(canary, str) and canary.startswith("https://")):', "if False:"),
 ("settings: second pass may name nobody", S, "        if unknown:\n", "        if False:\n"),
 ("settings: any clearance choice accepted", S, '        if when not in ("drop", "keep"):\n', "        if False:\n"),
 ("settings: empty pattern accepted", S, "        if not isinstance(frag, str) or not frag.strip():", "        if not isinstance(frag, str):"),
 # ---------------- census
 ("census: safe() is a no-op", C, "    return re.sub(r'[^A-Za-z0-9-]', '', s or '')", "    return s or ''"),
 ("census: no hash in the saved name", C, '''    return f"{safe(r.get('employer'))}_{safe(r.get('req'))}_{h}.txt"''', '''    return f"{safe(r.get('employer'))}_{safe(r.get('req'))}.txt"'''),
 ("census: 'No' is a value", C, 'NO_VALUE = re.compile(r"(none|no\\b|n/a|not applicable|not required)", re.I)', 'NO_VALUE = re.compile(r"(none|n/a|not applicable|not required)", re.I)'),
 ("census: levels in capitals only", C, LEVEL, LEVEL.replace("(?i:top[- ]secret|secret|q clearance|polygraph|ci poly|fs poly)", "(?:Top[- ]Secret|Secret|Q clearance|polygraph|CI poly|FS poly)")),
 ("census: TS inside a word", C, LEVEL, LEVEL.replace(r"\bTS\b", r"(?i:TS\b)")),
 ("census: obtain-before-active ignored", C, "        if soft and (not held or soft.start() < held.start()): continue", "        if soft and not held: continue"),
 ("census: public-trust alternative ignored", C, '''        if re.search(r"public trust[^.]{0,60}\\bor\\b|\\bor\\b[^.]{0,60}public trust", l, re.I):''', "        if False:"),
 ("census: 'not required' sentence read as a requirement", C, "        if NOT_NEEDED.search(l): continue\n", ""),
 ("census: 'not needed' value read as a requirement", C, "        if not v or NO_VALUE.match(v) or NOT_NEEDED.search(v):", "        if not v or NO_VALUE.match(v):"),
 ("census: process sentence read as a requirement", C, "        if PROCESS.search(l):", "        if False:"),
 ("census: process sentence never a requirement", C, "            if IS_REQUIRED.search(l): return 'ACTIVE_REQUIRED', l[:200]\n", ""),
 ("census: 'must have the ability to obtain' a requirement", C, '''        if m and not re.search(r"abilit|able to|eligib|obtain", m.group(1), re.I): return 'ACTIVE_REQUIRED', l[:200]''', "        if m: return 'ACTIVE_REQUIRED', l[:200]"),
 ("census: 'requires' not read", C, r"required|\brequires\b|maintain", "required|maintain"),
 ("census: title exemptions off", C, '''    if TITLE.search(title) and not re.search(r"sponsorship|desired|eligible|obtain", title, re.I):''', "    if TITLE.search(title):"),
 ("census: 'cleared' inside a word", C, r"\bcleared\b))", "cleared))"),
 ("census: 'poly' inside a word", C, r"\bpoly(?:graph)?\b", "poly"),
 ("census: a field about obtaining read as a requirement", C, "        if not m or SOFT.search(m.group(1)):", "        if not m:"),
 ("census: header kept on re-read", C, "text = f.read().split('\\n', 2)[-1]", "text = f.read()"),
 ("census: no Accept header", C, "UA = dict(sweep_settings.HEADERS)", 'UA = {"User-Agent": sweep_settings.USER_AGENT}'),
 ("census: band lower bound off", C, "if 40000 <= lo and hi <= 900000", "if 4000 <= lo and hi <= 900000"),
 ("census: any two figures are a range", C, r'''\s*(?:-|\u2013|\u2014|to|and)\s*\$\s?(\d{2,3},\d{3})(?:\.\d\d)?")''', r'''[^$]*\$\s?(\d{2,3},\d{3})(?:\.\d\d)?")'''),
 ("census: lowest top quoted", C, "(best is None or hi > best[1])", "(best is None or hi < best[1])"),
 ("census: unread posting read as NONE_FOUND", C, "            v, line = clearance(text, r.get('title', '')) if text else ('UNREAD', '')", "            v, line = clearance(text, r.get('title', ''))"),
 ("census: saved posting fetched again", C, "            if os.path.exists(fn):", "            if False:"),
 ("census: absent Ashby job read as a page", C, "        return 'ABSENT FROM LIST', ''   # read from the board list", "        pass   # read from the board list"),
 # ---------------- weekly
 ("weekly: walled employers listed as closed", W, ' and r.get("employer", "") not in walls}.values())', "}.values())"),
 ("weekly: scanner walls dropped", W, '    L += ["- scanner: %s" % n for n in notes]\n', ""),
 ("weekly: canary result ignored", W, "    if code != 200:\n", "    if False:\n"),
 ("weekly: compares with every earlier day", W, "    prev_files = sorted(f for d, f in earlier if d == prev_day)", "    prev_files = sorted(f for d, f in earlier)"),
 ("weekly: compares with the oldest day", W, "prev_day = max(d for d, _ in earlier) if earlier else None", "prev_day = min(d for d, _ in earlier) if earlier else None"),
 ("weekly: second file of the earlier day ignored", W, 'm.group(2) in ("", "_pass2")', 'm.group(2) in ("",)'),
 ("weekly: notes not deduped", W, "    notes = list(dict.fromkeys(notes))   # a standing wall is printed by both passes: list it once\n", ""),
 ("weekly: zero-employer walls off", W, "    walls = sorted(e for e in oc if nc.get(e, 0) == 0)", "    walls = []"),
 ("weekly: scanner walls read to the end of the log", W, "            if not line.strip(): break\n", ""),
 ("weekly: %2C not decoded", W, 'return urllib.parse.unquote(v) if k == "title" else v', "return v"),
 ("weekly: no-canary check off", W, "    if not settings.weekly_canary:\n", "    if False:\n"),
 ("weekly: kinds not checked at load", W, "settings = sweep_settings.load(a.config, known_ats=KINDS)", "settings = sweep_settings.load(a.config)"),
 ("weekly: a posting in both files counted twice", W, 'prev if prev else "nothing (first run)", len(old_by_key)),', 'prev if prev else "nothing (first run)", len(old_rows)),'),
 ("weekly: no roles file not noticed", W, '    if not os.path.exists(out) or rc1 not in (0, "dry"):', '    if rc1 not in (0, "dry"):'),
 # ---------------- rules added after a review found them untested
 ('greenhouse: band bounds off', J, '    ranges = [r for r in ranges if 30_000 <= r[1] <= r[2] <= 2_000_000]   # an hourly zone is not a yearly band\n', ''),
 ('greenhouse: no pause after a pay call that raises', J, '                rows[-1]["_detail"] = type(e).__name__\n            time.sleep(PAUSE)\n', '                rows[-1]["_detail"] = type(e).__name__\n'),
 ('greenhouse: a refused list read as an empty board', J, '    if r.status_code != 200: return [], f"greenhouse {token}: HTTP {r.status_code}"\n', ''),
 ('ashby: a refused list read as an empty board', J, '    if r.status_code != 200: return [], f"ashby {name}: HTTP {r.status_code}"\n', ''),
 ('lever: a refused list read as an empty board', J, '        if r.status_code != 200:\n            return rows, f"lever {name}: HTTP {r.status_code} after {len(rows)}"\n', ''),
 ('icims: a refused sitemap read as an empty one', J, '    if r.status_code != 200:\n        return [], f"icims {sub}: sitemap HTTP {r.status_code}"\n', ''),
 ('sitemap: a refused sitemap read as an empty one', J, '    if r.status_code != 200: return [], f"sitemap {url}: HTTP {r.status_code}"\n', ''),
 ('successfactors: a refused feed read as an empty one', J, '    if r.status_code != 200: return [], f"successfactors-rss {host}: HTTP {r.status_code} on /sitemal.xml"\n', ''),
 ('avature: a refused page read as the end of the list', J, '        if r.status_code != 200:\n            why = " (406', '        if False:\n            why = " (406'),
 ('eightfold: a refused search read as the end of the list', J, '        if r.status_code != 200:\n            waf = ', '        if False:\n            waf = '),
 ('amazon: a refused page read as the end of the list', J, '        if r.status_code != 200:\n            return rows, f"amazon {spec!r}: HTTP {r.status_code} at offset={off}"\n', ''),
 ("verdict: 'existing' not read", J, '(hold|possess)|existing)', '(hold|possess))'),
 ('verdict: a level with a polygraph not read', J, 'r"|\\b(ts/sci|top secret)\\b[^.]{0,50}?\\bpolygraph\\b"', 'r""'),
 ('verdict: public trust not read', J, 'obtain and maintain|public trust|suitability|', 'obtain and maintain|suitability|'),
 ('verdict: suitability not read', J, 'obtain and maintain|public trust|suitability|', 'obtain and maintain|public trust|'),
 ('verdict: citizenship not read', J, 'r"preferred|u\\.?s\\.?\\s+citizen)"', 'r"preferred)"'),
 ('verdict: obtaining read before active', J, '    if CLR_ACTIVE.search(t or ""): return "ACTIVE REQUIRED"\n    if CLR_OBTAIN.search(t or ""): return "OBTAINABLE"', '    if CLR_OBTAIN.search(t or ""): return "OBTAINABLE"\n    if CLR_ACTIVE.search(t or ""): return "ACTIVE REQUIRED"'),
 ('verdict: the title not read', J, '            hay = f"{r[\'title\']} {r[\'text\']}"', "            hay = r['text']"),
 ('script and style bodies read as text', J, '    s = re.sub(r"<(script|style)[^>]*>.*?</\\1>", " ", s, flags=re.S | re.I)\n', ''),
 ("text band: 'to' not a joiner", J, '(?:\\.\\d\\d)?\\s*(?:-|–|—|to)\\s*"', '(?:\\.\\d\\d)?\\s*(?:-|–|—)\\s*"'),
 ('not-salary words: relocation', J, 'rsus?|relocation|commission|incentive|stipend|allowance)\\b", re.I)', 'rsus?|commission|incentive|stipend|allowance)\\b", re.I)'),
 ('not-salary words: commission', J, 'rsus?|relocation|commission|incentive|stipend|allowance)\\b", re.I)', 'rsus?|relocation|incentive|stipend|allowance)\\b", re.I)'),
 ('not-salary words: stipend', J, 'rsus?|relocation|commission|incentive|stipend|allowance)\\b", re.I)', 'rsus?|relocation|commission|incentive|allowance)\\b", re.I)'),
 ('not-salary words: allowance', J, 'rsus?|relocation|commission|incentive|stipend|allowance)\\b", re.I)', 'rsus?|relocation|commission|incentive|stipend)\\b", re.I)'),
 ('ashby: six-month component not annualised', J, '"6 MONTHS": 2,', '"6 MONTHS": 1,'),
 ('ashby: a summary in millions not read', J, '{"k": 1_000, "m": 1_000_000}', '{"k": 1_000}'),
 ("JSON-LD: 'DAILY' not annualised", J, '"DAILY": 260,', '"DAILY": 1,'),
 ("JSON-LD: 'WEEKLY' not annualised", J, '"WEEKLY": 52,', '"WEEKLY": 1,'),
 ("JSON-LD: 'MONTHLY' not annualised", J, '"MONTHLY": 12,', '"MONTHLY": 1,'),
 ('JSON-LD: validThrough today counted as expired', J, '.date() < date.today()', '.date() <= date.today()'),
 ('JSON-LD: identifier not taken as the req', J, '            if isinstance(ident, dict) and ident.get("value"):\n                row["req"] = str(ident["value"])\n', ''),
 ('a page with no JSON-LD not read', J, '            row["text"] = (row.get("text", "") + " " + strip_html(r.text))[:60000]', '            pass'),
 ('band_top_all is the chosen band', J, 'band_top_all=max([t[2] for t in b] + [int(hi or 0)]) or "")', 'band_top_all=int(hi or 0) or "")'),
 ('output not sorted by band', J, 'key=lambda r: -(int(r["band_high"]) if str(r["band_high"]).isdigit() else 0))', 'key=lambda r: 0)'),
 ('explicit nulls not blanked', J, '                r[k] = r.get(k) or ""', '                r[k] = r.get(k)'),
 ('phenom: the token in the page not used', J, '        if m and not csrf: csrf = m.group(1)\n', ''),
 ("phenom: a /global/ site searched as 'us'", J, '        if path.startswith("/global/"): country = "global"\n', ''),
 ('amazon: the search not fixed to the United States', J, 'base_params = {"country": "USA", "result_limit": 100, "sort": "recent"}', 'base_params = {"result_limit": 100, "sort": "recent"}'),
 ('eightfold: reported count ignored', J, '        if cnt is not None and start >= cnt: break\n', ''),
 ('eightfold: a host with a dot not used as given', J, '    host = sub if "." in sub else f"{sub}.eightfold.ai"', '    host = f"{sub}.eightfold.ai"'),
 ('eightfold: a short list not flagged', J, '    if cnt is not None and len(rows) < cnt and not bound:', '    if False:'),
 ('workday: detail cap off', J, '        if not lane or not lane.search(row["title"]) or (cap and n >= cap): continue', '        if not lane or not lane.search(row["title"]): continue'),
 ('workday: jobReqId not taken', J, '                row["req"] = info.get("jobReqId") or row["req"]\n', ''),
 ('workday: a short list not flagged', J, '    elif total is not None and len(rows) < total and not stopped:', '    elif False:'),
 ('icims: sitemap URLs that are not jobs fetched', J, 'r.text) if "/jobs/" in u]', 'r.text)]'),
 ('successfactors: a refused page counted as read', J, '            if row.get("_detail") == "ok": n += 1; continue\n        row["unread"] = "YES"', '            n += 1; continue\n        row["unread"] = "YES"'),
 ('discover: lever fingerprint broken', J, 'r"jobs\\.lever\\.co/([a-z0-9-]+)"', 'r"jobs\\.lever\\.io/([a-z0-9-]+)"'),
 ('discover: ashby fingerprint broken', J, 'r"jobs\\.ashbyhq\\.com/([A-Za-z0-9-]+)"', 'r"jobs\\.ashbyhq\\.io/([A-Za-z0-9-]+)"'),
 ('discover: no word when nothing is found', J, '    if not found:\n', '    if False:\n'),
 ("discover: 'embed' printed as a Greenhouse token", J, 'for=)?(?!embed\\b)(', 'for=)?('),
 ('probe: never reports a hit', J, 'hit = "HIT " if r.status_code == 200 and len(r.content) > 400 else "    "', 'hit = "    "'),
 ('lever: float figures not read', J, "${whole(sal.get('min',''))} - ${whole(sal.get('max',''))}", "${sal.get('min','')} - ${sal.get('max','')}"),
 ('delta: surfaced list holds every kept row', J, '    surfaced = [r for r in new if not title_gate(r)]', '    surfaced = list(new)'),
 ('delta: title-gate count leaves out the dropped rows', J, 'pass the title gate {len(kept_both) + len(dropped)}.', 'pass the title gate {len(kept_both)}.'),
 ('settings: accept_remote defaults to false', S, '            accept_remote = True\n', '            accept_remote = False\n'),
 ('settings: a null accept_remote is an error', S, '        if accept_remote is None:\n            accept_remote = True\n', ''),
 ('settings: accept_remote of any type accepted', S, '        if not isinstance(accept_remote, bool):\n', '        if False:\n'),
 ('settings: a null second pass is an error', S, '        if second is None:\n            second = []\n', ''),
 ('settings: a second pass of any type accepted', S, '        if not isinstance(second, list) or not all(isinstance(n, str) and n for n in second):', '        if False:'),
 ('settings: a negative floor accepted', S, 'if isinstance(floor, bool) or not isinstance(floor, int) or floor < 0:', 'if isinstance(floor, bool) or not isinstance(floor, int):'),
 ('settings: a file that holds a list accepted', S, '        if not isinstance(d, dict):\n            raise SettingsError("the settings file must hold one JSON object")\n', ''),
 ("settings: 'anywhere' not a remote word", S, '["remote", "anywhere", "nationwide", "telework"]', '["remote", "nationwide", "telework"]'),
 ("settings: 'nationwide' not a remote word", S, '["remote", "anywhere", "nationwide", "telework"]', '["remote", "anywhere", "telework"]'),
 ("settings: 'telework' not a remote word", S, '["remote", "anywhere", "nationwide", "telework"]', '["remote", "anywhere", "nationwide"]'),
 ("settings: 'coordinator' not a junior word", S, '"assistant", "coordinator", "new grad"]', '"assistant", "new grad"]'),
 ("settings: 'new grad' not a junior word", S, '"assistant", "coordinator", "new grad"]', '"assistant", "coordinator"]'),
 ("settings: 'emea' not on the foreign list", S, '"emea", "apac", "latam"]', '"apac", "latam"]'),
 ("settings: 'apac' not on the foreign list", S, '"emea", "apac", "latam"]', '"emea", "latam"]'),
 ("settings: 'latam' not on the foreign list", S, '"emea", "apac", "latam"]', '"emea", "apac"]'),
 ('settings: words matched inside words', S, 'return _compile(r"(?<![A-Za-z0-9_])(?:" + "|".join(frags) + r")(?![A-Za-z0-9_])"', 'return _compile(r"(?:" + "|".join(frags) + r")"'),
 ('census: band upper bound off', C, 'if 40000 <= lo and hi <= 900000', 'if 40000 <= lo'),
 ('census: a long line read as a pay line', C, "        if '$' not in l or len(l) > 700: continue", "        if '$' not in l: continue"),
 ('census: a paragraph read as a requirement line', C, '        if len(l) > 400 or not NAMES_LEVEL.search(l) or', '        if not NAMES_LEVEL.search(l) or'),
 ('census: a refused Greenhouse call read as text', C, "        if r.status_code != 200: return r.status_code, ''\n        d = r.json(); pay = ", '        d = r.json(); pay = '),
 ('census: a value two lines down not read', C, 'lines[i+1:i+3]', 'lines[i+1:i+2]'),
 ('census: the next label read as a value', C, "            if v.endswith(':') or not (", '            if not ('),
 ("census: a wish after 'active' read as a requirement", C, '        if WISH.search(l) and not re.search(r"required|must", l, re.I): continue', '        pass'),
 ('census: a wish beside a requirement undoes it', C, '        if WISH.search(l) and not re.search(r"required|must", l, re.I): continue', '        if WISH.search(l): continue'),
 ("census: 'at the time of application' not read", C, '|maintain|at the time of application|to be considered)', '|maintain|to be considered)'),
 ("census: 'to be considered' not read", C, '|maintain|at the time of application|to be considered)', '|maintain|at the time of application)'),
 ('census: --only ignored', C, '        rows = [r for r in rows if f"{r[\'employer\']}:{r[\'req\']}" in want]\n', ''),
 ('census: --skip-employers ignored', C, "        rows = [r for r in rows if r['employer'] not in skip]\n", ''),
 ('census: missing columns not checked', C, '    if missing:\n        sys.exit(', '    if False:\n        sys.exit('),
 ('weekly: a stopped sweep exits 0', W, '% os.path.basename(out), TODAY))\n        return 5', '% os.path.basename(out), TODAY))\n        return 0'),
 ('weekly: a failed sweep read from a roles file already on disk', W, '    if not os.path.exists(out) or rc1 not in (0, "dry"):', '    if not os.path.exists(out):'),
 ("weekly: canary sent without the tools' headers", W, 'headers=dict(sweep_settings.HEADERS))', 'headers={})'),
 ('weekly: second pass without --lane', W, '"--candidates", "--lane", "--cap", "0",', '"--candidates", "--cap", "0",'),
 ('weekly: second pass without --candidates', W, '"--candidates", "--lane", "--cap", "0",', '"--lane", "--cap", "0",'),
 ('weekly: second pass with the default cap', W, '"--candidates", "--lane", "--cap", "0",', '"--candidates", "--lane",'),
 ('weekly: sweep started with a wrong flag', W, '[sys.executable, SCANNER, "--config", a.config, "--out", out],', '[sys.executable, SCANNER, "--confg", a.config, "--out", out],'),
 ('weekly: a crash exits 0', W, '        return 9', '        return 0'),
 ('weekly: a timeout of the sweep is a crash', W, '        except subprocess.TimeoutExpired:\n            rc1 = "timeout"', '        except ZeroDivisionError:\n            rc1 = "timeout"'),
 ('weekly: rows with no URL keyed on nothing', W, '    return u if u else (r.get("employer", ""), r.get("req", ""), r.get("title", ""))', '    return u'),
 ('weekly: no line when no wall was recorded', W, '    if not walls and not notes and second_ok:\n', '    if False:\n'),
 ('weekly: a first run not named as one', W, 'prev if prev else "nothing (first run)"', 'prev'),
 ("weekly: today's second file not read", W, '    new_files = [out] + ([out2] if second_ok and os.path.exists(out2) else [])', '    new_files = [out]'),
 ('weekly: new roles counted per row', W, '    added = list({key(r): r for r in new_rows if key(r) not in old_k}.values())', '    added = [r for r in new_rows if key(r) not in old_k]'),
 ('weekly: run log not written', W, '            write(log1, (p.stdout or "") + "\\n--- stderr ---\\n" + (p.stderr or ""))\n', ''),
 ("phenom: a missing total ends the list after one page", J, "    while got and (frm < total or not known) and frm < 5000:", "    while got and frm < total and frm < 5000:"),
 ("avature: the last page not cut at the cap", J, "            if cap and len(rows) >= cap: break   # the last page is cut at the cap\n", ""),
 ("JSON-LD: a null date written as the word None", J, 'str(jp.get("datePosted") or "")[:10]', 'str(jp.get("datePosted", ""))[:10]'),
 ("probe: a URL not accepted", J, '    host = re.sub(r"^https?://", "", domain).split("/")[0]', "    host = domain"),
 ("discover: the Workday API path read as a site", J, r"(?!wday\b)(", "("),
 ("weekly: a failed second pass read from a file already on disk", W, '    second_ok = rc2 in (0, "dry", "not configured")', "    second_ok = True"),
]

def limit():
    resource.setrlimit(resource.RLIMIT_AS, (1500 * 1024 * 1024, 1500 * 1024 * 1024))


FILES = ("job_scanner.py", "sweep_settings.py", "posting_census.py", "weekly_run.py", "config.example.json")

def one(m):
    name, f, old, new = m
    with open(os.path.join(SRC, f), encoding="utf-8") as fh:
        src = fh.read()
    if src.count(old) != 1:
        return name, "SKIP (old text occurs %dx)" % src.count(old)
    d = tempfile.mkdtemp()
    os.makedirs(os.path.join(d, "t"))
    for fn in FILES:                                  # the code and the example settings, not your own files
        shutil.copy(os.path.join(SRC, fn), os.path.join(d, "t", fn))
    shutil.copytree(os.path.join(SRC, "tests"), os.path.join(d, "t", "tests"), ignore=shutil.ignore_patterns("__pycache__"))
    with open(os.path.join(d, "t", f), "w", encoding="utf-8") as fh:
        fh.write(src.replace(old, new))
    try:
        p = subprocess.run(["bash", "tests/run_all.sh"], cwd=os.path.join(d, "t"), capture_output=True, text=True, timeout=150,
                           env=dict(os.environ, PYTHONDONTWRITEBYTECODE="1", PYTHON=os.environ.get("PYTHON", sys.executable)),
                           preexec_fn=limit if resource else None)
        res = "caught" if p.returncode != 0 else "SURVIVED"
    except subprocess.TimeoutExpired:
        res = "caught (the test did not finish)"
    shutil.rmtree(d, ignore_errors=True)
    return name, res

def main():
    with ThreadPoolExecutor(WORKERS) as ex:
        res = list(ex.map(one, M))
    for n, r in res:
        if not r.startswith("caught"): print(f"{r:32} {n}")
    caught = sum(1 for _, r in res if r.startswith("caught"))
    hung = sum(1 for _, r in res if r.startswith("caught ("))
    survived = sum(1 for _, r in res if r == "SURVIVED")
    skipped = sum(1 for _, r in res if r.startswith("SKIP"))
    print(f"{len(M)} rules broken one at a time: {caught} caught ({hung} by a test that did not finish), {survived} survived, {skipped} skipped")
    return 0 if caught == len(M) else 1


if __name__ == "__main__":
    sys.exit(main())
