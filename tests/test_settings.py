#!/usr/bin/env python3
"""Offline check of sweep_settings.py: the example file loads, and each kind of mistake stops the
load with the name of the key that is wrong.

  python3 tests/test_settings.py
"""
import json, os, sys, tempfile
HERE = os.path.dirname(os.path.abspath(__file__)); ROOT = os.path.dirname(HERE); sys.path.insert(0, ROOT)
import sweep_settings as ss

# The kinds a caller can run, as job_scanner.py passes them: name -> the parts of a spec written a|b|c, or None.
KNOWN = {"greenhouse": None, "lever": None, "ashby": None, "icims": None, "phenom_widget": None,
         "workday": ("tenant", "shard", "site"), "eightfold": ("host", "domain.com")}


def check(cond, msg):
    print(("ok   " if cond else "FAIL ") + msg)
    return cond


def example():
    with open(os.path.join(ROOT, "config.example.json"), encoding="utf-8") as fh:
        return json.load(fh)


def error(change=None, drop=None, known=KNOWN, inside=None):
    """The SettingsError text for the example with one change, or '' when it loads.
    inside=("metro", {...}) merges keys into one section instead of replacing it."""
    d = example()
    if drop: del d[drop]
    if change: d.update(change)
    if inside: d[inside[0]] = dict(d[inside[0]], **inside[1])
    try:
        ss.Settings(d, known_ats=known); return ""
    except ss.SettingsError as e:
        return str(e)


def main():
    ok = True
    s = ss.Settings(example(), known_ats=KNOWN)
    ok &= check(s.pay_floor == 140000 and s.employers["example_workday"] == ("workday", "TENANT|wd5|SiteName")
                and s.candidates["example_blocked"][0] == "offlimits" and not s.drop_active_clearance,
                "the example file loads: floor, employers, candidates, clearance choice")
    ok &= check(bool(s.metro.search("Denver, CO")) and bool(s.metro.search("Remote")) and not s.metro.search("Denvers")
                and bool(s.places.search("Denver")) and not s.places.search("Remote"),
                "metro: places and remote words match as whole words; `places` holds the places alone")
    ok &= check(bool(s.lane.search("Senior CPA")) and not s.lane.search("CPAP Technician") and bool(s.lane.search("Auditor")),
                "lane: a fragment's own word boundary is kept; a fragment without one matches inside a word")
    ok &= check(bool(s.junior.search("Accounting Intern")) and bool(s.junior.search("Jr. Accountant")) and bool(s.foreign.search("Remote - Spain")),
                "the built-in junior and foreign word lists are compiled when the file does not override them")
    ok &= check(all(s.home.search(x) for x in ("Remote, USA", "Remote - US", "Remote, U.S. or Canada", "Remote (United States)"))
                and not s.home.search("Remote - Austria"), "home-country marks match, 'U.S.' before a space included")
    ok &= check(not s.home.search("Remote, London (join us)") and bool(s.home.search("Remote (united states)")) and not s.home.search("Remote - usa"),
                "home-country marks keep their case: 'US' is a mark, the word 'us' is not; 'United States' matches in any case")
    ok &= check(s.title_gate is not None and s.weekly_second_pass == ["example_phenom"]
                and s.weekly_canary.startswith("https://"), "optional sections are read")
    d = example(); d["metro"]["accept_remote"] = False; d["metro"]["foreign_places"] = ["atlantis"]; d["metro"]["home_country"] = ["Utopia"]
    d["junior_titles"] = ["apprentice"]
    s2 = ss.Settings(d, known_ats=KNOWN)
    ok &= check(not s2.metro.search("Remote") and bool(s2.foreign.search("Atlantis")) and not s2.foreign.search("Spain")
                and bool(s2.home.search("Utopia")) and not s2.home.search("utopia") and not s2.home.search("USA")
                and bool(s2.junior.search("Apprentice")) and not s2.junior.search("Intern"),
                "accept_remote false takes the remote words out; the three optional word lists replace the built-in ones; a home-country mark keeps its case")
    d = example()
    for k in ("title_gate", "candidates", "weekly", "about"): del d[k]
    del d["metro"]["accept_remote"]
    s3 = ss.Settings(d, known_ats=KNOWN)
    ok &= check(s3.title_gate is None and s3.candidates == {} and s3.weekly_canary is None and s3.weekly_second_pass == [],
                "every optional section may be left out")
    ok &= check(s3.accept_remote is True and bool(s3.metro.search("Remote")), "metro.accept_remote left out: remote counts as home")
    d = example()
    for k in ("title_gate", "candidates", "weekly", "junior_titles"): d[k] = None
    d["metro"]["home_country"] = None; d["metro"]["foreign_places"] = None; d["metro"]["accept_remote"] = None
    s4 = ss.Settings(d, known_ats=KNOWN)
    ok &= check(s4.title_gate is None and s4.candidates == {} and s4.weekly_canary is None and bool(s4.junior.search("Intern"))
                and bool(s4.home.search("USA")) and bool(s4.foreign.search("Spain")) and s4.accept_remote is True,
                "an optional key set to null counts as left out: three sections, three word lists, accept_remote")
    d = example(); d["weekly"] = {"canary_url": None, "second_pass_only": None}
    s5 = ss.Settings(d, known_ats=KNOWN)
    ok &= check(s5.weekly_canary is None and s5.weekly_second_pass == [], "the two keys of `weekly` set to null count as left out")
    ok &= check(all(s.metro.search(x) for x in ("Telework eligible", "Nationwide", "Work from anywhere")) and bool(s.junior.search("Project Coordinator"))
                and bool(s.junior.search("New Grad Accountant")) and all(s.foreign.search(x) for x in ("Remote - EMEA", "APAC", "LATAM")),
                "the built-in word lists: remote words, junior words, regions on the foreign list")
    ok &= check(not s.junior.search("Internal Auditor") and not s.title_gate[0].search("Misleading Indicators Analyst") and not s.title_gate[1].search("Internal Auditor")
                and not s.foreign.search("Remote - Ukraine"), "junior, title-gate and foreign words match whole words only: 'Internal' is not 'intern', 'Ukraine' is not 'UK'")

    for label, kw, want in (
        ("a missing floor", dict(drop="pay_floor"), "pay_floor: expected a whole number"),
        ("a floor in quotes", dict(change={"pay_floor": "140000"}), "pay_floor: expected a whole number"),
        ("true as a floor", dict(change={"pay_floor": True}), "pay_floor: expected a whole number"),
        ("a negative floor", dict(change={"pay_floor": -1}), "pay_floor: expected a whole number"),
        ("accept_remote in quotes", dict(inside=("metro", {"accept_remote": "yes"})), "metro.accept_remote: expected true or false"),
        ("a second pass that is not a list", dict(inside=("weekly", {"second_pass_only": "example_phenom"})), "weekly.second_pass_only: expected a list of names"),
        ("no places", dict(change={"metro": {"places": []}}), "metro.places: expected a non-empty list"),
        ("a broken pattern", dict(change={"lane_titles": ["audit", "(unclosed"]}), "lane_titles[1]: '(unclosed' is not a valid pattern"),
        ("an empty pattern", dict(change={"lane_titles": ["audit", " "]}), "lane_titles[1]: expected a non-empty string"),
        ("two patterns that do not combine", dict(change={"lane_titles": ["(?P<a>audit)", "(?P<a>tax)"]}), "lane_titles: the patterns do not combine"),
        ("two places that do not combine", dict(change={"metro": {"places": ["(?P<a>denver)", "(?P<a>boulder)"]}}), "metro.places: the patterns do not combine"),
        ("an unknown clearance choice", dict(change={"clearance": {"when_active_required": "maybe"}}), 'expected "drop" or "keep"'),
        ("a missing clearance section", dict(drop="clearance"), 'expected "drop" or "keep"'),
        ("an unknown ATS", dict(change={"employers": {"x": {"ats": "greenhose", "spec": "t"}}}), "employers.x: unknown ats 'greenhose'"),
        ("an employer without a spec", dict(change={"employers": {"x": {"ats": "lever"}}}), "employers.x: expected"),
        ("an employer with a blank spec", dict(change={"employers": {"x": {"ats": "lever", "spec": " "}}}), "employers.x: expected"),
        ("an employer with an extra key", dict(change={"employers": {"x": {"ats": "lever", "spec": "s", "note": "n"}}}), "employers.x: unknown key(s): note"),
        ("a Workday spec with two parts", dict(change={"employers": {"x": {"ats": "workday", "spec": "tenant|wd5"}}}), "employers.x: a workday spec is tenant|shard|site; got 'tenant|wd5'"),
        ("an Eightfold spec with an empty part", dict(change={"employers": {"x": {"ats": "eightfold", "spec": "host|"}}}), "employers.x: a eightfold spec is host|domain.com"),
        ("no employers", dict(change={"employers": {}}), "employers: expected an object"),
        ("one name in both sections", dict(change={"candidates": {"example_lever": {"ats": "lever", "spec": "s"}}}), "candidates: example_lever also listed under employers"),
        ("a misspelt section", dict(change={"weekley": {}}), "unknown key(s): weekley"),
        ("a misspelt key inside metro", dict(inside=("metro", {"acept_remote": False})), "metro: unknown key(s): acept_remote"),
        ("a misspelt key inside weekly", dict(inside=("weekly", {"canary_ur": "https://x.example"})), "weekly: unknown key(s): canary_ur"),
        ("a misspelt key inside clearance", dict(inside=("clearance", {"when_active": "drop"})), "clearance: unknown key(s): when_active"),
        ("a title gate with one list", dict(change={"title_gate": {"pass": ["senior"]}}), "title_gate.fail: expected a non-empty list"),
        ("a title gate with an extra list", dict(inside=("title_gate", {"maybe": ["x"]})), "title_gate: unknown key(s): maybe"),
        ("a canary that is not https", dict(change={"weekly": {"canary_url": "http://x.example"}}), "weekly.canary_url: expected an https:// address"),
        ("a second pass naming nobody", dict(change={"weekly": {"second_pass_only": ["nobody"]}}), "not defined under employers or candidates: nobody"),
    ):
        got = error(**kw)
        ok &= check(want in got, f"{label} stops the load: {got or 'LOADED'}")
    ok &= check(error(change={"employers": {"x": {"ats": "anything", "spec": "t"}}}, known=None) == "",
                "without a list of known kinds neither the ats name nor the spec is checked")
    try: ss.Settings(["pay_floor"], known_ats=KNOWN); msg = ""
    except ss.SettingsError as e: msg = str(e)
    ok &= check("must hold one JSON object" in msg, "a settings file that holds a list, not an object, stops the load")
    ok &= check(error(change={"employers": {"x": {"ats": "workday", "spec": "one-part"}}}, known=set(KNOWN)) == ""
                and "unknown ats" in error(change={"employers": {"x": {"ats": "workday", "spec": "t"}}}, known={"lever"}),
                "a plain set of kinds checks the name only")

    d = tempfile.mkdtemp(); p = os.path.join(d, "c.json")
    try: ss.load(os.path.join(d, "absent.json")); msg = ""
    except ss.SettingsError as e: msg = str(e)
    ok &= check("not found. Copy config.example.json" in msg, "a missing file says what to copy")
    with open(p, "w") as fh: fh.write("{not json")
    try: ss.load(p); msg = ""
    except ss.SettingsError as e: msg = str(e)
    ok &= check(msg.startswith(p) and "not valid JSON" in msg, "a file that is not JSON is named")
    with open(p, "wb") as fh: fh.write(b'{"pay_floor": "\xff\xfe"}')
    try: ss.load(p); msg = ""
    except ss.SettingsError as e: msg = str(e)
    ok &= check(msg.startswith(p) and "cannot be read as a UTF-8 text file" in msg, "a file that is not UTF-8 text is named")
    try: ss.load(d); msg = ""
    except ss.SettingsError as e: msg = str(e)
    ok &= check(msg.startswith(d) and "cannot be read" in msg, "a folder given as the settings file is named, not a traceback")
    with open(p, "w") as fh: json.dump({"pay_floor": 1}, fh)
    try: ss.load(p); msg = ""
    except ss.SettingsError as e: msg = str(e)
    ok &= check(msg.startswith(p + ": metro:"), "an error from a file on disk carries the path and the key")

    print("\nALL PASS" if ok else "\nFAILURES ABOVE")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
