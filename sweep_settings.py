#!/usr/bin/env python3
"""sweep_settings.py - the sweep's settings, read from one JSON file.

What describes the person running the sweep lives in that file: the pay floor, the places that
count as home, the title lane, what to do with a posting that demands an active security
clearance, and the employers to enumerate. config.example.json holds made-up values; copy it to
config.json and replace them.

A bad file stops the run and names the key that is wrong. An unknown key is an error at every
level, so a misspelt option cannot be skipped without a word. The optional keys and their
defaults: metro.accept_remote (true), metro.home_country, metro.foreign_places and junior_titles
(the word lists below), title_gate (none), candidates (none), weekly (none). An optional key set
to null counts as left out.
"""
import json
import re


class SettingsError(ValueError):
    """The settings file is missing a key, has an unknown key, or holds a value of the wrong type."""


# Words a posting uses for "no fixed place". Used only when metro.accept_remote is true.
REMOTE_WORDS = ["remote", "anywhere", "nationwide", "telework"]
# Marks that a remote posting is open to the home country (override: metro.home_country). These
# are matched with case as written, so that "US" is a mark and the word "us" is not.
HOME_COUNTRY = ["US", r"U\.S\.", "USA", "(?i:united states)"]
# A remote posting that names one of these and no home-country mark is not a home posting
# (override: metro.foreign_places). Plain word matching: "mexico" also matches "New Mexico".
FOREIGN_PLACES = [
    "united kingdom", "uk", "england", "london", "ireland", "dublin", "spain", "madrid", "france",
    "paris", "germany", "berlin", "munich", "netherlands", "amsterdam", "canada", "ontario", "toronto",
    "vancouver", "montreal", "british columbia", "india", "bangalore", "bengaluru", "hyderabad", "australia",
    "sydney", "melbourne", "singapore", "japan", "tokyo", "korea", "seoul", "israel", "tel aviv", "brazil",
    "mexico", "poland", "switzerland", "zurich", "sweden", "italy", "emea", "apac", "latam"]
# Titles dropped whatever the band says (override: junior_titles).
JUNIOR_TITLES = ["intern", "internship", "junior", r"jr\.?", "entry[- ]level", "assistant", "coordinator", "new grad"]

# The default headers of the scanner and the census. The User-Agent names the tool. The Accept
# header matters: iCIMS serves a job page, with its JSON-LD, to this Accept header, and a wrapper
# page with no posting in it to a request that sends none or asks for text/html alone (measured
# 3 Oct 2026). Some calls send an Accept of their own. Four of those carry no JSON type: the HTML
# pages read by --discover and by the Phenom route, the Phenom search call, and the SuccessFactors feed.
USER_AGENT = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) job_scanner/2.0"
HEADERS = {"User-Agent": USER_AGENT, "Accept": "application/json, text/html;q=0.9,*/*;q=0.8"}

# An employer entered with one of these kinds is written into the run's walls and never fetched.
NOT_FETCHED = ("unknown", "unsupported", "offlimits")

KEYS = {
    "": {"about", "pay_floor", "metro", "lane_titles", "junior_titles", "clearance", "title_gate",
         "employers", "candidates", "weekly"},
    "metro": {"places", "accept_remote", "home_country", "foreign_places"},
    "clearance": {"when_active_required"},
    "title_gate": {"pass", "fail"},
    "weekly": {"canary_url", "second_pass_only"},
    "employer": {"ats", "spec"},
}


def _section(value, key, known, required=True):
    """An object whose keys are all known. None when it is optional and absent."""
    if value is None and not required:
        return None
    if not isinstance(value, dict):
        raise SettingsError(f"{key}: expected an object")
    stray = sorted(set(value) - KEYS[known])
    if stray:
        where = f"{key}: " if key else ""
        raise SettingsError(f"{where}unknown key(s): {', '.join(stray)}; known: {', '.join(sorted(KEYS[known]))}")
    return value


def _fragments(value, key, required=True):
    """A list of regular-expression fragments. Each is checked on its own so the error names it."""
    if value is None and not required:
        return None
    if not isinstance(value, list) or not value:
        raise SettingsError(f"{key}: expected a non-empty list of patterns")
    for i, frag in enumerate(value):
        if not isinstance(frag, str) or not frag.strip():
            raise SettingsError(f"{key}[{i}]: expected a non-empty string")
        try:
            re.compile(frag)
        except re.error as e:
            raise SettingsError(f"{key}[{i}]: {frag!r} is not a valid pattern ({e})")
    return value


def _compile(pattern, flags, key):
    """Fragments that compile one by one can still fail when joined (a global flag in the middle,
    one group name used twice). That is the file's fault too, and is reported the same way."""
    try:
        return re.compile(pattern, flags)
    except re.error as e:
        raise SettingsError(f"{key}: the patterns do not combine ({e}); use (?i:...) rather than (?i), and name a group once")


def _words(frags, key, ignore_case=True):
    """Fragments matched as whole words. Lookarounds, not \\b: a fragment that ends in a full
    stop ("U\\.S\\.") must still match before a space."""
    return _compile(r"(?<![A-Za-z0-9_])(?:" + "|".join(frags) + r")(?![A-Za-z0-9_])", re.I if ignore_case else 0, key)


def _targets(value, key, known_ats, required):
    if value is None and not required:
        return {}
    if not isinstance(value, dict) or (required and not value):
        raise SettingsError(f"{key}: expected an object of name -> {{\"ats\": ..., \"spec\": ...}}")
    out = {}
    for name, entry in value.items():
        if (not isinstance(entry, dict) or not isinstance(entry.get("ats"), str) or not isinstance(entry.get("spec"), str)
                or not entry["spec"].strip()):
            raise SettingsError(f"{key}.{name}: expected {{\"ats\": \"<kind>\", \"spec\": \"<text>\"}}, neither empty")
        _section(entry, f"{key}.{name}", "employer")
        kind, spec = entry["ats"], entry["spec"]
        if known_ats is not None:
            if kind not in known_ats and kind not in NOT_FETCHED:
                raise SettingsError(f"{key}.{name}: unknown ats {kind!r}; known: "
                                    f"{', '.join(sorted(known_ats))}, {', '.join(NOT_FETCHED)}")
            parts = known_ats.get(kind) if isinstance(known_ats, dict) else None
            if parts and (len(spec.split("|")) != len(parts) or not all(p.strip() for p in spec.split("|"))):
                raise SettingsError(f"{key}.{name}: a {kind} spec is {'|'.join(parts)}; got {spec!r}")
        out[name] = (kind, spec)
    return out


class Settings:
    """The validated settings. Patterns are compiled once, here.

    known_ats: the adapter kinds the caller can run. A set of names, or a dict of name -> the
    parts a spec must have (("tenant", "shard", "site") for a spec written tenant|shard|site),
    or None to skip both checks."""

    def __init__(self, d, known_ats=None):
        if not isinstance(d, dict):
            raise SettingsError("the settings file must hold one JSON object")
        _section(d, "", "")

        floor = d.get("pay_floor")
        if isinstance(floor, bool) or not isinstance(floor, int) or floor < 0:
            raise SettingsError("pay_floor: expected a whole number of dollars per year, 0 or more")
        self.pay_floor = floor

        metro = d.get("metro")
        if not isinstance(metro, dict):
            raise SettingsError("metro: expected an object with a `places` list")
        _section(metro, "metro", "metro")
        places = _fragments(metro.get("places"), "metro.places")
        accept_remote = metro.get("accept_remote")
        if accept_remote is None:
            accept_remote = True
        if not isinstance(accept_remote, bool):
            raise SettingsError("metro.accept_remote: expected true or false")
        self.accept_remote = accept_remote
        self.remote = _words(REMOTE_WORDS, "remote words")
        self.places = _words(places, "metro.places")
        # One pattern for "this is home": a listed place, or a remote word when remote is accepted.
        self.metro = _words(places + (REMOTE_WORDS if accept_remote else []), "metro.places")
        self.home = _words(_fragments(metro.get("home_country"), "metro.home_country", required=False) or HOME_COUNTRY,
                           "metro.home_country", ignore_case=False)
        self.foreign = _words(_fragments(metro.get("foreign_places"), "metro.foreign_places", required=False)
                              or FOREIGN_PLACES, "metro.foreign_places")

        # The lane fragments carry their own word boundaries where they need them ("\\bCPA\\b").
        self.lane = _compile("(" + "|".join(_fragments(d.get("lane_titles"), "lane_titles")) + ")", re.I, "lane_titles")
        self.junior = _words(_fragments(d.get("junior_titles"), "junior_titles", required=False) or JUNIOR_TITLES, "junior_titles")

        clearance = d.get("clearance")
        if isinstance(clearance, dict):
            _section(clearance, "clearance", "clearance")
        when = clearance.get("when_active_required") if isinstance(clearance, dict) else None
        if when not in ("drop", "keep"):
            raise SettingsError('clearance.when_active_required: expected "drop" or "keep"')
        self.drop_active_clearance = (when == "drop")

        # Optional: a title-word gate, used only by --delta to show what such a gate hides.
        self.title_gate = None
        gate = _section(d.get("title_gate"), "title_gate", "title_gate", required=False)
        if gate is not None:
            self.title_gate = (_words(_fragments(gate.get("pass"), "title_gate.pass"), "title_gate.pass"),
                               _words(_fragments(gate.get("fail"), "title_gate.fail"), "title_gate.fail"))

        self.employers = _targets(d.get("employers"), "employers", known_ats, required=True)
        self.candidates = _targets(d.get("candidates"), "candidates", known_ats, required=False)
        both = sorted(set(self.employers) & set(self.candidates))
        if both:
            raise SettingsError(f"candidates: {', '.join(both)} also listed under employers; use one name once")

        # Optional: the weekly run (weekly_run.py).
        weekly = _section(d.get("weekly"), "weekly", "weekly", required=False) or {}
        canary = weekly.get("canary_url")
        if canary is not None and not (isinstance(canary, str) and canary.startswith("https://")):
            raise SettingsError("weekly.canary_url: expected an https:// address")
        second = weekly.get("second_pass_only")
        if second is None:
            second = []
        if not isinstance(second, list) or not all(isinstance(n, str) and n for n in second):
            raise SettingsError("weekly.second_pass_only: expected a list of names")
        unknown = [n for n in second if n not in self.employers and n not in self.candidates]
        if unknown:
            raise SettingsError(f"weekly.second_pass_only: not defined under employers or candidates: {', '.join(unknown)}")
        self.weekly_canary = canary
        self.weekly_second_pass = list(second)


def load(path, known_ats=None):
    """Read and validate a settings file. Raises SettingsError with the path in the message."""
    try:
        with open(path, encoding="utf-8") as fh:
            data = json.load(fh)
    except FileNotFoundError:
        raise SettingsError(f"{path}: not found. Copy config.example.json to config.json and replace its made-up values.")
    except json.JSONDecodeError as e:
        raise SettingsError(f"{path}: not valid JSON ({e})")
    except (OSError, UnicodeDecodeError) as e:
        raise SettingsError(f"{path}: cannot be read as a UTF-8 text file ({e.__class__.__name__})")
    try:
        return Settings(data, known_ats)
    except SettingsError as e:
        raise SettingsError(f"{path}: {e}")
