#!/usr/bin/env python3
"""weekly_run.py - run the sweep on a schedule and report only what changed.

Steps:
  1. canary: the address in weekly.canary_url must answer 200, or nothing runs;
  2. job_scanner.py over the `employers` section -> results/roles_<today>.csv;
  3. if weekly.second_pass_only names any, a second pass over those names with
     --candidates --lane --cap 0 -> results/roles_<today>_pass2.csv (a name that sits under
     `employers` therefore runs in both passes);
  4. results/WEEKLY_DELTA_<today>.md: today's roles against the newest earlier day's. It lists
     the walls first, then new roles, then closed roles.

Two kinds of wall are written at the top of the delta: every note the scanner printed under
WALLS in this run, and every employer that had rows last time and has none now. Such an
employer's roles are not listed as closed: a wall is not evidence that a role closed.

Read-only on the web: it never applies, emails, messages or contacts anyone. Nothing here
installs a schedule; call it from a scheduler such as cron.

Exit codes: 0 ok, 2 settings, 3 canary failed, 5 the sweep failed, timed out or wrote no roles
file, 9 crash.

  python3 weekly_run.py --config config.json --results results
"""
import argparse, csv, datetime, glob, os, re, subprocess, sys, urllib.parse, urllib.request

import sweep_settings

HERE = os.path.dirname(os.path.abspath(__file__))
SCANNER = os.path.join(HERE, "job_scanner.py")
TODAY = os.environ.get("WEEKLY_TODAY") or datetime.date.today().isoformat()
DRY = os.environ.get("WEEKLY_DRY") == "1"   # test the delta on files already on disk: runs nothing, writes *_DRY.md


def log(msg):
    print(datetime.datetime.now().isoformat(timespec="seconds") + " " + msg, flush=True)


def write(path, text):
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(text)


def rows(path):
    with open(path, newline="", encoding="utf-8") as fh:
        return list(csv.DictReader(fh))


def cell(r, k):
    v = (r.get(k) or "").replace("|", "/").strip()
    return urllib.parse.unquote(v) if k == "title" else v   # older files carry %2C in titles read from URL slugs


def scanner_walls(log_text):
    """The lines the scanner printed under its WALLS heading."""
    out, on = [], False
    for line in (log_text or "").split("\n"):
        if line.startswith("WALLS ("): on = True; continue
        if on:
            if not line.strip(): break
            out.append(line.strip())
    return out


def key(r):
    u = (r.get("url") or "").strip()
    return u if u else (r.get("employer", ""), r.get("req", ""), r.get("title", ""))


def main(argv=None):
    ap = argparse.ArgumentParser(description="Canary, sweep, and a delta against the previous run.")
    ap.add_argument("--config", default="config.json")
    ap.add_argument("--results", default="results", help="folder for the roles files, run logs and deltas")
    a = ap.parse_args(argv)
    try:
        from job_scanner import KINDS   # the same checks the sweep will make, before anything runs
        settings = sweep_settings.load(a.config, known_ats=KINDS)
    except sweep_settings.SettingsError as e:
        print(f"settings: {e}", file=sys.stderr)
        return 2
    if not settings.weekly_canary:
        print("settings: weekly.canary_url is not set; it is the first request of every run", file=sys.stderr)
        return 2
    res = a.results
    os.makedirs(res, exist_ok=True)

    delta = os.path.join(res, "WEEKLY_DELTA_%s%s.md" % (TODAY, "_DRY" if DRY else ""))
    canary = settings.weekly_canary
    try:
        req = urllib.request.Request(canary, headers=dict(sweep_settings.HEADERS))
        code = 200 if DRY else urllib.request.urlopen(req, timeout=20).status
    except Exception as e:
        code = "error %s: %s" % (e.__class__.__name__, e)
    log("canary %s -> %s" % (canary, code))
    if code != 200:
        write(delta, "# Weekly job sweep %s: STOPPED\n\n## WALLS\n- Canary failed: %s. Nothing ran; no zero here means 'no jobs'.\n" % (TODAY, code))
        return 3
    out = os.path.join(res, "roles_%s.csv" % TODAY)
    out2 = os.path.join(res, "roles_%s_pass2.csv" % TODAY)
    env = dict(os.environ, PYTHONDONTWRITEBYTECODE="1")
    second = settings.weekly_second_pass
    rc1, rc2 = "dry", ("dry" if second else "not configured")
    log1, log2 = os.path.join(res, "RUN_LOG_%s.txt" % TODAY), os.path.join(res, "RUN_LOG_%s_pass2.txt" % TODAY)
    if not DRY:
        try:
            p = subprocess.run([sys.executable, SCANNER, "--config", a.config, "--out", out],
                               env=env, capture_output=True, text=True, timeout=3 * 3600)
            write(log1, (p.stdout or "") + "\n--- stderr ---\n" + (p.stderr or ""))
            rc1 = p.returncode
        except subprocess.TimeoutExpired:
            rc1 = "timeout"
        log("sweep exit %s" % rc1)
        if second:
            try:
                p2 = subprocess.run([sys.executable, SCANNER, "--config", a.config, "--candidates", "--lane", "--cap", "0",
                                     "--only", ",".join(second), "--out", out2],
                                    env=env, capture_output=True, text=True, timeout=3 * 3600)
                write(log2, (p2.stdout or "") + "\n--- stderr ---\n" + (p2.stderr or ""))
                rc2 = p2.returncode
            except subprocess.TimeoutExpired:
                rc2 = "timeout"
            log("second pass exit %s" % rc2)
    # A sweep that failed or timed out is a stop even when a roles file for today is on disk: that
    # file is then an earlier run's.
    if not os.path.exists(out) or rc1 not in (0, "dry"):
        write(delta, "# Weekly job sweep %s: STOPPED\n\n## WALLS\n- job_scanner.py exited %s and %s; see RUN_LOG_%s.txt.\n"
              % (TODAY, rc1, ("wrote no %s" if not os.path.exists(out) else "the %s on disk is not this run's") % os.path.basename(out), TODAY))
        return 5
    earlier = []
    for f in glob.glob(os.path.join(res, "roles_*.csv")):
        m = re.match(r"roles_(\d{4}-\d{2}-\d{2})(.*)\.csv$", os.path.basename(f))
        if m and m.group(1) < TODAY and m.group(2) in ("", "_pass2"):
            earlier.append((m.group(1), f))
    prev_day = max(d for d, _ in earlier) if earlier else None
    prev_files = sorted(f for d, f in earlier if d == prev_day)
    second_ok = rc2 in (0, "dry", "not configured")   # a failed second pass: a file of that name is an earlier run's
    new_files = [out] + ([out2] if second_ok and os.path.exists(out2) else [])
    new_rows = [r for f in new_files for r in rows(f)]
    old_rows = [r for f in prev_files for r in rows(f)]
    prev = " + ".join(os.path.basename(f) for f in prev_files) if prev_files else None
    old_k = set(key(r) for r in old_rows)
    new_k = set(key(r) for r in new_rows)
    old_by_key, new_by_key = {key(r): r for r in old_rows}, {key(r): r for r in new_rows}   # a posting in both passes counts once
    oc, nc = {}, {}
    for r in old_by_key.values():
        oc[r.get("employer", "")] = oc.get(r.get("employer", ""), 0) + 1
    for r in new_by_key.values():
        nc[r.get("employer", "")] = nc.get(r.get("employer", ""), 0) + 1
    walls = sorted(e for e in oc if nc.get(e, 0) == 0)
    added = list({key(r): r for r in new_rows if key(r) not in old_k}.values())   # one row per posting across passes
    closed = list({key(r): r for r in old_rows if key(r) not in new_k and r.get("employer", "") not in walls}.values())
    notes = []
    for f in (log1, log2):
        if os.path.exists(f):
            with open(f, encoding="utf-8") as fh:
                notes += scanner_walls(fh.read())
    notes = list(dict.fromkeys(notes))   # a standing wall is printed by both passes: list it once
    L = ["# Weekly job sweep %s" % TODAY, "",
         "This run: %s, %d postings. Compared with: %s, %d postings." % (" + ".join(os.path.basename(f) for f in new_files), len(new_by_key),
                                                                      prev if prev else "nothing (first run)", len(old_by_key)),
         "Canary answered 200. Sweep exit %s; second pass exit %s." % (rc1, rc2), "", "## WALLS"]
    L += ["- %s: %d postings last time, 0 now. A wall until shown otherwise, not 'no jobs'; its roles are not listed as closed." % (e, oc[e])
          for e in walls]
    L += ["- scanner: %s" % n for n in notes]
    if not second_ok:
        L += ["- second pass: job_scanner.py exited %s; its roles file was not read. See RUN_LOG_%s_pass2.txt." % (rc2, TODAY)]
    if not walls and not notes and second_ok:
        L += ["- none recorded (no employer went to zero, and no wall line was read from this run's scanner logs)"]
    L += ["", "## New since last run (%d)" % len(added), "",
          "| Employer | Title | Location | Band as read | Clearance verdict | URL |",
          "|---|---|---|---|---|---|"]
    for r in added:
        band = " to ".join(x for x in (cell(r, "band_low"), cell(r, "band_high")) if x)
        if cell(r, "band_ctx"):
            band += " (%s)" % cell(r, "band_ctx")
        L.append("| %s | %s | %s | %s | %s | %s |" % (cell(r, "employer"), cell(r, "title"), cell(r, "location"),
                                                  band, cell(r, "clearance"), cell(r, "url")))
    L += ["", "## Closed since last run (%d)" % len(closed), ""]
    L += ["- %s: %s %s" % (cell(r, "employer"), cell(r, "title"), cell(r, "url")) for r in closed] or ["- none"]
    L += ["", "Read-only run: nothing was applied for or sent."]
    write(delta, "\n".join(L) + "\n")
    log("delta %s new=%d closed=%d walls=%d" % (delta, len(added), len(closed), len(walls)))
    return 0


def cli(argv=None):
    """main(), with a crash turned into exit code 9 and one log line."""
    try:
        return main(argv)
    except Exception as e:
        log("FAILED %s: %s" % (e.__class__.__name__, e))
        return 9


if __name__ == "__main__":
    sys.exit(cli())
