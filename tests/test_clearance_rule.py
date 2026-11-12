#!/usr/bin/env python3
"""Offline check of clearance_rule.py, on its own and as job_scanner.clearance_verdict (the rule over the
regex reading). Every phrase here is made up or is the labelled-field form a federal contractor prints.

  python3 tests/test_clearance_rule.py
"""
import os, sys
HERE = os.path.dirname(os.path.abspath(__file__)); ROOT = os.path.dirname(HERE); sys.path.insert(0, ROOT)
import clearance_rule as cr
import job_scanner as js

OK = True


def check(cond, msg):
    global OK
    print(("ok   " if cond else "FAIL ") + msg)
    OK = OK and bool(cond)
    return cond


A, O, N = cr.ACTIVE_REQUIRED, cr.OBTAINABLE, cr.NONE_STATED

# (text, verdict through job_scanner.clearance_verdict, short name)
CASES = [
    # labelled-field wording seen on contractor postings: HTML flattens the two labels onto one line
    ("Clearance Level Must Currently Possess: None Clearance Level Must Be Able to Obtain: Secret", O, "labelled-field wording, one line"),
    ("Clearance Level Must Currently Possess: None. Clearance Level Must Be Able to Obtain: Secret.", O, "labelled-field wording, with periods"),
    ("Clearance Level Must Currently Possess:\nNone\nClearance Level Must Be Able to Obtain:\nSecret", O, "labelled-field wording, split across lines"),
    ("Clearance Level Must Currently Possess: None Clearance Level Must Be Able to Obtain: Top Secret/SCI", O, "possess None, obtain TS/SCI"),
    ("Clearance Level Must Currently Possess: Secret Clearance Level Must Be Able to Obtain: Top Secret", A, "possess Secret, obtain TS"),
    ("Clearance Level Must Currently Possess: Top Secret/SCI Clearance Level Must Be Able to Obtain: TS/SCI w/ Poly", A, "possess TS/SCI"),
    ("Clearance Level Must Currently Possess: Public Trust", O, "possess Public Trust"),
    ("Clearance Level Must Currently Possess: None Clearance Level Must Be Able to Obtain: Public Trust", O, "possess None, obtain Public Trust"),
    # active, held now
    ("Active Secret clearance required.", A, "active Secret required"),
    ("An active Top Secret clearance is required for this position.", A, "active Top Secret required"),
    ("TS/SCI with polygraph required.", A, "TS/SCI with poly"),
    ("Candidates must currently hold a Top Secret clearance.", A, "must currently hold"),
    ("Must possess a current Secret clearance; U.S. citizenship required.", A, "current Secret with citizenship"),
    ("Public Trust position; an active Secret clearance is required.", A, "Public Trust with an active clearance"),
    ("Active\nSecret clearance\nrequired to start.", O, "active required, split across lines (kept by design: held_clearance.py drops only on plain held wording)"),
    # interim
    ("Must be able to obtain and maintain a Secret clearance; an interim Secret clearance is required to start.", O, "interim required to start (kept by design: held_clearance.py drops only on plain held wording)"),
    ("Candidates must hold an interim Secret clearance on day one.", O, "must hold an interim (kept by design: held_clearance.py drops only on plain held wording)"),
    ("Must be able to obtain an interim Secret clearance prior to start.", O, "able to obtain an interim"),
    ("No interim clearance required; must be eligible to obtain a Secret clearance.", O, "no interim required"),
    ("An interim Secret clearance is acceptable while the final adjudication is pending; ability to obtain required.", O, "interim acceptable"),
    # obtainable
    ("Ability to obtain a Secret clearance is required.", O, "ability to obtain"),
    ("Must be eligible to obtain a Top Secret clearance.", O, "eligible to obtain"),
    ("Candidates must be clearable.", O, "clearable"),
    ("U.S. citizenship required and must be clearable to the Secret level.", O, "clearable to a level"),
    ("Public Trust clearance required.", O, "Public Trust"),
    ("Secret clearance required within 90 days of hire.", O, "required within 90 days"),
    ("U.S. citizenship required; must be eligible for a security clearance.", O, "eligible for a clearance"),
    ("Public trust or DoD clearance (possession of or ability to obtain). TS/SCI with CI Poly preferred.", O, "possession-or-ability wording"),
    # none, or preferred only
    ("No clearance required.", N, "no clearance required"),
    ("A Top Secret clearance is not required for this role.", N, "clearance not required"),
    ("Secret clearance preferred.", O, "clearance preferred"),
    ("Current TS/SCI a plus.", N, "current clearance a plus"),
    ("Close the books and report monthly.", N, "no clearance wording at all"),
    ("", N, "empty text"),
    # mixed
    ("Must be able to obtain a Secret clearance. Top Secret clearance is required.", A, "obtain one level, another required"),
    ("Secret clearance preferred; active TS/SCI required for some tasks.", A, "preferred then active required"),
    ("Active Secret clearance required, relocation not required.", A, "not required on another noun"),
    ("Must be able to obtain a CPA license within one year. Secret clearance required.", A, "obtaining something else"),
]


def main():
    for text, want, name in CASES:
        got = js.clearance_verdict(text)
        check(got == want, "%s: %r -> %s" % (name, text[:60], got) + ("" if got == want else " (want %s)" % want))
    # the pure function on its own, without the base reading
    check(cr.clearance_rule("Clearance Level Must Currently Possess: None Clearance Level Must Be Able to Obtain: Secret") == O,
          "rule alone: labelled-field wording is OBTAINABLE")
    check(cr.clearance_rule("An interim Secret clearance is required to start.") == A, "rule alone: interim required")
    check(cr.clearance_rule("Must Currently Possess: Secret") == A, "rule alone: possess a level")
    check(cr.clearance_rule("Must be clearable.") == O, "rule alone: clearable")
    check(cr.clearance_rule("Active Secret clearance required.") == N, "rule alone: no base, no own reading -> NONE STATED")
    check(cr.clearance_rule("Active Secret clearance required.", base=js._clearance_verdict_regex) == A, "rule with base: active")
    # pure: the same text twice gives the same answer, and the input is not changed
    s = "Clearance Level Must Currently Possess:\tNone Must Be Able to Obtain: Secret"
    check(cr.clearance_rule(s, js._clearance_verdict_regex) == cr.clearance_rule(s, js._clearance_verdict_regex) == O
          and s.count("\t") == 1, "pure: same text, same verdict; input untouched")
    check(cr.normalise("a\n\nb\t c \u2013 d") == "a b c - d", "normalise joins lines and dashes")
    # held_clearance.py keeps by default (12 Nov 2026): the review findings that dropped postable jobs stay kept
    kept = ["Must be able to obtain a Secret clearance, or ability to obtain.",          # H1: "or ability to obtain." bare
            "Clearance: Secret (ability to obtain)",                                    # H2
            "<h3>Clearance</h3><p>Ability to obtain a Secret clearance</p>",             # H3: heading with no colon
            "Experience supporting the U.S. Secret Service is a plus.",                  # H4: names
            "Victoria's Secret merchandising analyst",
            "B.S. from Cal Poly preferred; must be able to obtain a security clearance.",
            "Must be able to obtain and thereafter maintain an active Secret clearance.",  # H5
            "This position may require a security clearance in the future.",          # H6
            "Manage retail clearance pricing and markdowns.",                           # H7: other kinds
            "Customs clearance experience required.", "Medical clearance required before travel.",
            "Our company holds a Top Secret facility clearance.",
            "Preferred Qualifications:\n- Active TS/SCI clearance\n- AWS certification",
            "Do you hold an active TS/SCI clearance?",
            "Skills: Windows Server, Active Directory, VMware, Secret clearance",              # review 2 (12 Nov)
            "Pending certifications will not be accepted; Security+ must be held at time of hire.",
            "Clearance:\nApplicants selected will be subject to a security investigation and may need to meet eligibility "
            "requirements for access to classified information; Secret clearance is required.",
            "Helpful, but not required:\n- Active TS/SCI clearance\n- Experience with ROS2",
            "Active Secret clearance - Highly Preferred",
            "Over 85% of our workforce holds active security clearances.",
            "Must be a U.S. citizen (required for Secret clearance)."]
    bad = [k for k in kept if js.clearance_verdict(k) == A]
    check(not bad, "keep by default: review findings stay kept " + (repr(bad) if bad else "(%d phrases)" % len(kept)))
    drop = ["Active TS/SCI with full-scope polygraph required.", "Cleared candidates only.",
            "Candidates without an active clearance will not be considered.", "We cannot sponsor a clearance for this role.",
            "Must currently hold a Top Secret clearance.", "Security Clearance Required: TS/SCI",
            "Required Qualifications:\n- TS/SCI clearance\n- Python",
            "Candidates without an active TS/SCI will not be considered."]
    bad = [k for k in drop if js.clearance_verdict(k) != A]
    check(not bad, "keep by default: plain held wording still drops " + (repr(bad) if bad else "(%d phrases)" % len(drop)))
    import time
    t0 = time.time()
    for big in ("<" * 200000, " " * 300000 + "but TS/SCI", "TS/SCI w/ Full Scope Poly - " * 20000, "secret " * 50000 + "clearance",
                "Active Secret clearance" + " - Welcome" * 30000, "active Secret clearance and ability to obtain Top Secret " * 5000):
        js.clearance_verdict(big)
    check(time.time() - t0 < 10, "linear time: six 140-300 KB adversarial texts in %.1f s" % (time.time() - t0))
    n = len(CASES) + 11
    print(("PASS" if OK else "FAIL") + " test_clearance_rule (%d checks)" % n)
    return 0 if OK else 1


if __name__ == "__main__":
    sys.exit(main())
