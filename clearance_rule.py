"""clearance_rule.py - one pure function over a posting's text: does the posting ask for a clearance the
candidate must already hold?

    clearance_rule(text, base=None) -> "ACTIVE REQUIRED" | "OBTAINABLE" | "NONE STATED"

The rule, for a candidate who is a U.S. citizen, has held a clearance before and holds none now:

  ACTIVE REQUIRED  The posting needs a clearance in hand: an active or current Secret, Top Secret, TS/SCI or
                   polygraph; "must currently hold"; or an interim clearance that is required to start.
  OBTAINABLE       The posting speaks of obtaining one ("must be able to obtain", "eligible to obtain",
                   "clearable", "within 90 days of hire"), of Public Trust or suitability, of citizenship,
                   or only prefers a clearance.
  NONE STATED      No clearance is asked for, or the posting says none is required.

Three readings are this module's own; everything else goes to `base`, the regex verdict in
job_scanner.py (clearance_rule(text) with no base answers NONE STATED for anything the three do not
decide, which is enough for the tests here):

  1. Labelled fields, the form many federal contractors print and HTML flattens onto one line:
     "Clearance Level Must Currently Possess: None   Clearance Level Must Be Able to Obtain: Secret".
     A possess-field answered None, No or N/A is not a requirement and is cut before the base reads the
     text, so "Must Currently Possess ... Secret" cannot be read across the two labels. An obtain-field
     answered with a level is OBTAINABLE. A possess-field answered with a level is ACTIVE REQUIRED
     (Public Trust is not a held clearance and is left to the base, which reads it as OBTAINABLE).
  2. An interim clearance that is required ("an interim Secret clearance is required to start", "must
     hold an interim clearance") is ACTIVE REQUIRED: the candidate holds none. Obtaining wording in the
     same clause ("must be able to obtain an interim Secret clearance") is not, nor is "no interim
     clearance required", nor "interim clearance is acceptable".
  3. "Clearable" (and "able to be cleared") is OBTAINABLE when nothing else is decided.

Text is read as one line: newlines, tabs and unicode dashes are normalised first, so a phrase split
across two lines reads as it would on one.
"""
import re

ACTIVE_REQUIRED = "ACTIVE REQUIRED"
OBTAINABLE = "OBTAINABLE"
NONE_STATED = "NONE STATED"

_LEVEL = r"(?:ts\s*/?\s*sci|top[\s-]+secret|secret|public\s+trust|(?:security\s+)?clearance|poly(?:graph)?)"
_HELD_LEVEL = r"(?:ts\s*/?\s*sci|top[\s-]+secret|secret|(?:security\s+)?clearance|poly(?:graph)?)"   # Public Trust is not a held clearance
_NONE = r"(?:none|no|n/?a|not\s+(?:required|needed|applicable)|none\s+required|not\s+at\s+this\s+time)"

# 1. Labelled fields. The label may carry words before it ("Clearance Level Must Currently Possess").
FIELD_POSSESS_NONE = re.compile(
    r"\b(?:must\s+)?(?:currently\s+)?(?:possess|hold)(?:es|ed|ing)?\s*(?:\([^)]{0,30}\))?\s*:\s*" + _NONE + r"\b", re.I)
FIELD_POSSESS_LEVEL = re.compile(
    r"\b(?:must\s+)?(?:currently\s+)?(?:possess|hold)(?:es|ed|ing)?\s*(?:\([^)]{0,30}\))?\s*:\s*"
    r"(?:an?\s+|active\s+|current\s+)*" + _HELD_LEVEL + r"\b", re.I)
FIELD_OBTAIN = re.compile(
    r"\b(?:must\s+)?(?:be\s+)?(?:able|ability|eligible|eligibility)\s+to\s+obtain\s*(?:\([^)]{0,30}\))?\s*:\s*"
    r"(?:an?\s+)?(?:" + _LEVEL + r"|yes)\b", re.I)

# 2. Interim.
_INTERIM_NOUN = r"interim\s+(?:" + _LEVEL + r")(?:\s+clearance)?"
INTERIM_REQUIRED = re.compile(
    r"\b" + _INTERIM_NOUN + r"\b(?:(?!\b(?:not|no|but|acceptable|accepted)\b)[^.;,?!]){0,40}?\b(?:is\s+)?(?:required|needed|necessary|mandatory)\b"
    r"|\b(?:must|need(?:s)?(?:\s+to)?|required\s+to)\s+(?:have|hold|possess|maintain)\s+(?:an?\s+)?(?:(?:active|current)\s+(?:or|and)\s+)?interim\b", re.I)
INTERIM_NOT = re.compile(
    r"\bno\s+" + _INTERIM_NOUN + r"\b[^.;]{0,30}?\b(?:required|needed|necessary)\b"
    r"|\b" + _INTERIM_NOUN + r"\b[^.;,]{0,25}?\b(?:is\s+)?(?:not\s+(?:required|needed|necessary)|acceptable|accepted)\b", re.I)
_OBTAIN_WORDS = re.compile(
    r"\bobtain\w*\b|\b(?:abilit\w*|able|eligib\w*)\s+to\b|\bwithin\s+\d+\s+(?:days?|weeks?|months?)\b"
    r"|\b(?:after|following|upon)\s+(?:hire|hiring|start\w*|onboarding|an?\s+offer|offer)\b|\bsponsor\w*\b", re.I)

# 3. Clearable.
CLEARABLE = re.compile(r"\bclearable\b|\bable\s+to\s+be\s+cleared\b|\bcapable\s+of\s+being\s+cleared\b", re.I)


def normalise(text):
    """One line: newlines and tabs become spaces, unicode dashes and non-breaking spaces their ASCII forms,
    runs of whitespace one space."""
    t = (text or "").replace("\xa0", " ").replace("–", "-").replace("—", "-").replace("‑", "-")
    return re.sub(r"\s+", " ", t).strip()


def _clause(text, i, j):
    """The clause holding text[i:j]: between the nearest ". " or ";" on either side."""
    start = max(text.rfind(". ", 0, i), text.rfind(";", 0, i)) + 1
    ends = [k for k in (text.find(". ", j), text.find(";", j)) if k != -1]
    return text[start:(min(ends) if ends else len(text))]


def interim_required(text):
    """True when an interim clearance is said to be required, with no obtaining wording in that clause."""
    for m in INTERIM_REQUIRED.finditer(text):
        clause = _clause(text, m.start(), m.end())
        if INTERIM_NOT.search(clause): continue
        if _OBTAIN_WORDS.search(clause): continue
        return True
    return False


def clearance_rule(text, base=None):
    """The verdict for one posting's text. `base` is the fallback reader (job_scanner's regex verdict); it is
    given the text with the possess-None fields cut out. Without a base, the three readings alone decide
    and anything else is NONE STATED."""
    t = normalise(text)
    if not t: return NONE_STATED
    if interim_required(t): return ACTIVE_REQUIRED
    if FIELD_POSSESS_LEVEL.search(t): return ACTIVE_REQUIRED
    cut = FIELD_POSSESS_NONE.sub(" ", t)
    obtain_field = bool(FIELD_OBTAIN.search(cut))
    verdict = base(cut) if base else NONE_STATED
    if verdict == NONE_STATED and (obtain_field or CLEARABLE.search(cut)):
        return OBTAINABLE
    return verdict
