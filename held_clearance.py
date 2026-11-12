"""held_clearance.py - one question about a job posting's text: must the candidate already HOLD a security
clearance (Secret, Top Secret, TS/SCI, a polygraph) to be considered?

    held_required(text) -> bool

Written for a U.S. citizen who has held a clearance before and holds none now. A posting he can apply to must
never be dropped, so the default is KEEP (False). A posting is dropped only on a short list of plain wordings:

  1. Decisive sentences: "cleared candidates only", "candidates without a clearance will not be considered",
     "must already hold ... clearance", "we cannot sponsor a clearance", "clearance sponsorship is not available".
  2. A clearance level (TS/SCI, Top Secret, Secret clearance, SCI, a CI or full-scope polygraph, DOE Q or L)
     next to held wording: active, current, existing, must have / hold / possess, in possession of, at the
     time of application, prior to start, on day one.
  3. A clearance level next to "required" or "mandatory", or in a "Clearance Required: <level>" field, unless
     the page offers to obtain or sponsor that clearance.

Rules 2 and 3 never fire in a unit (sentence, list item, ';' clause) that also speaks of obtaining, eligibility,
sponsoring, preference, "a plus", the future, "not required", or asks a question. A bare level with nothing else
("- TS/SCI clearance", a title "Analyst - TS/SCI w/ Poly") is KEPT: missing a held clearance shows a job he can
skip; reading one where there is none hides a job he could get. The second error is the costly one.
Every regular expression here is bounded or linear in the text length.
"""
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
    for a, b in (("\xa0", " "), (" ", " "), (" ", " "), ("–", "-"), ("—", "-"), ("‑", "-"),
                 ("​", ""), ("’", "'"), ("\t", " ")):
        t = t.replace(a, b)
    t = re.sub(r"\b(?:[A-Za-z]\.){2,}", lambda m: m.group(0).replace(".", ""), t)          # U.S. -> US, D.C. -> DC
    t = re.sub(r"\b(Inc|Corp|Co|Ltd|LLC|Sr|Jr|Dr|Mr|Ms|Mrs|St|No|vs|approx|Dept|Gov|Govt)\.(?=\s)", r"\1", t)
    return t


# a unit ends at a newline, ';', '|', a bullet, a sentence end, or a " - " list separator (not "- Required")
_SEP = re.compile(r"\n|;|\||(?<=\S),?\s+(?:but|however)\b,?|[•●·▪◦]|(?<=[.!?])\s+(?=[\"'(A-Z0-9-])"
                  r"|(?<=\S)\s-\s+(?=[A-Z0-9])(?!(?:No|None|N/A|NA|N|Yes|Y|Not|TBD|Negative|required|preferred|desired|optional|mandatory|a plus|plus|eligible|active|current|"
                  r"REQUIRED|PREFERRED|DESIRED|Required|Preferred|Desired|Mandatory|Eligible|Active|Current)\b)")


def units(text):
    t = normalise(text)
    t = re.sub(r"\(([^()\n]{1,160})\)", lambda m: ("\n" + m.group(1) + "\n") if _LEVEL.search(m.group(1)) else m.group(0), t)
    return [u.strip(" -*") for u in _SEP.split(t) if u and u.strip(" -*")]


# ---------------------------------------------------------------- levels
_NOT_PERSONAL = r"(?!\s+(?:data|information|material|materials|documents?|networks?|systems?|environments?|facilit\w*|programs?|spaces?|areas?|scifs?|work\b|contracts?|projects?|level\s+(?:data|information|systems?)))"
_LEVEL = re.compile(
    r"(?:\b[Tt][Ss]\s*(?:/{1,2}|-|\s)\s*[Ss][Cc][Ii]\b" + _NOT_PERSONAL +
    r"|\btop[\s-]+secret\b(?!\s+service)" + _NOT_PERSONAL +
    r"|\bsecret[\s-]+level\s+(?:security\s+)?clearances?\b|\bsecret\b[\"']?\s+(?:(?!service|facility|fcl)[\w/]+\s+){0,3}?(?:security\s+)?clearances?\b"
    r"|\b(?:dod|dos|doj|dhs|active|current|interim|final|existing|government|federal)\s+secret\b(?!\s+service)" + _NOT_PERSONAL +
    r"|(?-i:\bSCI\b)" + _NOT_PERSONAL +
    r"|(?-i:\bTS\b)(?=\s*(?:clearance|w/|with|/|\(|poly|security))"
    r"|\b(?:ci|fs|fsp|full[\s-]*scope|lifestyle|counter[\s-]?intelligence)\s*poly(?:graph)?s?\b"
    r"|\bpolygraph\b(?!\s+protection)"
    r"|\b(?:doe\s+)?(?-i:[QL])\s+clearance\b"
    r"|\byankee\s+white\b)", re.I)
# "Clearance: Secret", "Security Clearance Required: Secret", "Minimum Clearance Required to Start: Secret"
_FIELD_LEVEL = re.compile(
    r"\b(?:security\s+)?clearance(?:\s+(?:level|type))?(?:\s+required)?(?:\s+to\s+start)?\s*:\s*(?:an?\s+)?(?:active\s+|current\s+)?"
    r"(?:(?:dod|government)\s+)?(secret|top[\s-]+secret|ts\s*/\s*sci|ts|(?-i:Q|L))\b(?!\s*/\s*public)", re.I)
# a bare clearance with held wording in front of it: "an active security clearance", "must hold a current clearance"
_GENERIC = re.compile(
    r"\b(?:active|current|existing)\s+(?:(?:us|u\.s\.|federal|government|dod|national)\s+)?(?:security\s+)?clearances?\b"
    r"(?=\s*(?:$|[.,;:()/]|(?:required|is|with|and|or|at|of|level|to|in|for|that|as|preferred|needed|a\s+must|must|w/)\b))", re.I)

# ---------------------------------------------------------------- wordings
_DECISIVE = re.compile(
    r"\bcleared\s+(?:candidates|applicants|individuals|personnel|professionals)\s+only\b"
    r"|\bonly\s+(?:currently\s+)?cleared\s+(?:candidates|applicants|individuals)\b"
    r"|\bonly\s+(?:candidates|applicants)\s+(?:who\s+(?:currently\s+)?(?:hold|possess|have)|with)\s+(?:an?\s+)?(?:active|current)\b[^.;]{0,60}\b(?:will\s+be\s+considered|considered)\b"
    r"|\b(?:candidates|applicants|those)\s+(?:without|lacking)\s+(?:an?\s+)?(?:active\s+|current\s+)?(?:\w+\s+){0,2}?clearances?\s+(?:will\s+not|won't|should\s+not|need\s+not|cannot|can\s*not)\s+(?:be\s+considered|apply)"
    r"|\b(?:awaiting|pending)\s+adjudication\s+need\s+not\s+apply\b"
    r"|\bmust\s+already\s+(?:hold|possess|have|be\s+cleared|be\s+in\s+possession)\b"
    r"|\bmust\s+already\s+be\s+established\b"
    r"|\bmust\s+currently\s+(?:possess|hold)\s*:\s*(?:an?\s+|active\s+|current\s+)*(?:top\s+secret|secret|ts\b|tssci|ts/sci)"
    r"|\b(?:unable\s+to|not\s+able\s+to|cannot|can\s*not|can't|will\s+not|won't|do\s+not|does\s+not)\s+(?:sponsor|initiate|process)\s+(?:an?\s+|new\s+|your\s+)?(?:security\s+)?(?:clearances?|investigations?|ssbis?)\b"
    r"|\b(?:security\s+)?clearance\s+sponsorship\s+(?:is\s+)?(?:not|un)\s*available\b"
    r"|\bno\s+(?:security\s+)?clearance\s+sponsorship\b(?!\s*:)", re.I)
_VETO = re.compile(
    r"\b(?:obt(?:ai|ia)n\w*|attain\w*|acquire\w*|eligib\w*|clearable|(?:ability|able)\s+to\s+(?:obtain|attain|get|acquire|pass|receive|undergo|be\s+(?:cleared|granted|approved|sponsored|processed|polygraph\w*|investigated|read))|willing\w*\s+to\s+(?:obtain|undergo|be\s+(?:sponsored|processed|investigated|cleared|polygraph\w*)|submit|go\s+through|pursue|apply\s+for)|sponsor\w*"
    r"|prefer\w*|desir\w*|a\s+plus|plus\b|bonus|nice[\s-]+to[\s-]+have|ideal\w*|advantage\w*|beneficial|helpful|asset"
    r"|not\s+(?:be\s+)?(?:required|a\s+requirement|necessary|needed|mandatory)|n't\s+(?:required|needed|necessary)"
    r"|(?:do|does|will)\s+not\s+require|not\s+require|no\s+(?:active\s+|current\s+)?(?:security\s+)?clearance"
    r"|may\s+(?:be\s+)?(?:requir\w*|need\w*)|might|could|future|eventually"
    r"|(?:upon|after|following)\s+(?:hire|hiring|start\w*|an?\s+offer|offer|selection|onboarding|award)|post[\s-]?hire|once\s+(?:hired|selected)"
    r"|within\s+(?:the\s+)?(?:first\s+)?\d+|if\s+(?:selected|hired|required|you)|interim|investigation|reinvestigation|subject\s+to"
    r"|encourag\w*|priority|preference|either|(?<!to\sbe\s)considered|given\s+consideration|process\w*\s+(?:for|you|it)|we\s+will"
    r"|should|expedit\w*|speed\s+up|fast[\s-]*track\w*|previous\w*|formerly|in\s+the\s+past|(?:have|has|had)\s+(?:previously\s+)?held|have\s+held"
    r"|facilit\w*\s+(?:security\s+)?clearances?|fcl|indicate|whether|if\s+any|if\s+applicable|list\s+your|please|do\s+you|have\s+you|are\s+you|some\s+(?:of\s+our\s+)?(?:positions|roles|jobs|programs)"
    r"|no\s+(?:[\w/-]+\s+){0,3}?(?:clearance|required)"
    r"|stand\s+out|prioriti[sz]\w*|favou?r\w*|leg\s+up|differentiator)\b|\?|^\s*q\s*\*", re.I)
# a labelled field answered no: "Secret Clearance Required: No", "TS/SCI Required (Y/N): N"; not "Required: No exceptions"
_NO_ANSWER = re.compile(
    r"\brequired\b(?:\s*\(\s*y\s*/\s*n\s*\))?(?:\s+(?:at|to|for)\s+(?:start|this\s+(?:position|role)))?(?:\s*[:–-]\s*|\s+)"
    r"(?:(?:none|n/?a|tbd|negative|n|not)\b|no\b(?![\s-]*(?:exceptions?|waivers?|substitutions?|deviations?|lapses?|equivalents\b|alternatives\b|c2c|corp"
    r"|foreign\s+nationals\b(?!\s+may)|non-?u|dual|later\s+than|exemptions?|other\s+cert)))", re.I)
_OTHER_FIELD = re.compile(r"\b(?:travel|telework|relocation|overtime|remote|drug\s+test\w*|shift\s+work)\s+required\s*:\s*(?:no|yes|n|y)\b", re.I)
_HELD = re.compile(
    r"\b(?:active|current(?:ly)?|existing|already|possess\w*|in\s+possession|must\s+(?:have|hold|maintain|carry)|"
    r"(?:to|you|candidates?|applicants?)\s+(?:have|hold)|hold\w*\s+(?:an?\s+|the\s+)?(?:active|current|valid)?|cleared)\b", re.I)
_HELD_AFTER = re.compile(
    r"\b(?:at\s+(?:the\s+)?time\s+of\s+(?:application|applying|hire|offer|submission)|prior\s+to\s+(?:start\w*|hire|beginning|day\s+one|employment)"
    r"|before\s+(?:start\w*|day\s+one|employment)|on\s+day\s+one|day[\s-]+one|(?:required\s+)?to\s+start|in\s+place|in\s+hand|must\s+be\s+active|be\s+current)\b", re.I)
_REQUIRED_AFTER = re.compile(r"^[^.;:]{0,30}?\b(?:is\s+)?(?:required|mandatory|a\s+must|a\s+requirement|must\s+have)\b", re.I)
_REQUIRED_BEFORE = re.compile(r"\b(?:requires?|required|requirement|mandatory)\s*(?::|-)?\s*(?:an?\s+|the\s+)?(?:\w+\s+){0,2}$", re.I)
_PAGE_OBTAIN = re.compile(
    r"\b(?:obt(?:ai|ia)n\w*|attain\w*|eligib\w*|clearable|process\w*\s+(?:a|an|your|the)\s+(?:\w+\s+){0,2}?clearance)\b", re.I)
_PAGE_SPONSOR = re.compile(r"\bsponsor\w*\b|\brequired\s+at\s+start\s*:\s*no\b|\bsponsorship\s+available\s*:\s*yes\b", re.I)
_VISA = re.compile(r"\bvisa|\bh-?1b\b|\bwork\s+authori|\bimmigration\b|\bemployment\s+authori", re.I)
_PRONOUN = re.compile(r"\b(?:it|one|the\s+same|same|such)\b", re.I)
_NEGATED_SPONSOR = re.compile(r"\b(?:not|no)\s+(?:offer|provide)\w*\s+(?:\w+\s+)?sponsorship|\brequiring\s+sponsorship\s+will\s+not|\b(?:not|unable\s+to|cannot|can\s*not|can't|won't|will\s+not|do\s+not|does\s+not)\s+(?:be\s+able\s+to\s+|to\s+)?sponsor|\bsponsor\w*\s+(?:is\s+)?(?:not|un)\s*available|\bno\s+(?:\w+\s+)?sponsorship", re.I)
_CLEAR = re.compile(r"\bclear(?:ance|ed)\w*", re.I)


def _family(level_text):
    s = level_text.lower()
    if "poly" in s: return "P"
    if re.search(r"top|ts|sci|yankee", s): return "TS"
    if "secret" in s: return "S"
    if re.search(r"\bq\b", s): return "Q"
    if re.search(r"\bl\b", s): return "L"
    return "?"


def _mentions(u):
    out = [(m.start(), m.end(), m.group(0)) for m in _LEVEL.finditer(u)]
    out += [(m.start(), m.end(), m.group(0)) for m in _GENERIC.finditer(u)]
    return out


def _page_obtains(us):
    """Families of clearance the page offers to obtain or sponsor ('?' = a clearance with no level, or "it"/"one")."""
    fams = set()
    for u in us:
        u = _masked(u)
        hits = [m for m in _PAGE_OBTAIN.finditer(u)] if (_CLEAR.search(u) or _LEVEL.search(u) or _PRONOUN.search(u)) else []
        if not hits and _PAGE_SPONSOR.search(u) and not _VISA.search(u) and not _NEGATED_SPONSOR.search(u):
            hits = list(_PAGE_SPONSOR.finditer(u))
        for m in hits:
            if _NEGATED_SPONSOR.search(u[max(0, m.start() - 30):m.end()]): continue
            tgt = {_family(x.group(0)) for x in _LEVEL.finditer(u[m.end():m.end() + 60])}
            fams |= tgt or {"?"}
    return fams


_OB = re.compile(r"\b(?:obt(?:ai|ia)n\w*|attain\w*|acquire\w*|eligib\w*|(?:ability|able)\s+to(?:\s+be\s+approved\s+for)?|willing\w*\s+to\s+\w+)", re.I)


_MASK = re.compile(
    r"\bno[\s-]+(?:exceptions?|waivers?|substitutions?|deviations?|lapses?(?:\s+in\s+clearance)?|equivalents\b|alternatives\b"
    r"|c2c|corp[\s-]*to[\s-]*corp|foreign\s+nationals\b(?!\s+may)|non-?u\.?s\.?(?:\s+(?:persons?|citizens?))?|dual\s+citizens?|later\s+than"
    r"|exemptions?|other\s+certifications?)\b[^.;|]{0,25}"
    r"|\b(?:relocation|travel|degree|visas?|telework|overtime|experience|certifications?|licen[cs]e)\b[^,.;]{0,15}?\bnot\s+(?:be\s+)?(?:required|needed|available|necessary)"
    r"|\b(?:obtain\w*|maintain)\s+(?:and\s+maintain\s+)?(?:an?\s+|the\s+|one\s+(?:year\s+of\s+)?|one\s+of\s+the\s+following\s+)?(?:[\w-]+\s+){0,2}?"
    r"(?:licen[cs]e|certifications?|certificate|degree|experience|cissp|security\+|comptia|cpa|pmp|driver)\w*"
    r"|\bsponsor\w*\s+(?:\w+\s+){0,2}?visas?|\bvisa\s+sponsorship[^.;,]{0,30}|\b(?:not|no)\s+(?:offer\s+)?sponsorship[^.;,]{0,20}|\bsponsorship\s+(?:is\s+)?(?:not|un)\s*available"
    r"|\brequiring\s+sponsorship\s+will\s+not\s+be\s+considered|\bdo(?:es)?\s+not\s+(?:offer|provide)\s+sponsorship|\bdo(?:es)?\s+not\s+sponsor\s+visas?"
    r"|\b(?:travel|telework|relocation|overtime|remote)\s+required\s*:\s*(?:no|yes|n|y)\b", re.I)


_MASK_POLY = re.compile(r"\b(?:ci\s+|fs\s+|full[\s-]*scope\s+)?poly(?:graph)?\s+(?:is\s+)?(?:preferred|desired|a\s+plus|not\s+(?:required|needed)|optional)", re.I)


def _masked(u):
    m = _MASK.sub(lambda m: " " * len(m.group(0)), u)
    if any("poly" not in x.group(0).lower() for x in _LEVEL.finditer(u)):        # a polygraph only preferred, next to a held level
        m = _MASK_POLY.sub(lambda x: " " * len(x.group(0)), m)
    return m


def _other_level_only(u, ms):
    """True when every veto word in the unit is an obtaining word aimed at a DIFFERENT level than a held one before it:
    "Active Secret clearance and ability to obtain Top Secret", "Active TS/SCI with ability to be approved for a CI Poly"."""
    vs = list(_VETO.finditer(_masked(u)))
    if not vs or any(not _OB.match(u, v.start()) for v in vs): return False
    first = vs[0].start()
    held = [_family(lv) for a, b, lv in ms if a < first and (_HELD.search(u[max(0, a - 60):a]) or _HELD.search(lv))]
    if not held: return False
    for v in vs:
        tgt = [lv for a, b, lv in ms if v.end() <= a <= v.end() + 60]
        if not tgt or any(_family(t) in held for t in tgt): return False
    return True


_REQ_HEAD = re.compile(
    r"^\s*(?:(?:basic|minimum|required|mandatory|key|core|essential)\s+(?:qualifications|skills|requirements|experience)|requirements|required|must[\s-]*haves?"
    r"|what\s+you(?:'ll|\s+will)?\s+need|you\s+(?:must\s+)?have|who\s+you\s+are)\b\s*(?::|$)", re.I)
_SOFT_HEAD = re.compile(
    r"^\s*(?:(?:additional|highly|strongly)\s+)?(?:preferred|desired|desirable|nice[\s-]+(?:if|to)[\s-]+(?:you\s+)?have|good\s+to\s+have|"
    r"bonus(?:\s+points)?|pluses|a\s+plus|extra\s+credit|optional|what\s+would\s+be\s+nice|nice\s+to\s+haves?|ideal(?:ly)?|"
    r"(?:it\s+)?would\s+be\s+(?:nice|great|a\s+plus))\b[^:]{0,60}?(?::|$)", re.I)
_HEADING = re.compile(r"^[^.!?]{0,60}:\s*$|^\s*(?:basic|minimum|required|mandatory|key|core)\s+(?:qualifications|skills|requirements)\b|^\s*(?:requirements|required|responsibilities|qualifications|education|about\s+(?:the\s+role|us))\s*:?\s*$", re.I)


def held_required(text, explain=False):
    us = units(text)
    why = []
    obtained = None
    soft, soft_len, req = False, 0, False
    for u in us:
        if _SOFT_HEAD.search(u):
            soft, soft_len, req = True, 0, False
        elif _REQ_HEAD.search(u):
            soft, req = False, True
        elif _HEADING.search(u):
            soft = req = False
        if soft:
            soft_len += len(u)
            if soft_len > 3000: soft = False
        if _DECISIVE.search(u) and "?" not in u and not _VISA.search(u):
            why.append((u, "decisive"))
            return (True, why) if explain else True
        ms = _mentions(u)
        fm = _FIELD_LEVEL.search(u)
        if not ms and not fm: continue
        if soft:
            why.append((u, "soft section")); continue
        if _NO_ANSWER.search(_OTHER_FIELD.sub(lambda m: " " * len(m.group(0)), u)) or (_VETO.search(_masked(u)) and not _other_level_only(u, ms)):
            why.append((u, "veto")); continue
        if obtained is None: obtained = _page_obtains(us)
        offered = lambda lv: "?" in obtained or _family(lv) in obtained
        for a, b, lv in ms:
            before, after = u[max(0, a - 60):a], u[b:b + 80]
            if (_HELD.search(before) or _HELD.search(lv) or _HELD_AFTER.search(after)) and not offered(lv):
                why.append((u, "held: " + lv))
                return (True, why) if explain else True
        weak = [lv for a, b, lv in ms if _REQUIRED_AFTER.search(u[b:b + 60]) or _REQUIRED_BEFORE.search(u[max(0, a - 40):a])]
        if fm: weak.append(fm.group(1))
        if req: weak += [lv for a, b, lv in ms]
        if any(not offered(w) for w in weak):
            why.append((u, "required: " + ", ".join(weak)))
            return (True, why) if explain else True
        if weak: why.append((u, "required, but the page offers to obtain it"))
    return (False, why) if explain else False
