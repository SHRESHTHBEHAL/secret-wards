"""Shape-based recognisers for identifiers and for clinical text that must be kept.

Pure functions, no I/O. All offsets refer to the input string; Indic digits are mapped
to ASCII one character for one character, so offsets are preserved.
"""
from __future__ import annotations

import bisect
import re
import unicodedata
from typing import Iterable, List, Optional, Tuple

from . import lexicon, scripts
from .types import Span


# ---------------------------------------------------------------- helpers

def _to_ascii_digits(s: str) -> str:
    """Map every Unicode decimal digit to ASCII, keeping length (private fallback)."""
    if not s or max(s) < "\u0660":  # nothing to map (the loop below keeps every such character)
        return s
    out = []
    for ch in s:
        if "0" <= ch <= "9" or ch < "\u0660":
            out.append(ch)
            continue
        d = unicodedata.decimal(ch, None)
        out.append(str(d) if d is not None else ch)
    return "".join(out)


def _digits(s: str) -> str:
    return "".join(c for c in _to_ascii_digits(s) if "0" <= c <= "9")


def norm_id(s: str) -> str:
    """Canonical hospital-id key: upper-case ASCII alphanumerics only (Indic digits to ASCII; every
    separator, '#', '.', space and bracket removed). Used by harvest and link alike."""
    return re.sub(r"[^0-9A-Z]", "", _to_ascii_digits(s).upper())


def norm_digits(s: str) -> str:
    """Canonical Aadhaar / ABHA key: ASCII digits only."""
    return _digits(s)


def id_core(s: str) -> str:
    """Last digit group of an identifier (the scorer's digit core)."""
    groups = re.findall(r"[0-9]+", _to_ascii_digits(s))
    return groups[-1] if groups else ""


def norm_phone(s: str) -> str:
    """Last 10 digits of an Indian mobile after dropping +91 / 91 / 0 prefixes; '' otherwise."""
    d = _digits(s)
    if len(d) == 14 and d.startswith("0091"):
        d = d[4:]
    elif len(d) == 13 and d.startswith("091"):
        d = d[3:]
    elif len(d) == 12 and d.startswith("91"):
        d = d[2:]
    elif len(d) == 11 and d.startswith("0"):
        d = d[1:]
    if len(d) == 10 and d[0] in "6789":
        return d
    return ""


_VD = (
    (0, 1, 2, 3, 4, 5, 6, 7, 8, 9), (1, 2, 3, 4, 0, 6, 7, 8, 9, 5), (2, 3, 4, 0, 1, 7, 8, 9, 5, 6),
    (3, 4, 0, 1, 2, 8, 9, 5, 6, 7), (4, 0, 1, 2, 3, 9, 5, 6, 7, 8), (5, 9, 8, 7, 6, 0, 4, 3, 2, 1),
    (6, 5, 9, 8, 7, 1, 0, 4, 3, 2), (7, 6, 5, 9, 8, 2, 1, 0, 4, 3), (8, 7, 6, 5, 9, 3, 2, 1, 0, 4),
    (9, 8, 7, 6, 5, 4, 3, 2, 1, 0),
)
_VP = (
    (0, 1, 2, 3, 4, 5, 6, 7, 8, 9), (1, 5, 7, 6, 2, 8, 3, 0, 9, 4), (5, 8, 0, 3, 7, 9, 6, 1, 4, 2),
    (8, 9, 1, 6, 0, 4, 3, 5, 2, 7), (9, 4, 5, 3, 1, 2, 6, 8, 7, 0), (4, 2, 8, 6, 5, 7, 3, 9, 0, 1),
    (2, 7, 9, 3, 8, 0, 6, 4, 1, 5), (7, 0, 4, 6, 9, 1, 3, 2, 5, 8),
)


def verhoeff_ok(digits: str) -> bool:
    d = _digits(digits)
    if not d:
        return False
    c = 0
    for i, ch in enumerate(reversed(d)):
        c = _VD[c][_VP[i % 8][int(ch)]]
    return c == 0


class Intervals:
    """Overlap test against a fixed set of [start, end) intervals in O(log n): sorted starts plus a
    running maximum of ends. hits(s, e) == any(a < e and s < b for a, b in intervals)."""

    def __init__(self, iv: Iterable[Tuple[int, int]]) -> None:
        ivs = sorted((a, b) for a, b in iv)
        self.starts = [a for a, _ in ivs]
        self.pmax = []  # type: List[int]
        m = None  # type: Optional[int]
        for _, b in ivs:
            m = b if m is None or b > m else m
            self.pmax.append(m)

    def hits(self, s: int, e: int) -> bool:
        i = bisect.bisect_left(self.starts, e)
        return i > 0 and self.pmax[i - 1] > s

    def __bool__(self) -> bool:
        return bool(self.starts)


def _resolve(cands: List[Tuple[int, int, int, str, str]]) -> List[Span]:
    """cands: (priority, start, end, kind, value). Lower priority wins, then longer."""
    cands = sorted(cands, key=lambda c: (c[0], -(c[2] - c[1]), c[1]))
    out: List[Span] = []
    if any(c[2] <= c[1] for c in cands):  # empty candidates: keep the plain scan (never seen in practice)
        taken: List[Tuple[int, int]] = []
        for _p, s, e, k, v in cands:
            if any(s < te and ts < e for ts, te in taken):
                continue
            taken.append((s, e))
            out.append(Span(s, e, k, v))
        out.sort(key=lambda sp: (sp.start, sp.end))
        return out
    # taken intervals never overlap: sorted by start their ends increase, so the neighbours of the
    # insertion point decide a clash
    starts: List[int] = []
    ends: List[int] = []
    for _p, s, e, k, v in cands:
        i = bisect.bisect_left(starts, s)
        if (i > 0 and ends[i - 1] > s) or (i < len(starts) and starts[i] < e):
            continue
        starts.insert(i, s)
        ends.insert(i, e)
        out.append(Span(s, e, k, v))
    out.sort(key=lambda sp: (sp.start, sp.end))
    return out


def _segment_before(t: str, start: int, limit: int = 60) -> str:
    """Text between the previous field delimiter and start (lowercase, bounded)."""
    lo = max(0, start - limit)
    seg = t[lo:start]
    cut = max(seg.rfind(c) for c in ",\t\n;|{[")
    if cut >= 0:
        seg = seg[cut + 1:]
    return seg.lower()


def _line_before(t: str, start: int, limit: int = 80) -> str:
    lo = max(0, start - limit)
    seg = t[lo:start]
    nl = seg.rfind("\n")
    if nl >= 0:
        seg = seg[nl + 1:]
    return seg


# ---------------------------------------------------------------- identifiers

_SEP = r"[ \t.\-\u2010-\u2015]"
_NB = r"(?<![0-9A-Za-z])"          # not glued to a letter or digit on the left
_NA = r"(?![0-9A-Za-z])"           # ... or on the right

_RE_PHONE = re.compile(
    r"(?<![0-9A-Za-z+])(?:\(?(?:\+|00)\s?91\)?" + _SEP + r"*|\(?91\)" + _SEP + r"*|91" + _SEP + r"+|\(?0\)?" + _SEP + r"?)?"
    r"[6-9](?:" + _SEP + r"?[0-9]){9}(?![0-9A-Za-z])"
)
_RE_PHONE_PLUS = re.compile(r"\+91[0-9]{10}(?![0-9])")
# "+971 50 318 2264", "+44 7700 900123": any other country code, 7-12 digits in groups
_RE_PHONE_INTL = re.compile(r"(?<![0-9A-Za-z+])\+(?!91)[1-9][0-9]{0,2}(?:[ \t.\-]?[0-9]){7,12}(?![0-9A-Za-z])")
# "(04576) 262418", "(011) 2345 6789": STD code in brackets
_RE_PHONE_STD = re.compile(r"(?<![0-9A-Za-z])\(0[1-9][0-9]{1,4}\)[ \t\-]?[2-9][0-9]{1,3}[ \t\-]?[0-9]{2,4}(?![0-9A-Za-z])")
# "+91 (98765) 43210", "(98765) 43210", "0091 (98765)-43210"
_RE_PHONE_PAREN = re.compile(r"(?<![0-9A-Za-z+])(?:(?:\+|00)[ \t]?91[ \t.\-]*)?\([ \t]?[6-9][0-9]{4}[ \t]?\)"
                             r"[ \t.\-]?[0-9]{5}(?![0-9A-Za-z])")
_RE_AADHAAR_SPACED = re.compile(_NB + r"[2-9][0-9]{3}( {1,2}|[\-.])[0-9]{4}\1[0-9]{4}" + _NA)
_RE_AADHAAR_SOLID = re.compile(r"(?<![0-9A-Za-z+])[2-9][0-9]{11}" + _NA)
_RE_AADHAAR_MASK = re.compile(
    _NB + r"(?:[xX*\u2022]{4}[ \-]?[xX*\u2022]{4}[ \-]?|[xX*\u2022]{8})([0-9]{4})" + _NA
)
_RE_ABHA_SEP = re.compile(_NB + r"[0-9]{2}([ \-.])[0-9]{4}\1[0-9]{4}\1[0-9]{4}" + _NA)
_RE_ABHA_SOLID = re.compile(_NB + r"[0-9]{14}" + _NA)
_RE_ABHA_ADDR = re.compile(
    r"(?<![\w.@])[A-Za-z0-9][A-Za-z0-9._\-]{1,63}@(?:abdm|sbx|ndhm|abha)(?![\w.])", re.I
)
_RE_EMAIL = re.compile(
    r"(?<![\w.@+-])[A-Za-z0-9][A-Za-z0-9._%+\-]{0,63}@[A-Za-z0-9](?:[A-Za-z0-9\-]*[A-Za-z0-9])?"
    r"(?:\.[A-Za-z0-9\-]+)*\.[A-Za-z]{2,24}(?![\w])"
)
_RE_PAN = re.compile(r"(?<![0-9A-Za-z])[A-Z]{5}[0-9]{4}[A-Z](?![0-9A-Za-z])", re.I)

# code-like token: letters first, then letter/digit groups with optional separators
_RE_CODE = re.compile(
    r"(?<![0-9A-Za-z])[A-Za-z]{1,10}(?:(?:[\-/._]|#\s?|\s?#)?(?:[A-Za-z]{1,10}|[0-9]{1,14}))*(?![0-9A-Za-z])"
)
_RE_ANY_TOKEN = re.compile(r"(?<![0-9A-Za-z])[A-Za-z0-9](?:[A-Za-z0-9]|[\-/._](?=[A-Za-z0-9])){3,40}")

_INS_PREFIXES = frozenset("""
PMJAY ABPMJAY PMJ AB ABHI POL POLICY PLCY INS INSR INSU CGHS ESIC ESI ECHS TPA MED MEDI HLTH HI MEM MBR
BEN BNF RSBY MJPJAY CMCHIS GIC NIC NIA OIC UII LIC STAR CARE HDFC ICICI BAJAJ SBI NHPS SHIS JAY
""".split())
_RE_INS_LABEL = re.compile(
    r"(?<![a-z])(?:policy|insurance|insurer|insured|pmjay|pm-jay|ayushman|scheme|tpa|cghs|esic|echs|"
    r"health\s*card|member\s*id|beneficiary|card\s*no|ins\s*id|ins\s*no|बीमा|पॉलिसी|आयुष्मान)"
    r"[^0-9\n]{0,18}$"
)
_RE_ABHA_LABEL = re.compile(r"(?:abha|health\s*id|आभा)[^0-9\n]{0,15}$")


# a reference number shaped like a mobile: "Trip ID 98...", "package 98...", "LRN-98...", "SPL/26/98..."
_RE_REF_BEFORE = re.compile(
    r"(?<![a-z])(?:trip\s*(?:id|no)|token|package|pkg|lab\s*(?:ref|no|id)|ref(?:erence)?\.?\s*(?:no|id|#)?|bill(?:\s*no)?|"
    r"sample(?:\s*(?:id|no))?|claim(?:\s*no)?|cyto\s*no|barcode|accession|batch|lot|invoice|receipt|order|rs\.?|inr|₹|"
    r"booking(?:\s*(?:id|no|ref))?|appointment\s*(?:id|no)|ticket(?:\s*(?:id|no))?|serial(?:\s*no)?|cat(?:alogue)?\s*no|"
    r"helpline|help\s*line|toll[\s\-]*free|reception|enquiry|enquiries|front\s*desk|control\s*room|call\s+us\s+(?:at|on))"
    r"[\s:#.\-]*$")


# Indian vehicle registration plate: state code + RTO number + series + 4 digits ("MH-20-EF-4471", "DL 1V 5522")
_STATE_CODES = frozenset("""
AN AP AR AS BR CG CH DD DL DN GA GJ HP HR JH JK KA KL LA LD MH ML MN MP MZ NL OD OR PB PY RJ SK TG TN TR TS UK UP WB
""".split())
_RE_PLATE = re.compile(r"([A-Z]{2})[ \-]?[0-9]{1,2}[ \-]?[A-Z]{0,3}[ \-]?[0-9]{4}")
# a doctor's / facility's council registration: "MCh (Uro), Reg APMC/...", "DMC Reg DMC/R/..."
_RE_COUNCIL_REG = re.compile(
    r"(?:(?<![a-z])(?:mbbs|md|ms|dm|mch|m\.ch|dnb|frcs|mrcp|dgo|dch|doms|bds|mds|bams|bhms)(?![a-z])(?:(?! {2})[^\n\t]){0,40}|"
    r"(?<![a-z])(?:mci|nmc|smc|[a-z]{1,4}mc|medical\s+council|council)\s*)"
    r"(?:reg(?:istration|n|d)?\.?\s*(?:no\.?|number|#)?)[\s:#.\-]*$")


_RE_SERVICE_VEHICLE = re.compile(r"(?<![a-z])(?:ambulance|108|102|auto|autorickshaw|e-?rickshaw|toto|hearse|van|taxi|cab|bus|"
                                 r"tipper|truck|lorry|tractor|dumper|police|pcr|jeep|delivery|courier|vehicle)(?![a-z])")
_RE_OWN_VEHICLE = re.compile(r"(?<![a-z])(?:his|her|own|their|my|patient'?s|riding|driving|motorcycle|motor\s*cycle|bike|scooty|"
                             r"scooter|car)(?![a-z])")


def _plate(tok: str) -> bool:
    m = _RE_PLATE.fullmatch(tok)
    return bool(m) and m.group(1) in _STATE_CODES and bool(re.search(r"[0-9][ \-]?[A-Z]", tok[2:]))


def is_reference(t: str, tl: str, start: int, tok: str) -> bool:
    """One decision for every id / phone recogniser: is the number at `start` a reference number of an
    object, a document or the institution (vehicle plate, council registration, requisition / bag / film /
    post-mortem / pre-auth number) rather than the patient's own identifier?"""
    if _plate(tok):
        # a hired / service vehicle (ambulance, auto, hearse) is not the patient's; "his motorcycle no. ..." is
        lb = _line_before(tl, start, 40)
        return bool(_RE_SERVICE_VEHICLE.search(lb)) and not _RE_OWN_VEHICLE.search(lb)
    seg = _segment_before(tl, start, 40)
    if _RE_NON_PATIENT_LABEL.search(seg) and not _RE_PID_SEGMENT.search(tok):
        return True
    return bool(_RE_COUNCIL_REG.search(_line_before(tl, start, 80)))


def _phone_vetoed(t: str, tl: str, start: int) -> bool:
    if start >= 2 and t[start - 1] in "-/" and t[start - 2].isalnum():
        return True                    # glued to a letter / number prefix: part of a reference number
    return bool(_RE_REF_BEFORE.search(tl, max(0, start - 24), start))


# OCR wrap inside a number: "90031\n77462", "6620 1947\n3085"
_RE_PHONE_WRAP = re.compile(r"(?<![0-9A-Za-z+])[6-9][0-9]{4}[ \t]*\n[ \t]*[0-9]{5}(?![0-9A-Za-z])")
_RE_AADHAAR_WRAP = re.compile(_NB + r"[2-9][0-9]{3}[ \t\n\-]+[0-9]{4}[ \t]*\n[ \t]*[0-9]{4}" + _NA
                              + r"|" + _NB + r"[2-9][0-9]{3}[ \t]*\n[ \t]*[0-9]{4}[ \t\-]+[0-9]{4}" + _NA)
# landline: STD code 0NN / 0NNN / 0NNNN + subscriber number (total 11 digits with the 0)
_RE_LANDLINE = re.compile(
    r"(?<![0-9A-Za-z/\-])(?:\+91[ \-]?|0)(?:[1-9][0-9][ \-]?[2-9][0-9]{3}[ \-]?[0-9]{4}|[1-9][0-9]{2}[ \-]?[2-9][0-9]{2,3}[ \-]?[0-9]{3,4}"
    r"|[1-9][0-9]{3}[ \-]?[2-9][0-9]{5})(?![0-9A-Za-z]|[/\-][0-9])")
# partial Aadhaar spoken or written: "last four 7745", "Aadhaar ending 1234"
_RE_AADHAAR_LAST4 = re.compile(
    r"(?:aadhaa?r|aadhar|आधार|uid)[^0-9\n]{0,30}?(?:last|ending|ends?\s+(?:in|with)|अंतिम|आखिरी)[^0-9\n]{0,15}?"
    r"(?<![0-9])([0-9]{4})(?![0-9])"
    r"|(?:last|ending)\s+(?:four|4)\s+(?:digits?\s+)?(?:of\s+(?:my\s+|her\s+|his\s+)?aadhaa?r\s+)?(?:is\s+|are\s+)?(?<![0-9])([0-9]{4})(?![0-9])", re.I)


# a mobile read out in number words, possibly finished in digits: "nau-aath-ek-chhe-shunya, 43725"
_NUM_WORDS = {"shunya": "0", "shoonya": "0", "sunya": "0", "zero": "0", "ek": "1", "one": "1", "do": "2", "two": "2",
              "teen": "3", "tin": "3", "three": "3", "char": "4", "chaar": "4", "four": "4", "paanch": "5", "panch": "5",
              "five": "5", "chhe": "6", "chhah": "6", "che": "6", "six": "6", "saat": "7", "sat": "7", "seven": "7",
              "aath": "8", "ath": "8", "eight": "8", "nau": "9", "no": "9", "nine": "9"}
_NW = r"(?:" + "|".join(sorted(_NUM_WORDS, key=len, reverse=True)) + r")"
_RE_PHONE_WORDS = re.compile(r"(?<![A-Za-z])" + _NW + r"(?:[ \t]*[\-,][ \t]*|[ \t]+)(?:" + _NW +
                             r"(?:[ \t]*[\-,][ \t]*|[ \t]+))+(?:" + _NW + r"|[0-9]{1,8})(?![A-Za-z0-9])", re.I)


_RE_NUMWORD_HINT = re.compile(r"shunya|shoonya|sunya|zero|aath|chhe|paanch|saat|nine|eight|seven|teen|char")


def _spoken_digits(g: str) -> str:
    out = []
    for w in re.findall(r"[A-Za-z]+|[0-9]+", g):
        out.append(_NUM_WORDS.get(w.lower(), w if w.isdigit() else ""))
    return "".join(out)


def find_identifiers(text: str) -> List[Span]:
    """PHONE, AADHAAR, AADHAAR_MASKED, ABHA_NUMBER, ABHA_ADDRESS, EMAIL, PAN, INSURANCE_ID."""
    t = _to_ascii_digits(text)
    tl = t.lower()
    c: List[Tuple[int, int, int, str, str]] = []
    for m in _RE_ABHA_ADDR.finditer(t):
        c.append((0, m.start(), m.end(), "ABHA_ADDRESS", m.group().lower()))
    for m in _RE_EMAIL.finditer(t):
        c.append((1, m.start(), m.end(), "EMAIL", m.group().lower()))
    # insurance: known prefix tokens, or any id-ish token right after an insurance label
    for m in _RE_CODE.finditer(t):
        tok = m.group()
        first = re.match(r"[A-Za-z]+", tok).group().upper()
        if first in _INS_PREFIXES and len(_digits(tok)) >= 5 and not is_reference(t, tl, m.start(), tok):
            c.append((2, m.start(), m.end(), "INSURANCE_ID", norm_id(tok)))
    for m in _RE_ANY_TOKEN.finditer(t):
        tok = m.group()
        if len(_digits(tok)) < 5 or _looks_like_date(tok):
            continue
        if _RE_INS_LABEL.search(_segment_before(tl, m.start(), 40)):
            c.append((2, m.start(), m.end(), "INSURANCE_ID", norm_id(tok)))
    for m in _RE_ABHA_SEP.finditer(t):
        c.append((3, m.start(), m.end(), "ABHA_NUMBER", _digits(m.group())))
    for m in _RE_ABHA_SOLID.finditer(t):
        g = m.group()
        if g.startswith("91") or _RE_ABHA_LABEL.search(_segment_before(tl, m.start(), 30)):
            c.append((3, m.start(), m.end(), "ABHA_NUMBER", g))
    for m in _RE_AADHAAR_MASK.finditer(t):
        c.append((4, m.start(), m.end(), "AADHAAR_MASKED", m.group(1)))
    for m in _RE_AADHAAR_SPACED.finditer(t):
        c.append((5, m.start(), m.end(), "AADHAAR", _digits(m.group())))
    for m in _RE_AADHAAR_SOLID.finditer(t):
        g = m.group()
        # a 91-prefixed mobile is far likelier than an Aadhaar failing its checksum
        if g.startswith("91") and g[2] in "6789" and not verhoeff_ok(g):
            c.append((7, m.start(), m.end(), "PHONE", g[2:]))    # "919876543210": country code + mobile
            continue
        if _phone_vetoed(t, tl, m.start()) and not re.search(r"aadhaa?r|aadhar|uid|आधार", _segment_before(tl, m.start(), 30)):
            continue                      # "Lab Ref 2508...": a 12-digit accession number
        c.append((5, m.start(), m.end(), "AADHAAR", g))
    for m in _RE_PAN.finditer(t):
        c.append((6, m.start(), m.end(), "PAN", m.group().upper()))
    for rx in (_RE_PHONE_INTL, _RE_PHONE_STD):
        for m in rx.finditer(t):
            d = _digits(m.group())
            if 9 <= len(d) <= 14 and not _phone_vetoed(t, tl, m.start()):
                c.append((7, m.start(), m.end(), "PHONE", d))
    for rx in (_RE_PHONE_PLUS, _RE_PHONE, _RE_PHONE_PAREN, _RE_PHONE_WRAP):
        for m in rx.finditer(t):
            p = norm_phone(m.group())
            if p and not _phone_vetoed(t, tl, m.start()):
                c.append((7, m.start(), m.end(), "PHONE", p))
    for m in (_RE_PHONE_WORDS.finditer(t) if _RE_NUMWORD_HINT.search(tl) else ()):
        d = _spoken_digits(m.group())
        words = len(re.findall(r"[A-Za-z]+", m.group()))
        if len(d) == 10 and d[0] in "6789" and words >= 4:
            c.append((7, m.start(), m.end(), "PHONE", d))
    for m in _RE_LANDLINE.finditer(t):
        if not _phone_vetoed(t, tl, m.start()):
            c.append((8, m.start(), m.end(), "PHONE", _digits(m.group())))
    for m in _RE_AADHAAR_WRAP.finditer(t):
        c.append((5, m.start(), m.end(), "AADHAAR", _digits(m.group())))
    for m in _RE_AADHAAR_LAST4.finditer(t):
        g = 1 if m.group(1) else 2
        c.append((4, m.start(g), m.end(g), "AADHAAR_MASKED", m.group(g)))
    return _resolve(c)


def _looks_like_date(tok: str) -> bool:
    return bool(re.fullmatch(r"[0-9]{1,4}[\-/.][0-9]{1,2}[\-/.][0-9]{1,4}(?:T.*)?", tok)
                or re.fullmatch(r"(?:19|20)[0-9]{6}", tok))


# ---------------------------------------------------------------- patient ids (MRN)

_NON_PATIENT_PREFIXES = frozenset("""
BL BILL BLL INV INVC INVOICE RCPT RCP RCT REC RECEIPT SMP SAM SAMP SAMPLE SPL SPEC SPECIMEN VIS VST
VISIT PKG PKGE PACK PACKAGE TXN TRN TRX ORD ORDER TKN TOKEN CLM CLAIM VCH VOUCHER ACC ACCN AMB HD TKT
TICKET LAB LB BAR BC REF PAY PMT CHQ UTR GST GSTIN BATCH LOT ICD LOINC SNOMED BB DDSSY PMNDP
""".split())
_RE_NON_PATIENT_LABEL = re.compile(
    r"(?<![a-z])(?:bill|invoice|inv|receipt|rcpt|sample|specimen|visit|package|pkg|txn|transaction|"
    r"order|token|barcode|claim|voucher|accession|ticket|batch|lot|payment|बिल|रसीद|नमूना|"
    r"lab\s*(?:no|ref|id|number|#|accession)|(?<!patient )(?<!pt )ref(?:erence)?\.?\s*(?:no|number|#)|cyto(?:logy)?\s*no|"
    r"trip\s*(?:id|no)|mlc|mlr|ml\s*no|certificate|cert|film|slide|room|ext|extn|"
    r"pre-?\s*auth(?:ori[sz]ation)?|approval|rejection|letter|fir|gd|session|consultation|"
    r"(?<!patient )(?<!pt )ref(?:erence)?\.?\s*[:#]|call\s*ref|complaint|vehicle|ambulance|utr|bag|"
    r"req(?:uisition)?\.?\s*(?:no|id|#)|donor(?:\s*card)?|unit\s*no|crossmatch|cross-match|issue\s*no|"
    r"x-?ray(?:\s*no)?|scan\s*no|ct\s*no|mri\s*no|usg\s*no|mortuary|post-?\s*mortem|pm\s*no|inquest|panchnama|"
    r"marg|dd\s*(?:entry|no)|serial|catalog(?:ue)?|cat\s*no|booking|appointment\s*(?:id|no)|hearse|"
    r"एक्स-रे(?:\s*सं\.?)?|फिल्म)(?![a-z])"
)
_RE_PATIENT_LABEL = re.compile(
    r"(?<![a-z])(?:uhid|mrn|mr\s*no|cr\s*no|hosp(?:ital)?[\s_]*(?:no|id|uhid)|patient[\s_]*(?:id|no|ref)|"
    r"pt[\s_]*id|reg(?:istration|n|d)?\.?[\s_]*(?:no|number|id|#)?|ipd?[\s_]*(?:no|number|id)?|opd[\s_]*(?:no|number|id|reg)?|"
    r"adm(?:ission)?[\s_]*(?:no|number|id)?|inpatient[\s_]*(?:no|id)?|case[\s_]*(?:no|id)|"
    r"rch[\s_]*(?:id|no|number)?|mcts[\s_]*(?:id|no|number)?|ni-?kshay[\s_]*(?:id|no|number)?|"
    r"(?:mother|child|beneficiary|member)[\s_]*(?:id|no)|tb[\s_]*(?:no|number|id)|pid|samagra[\s_]*(?:id|no)?|"
    r"mcp[\s_]*card[\s_]*(?:no|id)?|"
    r"पंजीकरण\s*सं\.?|पंजीयन\s*सं\.?|आईपीडी\s*सं\.?|यूएचआईडी|भर्ती\s*सं\.?|रजि\.?\s*नं\.?)"
    r"[\s\"':#.\-=]*$"
)
_RE_HEXISH = re.compile(r"[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-|[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}")
_RE_BLOB = re.compile(
    r"[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}"   # uuid
    r"|(?<![A-Za-z0-9+/])[A-Za-z0-9+/]{40,}={0,2}"                                   # base64 / hash
    r"|(?:https?://|www\.)[^\s\"'<>]+"                                                # url
    r"|(?<![A-Za-z0-9])[A-Za-z0-9\-]+(?:\.[A-Za-z0-9\-]+)*\.(?:org|com|net|gov|io|in|nic|int)/[^\s\"'<>]*"
)
_RE_DIGIT_TOKEN = re.compile(r"(?<![0-9A-Za-z/.\-])[0-9]{5,14}(?![0-9A-Za-z]|[/.\-][0-9])")


_UNDERSCORE_WORDS = frozenset("""
report reports visit visits opd ipd export exports result results summary summaries note notes bundle bundles
claim claims forward forwarded file files page pages month year data dump backup list sheet log logs scan scans
copy draft final batch upload download index records record discharge lab labs bill bills
""".split())
_RE_UNDERSCORE_ID = re.compile(r"[A-Za-z]{2,10}_[0-9][0-9A-Za-z\-/]*|[A-Za-z]{2,10}_[A-Za-z]{1,4}[0-9]{4,}")


def _underscore_id(tok: str) -> bool:
    """'_' joins a letter prefix and digits of one identifier ("UHID_010610"), not ordinary words."""
    if not _RE_UNDERSCORE_ID.fullmatch(tok):
        return False
    lead = tok.split("_", 1)[0].lower()
    return lead not in _UNDERSCORE_WORDS


_RE_FILE_EXT = re.compile(r"\.(?:txt|csv|tsv|json|pdf|xml|html?|log|md|docx?|xlsx?|jpe?g|png)$", re.I)


# an OP / IP / UHID segment inside the id itself marks a patient number whatever label precedes it
_RE_PID_SEGMENT = re.compile(r"(?:^|[/\-])(?:OP|IP|OPD|IPD|UHID|MRN|MRD)(?:[/\-])", re.I)
# a patient / mother-child tracking number written in spaced digit groups: "MCTS 32 045 0091 7745 2"
_RE_SPACED_PID = re.compile(r"(?<![A-Za-z])(?:MCTS|RCH|UHID|MRN|MRD|CR[ \t]*No\.?|IP[ \t]*No\.?|Reg(?:n|d)?\.?[ \t]*No\.?)"
                            r"[ \t]*[:#\-]?[ \t]*([0-9]{2,6}(?:[ ][0-9]{1,6}){2,5})(?![0-9A-Za-z])", re.I)


def find_patient_ids(text: str, after_label_only: bool = False) -> List[Span]:
    """Hospital / registration / admission numbers (kind MRN), value = norm_id."""
    t = _to_ascii_digits(text)
    tl = t.lower()
    out: List[Tuple[int, int, int, str, str]] = []
    blobs = [(u.start(), u.end()) for u in _RE_BLOB.finditer(t)]
    toks: List[Tuple[int, int, str]] = []
    for m in _RE_CODE.finditer(t):
        tok = m.group()
        if "_" in tok and not _underscore_id(tok):
            # file-name-like run ("report_00005", "visits_2026_02"): judge each piece alone
            pos = m.start()
            prev = ""
            for piece in tok.split("_"):
                if piece and _RE_CODE.fullmatch(piece):
                    toks.append((pos, pos + len(piece), piece))
                elif (re.fullmatch(r"[0-9]{5,14}", piece) and re.fullmatch(r"[A-Za-z]{2,}", prev)
                      and prev.lower() not in _UNDERSCORE_WORDS and not _looks_like_date(piece)):
                    # "<Name>_<digits>" folder of an export: the digits are the patient's number
                    out.append((1, pos, pos + len(piece), "MRN", piece))
                prev = piece
                pos += len(piece) + 1
            continue
        toks.append((m.start(), m.end(), tok))
    blob_iv = Intervals(blobs)
    for ms, me, tok in toks:
        ext = _RE_FILE_EXT.search(tok)
        if ext:                                   # "P.00454.txt": the extension is not part of the id
            tok = tok[:ext.start()]
            me = ms + len(tok)
        if len(_digits(tok)) < 5:
            continue
        if tok.count("/") >= 3 and re.search(r"/[0-9]{1,3}[MFmf]/", tok):
            continue                              # slash-packed header line: judged field by field
        if blob_iv.hits(ms, me):
            continue
        lead = re.match(r"[A-Za-z]+", tok).group()
        if len(lead) < 2 and not (len(tok) > 2 and tok[1] in ".-/#" and tok[2].isdigit()):
            continue                                                 # "P.00432" / "P-00432" pass
        first = lead.upper()
        if first in _NON_PATIENT_PREFIXES or first in _INS_PREFIXES:
            continue
        if re.fullmatch(r"[A-Za-z]{5}[0-9]{4}[A-Za-z]", tok):      # PAN
            continue
        if _RE_HEXISH.search(tok) or (len(tok) > 24 and not re.search(r"[\-/._]", tok)):
            continue                                                 # uuid / hash / base64 run
        seg = _segment_before(tl, ms, 40)
        if is_reference(t, tl, ms, tok):
            continue
        if re.match(r"(?:mob|mobile|ph|phone|tel|cell|call|contact)$", lead, re.I):
            continue
        labelled = bool(_RE_PATIENT_LABEL.search(seg)) or bool(
            re.match(r"(?:uhid|mrn|reg|ipd|ip|adm|crno|hosp)", lead, re.I))
        if after_label_only and not labelled:
            continue
        out.append((0, ms, me, "MRN", norm_id(tok)))
    for m in _RE_SPACED_PID.finditer(t):
        if len(_digits(m.group(1))) >= 8:
            out.append((0, m.start(1), m.end(1), "MRN", _digits(m.group(1))))
    # bare digit numbers right after an explicit patient-id label
    for m in _RE_DIGIT_TOKEN.finditer(t):
        seg = _segment_before(tl, m.start(), 40)
        if _RE_PATIENT_LABEL.search(seg) and not _RE_NON_PATIENT_LABEL.search(seg):
            out.append((1, m.start(), m.end(), "MRN", m.group()))
    return _resolve(out)


# ---------------------------------------------------------------- PIN codes

# address cues in every script: native village / address / district labels arrive folded onto Devanagari
_FOLDED_ADDR_CUES = tuple(w for w, c in scripts.LABEL_ALIAS.items() if c in ("ग्राम", "पता", "जिला"))
_ADDR_CUE_RX = re.compile(
    r"(?<![a-z\u0900-\u097f])(?:" + "|".join(
        re.escape(c) for c in sorted(set(lexicon.ADDRESS_CUES) | set(_FOLDED_ADDR_CUES), key=len, reverse=True)
        if len(c) >= 3
    ) + r")(?![a-z])"
)
_RE_PIN = re.compile(r"(?<![0-9A-Za-z.,/:\-])[1-9][0-9]{5}(?![0-9A-Za-z]|[.,/:][0-9]|-[0-9A-Za-z])")
_RE_TOWN_BEFORE = re.compile(r",[ \t]*(?:[A-Z][a-z]+[ \t]+)?([A-Z][a-z]{2,})[ \t]*[\-,]?[ \t]*$")
_RE_PIN_SPACED = re.compile(r"(?<![0-9A-Za-z])[1-9][0-9]{2} [0-9]{3}(?![0-9A-Za-z])")
_RE_UNIT_AFTER = re.compile(r"\s*(?:/|per\b|cells|lakh|mg|ml|iu|u/l|units?|rs|inr|₹|%|x\s*10)", re.I)
_RE_MONEY_BEFORE = re.compile(r"(?:rs\.?|inr|₹|amount|amt|total|paid|fee|charges?|cost|price|count|wbc|platelets?)[\s:=]*$", re.I)


def find_pins(text: str) -> List[Span]:
    """6-digit PIN codes after an address cue, a PIN label, or an address-line dash."""
    t = _to_ascii_digits(text)
    tl = scripts.fold(t).lower()      # same length: native-script cues (கிராமம், ਪਿੰਡ, ગામ) read as Devanagari
    out: List[Span] = []
    for rx in (_RE_PIN, _RE_PIN_SPACED):
        for m in rx.finditer(t):
            s, e = m.start(), m.end()
            if _RE_UNIT_AFTER.match(t, e):
                continue
            before = _line_before(tl, s, 120)
            if _RE_MONEY_BEFORE.search(before):
                continue
            ok = bool(re.search(r"(?:pin|pincode|pin\s*code|zip|पिन|पिनकोड)[\s\"':#.\-=]*$", before))
            if not ok and re.search(r"[\-\u2013]\s*$", before) and _ADDR_CUE_RX.search(before):
                ok = True
            if not ok and _ADDR_CUE_RX.search(before):
                ok = True
            if not ok:
                tm = _RE_TOWN_BEFORE.search(t, max(0, s - 60), s)
                if tm and tm.group(1).lower() not in lexicon.CLINICAL_WORDS:
                    ok = True                 # "..., Vallabh Nagar, Anand 388120": a PIN closing an address
            if ok:
                out.append(Span(s, e, "PIN", _digits(m.group())))
    out.sort(key=lambda sp: (sp.start, sp.end))
    dedup: List[Span] = []
    for sp in out:
        if dedup and sp.start < dedup[-1].end:
            continue
        dedup.append(sp)
    return dedup


# ---------------------------------------------------------------- protected clinical spans

_DEVA_WORD = r"[\u0900-\u097F]+"
_LAT_NAME = r"(?:[A-Z][A-Za-z'\-]*\.?|[A-Z]\.)"
_QUAL = r"(?:\s*\((?:[^()\n]{1,40})\))?"
_RE_DOCTOR = re.compile(
    r"(?<![A-Za-z])(?:Dr|DR|dr|Doctor|DOCTOR)\.?\s*(?:" + _LAT_NAME + r"(?:[ \t]+" + _LAT_NAME + r"){0,3})" + _QUAL
    + r"|(?:(?:" + "|".join(re.escape(w) for w in scripts.DOCTOR_PREFIXES) + r")(?:[\.ः][ \t]*|[ \t]+)|(?:डॉक्टर|डॉ|डाॅ|डा)(?:\.\s*|\s+))" + _DEVA_WORD + r"(?:[ \t]+" + _DEVA_WORD + r"){0,2}" + _QUAL
)

_UNITS = (r"(?:mg/dl|mg/dL|g/dl|g/dL|mmol/l|mmol/L|meq/l|mEq/L|iu/l|IU/L|u/l|U/L|ng/ml|ng/mL|pg/ml|pg/mL|"
          r"µiu/ml|uIU/mL|µIU/mL|/uL|/ul|/µL|/cumm|/mm3|cells/cumm|/hpf|lakh(?:s)?(?:/cumm)?|x\s*10\^?\d+/[uµ]?L|"
          r"mmHg|mm\s*Hg|fl|fL|pg|sec|%|mm/hr|mm/1st\s*hr|gm/dl|gm%|g%|ml/min|/min|bpm|cc|"
          r"ग्राम[ \t]*/[ \t]*डी\.?[ \t]*एल\.?|ग्रा\.?[ \t]*/[ \t]*डी\.?[ \t]*एल\.?|ग्राम[ \t]*प्रतिशत|ग्राम%|"
          r"मि\.?[ \t]*ग्रा\.?(?:[ \t]*/[ \t]*डी\.?[ \t]*एल\.?)?|मिग्रा|मि\.?[ \t]*ली\.?|मिली|मिमी[ \t]*पारा|प्रति[ \t]*मिनट)")
_DOSE_UNITS = r"(?:mg|mcg|µg|ug|gm|g|ml|mL|iu|IU|units?|U|meq|mEq|mmol|%|puffs?|drops?|tabs?|caps?)"
_FORMS = r"(?:tab|tabs|tablet|cap|caps|capsule|inj|injection|syp|syr|syrup|susp|oint|cream|gel|drops?|neb|inh|sachet|lotion|iv|im)"
_RE_DOSE = re.compile(
    r"(?<![A-Za-z])" + _FORMS + r"\.?\s+[A-Za-z][A-Za-z\-]*(?:[ \t+/]+[A-Za-z][A-Za-z\-]*){0,2}"
    r"(?:[ \t]*[0-9]+(?:\.[0-9]+)?(?:/[0-9]+(?:\.[0-9]+)?)?[ \t]*" + _DOSE_UNITS + r"?)?(?![A-Za-z])"
    r"|(?<![0-9A-Za-z.])[0-9]+(?:\.[0-9]+)?(?:/[0-9]+(?:\.[0-9]+)?)?[ \t]*" + _DOSE_UNITS + r"(?![A-Za-z/])",
    re.I,
)
_RE_DRUG_NUM = re.compile(r"(?<![A-Za-z])([A-Za-z][A-Za-z\-]{2,})[ \t]+([0-9]{2,4}(?:\.[0-9]+)?)(?![0-9])")
_NOT_DRUG = frozenset("""
ward bed room age opd ipd icu ot patient attendant hospital clinic medicine surgery general day days week weeks
month months year years yrs hrs hours min mins unit units no case history stage grade type gram
""".split())
_FREQW = r"(?:OD|BD|BID|TDS|TID|QID|QDS|HS|SOS|STAT|QHS|PRN|AC|PC|OW|QW|daily|once|twice|thrice)"
_DUR = r"(?:days?|d|wks?|weeks?|months?|mths?|mo|yrs?|years?|hrs?|hours?|din|दिन|हफ्ते|महीने)"
_RE_FREQ = re.compile(
    r"(?<![0-9A-Za-z\-])[0-2](?:\.5|½)?-[0-2](?:\.5|½)?-[0-2](?:\.5|½)?(?:-[0-2](?:\.5|½)?)?(?![0-9\-])"
    r"(?:[ \t]*(?:[x×*]|for)[ \t]*[0-9]+[ \t]*" + _DUR + r"\b)?"
    r"|(?<![A-Za-z0-9\-])" + _FREQW + r"(?![A-Za-z0-9\-])(?:[ \t]*(?:[x×*]|for)[ \t]*[0-9]+[ \t]*" + _DUR + r"(?![A-Za-z]))?"
    r"|(?<![A-Za-z0-9])(?:[x×*]|for)[ \t]*[0-9]+[ \t]*" + _DUR + r"(?![A-Za-z])",
    re.I,
)
_RE_VITAL = re.compile(
    r"(?<![A-Za-z])(?:BP|B\.P\.?|blood\s+pressure|रक्तचाप)[\s:=\-]*(?:was\s+|is\s+)?[0-9]{2,3}\s*/\s*[0-9]{2,3}(?:\s*mm\s*Hg)?"
    r"|(?<![0-9/])[0-9]{2,3}\s*/\s*[0-9]{2,3}\s*mm\s*Hg"
    r"|(?<![A-Za-z])(?:pulse|PR|HR|heart\s+rate|RR|resp(?:iratory)?\s*rate|नाड़ी|नब्ज)[\s:=\-]*[0-9]{2,3}(?:\s*/\s*min|\s*bpm)?"
    r"|(?<![A-Za-z])(?:temp(?:erature)?|T|bukhar|bukhaar|fever|बुखार|तापमान)[\s:=\-]*[0-9]{2,3}(?:\.[0-9])?\s*°?\s*[FC]?(?![A-Za-z])"
    r"|(?<![0-9.])[0-9]{2,3}(?:\.[0-9])?\s*°\s*[FC]?(?![A-Za-z])|(?<![0-9.])(?:9[5-9]|10[0-7])(?:\.[0-9])?\s?(?:F|°F)(?![A-Za-z])"
    r"|(?<![A-Za-z])(?:SpO2|SPO2|spo2|O2\s*sat|sat(?:uration)?|SaO2)[\s:=\-]*[0-9]{2,3}\s*%?"
    r"|(?<![A-Za-z])(?:weight|wt|height|ht|BMI|GCS|RBS|FBS|PPBS|CBG|GRBS)[\s:=\-]*[0-9]{1,3}(?:\.[0-9]+)?\s*(?:kg|cm|kg/m2|mg/dl|mg/dL)?",
    re.I,
)
_LAB_NAMES = (
    "haemoglobin", "hemoglobin", "hb", "hgb", "hba1c", "total wbc count", "wbc count", "total wbc", "wbc", "tlc",
    "total leucocyte count", "platelet count", "platelets", "platelet", "rbc", "pcv", "hct", "esr", "crp",
    "random blood sugar", "fasting blood sugar", "blood sugar", "rbs", "fbs", "ppbs", "blood urea", "urea",
    "serum creatinine", "creatinine", "serum sodium", "sodium", "serum potassium", "potassium", "chloride",
    "total bilirubin", "bilirubin", "sgot", "sgpt", "ast", "alt", "alp", "albumin", "tsh", "t3", "t4",
    "cholesterol", "triglycerides", "hdl", "ldl", "uric acid", "mcv", "mch", "mchc", "inr", "neutrophils",
    "lymphocytes", "eosinophils", "monocytes", "ns1", "s. creatinine", "s.creatinine",
)
_RE_LAB = re.compile(
    r"(?<![A-Za-z])(?:" + "|".join(re.escape(n) for n in sorted(_LAB_NAMES, key=len, reverse=True)) + r")"
    r"(?![A-Za-z])[ \t:=\-]*(?:\(?[A-Za-z/%]{0,8}\)?[ \t]*)?[<>≤≥]?[ \t]*[0-9]+(?:\.[0-9]+)?(?:[ \t]*" + _UNITS + r"(?![A-Za-z]))?"
    r"|(?<![0-9A-Za-z.])[0-9]+(?:\.[0-9]+)?[ \t]*" + _UNITS + r"(?![A-Za-z])",
    re.I,
)
_RE_RANGE = re.compile(r"(?<![0-9A-Za-z.\-/])([0-9]+(?:\.[0-9]+)?)\s*[\-\u2013]\s*([0-9]+(?:\.[0-9]+)?)(?![0-9\-/])")
_RE_WARD = re.compile(
    r"(?<![A-Za-z])(?:ward|वार्ड)(?:\s*/\s*bed)?\s*(?:no\.?|number|सं\.?|नं\.?)?\s*[:#\-]?\s*"
    r"(?:ward\s*)?[0-9]+[A-Z]?(?:\s*\([^()\n]{1,30}\))?"
    r"(?:\s*[,/\-]?\s*(?:bed|बेड|बिस्तर)\s*(?:no\.?|number)?\s*[:#\-]?\s*[0-9]+[A-Z]?)?"
    r"|(?<![A-Za-z])(?:bed|बेड|बिस्तर)\s*(?:no\.?|number)?\s*[:#\-]?\s*[0-9]+[A-Z]?",
    re.I,
)
_RE_WARD_ADDR_CTX = re.compile(
    r"(?<![a-z])(?:h\.?\s*no|house|makan|mohalla|near|opp|gram|vill|village|address|addr|pata|tehsil|distt|"
    r"street|colony|nagar|mकान|मकान|मोहल्ला|ग्राम|पता|गांव)(?![a-z])|c/o\s+[A-Z][a-z]+|c/o\s+[\u0900-\u097F]",
    re.I,
)
_EPON_TAIL = (r"(?:disease|syndrome|palsy|sign|test|phenomenon|tumou?r|ulcer|fracture|reflex|law|operation|"
              r"procedure|anomaly|triad|criteria|scale|score|lymphoma|sarcoma|disorder|encephalopathy|"
              r"thyroiditis|chorea|anaemia|anemia|contracture|cyst|node|nodes|angina|aneurysm|manoeuvre|maneuver|"
              r"position|method|classification|stage|staging|neuralgia|block|incision|repair|nuclei|cells?|catheter|tube|"
              r"grade|type|category|features|body|bodies|space|line|ward)")
_RE_EPONYM = re.compile(
    r"(?<![A-Za-z])[A-Za-z][a-z]+(?:[\-\s][A-Z][a-z]+)?(?:'s|’s|s'|’)\s+" + _EPON_TAIL + r"(?![A-Za-z])"
    r"|(?<![A-Za-z])(?:Down|Hodgkin|Non-Hodgkin|Guillain[\- ]Barr[eé]|Glasgow\s+Coma|Wilms|Kawasaki|Hashimoto|"
    r"Graves|Cushing|Addison|Parkinson|Alzheimer|Crohn|Bell|Raynaud|Marfan|Turner|Klinefelter|Hirschsprung|"
    r"Sjogren|Sjögren|Behcet|Kaposi|Burkitt|Ewing|Huntington|Tourette|Wilson|Meniere|Paget|Peyronie|"
    r"Dupuytren|Colles|Pott|Stevens[\- ]Johnson|Reiter|Kussmaul|Cheyne[\- ]Stokes|Apgar|Glasgow|Widal|Mantoux|"
    r"Gram|Ziehl[\- ]Neelsen|Pfannenstiel|Whipple|Fallot)(?:'s|’s)?\s+" + _EPON_TAIL + r"?",
    re.I,
)
# named grades, scores, devices and descriptors that look like person names
_RE_EPONYM2 = re.compile(
    r"(?<![A-Za-z])(?:Forrest\s+I{1,3}[abc]?|Orphan\s+Annie(?:\s+(?:eye\s+)?nuclei)?|H[uü]rthle(?:\s+cells?)?|"
    r"Reed[\- ]Sternberg(?:\s+cells?)?|Bethesda(?:\s+(?:category|class|system))?|Nottingham(?:\s+grade)?|"
    r"Bloom[\- ]Richardson(?:\s+(?:score|grade))?|Sengstaken[\- ]Blakemore(?:\s+tube)?|Swan[\- ]Ganz(?:\s+catheter)?|"
    r"Ranson(?:'s)?(?:\s+(?:score|criteria))?|Balthazar(?:\s+(?:grade|score))?|Karnofsky(?:\s+score)?|"
    r"McBurney(?:'s)?(?:\s+(?:point|incision))?|Foley(?:'s)?(?:\s+catheter)?|Ryle(?:'s)?(?:\s+tube)?|"
    r"Murray\s+score|Weil(?:'s)?\s+disease|Child[\- ]Pugh|Mallampati|Killip|Gleason|Breslow|Clark(?:'s)?\s+level)"
    r"(?![A-Za-z])")
# government schemes and programmes named after people or ordinary words
_RE_SCHEME = re.compile(
    r"(?<![A-Za-z])(?:(?:[A-Z][a-z]+[ \t]+){0,3}(?:Yojana|Yojna|Abhiyan|Abhiyaan)|(?:[A-Z][a-z]+[ \t]+){1,2}(?:Vahan|Vahini|Vahika)|Mission[ \t]+[A-Z][a-z]+(?:[ \t]+[A-Z][a-z]+)?|"
    r"Ayushman[ \t]+Bharat(?:[ \t]+[A-Z][A-Za-z\-]+)?|Janani[ \t]+Suraksha|Nikshay(?:[ \t]+Poshan)?)(?![A-Za-z])"
    r"|(?:[ऀ-ॿ]+[ \t]+){0,3}(?:योजना|अभियान)(?![ऀ-ॿ])|(?:आयुष्मान[ \t]+भारत|निक्षय|महात्मा[ \t]+फुले)(?:[ \t]+[ऀ-ॿ]+){0,3}")
_RE_ASHA = re.compile(
    r"(?<![A-Za-z])ASHA(?:\s+(?:workers|worker|didi|sahayogini|sahyogini|karyakarta|facilitator|bahu|behenji|kendra))?(?![A-Za-z])"
    r"(?!\s+[A-Z][a-z])|(?<![A-Za-z])asha\s+(?:workers|worker|didi|sahayogini|sahyogini|karyakarta|facilitator|bahu|behenji)(?![A-Za-z])"
    r"|आशा\s+(?:कार्यकर्ता|दीदी|बहू|सहयोगिनी)",
    re.I,
)
_RE_HIST_MARK = re.compile(
    r"(?<![A-Za-z/])(?:k/c/o|kco|h/o|c/o|known\s+case\s+of|history\s+of|complain(?:s|ts|ing)?\s+of|"
    r"p/h/o|f/h/o|पुराना|शिकायत)(?![A-Za-z/])",
    re.I,
)
_RE_HIST_END = re.compile(r"(?:\.(?![0-9])|[;\n\r\t|,\"।]|\s+(?:mob|mobile|ph|phone|contact|tel)\b|$)", re.I)


# ---- institutions, programmes, designations, roads: never a person or a residence
_INST_TAIL = (r"(?:Memorial(?:[ \t]+(?:Hospital|Trust|Clinic|Institute|Medical[ \t]+College))?|Nursing[ \t]+Home|Pharmacy|"
              r"Medical[ \t]+Store|Medical[ \t]+Hall|Medicals|Chemists?|Druggists?|Diagnostics|Diagnostic[ \t]+Cent(?:re|er)|"
              r"Path(?:ology)?[ \t]+Lab(?:s)?|Polyclinic|Medical[ \t]+College(?:[ \t]+(?:&|and)[ \t]+Hospital)?|"
              r"Hospital|Clinic|Police[ \t]+Station|Thana|Eye[ \t]+Hospital|Heart[ \t]+Institute|Cancer[ \t]+Institute)")
_RE_INST = re.compile(
    r"(?<![A-Za-z])(?:(?:Sir|Saint|St\.?|Shri|Sri|Smt\.?|Late|Dr\.?|Al|El)[ \t]+)?"
    r"(?:[A-Z][A-Za-z'’\-]+[ \t]){1,3}" + _INST_TAIL + r"(?![A-Za-z])(?![ \t]*(?:[:#]|No\b|no\b|Reg|ID\b|Id\b))")
_RE_HI_INST2 = re.compile(r"(?<![ऀ-ॿ])(?:[ऀ-ॿ]+[ \t]+){1,3}(?:मेडिकल[ \t]+कॉलेज|मेमोरियल|स्मारक|चिकित्सालय|नर्सिंग[ \t]+होम)(?![ऀ-ॿ])")
_RE_PROGRAMME = re.compile(
    r"(?<![A-Za-z\-])(?:JSY|JSSK|PMSMA|RBSK|RKSK|NTEP|RNTCP|NHM|NRHM|NUHM|PMMVY|PM-?JAY|AB-?PMJAY|CMCHIS|MJPJAY|RSBY|"
    r"NPCDCS|NVBDCP|NLEP|NPCB|NACO|ICDS|IMNCI|HBNC|HBYC|SNCU|DEIC|PMNDP|NIDDCP|IDSP|NPHCE|NMHP|UIP|PCPNDT|"
    r"MMJAY|BSKY|DDSSY|SAST|KASP|YSR)(?![A-Za-z\-])"
    r"|(?<![A-Za-z])(?:National|Pradhan[ \t]+Mantri|Mukhya[ \t]+?Mantri|Mukhyamantri|Rashtriya|Intensified)"
    r"(?:[ \t]+[A-Z][a-z]+){0,4}?[ \t]+(?:Day|Programme|Program|Mission|Week|Fortnight|Campaign|Scheme|Abhiyan|Yojana|Karyakram)(?![A-Za-z])"
    r"|(?<![A-Za-z])(?:Mission[ \t]+Indradhanush|Pulse[ \t]+Polio|Nikshay[ \t]+Poshan(?:[ \t]+Yojana)?|Ayushman[ \t]+Bharat|"
    r"Aarogyasri|Arogyasri|Swasthya[ \t]+Sathi|Biju[ \t]+Swasthya[ \t]+Kalyan|Janani[ \t]+Shishu[ \t]+Suraksha|Kayakalp|LaQshya|"
    r"Poshan[ \t]+Abhiyaan|(?:Mamata|Rajshri|Kanyashree|Ladli|Mamta)[ \t]+(?:scheme|Scheme|Yojana|yojana))(?![A-Za-z])")
_RE_DESIG = re.compile(
    r"(?<![A-Za-z])(?:(?:Senior|Junior|Chief|Sr\.?|Jr\.?|Staff|Dialysis|Lab(?:oratory)?|OT|X-?[Rr]ay|Radiology|ECG|Pharmacy|"
    r"Blood[ \t]+Bank|Anaesthesia|Anesthesia|Perfusion|Physiotherapy|Ward|Nursing)[ \t]+)?"
    r"(?:Technician|Technologist|Nursing[ \t]+Officer|Staff[ \t]+Nurse|Matron|Ward[ \t]+[Bb]oy|Attendant|Pharmacist|Dresser|"
    r"Physiotherapist|Counsellor|Dietician|Dietitian|Orderly)"
    r"(?:[ \t]+Gr(?:ade)?\.?[ \t\-]*(?:I{1,3}|IV|[1-4]|A|B))?(?![A-Za-z])")
_KEEP_SHIELDS = ()  # filled below: (shield, cheap hint that must occur first)
_RE_ROAD_NO = re.compile(r"(?<![A-Za-z])(?:NH|SH|MDR|ODR)[ \t\-]?[0-9]{1,3}[A-Z]?(?![0-9A-Za-z])")


_KEEP_SHIELDS = (
    (_RE_INST, re.compile(r"Memorial|Nursing|Pharmacy|Medical|Chemist|Druggist|Diagnostic|Path|Polyclinic|Hospital|Clinic|"
                          r"Police|Thana|Institute")),
    (_RE_HI_INST2, re.compile(r"मेडिकल|मेमोरियल|स्मारक|चिकित्सालय|नर्सिंग")),
    (_RE_PROGRAMME, re.compile(r"[A-Z]{2,}|National|Mantri|Rashtriya|Intensified|Mission|Pulse|Nikshay|Ayushman|"
                               r"rogyasri|Swasthya|Janani|Kayakalp|LaQshya|Poshan|cheme|ojana")),
    (_RE_DESIG, re.compile(r"Technic|Technol|Nursing|Nurse|Matron|Ward|Attendant|Pharmacist|Dresser|Physio|Counsel|Diet|Orderly")),
    (_RE_ROAD_NO, re.compile(r"NH|SH|MDR|ODR")),
)


# ---- generalised eponym shield: "<Name> [<Name>] <scale / score / prosthesis / ...>"
EPONYMS = frozenset(w.lower() for w in """
Apgar Glasgow Barthel Berg Ashworth Braden Morse Norton Waterlow Ramsay Richmond Mallampati Child-Pugh Child Pugh
Ranson Wells Framingham Lake-Louise Louise Bishop Ballard Silverman Downes Tanner Gleason Breslow Clark Dukes
Ann-Arbor Arbor Bethesda Bosniak Fisher Hunt-Hess Hunt Hess Killip Kellgren-Lawrence Kellgren Lawrence Garden
Gartland Salter-Harris Salter Harris Neer Schatzker Gustilo Anderson Austin-Moore Moore Thompson Kirschner Steinmann
Ilizarov Thomas Denis-Browne Browne Foley Ryle Swan-Ganz Sengstaken Blakemore Hickman Seldinger Heimlich Valsalva
Trendelenburg Fowler Sims McBurney Pfannenstiel Kocher Whipple Hartmann Billroth Roux Nissen Heller Lichtenstein
Shouldice Bassini Burch Wertheim Bartholin Papanicolaou Ziehl-Neelsen Ziehl Neelsen Mantoux Widal Weil-Felix Weil
Felix Coombs Romberg Babinski Kernig Brudzinski Murphy Rovsing Homans Tinel Phalen Lachman McMurray Trousseau
Chvostek Cushing Addison Graves Hashimoto Crohn Hodgkin Non-Hodgkin Parkinson Alzheimer Bell Down Turner Marfan
Kawasaki Guillain-Barre Guillain-Barré Guillain Barre Barré Stevens-Johnson Stevens Johnson Wilson Paget Raynaud
Sjogren Sjögren Behcet Behçet Reiter Still Pott Colles Smith Monteggia Galeazzi Bennett Jones Lisfranc Barton
Jefferson Hangman Maisonneuve Rolando Chopart Hoehn Yahr Karnofsky ECOG Mini-Mental Folstein Hamilton Beck Likert
Wong-Baker Wong Baker Lund Browder Rule Parkland Brooke Cockcroft-Gault Cockcroft Gault Friedewald Henderson
Hasselbalch Starling Frank Poiseuille Laplace Duke Jones Centor McIsaac Alvarado Rockall Blatchford Glasgow-Blatchford
Forrest Balthazar Marshall Atlanta Rome Manning Bristol Kayser-Fleischer Kayser Fleischer Argyll Robertson Horner
Holmes Adie Marcus Gunn Battle Cullen Grey-Turner Kehr Courvoisier Virchow Troisier Sister Joseph Osler Janeway Roth
Quincke Corrigan Duroziez Traube Austin-Flint Flint Kussmaul Cheyne-Stokes Cheyne Stokes Biot Beck Ortner Pemberton
Kanavel Finkelstein Allen Adson Spurling Lhermitte Hoffmann Gower Gowers Ober Patrick FABER Thomas Trendelenburg
Ortolani Barlow Galeazzi Perthes Legg-Calve-Perthes Calve Osgood-Schlatter Osgood Schlatter Sever Kienbock Kienböck
Preiser Freiberg Kohler Köhler Scheuermann Sprengel Klippel-Feil Klippel Feil Erb Klumpke Volkmann Sudeck Charcot
Dupuytren Ledderhose Peyronie Baker Morton Heberden Bouchard Tietze Mondor Buerger Takayasu Wegener Churg-Strauss
Henoch-Schonlein Henoch Schonlein Kaposi Burkitt Ewing Wilms Krukenberg Brenner Meigs Sertoli Leydig Hurthle Hürthle
Reed-Sternberg Sternberg Langerhans Kupffer Purkinje Schwann Auer Howell-Jolly Howell Jolly Heinz Russell Mallory
Councilman Aschoff Negri Lewy Pick Hirano Call-Exner Psammoma Charcot-Leyden Leyden Curschmann Rokitansky Meckel
Zenker Barrett Mallory-Weiss Boerhaave Plummer-Vinson Plummer Vinson Schatzki Hirschsprung Ogilvie Dieulafoy
Menetrier Ménétrier Zollinger-Ellison Zollinger Ellison Gilbert Crigler-Najjar Crigler Najjar Dubin-Johnson Dubin
Rotor Budd-Chiari Budd Chiari Wernicke Korsakoff Broca Bell Todd Jacksonian Lennox-Gastaut Lennox Gastaut West
Dravet Rett Tourette Huntington Friedreich Charcot-Marie-Tooth Duchenne Becker Erb Guyon Volkmann Bankart Hill-Sachs
Hill Sachs Monteggia Essex-Lopresti Lauge-Hansen Weber Danis Tscherne Gustilo-Anderson Sanders Hawkins Garden Pauwels
Evans Seinsheimer Winquist Schatzker Tile Young-Burgess Letournel Judet Denis Frankel ASIA Nurick Japanese Oswestry
Constant Harris Lysholm Tegner WOMAC Kapandji Jebsen Purdue Fugl-Meyer Fugl Meyer Brunnstrom Rivermead Tinetti
Timed Snellen Jaeger Ishihara Amsler Schirmer Goldmann Tonometry Rinne Weber Schwabach Dix-Hallpike Hallpike Epley
Caloric Mallampati Cormack-Lehane Cormack Lehane Macintosh Miller Magill Guedel Ambu Bain Mapleson Jackson-Rees
Rees Boyle Venturi Hudson Bird Starling Gram Giemsa Leishman Wright Field Romanowsky Masson Perls Congo Alcian
Grocott Warthin-Starry Warthin Starry Fontana Gomori Papanicolaou Pap Kleihauer Ham Schilling Coombs Paul-Bunnell
Monospot Elek Schick Dick Casoni Frei Tzanck Nikolsky Auspitz Koebner Darier Wickham Kerley Westermark Hampton
Fleischner Golden Spalding Robert Hegar Chadwick Goodell Jacquemier Braxton-Hicks Braxton Hicks Naegele Leopold
Pawlik Pinard Bandl Montgomery Mauriceau Lovset Burns-Marshall Ritgen Kielland Simpson Wrigley Shirodkar McDonald
Pomeroy Irving Uchida Madlener Cesarean Joel-Cohen Misgav-Ladach Pfannenstiel Maylard Cherney Lanz Rutherford
Kocher Mercedes Chevron Battle Rockey-Davis Rockey Davis Gridiron Lord Jaboulay Milligan-Morgan Milligan Morgan
Longo Ferguson Parks Goodsall Hartmann Roux-en-Y Kasai Duhamel Swenson Soave Ramstedt Ladd Nuss Ravitch Malgaigne
Tenckhoff Quinton Permcath Groshong Broviac Hickman Port-a-Cath Sengstaken-Blakemore Minnesota Linton Levin Salem
Malecot Pezzer Nelaton Coude Tiemann Councill Silastic Kehr Penrose Jackson-Pratt Redivac Romovac Hemovac Blake
Pigtail Malecot Babcock Allis Kocher Mosquito Halsted Kelly Crile Mayo Metzenbaum Langenbeck Deaver Morris Doyen
Balfour Gelpi Weitlaner Volkmann Hohmann Bennett Cobb Kerrison Gigli Liston Lane Lambotte Verbrugge Steinmann
Kirschner Kuntscher Küntscher Ender Rush Gamma Russell-Taylor Dynamic Condylar DHS DCS Herbert Acutrak Bohler Böhler
Braun Thomas Bohler-Braun Denis-Browne Milwaukee Boston Jewett Taylor Knight Philadelphia Minerva Halo Aspen Miami
Sarmiento Gallows Hamilton-Russell Bryant Buck Dunlop Perkins Charnley Exeter Muller Thompson Moore Bipolar Unipolar
Bateman Hastings Neer Copeland Swanson Silastic Starr-Edwards Starr Edwards Bjork-Shiley Bjork Shiley Carpentier
Hancock Medtronic Palmaz Wallstent Greenfield Fogarty Swan Ganz Pulmonary Dotter Judkins Amplatz Sones Cournand
Seldinger Tuohy Quincke Whitacre Sprotte Veress Hasson Verres Tru-Cut Menghini Jamshidi Klima Salah Chiba Cope
""".replace("-", " ").split()) | frozenset(w.lower() for w in """
Child-Pugh Hunt-Hess Kellgren-Lawrence Salter-Harris Swan-Ganz Ziehl-Neelsen Weil-Felix Guillain-Barre Stevens-Johnson
Austin-Moore Denis-Browne Wong-Baker Cockcroft-Gault Kayser-Fleischer Cheyne-Stokes Mallory-Weiss Reed-Sternberg
""".split())
# tails after which a capitalised run is a named instrument whatever the run is
_EP_STRONG = (r"scales?|scores?|scoring|index|indices|classification|criteria|staging|prosthesis|prostheses|implant|"
              r"manoeuvre|maneuver|technique|incision|flap|graft|splint|brace|forceps|retractor|clamp|stent|catheter|"
              r"syndrome|reflex|balance|questionnaire|inventory|scoring[ \t]+system|grading[ \t]+system|nomogram|"
              r"murmur|fistula|AVF|shunt|rhythm|pentad|agar|ganglion|plexus|apparatus|units")
# tails that need the run to hold a known eponym ("Ramesh type 2 DM" stays a person)
_EP_WEAK = (r"grade|grading|type|test|sign|method|procedure|operation|repair|approach|nail|plate|screw|cast|traction|"
            r"tube|drain|needle|valve|pouch|gait|position|view|projection|fracture|dislocation|deformity|contracture|"
            r"disease|disorder|anomaly|tumou?r|sarcoma|lymphoma|cells?|bodies|body|nodes?|nodules?|spots|lines?|law|"
            r"formula|equation|rule|protocol|regimen|stage|level|point|triad|phenomenon|palsy|ulcer|cyst|space|"
            r"pump|tonometer|stain|staining|reaction|maneuvre|bag|mask|circuit|blade|laryngoscope|chart|ratio")
_EP_RUN = r"(?:[A-Z][A-Za-zéèöüçä]+(?:[\-][A-Z]?[A-Za-zéèöüçä]+)*)"
# tail first (cheap), then the capitalised run just before it
_RE_EP_TAIL = re.compile(r"(?<=[ \t])(?:(" + _EP_STRONG + r")|(" + _EP_WEAK + r"))(?![A-Za-z])", re.I)
_RE_EP_BACK = re.compile(
    r"(?<![A-Za-z])((?:(?:Modified|Revised|New|Simplified|Mod\.|Extended|Paediatric|Pediatric)[ \t]+)?"
    + _EP_RUN + r"(?:'s|’s)?(?:[ \t]+(?:and|&)[ \t]+" + _EP_RUN + r"|[ \t]+" + _EP_RUN + r"){0,2})[ \t]+\Z")
_RE_EP_MOD = re.compile(r"(?<![A-Za-z])(?:Modified|Revised|Simplified|Mod\.)[ \t]+(" + _EP_RUN + r")(?![A-Za-z])")
_EP_RUN_TOK = re.compile(r"[A-Za-zéèöüçä]+")


def _eponym_spans(t: str) -> List[Tuple[int, int]]:
    out = []
    for m in _RE_EP_TAIL.finditer(t):
        lo = max(0, m.start() - 70, t.rfind("\n", 0, m.start()) + 1)
        b = None
        win = t[lo:m.start()]
        for k in range(len(win)):           # earliest start whose run reaches the tail
            if win[k].isupper() and (k == 0 or not win[k - 1].isalpha()):
                b = _RE_EP_BACK.match(win, k)
                if b:
                    break
        if not b:
            continue
        run = b.group(1)
        if not run[:1].isupper() or not all(w[:1].isupper() for w in run.replace("&", " ").split()
                                             if w.lower() not in ("and",)):
            continue
        words = [w.lower() for w in _EP_RUN_TOK.findall(run)]
        if not m.group(1) and not any(w in EPONYMS for w in words):
            continue                      # a weak tail needs a known eponym in the run
        out.append((lo + b.start(), m.end()))
    for m in _RE_EP_MOD.finditer(t):
        if m.group(1).lower() in EPONYMS:
            out.append((m.start(), m.end()))
    return out


# ---- drug brands: "<Brand> Plus", "<Brand>-AT", "<Brand> 125 mg", "Tab. <Brand>"
_BRAND_SFX = r"(?:Plus|Forte|DS|SR|XR|ER|XL|LA|MR|CR|CV|OD|Gold|Duo|Trio|Kid|Kids|Junior|Total|Max|Neo|Z)"
_RE_BRAND = re.compile(
    r"(?<![A-Za-z])[A-Z][a-z]{2,}(?:[ \t]+" + _BRAND_SFX + r"|-(?:[A-Z]{1,3}|" + _BRAND_SFX + r"))(?![A-Za-z])"
    r"(?:[ \t]*[0-9]+(?:\.[0-9]+)?(?:/[0-9]+(?:\.[0-9]+)?)?[ \t]*(?:mg|mcg|µg|g|gm|ml|mL|IU|iu|%))?"
    r"|(?<![A-Za-z])[A-Z][A-Za-z]{2,}(?:-[A-Z0-9]{1,3})?[ \t]+[0-9]+(?:\.[0-9]+)?(?:/[0-9]+(?:\.[0-9]+)?)?[ \t]*"
    r"(?:mg|mcg|µg|gm|ml|mL|IU|iu)(?![A-Za-z])"
    r"|(?<![A-Za-z])(?:Tab|Cap|Inj|Syp|Syr|Susp|Oint|Rotacap|Respule|Respules|Sachet|Supp)\.[ \t]*[A-Z][A-Za-z]{2,}"
    r"(?:-[A-Z0-9]{1,3})?(?![A-Za-z])"
    # one-letter forms (T. / C. / I.) look like initials ("Pt C. Rathod"): only with a strength or frequency after
    r"|(?<![A-Za-z])(?:T|C|I)\.[ \t]*[A-Z][A-Za-z]{2,}(?:-[A-Z0-9]{1,3})?(?![A-Za-z])"
    r"(?=[ \t]*(?:[0-9]|(?:OD|BD|BID|TDS|TID|QID|HS|SOS|STAT|stat|PRN)(?![A-Za-z])))")
_BRAND_NOT = frozenset("""
mr mrs ms dr shri smt sri kumar kumari devi singh age aged ward bed room day days dose total
""".split())

# ---- institutions written in Hinglish / Hindi, and community health roles
_RE_ASPATAL = re.compile(
    r"(?<![A-Za-z])(?:(?:Sadar|Zila|Jila|Zilla|Anumandal|Anumandaliya|Upmandal|Up-mandal|Mahila|Bal|Referral|Rajkiya|"
    r"Sarkari|Sarkaari|Samudayik|Prathmik|Prathamik|Upkhand|Prakhand|Rafral|Taluka|Taluk|Civil|District|Sub-?divisional)"
    r"[ \t]+)+(?:Aspatal|Aspataal|Hospital|Swasthya[ \t]+Kendra|Chikitsalaya)(?:[ \t]+(?!(?:mein|me|se|ko|ka|ki|ke|le|pe|par)\b)[A-Z][a-z]+)?"
    r"|(?<![A-Za-z])(?:PHC|CHC|SDH|UPHC|HWC|AAM|HSC|CHC/FRU|FRU)[ \t]+[A-Z][a-z]{2,}(?![A-Za-z])")
_HI_INST = (r"(?:चिकित्सा[ \t]+महाविद्यालय|मेडिकल[ \t]+कॉलेज|चिकित्सालय|अस्पताल|उप[ \t]+स्वास्थ्य[ \t]+केंद्र|"
            r"सामुदायिक[ \t]+स्वास्थ्य[ \t]+केंद्र|प्राथमिक[ \t]+स्वास्थ्य[ \t]+केंद्र|स्वास्थ्य[ \t]+केंद्र|स्वास्थ्य[ \t]+केन्द्र|नर्सिंग[ \t]+होम)")
_RE_HI_INST_TYPE = re.compile(r"(?<![ऀ-ॿ])(?:(?:जिला|ज़िला|सदर|अनुमंडल|अनुमंडलीय|राजकीय|सरकारी|महिला|बाल|रेफरल|उप|"
                              r"सामुदायिक|प्राथमिक|संभागीय|क्षेत्रीय|केंद्रीय|मंडलीय)[ \t]+)+" + _HI_INST + r"(?![ऀ-ॿ])")
# a facility name heading a line: "<Name> <Name> चिकित्सा महाविद्यालय, <Town>"
_RE_HI_INST_HEAD = re.compile(r"(?m)^[ \t]*(?:[ऀ-ॿ]+[ \t]+){1,5}" + _HI_INST + r"(?![ऀ-ॿ])")
_RE_ROLE = re.compile(
    r"(?<![A-Za-z])(?:sahiya|sahiyya|sahia|mitanin|anganwadi|aanganwadi|anganvadi)(?:[ \t]+(?:didi|di|behenji|bahenji|"
    r"sevika|sahayika|sahaika|worker|karyakarta|kendra|wali))?(?![A-Za-z])"
    r"|(?<![A-Za-z])(?:ANM|anm|Anm)[ \t]+(?:didi|di|behenji|bahenji|sister)(?![A-Za-z])"
    r"|(?<![A-Za-z])(?:staff[ \t]+nurse|ward[ \t]+boy|ward[ \t]+aaya|ward[ \t]+ayah|nursing[ \t]+orderly)(?![A-Za-z])"
    r"|(?:सहिया|मितानिन|आंगनवाड़ी|आँगनवाड़ी|आंगनबाड़ी)(?:[ \t]+(?:दीदी|सेविका|सहायिका|कार्यकर्ता))?", re.I)


_RE_ROLE_HINT = re.compile(r"(?i)sahi|mitanin|anganwadi|aanganwadi|anganvadi|anm|staff|ward|nursing|सहिया|मितानिन|आंगन|आँगन")


def _word_after(text: str, pos: int) -> Tuple[str, str]:
    """(first word, second word) after pos, skipping spaces and punctuation like ':' or '-'."""
    m = re.match(r"[\s:\-.]*([^\s,;:.()\"]+)(?:\s+([^\s,;:.()\"]+))?", text[pos:])
    if not m:
        return "", ""
    return m.group(1) or "", m.group(2) or ""


def _is_clinical_word(w: str) -> bool:
    lw = w.lower().strip("'\"")
    if not lw:
        return False
    if lw in lexicon.COMPLAINT_WORDS or lw in lexicon.CLINICAL_WORDS:
        return True
    if any(ch.isdigit() for ch in lw):
        return True
    return False


_RE_ACRO = re.compile(r"[A-Z][A-Z0-9]{1,5}")


def _hist_follows(text: str, marker_end: int, kind: str) -> bool:
    w1, w2 = _word_after(text, marker_end)
    if not w1:
        return False
    if kind == "kco":
        return True
    if _is_clinical_word(w1):
        return True
    if _RE_ACRO.fullmatch(w1) and not (w2 and w2.isalpha() and w2.isupper() and len(w2) > 1):
        return True                    # "C/O: RTA - bike skid", "h/o PCOS", "h/o PTB 2011": an acronym in mixed text
    if kind == "low" and w1[:1].islower() and w1.isalpha():
        return True                    # lowercase "h/o tobacco (mishri)": history of a habit
    if re.match(r"[\u0900-\u097F]", w1):
        return w1 in lexicon.COMPLAINT_WORDS or w1 in lexicon.CLINICAL_WORDS
    if w1[:1].islower():
        if w1 in lexicon.HINDI_COMMON_WORDS:
            return True
        # 'c/o pet mein dard' style: a lowercase run, not a lowercase name followed by a surname
        return bool(w2) and w2[:1].islower()
    return False


def is_complaint_of(text: str, pos: int) -> bool:
    """True when the C/O (or H/O) marker at pos introduces a complaint, not a 'care of' person."""
    t = _to_ascii_digits(text)
    m = _RE_HIST_MARK.match(t, pos)
    if not m:
        return False
    mk = re.sub(r"\s+", " ", m.group().lower())
    kind = "kco" if mk in ("k/c/o", "kco", "known case of", "history of", "p/h/o", "f/h/o") or mk.startswith("complain") else "co"
    if kind == "co" and m.group() in ("h/o", "c/o"):
        kind = "low"
    return _hist_follows(t, m.end(), kind)


_PCACHE = {}  # type: dict
_PCACHE_MAX = 4096


def reset_protected_cache() -> None:
    _PCACHE.clear()


def protected_spans(text: str) -> List[Span]:
    """Clinical stretches that must never be redacted, non-overlapping and sorted. Memoised per text
    (detect, sanitize and the field layer ask for the same string); callers get a fresh list."""
    hit = _PCACHE.get(text)
    if hit is None:
        hit = tuple((sp.start, sp.end, sp.kind, sp.value) for sp in _protected_spans(text))
        if len(_PCACHE) >= _PCACHE_MAX:
            _PCACHE.clear()
        _PCACHE[text] = hit
    return [Span(a, b, c, d) for a, b, c, d in hit]


def _protected_spans(text: str) -> List[Span]:
    t = _to_ascii_digits(text)
    c: List[Tuple[int, int, int, str, str]] = []
    for m in _RE_HIST_MARK.finditer(t):
        if not is_complaint_of(t, m.start()):
            continue
        e = _RE_HIST_END.search(t, m.end())
        end = e.start() if e else len(t)
        end = min(end, m.end() + 80)
        if end > m.end():
            c.append((0, m.start(), end, "HISTORY", ""))
    for m in _RE_DOCTOR.finditer(t):
        if not re.match(r"(?:Dr|DR|dr|Doctor|DOCTOR|डॉ|डा|डाॅ)", m.group()) and \
                re.search(r"[ऀ-ॿ][ \t]+$", t[max(0, m.start() - 4):m.start()]):
            continue   # "<given> <given> वैद्य": a surname after a name, not the "Vaidya <name>" title
        if m.end() - m.start() > 3:
            c.append((1, m.start(), m.end(), "DOCTOR", ""))
    for m in _RE_EPONYM.finditer(t):
        c.append((2, m.start(), m.end(), "EPONYM", ""))
    for rx in (_RE_EPONYM2, _RE_SCHEME):
        for m in rx.finditer(t):
            c.append((2, m.start(), m.end(), "EPONYM", ""))
    for m in _RE_ASHA.finditer(t):
        c.append((2, m.start(), m.end(), "ASHA", ""))
    for rx, hint in _KEEP_SHIELDS:
        if hint.search(t):
            for m in rx.finditer(t):
                c.append((2, m.start(), m.end(), "EPONYM", ""))
    for a, b in _eponym_spans(t):
        c.append((2, a, b, "EPONYM", ""))
    for m in _RE_BRAND.finditer(t):
        w = re.match(r"(?:[A-Za-z]+\.[ \t]*)?([A-Za-z]+)", m.group()).group(1).lower()
        if w not in _BRAND_NOT:
            c.append((8, m.start(), m.end(), "DOSE", ""))
    for rx in (_RE_ASPATAL, _RE_HI_INST_TYPE, _RE_HI_INST_HEAD):
        for m in rx.finditer(t):
            c.append((2, m.start(), m.end(), "EPONYM", ""))
    for m in (_RE_ROLE.finditer(t) if _RE_ROLE_HINT.search(t) else ()):
        c.append((2, m.start(), m.end(), "EPONYM", ""))
    for m in _RE_WARD.finditer(t):
        g = m.group()
        strong = "(" in g or re.search(r"bed|बेड|बिस्तर", g, re.I) or re.match(r"ward\s*(?:/\s*bed)?\s*(?:no\.?)?\s*[:#]", g, re.I)
        if not strong and _RE_WARD_ADDR_CTX.search(_line_before(t, m.start(), 100)):
            continue
        c.append((3, m.start(), m.end(), "WARD", ""))
    for m in _RE_VITAL.finditer(t):
        if re.search(r"[0-9]", m.group()):
            c.append((4, m.start(), m.end(), "VITAL", ""))
    for m in _RE_LAB.finditer(t):
        c.append((5, m.start(), m.end(), "LAB", ""))
    for m in _RE_RANGE.finditer(t):
        a, b = m.group(1), m.group(2)
        if len(a.replace(".", "")) > 5 or len(b.replace(".", "")) > 5:
            continue
        if "." not in a + b and len(a) >= 5 and len(b) >= 5:
            continue                      # 12345-67890 is a phone, never a range
        c.append((6, m.start(), m.end(), "LAB", ""))
    for m in _RE_FREQ.finditer(t):
        c.append((7, m.start(), m.end(), "FREQ", ""))
    for m in _RE_DOSE.finditer(t):
        c.append((8, m.start(), m.end(), "DOSE", ""))
    for m in _RE_DRUG_NUM.finditer(t):
        w = m.group(1).lower()
        if w in lexicon.CLINICAL_WORDS and w not in _NOT_DRUG:
            c.append((8, m.start(), m.end(), "DOSE", ""))
    return _resolve(c)
