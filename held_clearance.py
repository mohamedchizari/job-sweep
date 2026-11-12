"""held_clearance.py - one question about a job posting's text: must the candidate already HOLD a security
clearance (Secret, Top Secret, TS/SCI, a CI or full-scope polygraph) to be considered?

    held_required(text) -> bool

Written for a U.S. citizen who has held a clearance before and holds none now. A posting he can apply to must
never be dropped, so the default is KEEP (False). A posting is dropped only on a short list of plain wordings:

  1. Decisive sentences that name a clearance: "cleared candidates only", "candidates without an active
     clearance will not be considered", "must already hold a TS/SCI", "we cannot sponsor a clearance",
     "Must Currently Possess: Secret".
  2. A clearance level next to held wording: active, current, existing, must have / hold / possess, in
     possession of, at the time of application, prior to start, on day one.
  3. A clearance level that is required: next to "required" or "mandatory", in a "Clearance Required: <level>"
     field, or listed under a "Required Qualifications" heading; unless the page offers to obtain or sponsor
     that clearance, or reads as a federal (USAJOBS) posting, where the agency processes the clearance.

Rules 2 and 3 never fire in a unit (sentence, list item, ';' clause, with any short qualifier after it such as
"- Highly Preferred" or "but not required") that also speaks of obtaining, eligibility, sponsoring, taking a
polygraph, preference, "a plus", the future, a prior or lapsed clearance, "not required", a field answered No,
or a question; nor under a "Preferred / Nice to have / What will set you apart" heading.

A bare level with nothing else ("- TS/SCI clearance", "Security clearance: Secret", a title "Analyst - TS/SCI
w/ Poly") is KEPT. Missing a held clearance shows a job he can skip; reading one where there is none hides a
job he could get. The second error is the costly one. Every regular expression here is bounded or linear.
"""
import bisect
import html
import re

# ---------------------------------------------------------------- text
_TAG = re.compile(r"<[^<>]{0,400}>")
_BLOCK = re.compile(r"^</?(?:li|ul|ol|p|div|br|h[1-6]|tr|td|th|section|article|header|footer|dt|dd|table)\b", re.I)


def normalise(text):
    t = text or ""
    t = re.sub(r"\\u([0-9a-fA-F]{4})", lambda m: chr(int(m.group(1), 16)), t)
    t = t.replace("\\/", "/").replace("\\n", "\n").replace("\\t", " ")
    t = html.unescape(html.unescape(t))
    t = _TAG.sub(lambda m: "\n" if _BLOCK.match(m.group(0)) else " ", t)
    for a, b in (("\xa0", " "), ("\u202f", " "), ("\u2009", " "), ("\u2013", "-"), ("\u2014", "-"), ("\u2011", "-"),
                 ("\u200b", ""), ("\u2019", "'"), ("\t", " ")):
        t = t.replace(a, b)
    t = re.sub(r"\b(?:[A-Za-z]\.){2,}", lambda m: m.group(0).replace(".", ""), t)          # U.S. -> US
    t = re.sub(r",\s*or\s+(higher|above|better|equivalent),", r" or \1", t, flags=re.I)
    t = re.sub(r"\b(Inc|Corp|Co|Ltd|LLC|Sr|Jr|Dr|Mr|Ms|Mrs|St|No|vs|approx|Dept|Gov|Govt)\.(?=\s)", r"\1", t)
    return t


# ---------------------------------------------------------------- levels
_NOT_PERSONAL = (r"(?!\s*(?:/\s*sci\b\s*)?(?:data|information|material|materials|documents?|networks?|systems?|environments?|facilit\w*"
                 r"|programs?|spaces?|areas?|scifs?|work\b|contracts?|projects?|customers?|missions?|opportunit\w*|intelligence"
                 r"|reporting|infrastructure|inventor\w*|recipes?|security\s+requirements|requirements\b(?!\s*:)|positions|roles|jobs|teams?"
                 r"|enclaves?|community|domains?|markings?|classification|classified|control\s+officer|tsco|government\s+clients?|clients?|accounts?|position\b|level\s+(?:data|information|systems?|work)|clearance\s+process\w*"
                 r"|clearance\s+requirements|processing))")
_LEVEL = re.compile(
    r"(?:\b[Tt][Ss]\s*(?:/{1,2}|-|\s)\s*[Ss][Cc][Ii]\b" + _NOT_PERSONAL +
    r"|\btop[\s-]+secret(?:\s*/\s*sci)?\b(?!\s+service)" + _NOT_PERSONAL +
    r"|\bsecret[\s-]+level\s+(?:security\s+)?clearances?\b" + _NOT_PERSONAL +
    r"|(?<!victoria's\s)\bsecret\b[\"']?\s+(?:(?!service|facility|fcl)[\w/]+\s+){0,3}?(?:security\s+)?clearances?\b" + _NOT_PERSONAL +
    r"|\b(?:dod|dos|doj|dhs|active|current|interim|final|existing|government|federal)\s+secret\b(?!\s+service)" + _NOT_PERSONAL +
    r"|(?-i:\bSCI\b)(?=\s*(?:clearance|access|eligib|w/|with|indoc))"
    r"|(?-i:\bTS\b)(?!\s*(?:/{1,2}|-)\s*SCI)(?=\s*(?:clearance|w/|with|\(|poly|security))"
    r"|\b(?:ci|fs|fsp|full[\s-]*scope|lifestyle|counter[\s-]?intelligence)\s*poly(?:graph)?s?\b(?!\s+(?:examiner|certification))"
    r"|\b(?:w/|with(?:\s+an?)?|and|plus|&)\s+(?:a\s+)?poly(?:graph)?\b(?!\s+(?:examiner|certification|protection))"
    r"|\b(?:doe\s+)?(?-i:[QL])\s+clearance\b"
    r"|\byankee\s+white\b)", re.I)
# "Clearance Required: Secret", "Minimum Clearance Required to Start: Secret" (a bare "Clearance: Secret" is not one:
# USAJOBS prints the position's level that way, and the agency processes it)
_FIELD_LEVEL = re.compile(
    r"\b(?:(?:security\s+)?clearance(?:\s+(?:level|type))?\s+required(?:\s+to\s+start)?|required\s+(?:security\s+)?clearance(?:\s+level)?"
    r"|minimum\s+clearance(?:\s+required)?(?:\s+to\s+start)?)\s*:\s*(?:an?\s+)?(?:active\s+|current\s+)?(?:(?:dod|government)\s+)?"
    r"(secret|top[\s-]+secret|ts\s*/\s*sci|ts|(?-i:Q|L))\b(?!\s*/\s*public)", re.I)
_GENERIC = re.compile(
    r"\b(?:active|current|existing)\s+(?:(?:us|federal|government|dod|national)\s+)?(?:security\s+)?clearances?\b"
    r"(?=\s*(?:$|[.,;:()/]|(?:required|is|with|and|or|at|of|level|to|in|for|that|as|needed|a\s+must|must|w/|holders?)\b))", re.I)


def _family(level_text):
    s = level_text.lower()
    if "poly" in s: return "P"
    if re.search(r"top|ts|sci|yankee", s): return "TS"
    if "secret" in s: return "S"
    if re.search(r"\bq\b", s): return "Q"
    if re.search(r"\bl\b", s): return "L"
    return "?"


def _mentions(u):
    um = re.sub(r"\bactive\s+(?:directory|duty|learning|listening|record|voice)\b|\bstatus\s*:\s*active\b", lambda x: " " * len(x.group(0)), u, flags=re.I)
    out = [(m.start(), m.end(), m.group(0)) for m in _LEVEL.finditer(um)]
    out += [(m.start(), m.end(), m.group(0)) for m in _GENERIC.finditer(um)]
    out.sort()
    return out


# ---------------------------------------------------------------- wordings
_DECISIVE = re.compile(
    r"\b(?:candidates|applicants|those)\s+(?:without|lacking)\s+(?:an?\s+)?(?:active\s+|current\s+)?(?:[\w/]+\s+){0,3}?"
    r"(?:will\s+not|won't|should\s+not|need\s+not|cannot|can\s*not)\s+(?:be\s+considered|apply)"
    r"|\b(?:awaiting|pending)\s+adjudication\s+need\s+not\s+apply\b"
    r"|\bmust\s+currently\s+(?:possess|hold)\s*:\s*(?:an?\s+|active\s+|current\s+)*(?:top\s+secret|secret|ts\b|tssci|ts/sci)", re.I)
_DECISIVE_NAMES = re.compile(r"\bclearances?\b|\bts\s*/\s*sci\b|\btop\s+secret\b|\bsecret\b|\bpoly|\badjudication\b|\bpossess", re.I)
# decisive only when the unit names a clearance and has no veto
_DECISIVE_CTX = re.compile(
    r"\bcleared\s+(?:candidates|applicants|individuals|personnel|professionals)\s+only\b"
    r"|\bonly\s+(?:currently\s+)?cleared\s+(?:candidates|applicants|individuals)\b"
    r"|\b(?:pending|interim|in[\s-]process)\s+(?:\w+\s+){0,2}?(?:will\s+not|won't|not)\s+be\s+(?:considered|accepted|acceptable|submitted)"
    r"|\binterim\s+(?:\w+\s+)?(?:is\s+)?not\s+(?:be\s+)?(?:acceptable|accepted)|\bclearances?\s+in\s+process\s+will\s+not\b"
    r"|\bmust\s+already\s+(?:hold|possess|have|be\s+cleared|be\s+in\s+possession)\b"
    r"|\bonly\s+(?:candidates|applicants)\s+(?:who\s+(?:currently\s+)?(?:hold|possess|have)|with)\s+(?:an?\s+)?(?:active|current)\b[^.;]{0,60}\bwill\s+be\s+considered\b"
    r"|\bonly\s+(?:candidates|applicants)\s+who\s+are\s+(?:already\s+|currently\s+)?cleared\b"
    r"|\b(?:unable\s+to|not\s+able\s+to|cannot|can\s*not|can't|will\s+not|won't|do\s+not|does\s+not)\s+(?:sponsor|initiate|process)(?:\s+or\s+\w+)?\s+(?:an?\s+|new\s+|your\s+)?(?:security\s+)?(?:clearances?|investigations?|ssbis?)\b"
    r"|\b(?:security\s+)?clearance\s+sponsorship\s+(?:is\s+)?(?:not|un)\s*available\b|\bno\s+(?:security\s+)?clearance\s+sponsorship\b(?!\s*:)", re.I)
_VETO = re.compile(
    # obtaining, processing, a polygraph taken as a step
    r"\b(?:obt(?:ai|ia)n\w*|attain\w*|acquire\w*|eligib\w*|clearable|qualify\s+for\s+(?:an?\s+|the\s+)?(?:\w+\s+){0,2}?(?:security\s+)?clearance|capable\s+of|granted|grant\b"
    r"|(?:ability|able)\s+to\s+(?:obtain|attain|get|acquire|pass|receive|undergo|gain|achieve|secure|hold|qualify|be\s+\w+)"
    r"|(?:can|could|will)\s+be\s+cleared|being\s+cleared|become\s+cleared|get\s+(?:you\s+)?cleared|sponsor\w*"
    r"|willing\w*\s+to\s+(?:obtain|undergo|take|sit|submit|be\s+\w+|pursue|apply\s+for|go\s+through|get)"
    r"|initiat\w*|submit\w*|process(?:ed|ing)?\b|(?<!pending\s)investigation\w*|reinvestigation|background\s+check"
    r"|take\b|taking|pass\b|passing|undergo\w*|agree\s+to|successful(?:ly)?\s+complet\w*|meet\s+(?:the\s+)?requirements\s+for"
    # preference
    r"|prefer\w*|desir\w*|a\s+plus|plus\b|bonus|nice|ideal\w*|advantage\w*|beneficial|helpful|help\b|asset|appreciat\w*|valu(?:ed|able)"
    r"|recommend\w*|optional|welcom\w*|special\s+consideration|(?<!to\sbe\s)considered|consideration|great|love|apart|stronger|strengthen\w*"
    r"|extra|stand\s+out|prioriti[sz]\w*|priority|preference|favou?r\w*|leg\s+up|differentiator|encourag\w*|either|sooner|faster"
    r"|expedit\w*|speed\s+up|fast[\s-]*track\w*|competitive|benefit\w*|good\s+to\s+have|regarded|typically|usually|often"
    r"|workforce|differential|of\s+our\s+(?:employees|staff|team|people)|\d+\s*%|markdown|merchandis\w*|inventory|pricing"
    r"|recent\w*|inactive|re-?activat\w*|in[\s-]house|post[\s-]?start"
    # negation
    r"|not\s+(?:be\s+)?(?:required|a\s+(?:hard\s+)?requirement|necessary|needed|mandatory|essential|a\s+prerequisite|a\s+must)"
    r"|(?:do|does|did|will)\s+not\s+(?:need|require)|not\s+require|no\s+need|still\s+apply|may\s+apply|not\s+disqualif\w*"
    r"|without\s+(?:an?\s+)?(?:active|current)|do\s+not\s+(?:currently\s+)?hold|not\s+(?:currently\s+)?cleared|not\s+have"
    r"|no\s+(?:[\w/-]+\s+){0,3}?(?:clearance|required|needed)"
    # time, conditions, a prior clearance
    r"|may\s+(?:be\s+)?(?:requir\w*|need\w*)|might|could|future|eventually"
    r"|(?:upon|after|following)\s+(?:hire|hiring|start\w*|an?\s+offer|offer|selection|onboarding|award|acceptance)|post[\s-]?hire"
    r"|once\s+(?:hired|selected)|within\s+(?:the\s+)?(?:first\s+)?(?:\d+|one|two|three|six|thirty|sixty|ninety)|within\s+the\s+(?:past|last)"
    r"|if\s+(?:selected|hired|required|you|any|applicable)|subject\s+to|we\s+will|we'll|should"
    r"|interim\b(?![^.;]{0,30}\bnot\b)(?=[^.;]{0,30}\b(?:accept\w*|considered|ok|okay|fine|sufficient|allowed))"
    r"|prior\b(?!\s+to\b)|previous\w*|former\w*|expired|reinstat\w*|laps\w*|recently|had\s+an?|in\s+the\s+past|have\s+held"
    # questions, forms, company clearances
    r"|indicate|whether|list\s+your|please|do\s+you|have\s+you|are\s+you|some\s+(?:of\s+our\s+)?(?:positions|roles|jobs|programs)"
    r"|facilit\w*\s+(?:security\s+)?clearances?|fcl)\b"
    r"|n't\s+(?:need|required|needed|necessary|a\s+requirement)|\?|^\s*q\s*\*", re.I)
_NO_KEEP = (r"(?![\s-]*(?:exceptions?|waivers?|substitutions?|deviations?|lapses?|equivalents\b|alternatives\b|c2c|corp"
            r"|foreign\s+nationals\b(?!\s+may)|non-?u|dual|later\s+than|exemptions?|other\s+cert))")
# a field answered no: "Secret Clearance Required: No", "Active Secret Clearance (Y/N): N", "Polygraph: None"
_NO_ANSWER = re.compile(
    r"\b(?:required|needed|clearance|active|at\s+start|secret|sci|poly(?:graph)?)\b(?:\s*\(\s*y\s*/\s*n\s*\))?"
    r"(?:\s+(?:at|to|for)\s+(?:start|this\s+(?:position|role)))?(?:\s*[:\u2013-]\s*|\s+(?=no\b|none\b|n/a\b))"
    r"(?:(?:none|n/?a|tbd|negative|n|not)\b|no\b" + _NO_KEEP + r")", re.I)
_OTHER_FIELD = re.compile(r"\b(?:travel|telework|relocation|overtime|remote|drug\s+test\w*|shift\s+work)\s+required\s*:\s*(?:no|yes|n|y)\b", re.I)
_MASK = re.compile(
    r"\bno[\s-]+(?:exceptions?|waivers?|substitutions?|deviations?|lapses?(?:\s+in\s+clearance)?|equivalents\b|alternatives\b"
    r"|c2c|corp[\s-]*to[\s-]*corp|foreign\s+nationals\b(?!\s+may)|non-?us(?:\s+(?:persons?|citizens?))?|dual\s+citizens?|later\s+than"
    r"|exemptions?|other\s+certifications?)\b[^.;|]{0,25}"
    r"|\b(?:relocation|travel|degree|visas?|telework|overtime|experience|certifications?|licen[cs]e)\b[^,.;]{0,15}?\bnot\s+(?:be\s+)?(?:required|needed|available|necessary)"
    r"|\b(?:obtain\w*|maintain)\s+(?:and\s+maintain\s+)?(?:an?\s+|the\s+|one\s+(?:year\s+of\s+)?|one\s+of\s+the\s+following\s+)?(?:[\w-]+\s+){0,2}?"
    r"(?:licen[cs]e|certifications?|certificate|degree|experience|cissp|security\+|comptia|cpa|pmp|driver)\w*(?:\s+(?:licen[cs]e|certification))?"
    r"(?:\s+within\s+(?:\w+\s+){0,3}?(?:years?|months?|days?)(?:\s+of\s+(?:hire|start))?)?"
    r"|\b(?:certification|licen[cs]e|security\+)\s+within\s+(?:\w+\s+){0,3}?(?:years?|months?|days?)(?:\s+of\s+(?:hire|start))?"
    r"|\bsponsor\w*\s+(?:\w+\s+){0,2}?visas?|\bvisa\s+sponsorship[^.;,]{0,30}|\b(?:not|no)\s+(?:offer\s+)?sponsorship[^.;,]{0,20}"
    r"|\bsponsorship\s+(?:is\s+)?(?:not|un)\s*available|\brequiring\s+sponsorship\s+will\s+not\s+be\s+considered"
    r"|\bdo(?:es)?\s+not\s+(?:offer|provide)\s+sponsorship|\bdo(?:es)?\s+not\s+sponsor\s+visas?"
    r"|\b(?:travel|telework|relocation|overtime|remote)\s+required\s*:\s*(?:no|yes|n|y)\b"
    r"|\bdrug\s+(?:test|screen)\w*|\bactive\s+(?:directory|duty|learning|listening|record|voice)\b|\bstatus\s*:\s*active\b", re.I)
_MASK_POLY = re.compile(r"\b(?:ci\s+|fs\s+|full[\s-]*scope\s+)?poly(?:graph)?\s+(?:is\s+)?(?:preferred|desired|a\s+plus|not\s+(?:required|needed)|optional)", re.I)


def _masked(u):
    m = _MASK.sub(lambda x: " " * len(x.group(0)), u)
    if any("poly" not in x.group(0).lower() for x in _LEVEL.finditer(u)):        # a polygraph only preferred, next to a held level
        m = _MASK_POLY.sub(lambda x: " " * len(x.group(0)), m)
    return m


_HELD = re.compile(
    r"\b(?:active|current(?:ly)?|existing|already|possess\w*|in\s+possession|must\s+(?:have|hold|maintain|carry)"
    r"|(?:you|candidates?|applicants?)\s+(?:must\s+)?(?:have|hold)|holds?\b|holding)\b", re.I)
_HELD_AFTER = re.compile(
    r"\b(?:at\s+(?:the\s+)?time\s+of\s+(?:application|applying|hire|offer|submission)|prior\s+to\s+(?:start\w*|hire|beginning|day\s+one|employment)"
    r"|before\s+(?:start\w*|day\s+one|employment)|on\s+day\s+one|day[\s-]+one|required\s+to\s+start|in\s+place|in\s+hand|must\s+be\s+active)\b", re.I)
_REQUIRED_AFTER = re.compile(r"^[^.;:,]{0,30}?\b(?:is\s+)?(?:required|mandatory|a\s+must|a\s+requirement|must\s+have)\b", re.I)
_REQUIRED_BEFORE = re.compile(r"\b(?:requires?|required|requirement|mandatory)\s*(?::|-)?\s*(?:an?\s+|the\s+)?(?:(?!for\b|to\b|by\b|of\b)\w+\s+){0,2}$", re.I)

# ---------------------------------------------------------------- what the page offers
_PAGE_OBTAIN = re.compile(
    r"\b(?:obt(?:ai|ia)n\w*|attain\w*|eligib\w*|clearable|gain|achieve|qualify\s+for\s+(?:an?\s+|the\s+)?(?:\w+\s+){0,2}?clearance|initiat\w*|submit\w*|granted|processed"
    r"|process\w*\s+(?:a|an|your|the)\s+(?:\w+\s+){0,2}?clearance|clearance\s+process\w*|clearance\s+paperwork"
    r"|get\s+you\s+(?:one|cleared)|put\s+in\s+for|can\s+be\s+cleared|be\s+cleared|in\s+place\s+within)\b", re.I)
_PAGE_INTERIM = re.compile(r"\binterim\b(?![^.;]{0,30}\bnot\b)[^.;]{0,30}\b(?:accept\w*|considered|ok|okay|fine|sufficient|allowed)", re.I)
_PAGE_SPONSOR = re.compile(r"\bsponsor\w*\b|\b(?:required|active)\s+at\s+start\s*:\s*no\b|\bsponsorship\s+available\s*:\s*yes\b", re.I)
_FEDERAL = re.compile(r"\bconditions\s+of\s+employment\b|\bselectee\b|\bspecialized\s+experience\b|\bGS-\d|\busajobs\b|\bbackground\s+investigation\b", re.I)
_VISA = re.compile(r"\bvisa|\bh-?1b\b|\bwork\s+authori|\bimmigration\b|\bemployment\s+authori|\bauthorized\s+to\s+work|\bemployer\s+sponsorship|\bwithout\s+(?:the\s+)?need\s+for\s+(?:employer\s+)?sponsorship", re.I)
_POLY_WORD = re.compile(r"\bpoly(?:graph)?s?\b", re.I)
_PRONOUN = re.compile(r"\b(?:it|one|the\s+same|same|such)\b", re.I)
_NEGATED_SPONSOR = re.compile(
    r"\b(?:not|no)\s+(?:offer|provide)\w*\s+(?:\w+\s+)?sponsorship|\brequiring\s+sponsorship\s+will\s+not"
    r"|\b(?:not|unable\s+to|cannot|can\s*not|can't|won't|will\s+not|do\s+not|does\s+not)\s+(?:be\s+able\s+to\s+|to\s+)?sponsor"
    r"|\bsponsor\w*\s+(?:is\s+)?(?:not|un)\s*available|\bno\s+(?:\w+\s+)?sponsorship", re.I)
_CLEAR = re.compile(r"\bclear(?:ance|ed)\w*", re.I)


def _page_obtains(us):
    """Families of clearance the page offers to obtain or sponsor ('?' = a clearance with no level, "it" or "one")."""
    fams = set()
    for u in us:
        u = _masked(u)
        if _FEDERAL.search(u): fams.add("?"); continue
        hits = list(_PAGE_OBTAIN.finditer(u)) if (_CLEAR.search(u) or _LEVEL.search(u) or _PRONOUN.search(u)) else []
        if not hits and _PAGE_SPONSOR.search(u) and not _VISA.search(u) and not _NEGATED_SPONSOR.search(u):
            hits = list(_PAGE_SPONSOR.finditer(u))
        for m in hits[:20]:
            if _NEGATED_SPONSOR.search(u[max(0, m.start() - 30):m.end()]): continue
            tgt = {_family(x.group(0)) for x in _LEVEL.finditer(u[m.end():m.end() + 60])}
            if not tgt and _POLY_WORD.search(u[m.end():m.end() + 40]): tgt = {"P"}
            fams |= tgt or {"?"}
        if "?" in fams: break
    return fams


_PAGE_ELIG = re.compile(r"\bsubject\s+to\s+a\s+(?:security|background)\s+investigation|\beligibility\s+requirements\s+for\s+access\s+to\s+classified", re.I)


def _page_interim(us):
    return any(_PAGE_INTERIM.search(u) or _PAGE_ELIG.search(u) for u in us)


_OB = re.compile(r"\b(?:obt(?:ai|ia)n\w*|attain\w*|acquire\w*|eligib\w*|(?:ability|able)\s+to(?:\s+be\s+approved\s+for)?|willing\w*\s+to\s+\w+"
                 r"|take\b|taking|pass\b|passing|undergo\w*|agree\s+to|successful(?:ly)?\s+complet\w*)", re.I)
_POLY_WORD = re.compile(r"\bpoly(?:graph)?s?\b", re.I)


def _other_level_only(u, ms):
    """True when every veto word in the unit is an obtaining word aimed at a DIFFERENT level than a held one before it,
    joined by "and" or "with", not "or": "Active Secret clearance and ability to obtain Top Secret", "Active TS/SCI with
    ability to be approved for a CI Poly"."""
    vs = list(_VETO.finditer(_masked(u)))
    if not vs or len(vs) > 20 or len(ms) > 200 or any(not _OB.match(u, v.start()) for v in vs): return False
    first = vs[0].start()
    held = [(a, b, _family(lv)) for a, b, lv in ms if a < first and (_HELD.search(u[max(0, a - 60):a]) or _HELD.search(lv))]
    if not held: return False
    gap = u[held[-1][1]:first]
    if re.search(r"\bor\b", gap, re.I) and not re.search(r"\b(?:with|and)\b", gap, re.I): return False
    hf = {f for _, _, f in held}
    starts = [a for a, b, lv in ms]
    for v in vs:
        i, j = bisect.bisect_left(starts, v.end()), bisect.bisect_right(starts, v.end() + 60)
        tgt = [ms[k][2] for k in range(i, j)] + (["poly"] if _POLY_WORD.search(u[v.end():v.end() + 60]) else [])
        if not tgt or any(_family(t) in hf for t in tgt): return False
    return True


# ---------------------------------------------------------------- units and sections
_SOFT_WORDS = r"(?:highly|strongly|nice|bonus|a\s+plus|plus|big|huge|optional|ideal\w*|great|desired|preferred|required|eligible|active|current|mandatory|not|no|none|n/a|na|yes|tbd|negative|a\s+must|must)"
_HARD_SEP = re.compile(r"\n|;|\||[•●·▪◦]|(?<=[.!?])\s+(?=[\"'(*A-Z0-9-])")
_SOFT_SEP = re.compile(r"(?<=\S),?\s+(?:but|however)\b,?|(?<=\S)\s-\s+(?=[A-Z0-9])(?!(?i:" + _SOFT_WORDS + r")\b)")
# a qualifier with no subject of its own: "Highly Preferred", "but not required", "is a plus", "Ability to obtain"
_PURE_QUAL = re.compile(
    r"^\W*(?:and\s+|it\s+)?(?:(?:is|are|would\s+be|will\s+be)\s+)?(?:(?:very|highly|strongly|really)\s+)?"
    r"(?:preferred|desired|desirable|nice(?:\s+to\s+have)?|a\s+(?:big\s+|huge\s+|nice\s+)?plus|plus|bonus|optional|ideal|great|welcome|appreciated|valued"
    r"|not\s+(?:a\s+)?(?:required|requirement|mandatory|necessary|needed|essential|a\s+must)|isn't\s+required"
    r"|(?:must\s+be\s+)?(?:ability|able)\s+to\s+(?:obtain|get)(?:\s+(?:and\s+maintain\s+)?(?:it|one))?|obtainable|eligible|clearable"
    r"|(?:candidates\s+)?must\s+be\s+able\s+to\s+obtain(?:\s+(?:it|one))?|good\s+to\s+have|helpful)"
    r"(?:\W+(?:but\s+)?(?:not\s+(?:required|mandatory|necessary)|preferred|desired|a\s+plus|optional))*\W*$", re.I)


def units(text):
    t = normalise(text)
    # an aside that names a level AND qualifies it is its own unit: "(Top Secret eligibility preferred)"
    t = re.sub(r"\(([^()\n]{1,160})\)", lambda m: ("\n" + m.group(1) + "\n") if (_LEVEL.search(m.group(1)) and _VETO.search(m.group(1))) else m.group(0), t)
    out = []          # each unit is a list of pieces, joined at the end (joining as we go is quadratic)
    for piece in _HARD_SEP.split(t):
        if not piece or not piece.strip(" -*"): continue
        first = True
        for u in ([piece] if piece.rstrip().endswith(":") else _SOFT_SEP.split(piece)):   # "Helpful, but not required:" is a heading
            u = (u or "").strip(" -*")
            if not u: continue
            pure = len(u) <= 60 and _PURE_QUAL.match(u.strip("()[] ")) and not u.rstrip().endswith(":")
            # "Active Secret - Highly Preferred", and a qualifier alone in the next cell or line: "<td>Preferred</td>"
            if out and pure and (not first or len(out[-1]) < 40):
                out[-1].append(", " + u)
            else:
                out.append([u])
            first = False
    return ["".join(x) for x in out]


_HEADLIKE = re.compile(r"^[^.!?]{1,80}$")
_SOFT_HEAD = re.compile(
    r"\b(?:prefer\w*|desir\w*|nice[\s-]+(?:to|if)|bonus\s+(?:points|if|qualifications|skills)|pluses|(?:a|big|huge)\s+plus|plus\s+if|plus\s*$"
    r"|ideal(?:ly)?\s+(?:you|candidates?|qualifications|skills)|set\s+you\s+apart|even\s+better|might\s+also\s+have|would\s+be\s+(?:nice|great|a\s+plus)"
    r"|stand\s+out|great\s+to\s+have|good\s+to\s+have|optional\s+(?:qualifications|skills)|optional\s*$|extra\s+credit|added\s+advantage|we\s+prefer"
    r"|additional\s+qualifications|ideally|we'?d\s+love|we\s+would\s+love|bonus\s*$|helpful|differentiators?|extra\s+points|impress|assets?\s*$|nice[\s-]+to[\s-]+haves?)\b", re.I)
_REQ_HEAD = re.compile(
    r"^\s*(?:(?:basic|minimum|required|mandatory|key|core|essential)\s+(?:qualifications|skills|requirements|experience)|requirements|required"
    r"|must[\s-]*haves?|what\s+you(?:'ll|\s+will)?\s+(?:need|bring)|you\s+(?:must\s+)?have|who\s+you\s+are|qualifications\s+you\s+must\s+have)\b", re.I)
_END_HEAD = re.compile(
    r"^\s*(?:who\s+we\s+are|about\b|company\s+overview|overview|benefits|what\s+we\s+offer|perks|compensation|pay\b|salary|location"
    r"|equal\s+(?:employment\s+)?opportunity|eeo|additional\s+information|job\s+details|other\s+information|(?:security\s+)?clearance\s+statement|travel\b|work\s+schedule|physical\s+(?:requirements|demands)|identity\s+statement|responsibilities|what\s+you(?:'ll|\s+will)\s+do|duties|job\s+description|conditions\s+of\s+employment"
    r"|the\s+role|why\s+join|our\s+company|company\b)", re.I)


_INLINE_HEAD = re.compile(
    r"\b(?:(preferred|desired|nice[\s-]+to[\s-]+have|bonus)\s+(?:qualifications|skills|experience)?|(?:basic|minimum|required|mandatory|key)\s+(?:qualifications|skills|requirements))\s*:", re.I)


def _heading(u):
    """'soft', 'req', 'end', 'field', 'other' or None for a unit that reads as a section heading or a field."""
    u = u.strip("#* ")
    if not _HEADLIKE.match(u): return None
    if ":" in u:
        head, rest = u.split(":", 1)
        if rest.strip() and (not _SOFT_HEAD.search(head) or re.search(r"[$\d]", rest) or re.search(r"(?:bonus|assets?)\s*$", head, re.I)):
            return "field"                                                       # "Location: Remote", "Sign-On Bonus: $10,000"
    else:
        head = u
        if len(u.split()) > 6 or _mentions(u) or re.search(r"\b(?:is|are|must)\b", u, re.I): return None
    if len(head) > 70: return None
    if _SOFT_HEAD.search(head) and not _REQ_HEAD.match(head): return "soft"
    if _REQ_HEAD.match(head): return "req"
    if _END_HEAD.match(head): return "end"
    if ":" in u and not u.split(":", 1)[1].strip(): return "other"                 # an unknown heading ends a Required section
    return None


def held_required(text, explain=False):
    us = units(text)
    why = []
    obtained = None
    section = None
    for u in us:
        h = _heading(u)
        inline = None
        for m in _INLINE_HEAD.finditer(u): inline = "soft" if m.group(1) else "req"
        if h is None and inline: h = inline
        if h == "soft": section = "soft"
        elif h == "req": section = "req"
        elif h == "end" or (h == "other" and section == "req"): section = None
        dd = _DECISIVE.search(u)
        if dd and _DECISIVE_NAMES.search(dd.group(0)) and "?" not in u and not _VISA.search(u):
            why.append((u, "decisive"))
            return (True, why) if explain else True
        mu = _masked(u)
        dm = _DECISIVE_CTX.search(u)
        if dm:
            rest = mu if "considered" in dm.group(0) else mu[:dm.start()] + " " + mu[dm.end():]
            rest = re.sub(r"\bwill\s+be\s+con\w*", " ", rest)
        if dm and (_CLEAR.search(u) or _LEVEL.search(u) or re.search(r"\bssbi|\bsci\b|\binvestigation", u, re.I)) \
                and (not re.match(r"(?:pending|interim|in)", dm.group(0), re.I) or re.search(r"clear|investigation|ssbi|adjudicat|secret|\bts\b|sci\b", u, re.I)) \
                and not _VETO.search(rest) and not re.search(r"\bnot\s+only\b", u, re.I) \
                and not _VISA.search(u) and not re.search(r"\bunclassified\b|\bnot\s+require|\bno\s+clearance\s+(?:is\s+)?(?:required|needed)", u, re.I):
            why.append((u, "decisive"))
            return (True, why) if explain else True
        ms = [m for m in _mentions(u) if not m[2].lower().startswith("interim")]      # an interim clearance the employer gets
        fm = _FIELD_LEVEL.search(u)
        if not ms and not fm: continue
        if section == "soft":
            why.append((u, "soft section")); continue
        if _NO_ANSWER.search(_OTHER_FIELD.sub(lambda m: " " * len(m.group(0)), u)) or (_VETO.search(mu) and not _other_level_only(u, ms)):
            why.append((u, "veto")); continue
        if obtained is None: obtained, interim_ok = _page_obtains(us), _page_interim(us)
        offered = lambda lv: "?" in obtained or _family(lv) in obtained
        for a, b, lv in ms:
            before, after = mu[max(0, a - 60):a], u[b:b + 80]
            if re.search(r"\b(?:information|data|materials?|documents?)\s+(?:up\s+to|at)\s+(?:the\s+)?$", before, re.I): continue
            if (_HELD.search(before) or _HELD.search(lv) or _HELD_AFTER.search(after)) and not offered(lv):
                why.append((u, "held: " + lv))
                return (True, why) if explain else True
        weak = [lv for a, b, lv in ms if _REQUIRED_AFTER.search(u[b:b + 60]) or _REQUIRED_BEFORE.search(u[max(0, a - 40):a])]
        if fm: weak.append(fm.group(1))
        if section == "req" and h != "field":
            weak += [lv for a, b, lv in ms if not re.search(r"\b(?:for|to|of|from|about|in)\s+(?:an?\s+|the\s+)?$", u[max(0, a - 20):a], re.I)]
        if any(not offered(w) for w in weak) and not interim_ok:
            why.append((u, "required: " + ", ".join(weak)))
            return (True, why) if explain else True
        if weak: why.append((u, "required, but the page offers to obtain it"))
    return (False, why) if explain else False
