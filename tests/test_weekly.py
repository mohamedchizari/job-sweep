#!/usr/bin/env python3
"""Offline check of weekly_run.py: the canary stop, the delta between two runs on disk, and the
part that starts the sweep. No sweep runs. In the first half WEEKLY_DRY=1 makes it compare files
that are already there, and the one request made is the canary test's, to a name under .invalid,
which is reserved and never resolves. In the second half the canary call and the scanner process
are replaced by stand-ins, so the commands it would run can be read without running them.

  python3 tests/test_weekly.py
"""
import csv, json, os, subprocess, sys, tempfile
HERE = os.path.dirname(os.path.abspath(__file__)); ROOT = os.path.dirname(HERE)
COLS = ["employer", "req", "title", "location", "clearance", "band_low", "band_high", "band_ctx", "url"]


def check(cond, msg):
    print(("ok   " if cond else "FAIL ") + msg)
    return cond


def roles(path, rows):
    with open(path, "w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=COLS); w.writeheader()
        for r in rows:
            w.writerow(dict(zip(COLS, r)))


def run(cfg, res, **env):
    return subprocess.run([sys.executable, os.path.join(ROOT, "weekly_run.py"), "--config", cfg, "--results", res],
                          env=dict(os.environ, **env), capture_output=True, text=True)


def started_sweep(d):
    """The part of weekly_run.py that starts the sweep, with the canary call and the scanner
    process replaced by stand-ins that record what they were asked."""
    sys.path.insert(0, ROOT)
    import weekly_run as wr
    ok = True
    cfg_p = os.path.join(d, "config_started.json")
    with open(os.path.join(ROOT, "config.example.json"), encoding="utf-8") as fh:
        cfg = json.load(fh)
    with open(cfg_p, "w", encoding="utf-8") as fh:
        json.dump(cfg, fh)
    res = os.path.join(d, "results_started")
    asked, cmds, plan = {}, [], {}
    class Answer:
        status = 200
    def fake_open(req, timeout=None):
        asked["url"], asked["headers"] = req.full_url, {k.lower(): v for k, v in req.header_items()}
        return Answer()
    class Done:
        def __init__(self, rc, out): self.returncode, self.stdout, self.stderr = rc, out, ""
    def fake_run(cmd, **kw):
        cmds.append(list(cmd))
        if plan.get("raise"): raise plan["raise"]
        if plan.get("rows") is not None:
            roles(cmd[cmd.index("--out") + 1], plan["rows"])
        return Done(plan.get("rc", 0), plan.get("out", ""))
    real = (wr.urllib.request.urlopen, wr.subprocess.run, wr.TODAY, wr.DRY, wr.log)
    wr.urllib.request.urlopen, wr.subprocess.run, wr.DRY, wr.log = fake_open, fake_run, False, lambda msg: None
    def go(day, **p):
        plan.clear(); plan.update(p); del cmds[:]; wr.TODAY = day
        rc = wr.cli(["--config", cfg_p, "--results", res])
        f = os.path.join(res, "WEEKLY_DELTA_%s.md" % day)
        return rc, (open(f, encoding="utf-8").read() if os.path.exists(f) else "")
    one = ("alpha", "1", "Controller", "Denver, CO", "NONE STATED", "150000", "190000", "Denver", "https://x.example/1")
    try:
        rc, md = go("2026-04-01", rows=[one], out="WALLS (a wall is a finding, not an empty board):\n  lever beta: HTTP 503 after 0\n")
        ok &= check(rc == 0 and asked["url"] == cfg["weekly"]["canary_url"] and "job_scanner/" in asked["headers"].get("user-agent", "")
                    and "json" in asked["headers"].get("accept", ""), "started: the canary is asked first, with the tools' User-Agent and Accept header")
        first = [sys.executable, wr.SCANNER, "--config", cfg_p, "--out", os.path.join(res, "roles_2026-04-01.csv")]
        second = [sys.executable, wr.SCANNER, "--config", cfg_p, "--candidates", "--lane", "--cap", "0", "--only", "example_phenom",
                  "--out", os.path.join(res, "roles_2026-04-01_pass2.csv")]
        ok &= check(cmds == [first, second], "started: the sweep, then the second pass with --candidates --lane --cap 0 over the names in the settings")
        ok &= check("This run: roles_2026-04-01.csv + roles_2026-04-01_pass2.csv, 1 postings. Compared with: nothing (first run), 0 postings." in md
                    and "## New since last run (1)" in md, "started: both of today's files are read; a posting in both is one posting and one new role; a first run says so")
        ok &= check("Sweep exit 0; second pass exit 0." in md and "- scanner: lever beta: HTTP 503 after 0" in md
                    and os.path.exists(os.path.join(res, "RUN_LOG_2026-04-01.txt")) and os.path.exists(os.path.join(res, "RUN_LOG_2026-04-01_pass2.txt")),
                    "started: each pass's output is saved as a run log, and its walls reach the delta")
        nourl = [("delta", "", "One", "Remote", "NONE STATED", "", "", "", ""), ("delta", "", "Two", "Remote", "NONE STATED", "", "", "", "")]
        rc, md = go("2026-04-03", rows=[one] + nourl)
        ok &= check(rc == 0 and "## New since last run (2)" in md and "- none recorded (" in md and "## Closed since last run (0)" in md,
                    "started: rows with no URL are told apart by employer, req and title; a run with no wall says none was recorded")
        rc, md = go("2026-04-05", rc=1)
        ok &= check(rc == 5 and "exited 1 and wrote no roles_2026-04-05.csv" in md, "started: a sweep that fails and writes nothing: exit 5 and a STOPPED delta")
        rc, md = go("2026-04-03", rc=1)
        ok &= check(rc == 5 and "exited 1 and the roles_2026-04-03.csv on disk is not this run's" in md,
                    "started: a sweep that fails is a stop even when a roles file for today is already on disk")
        seq = iter([0, 1])
        def second_fails(cmd, **kw):
            cmds.append(list(cmd)); rc = next(seq)
            if rc == 0: roles(cmd[cmd.index("--out") + 1], [one])
            return Done(rc, "")
        roles(os.path.join(res, "roles_2026-04-04_pass2.csv"), nourl)
        wr.subprocess.run = second_fails; wr.TODAY = "2026-04-04"; del cmds[:]
        rc = wr.cli(["--config", cfg_p, "--results", res]); md = open(os.path.join(res, "WEEKLY_DELTA_2026-04-04.md"), encoding="utf-8").read()
        wr.subprocess.run = fake_run
        ok &= check(rc == 0 and "This run: roles_2026-04-04.csv, 1 postings." in md and "- second pass: job_scanner.py exited 1; its roles file was not read" in md
                    and "none recorded" not in md, "started: a second pass that fails is a wall, and a second-pass file an earlier run left is not read")
        rc, md = go("2026-04-06", **{"raise": wr.subprocess.TimeoutExpired("x", 1)})
        ok &= check(rc == 5 and "exited timeout" in md and len(cmds) == 2, "started: a sweep that times out: exit 5, and the second pass is still tried")
        rc, md = go("2026-04-07", **{"raise": RuntimeError("boom")})
        ok &= check(rc == 9, "started: a crash is exit 9, not a traceback and not exit 0")
        Answer.status = 503
        rc, md = go("2026-04-08", rows=[one])
        ok &= check(rc == 3 and cmds == [] and "Canary failed: 503" in md, "started: a canary that answers 503 stops the run before the scanner is started")
    finally:
        wr.urllib.request.urlopen, wr.subprocess.run, wr.TODAY, wr.DRY, wr.log = real
    return ok


def main():
    ok = True
    d = tempfile.mkdtemp(); res = os.path.join(d, "results"); os.makedirs(res)
    with open(os.path.join(ROOT, "config.example.json"), encoding="utf-8") as fh:
        cfg = json.load(fh)
    cfg_p = os.path.join(d, "config.json")
    with open(cfg_p, "w", encoding="utf-8") as fh:
        json.dump(cfg, fh)

    roles(os.path.join(res, "roles_2026-01-05.csv"), [
        ("alpha", "1", "Controller", "Denver, CO", "NONE STATED", "150000", "190000", "Denver", "https://x.example/1"),
        ("alpha", "2", "Audit Lead", "Denver, CO", "OBTAINABLE", "", "", "", "https://x.example/2"),
        ("beta", "9", "Treasury Analyst", "Remote", "NONE STATED", "", "", "", "https://y.example/9")])
    roles(os.path.join(res, "roles_2026-01-05_pass2.csv"), [
        ("beta", "9", "Treasury Analyst", "Remote", "NONE STATED", "", "", "", "https://y.example/9"),
        ("gamma", "5", "Auditor", "Boulder, CO", "NONE STATED", "", "", "", "https://z.example/5")])
    roles(os.path.join(res, "roles_2025-12-29.csv"), [
        ("old", "0", "Not compared: an older day", "Denver, CO", "NONE STATED", "", "", "", "https://o.example/0")])
    roles(os.path.join(res, "roles_2026-01-12.csv"), [
        ("alpha", "1", "Controller", "Denver, CO", "NONE STATED", "150000", "190000", "Denver", "https://x.example/1"),
        ("alpha", "3", "Manager%2C Audit", "Denver, CO", "ACTIVE REQUIRED", "205000", "265000", "Zone | A", "https://x.example/3"),
        ("gamma", "5", "Auditor", "Boulder, CO", "NONE STATED", "", "", "", "https://z.example/5")])

    with open(os.path.join(res, "RUN_LOG_2026-01-12.txt"), "w", encoding="utf-8") as fh:
        fh.write("  lever beta: HTTP 503 after 0\n\n3 enumerated -> 3 pass the gates -> 1 clear $140,000\nwritten: x\n\n"
                 "WALLS (a wall is a finding, not an empty board):\n  lever beta: HTTP 503 after 0\n  blocked: offlimits: robots\n\nnot a wall line\n")
    with open(os.path.join(res, "RUN_LOG_2026-01-12_pass2.txt"), "w", encoding="utf-8") as fh:
        fh.write("WALLS (a wall is a finding, not an empty board):\n  blocked: offlimits: robots\n  workday gamma: 9 of total 9; 1 lane rows read from the detail endpoint\n")
    p = run(cfg_p, res, WEEKLY_DRY="1", WEEKLY_TODAY="2026-01-12")
    md_p = os.path.join(res, "WEEKLY_DELTA_2026-01-12_DRY.md")
    md = open(md_p, encoding="utf-8").read() if os.path.exists(md_p) else ""
    ok &= check(p.returncode == 0 and md.startswith("# Weekly job sweep 2026-01-12"), f"dry run exits 0 and writes the delta ({p.stderr.strip()[-80:]})")
    ok &= check("Compared with: roles_2026-01-05.csv + roles_2026-01-05_pass2.csv, 4 postings." in md,
                "compared with both files of the newest earlier day, not with an older day; a posting in both files counts once")
    ok &= check("- beta: 1 postings last time, 0 now. A wall until shown otherwise, not 'no jobs'; its roles are not listed as closed." in md,
                "an employer that went to zero is a wall")
    ok &= check("- scanner: lever beta: HTTP 503 after 0" in md and "- scanner: workday gamma: 9 of total 9" in md and "not a wall line" not in md,
                "the notes the scanner printed under WALLS, in both passes, are copied into the delta")
    ok &= check(md.count("- scanner: blocked: offlimits: robots") == 1, "a note printed by both passes is listed once")
    ok &= check("## New since last run (1)" in md and "| alpha | Manager, Audit | Denver, CO | 205000 to 265000 (Zone / A) | ACTIVE REQUIRED | https://x.example/3 |" in md,
                "the new role is listed with its band and verdict; %2C decoded, a pipe in a cell replaced")
    ok &= check("## Closed since last run (1)" in md and "- alpha: Audit Lead https://x.example/2" in md and "- beta: Treasury Analyst" not in md,
                "a role that is gone is listed as closed; the walled employer's role is not")
    ok &= check("second pass exit dry" in md, "the run line says what ran")

    p = run(cfg_p, res, WEEKLY_DRY="1", WEEKLY_TODAY="2026-02-01")
    ok &= check(p.returncode == 5 and "wrote no roles_2026-02-01.csv" in open(os.path.join(res, "WEEKLY_DELTA_2026-02-01_DRY.md")).read(),
                "no roles file for today: exit 5 and a STOPPED delta that says so")

    cfg["weekly"] = {"canary_url": "https://canary.invalid/none"}
    with open(cfg_p, "w", encoding="utf-8") as fh:
        json.dump(cfg, fh)
    p = run(cfg_p, res, WEEKLY_TODAY="2026-03-01")
    stopped = os.path.join(res, "WEEKLY_DELTA_2026-03-01.md")
    ok &= check(p.returncode == 3 and "Canary failed" in open(stopped).read() and not os.path.exists(os.path.join(res, "roles_2026-03-01.csv")),
                "a canary that does not answer stops the run before any sweep: exit 3, a STOPPED delta, no roles file")

    cfg["weekly"] = {"canary_url": "https://canary.invalid/none"}; cfg["employers"]["typo"] = {"ats": "greenhose", "spec": "t"}
    with open(cfg_p, "w", encoding="utf-8") as fh:
        json.dump(cfg, fh)
    p = run(cfg_p, res)
    ok &= check(p.returncode == 2 and "employers.typo: unknown ats 'greenhose'" in p.stderr, "a kind the sweep cannot run stops the weekly run at load: exit 2")
    del cfg["employers"]["typo"]
    del cfg["weekly"]
    with open(cfg_p, "w", encoding="utf-8") as fh:
        json.dump(cfg, fh)
    p = run(cfg_p, res)
    ok &= check(p.returncode == 2 and "weekly.canary_url is not set" in p.stderr, "no canary in the settings: exit 2 with the reason")

    ok &= started_sweep(d)
    print("\nALL PASS" if ok else "\nFAILURES ABOVE")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
