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
# "+91 (98765) 43210", "(98765) 43210", "0091 (98765)-43210"
_RE_PHONE_PAREN = re.compile(r"(?<![0-9A-Za-z+])(?:(?:\+|00)[ \t]?91[ \t.\-]*)?\([ \t]?[6-9][0-9]{4}[ \t]?\)"
                             r"[ \t.\-]?[0-9]{5}(?![0-9A-Za-z])")
_RE_AADHAAR_SPACED = re.compile(_NB + r"[2-9][0-9]{3}([ \-.])[0-9]{4}\1[0-9]{4}" + _NA)
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
    r"sample(?:\s*(?:id|no))?|claim(?:\s*no)?|cyto\s*no|barcode|accession|batch|lot|invoice|receipt|order|rs\.?|inr|₹)"
    r"[\s:#.\-]*$")


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
        if first in _INS_PREFIXES and len(_digits(tok)) >= 5:
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
            continue
        c.append((5, m.start(), m.end(), "AADHAAR", g))
    for m in _RE_PAN.finditer(t):
        c.append((6, m.start(), m.end(), "PAN", m.group().upper()))
    for rx in (_RE_PHONE_PLUS, _RE_PHONE, _RE_PHONE_PAREN, _RE_PHONE_WRAP):
        for m in rx.finditer(t):
            p = norm_phone(m.group())
            if p and not _phone_vetoed(t, tl, m.start()):
                c.append((7, m.start(), m.end(), "PHONE", p))
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
TICKET LAB LB BAR BC REF PAY PMT CHQ UTR GST GSTIN BATCH LOT ICD LOINC SNOMED
""".split())
_RE_NON_PATIENT_LABEL = re.compile(
    r"(?<![a-z])(?:bill|invoice|inv|receipt|rcpt|sample|specimen|visit|package|pkg|txn|transaction|"
    r"order|token|barcode|claim|voucher|accession|ticket|batch|lot|payment|बिल|रसीद|नमूना|"
    r"lab\s*(?:no|ref|id|number|#|accession)|(?<!patient )(?<!pt )ref(?:erence)?\.?\s*(?:no|number|#)|cyto(?:logy)?\s*no|"
    r"trip\s*(?:id|no)|mlc|mlr|ml\s*no|certificate|cert|film|slide|room|ext|extn)(?![a-z])"
)
_RE_PATIENT_LABEL = re.compile(
    r"(?<![a-z])(?:uhid|mrn|mr\s*no|cr\s*no|hosp(?:ital)?[\s_]*(?:no|id|uhid)|patient[\s_]*(?:id|no|ref)|"
    r"pt[\s_]*id|reg(?:istration|n|d)?\.?[\s_]*(?:no|number|id|#)?|ipd?[\s_]*(?:no|number|id)?|opd[\s_]*(?:no|number|id|reg)?|"
    r"adm(?:ission)?[\s_]*(?:no|number|id)?|inpatient[\s_]*(?:no|id)?|case[\s_]*(?:no|id)|"
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
        if _RE_NON_PATIENT_LABEL.search(seg):
            continue
        if re.match(r"(?:mob|mobile|ph|phone|tel|cell|call|contact)$", lead, re.I):
            continue
        labelled = bool(_RE_PATIENT_LABEL.search(seg)) or bool(
            re.match(r"(?:uhid|mrn|reg|ipd|ip|adm|crno|hosp)", lead, re.I))
        if after_label_only and not labelled:
            continue
        out.append((0, ms, me, "MRN", norm_id(tok)))
    # bare digit numbers right after an explicit patient-id label
    for m in _RE_DIGIT_TOKEN.finditer(t):
        seg = _segment_before(tl, m.start(), 40)
        if _RE_PATIENT_LABEL.search(seg) and not _RE_NON_PATIENT_LABEL.search(seg):
            out.append((1, m.start(), m.end(), "MRN", m.group()))
    return _resolve(out)


# ---------------------------------------------------------------- PIN codes

_ADDR_CUE_RX = re.compile(
    r"(?<![a-z\u0900-\u097f])(?:" + "|".join(
        re.escape(c) for c in sorted(lexicon.ADDRESS_CUES, key=len, reverse=True) if len(c) >= 3
    ) + r")(?![a-z])"
)
_RE_PIN = re.compile(r"(?<![0-9A-Za-z.,/:\-])[1-9][0-9]{5}(?![0-9A-Za-z]|[.,/:][0-9])")
_RE_PIN_SPACED = re.compile(r"(?<![0-9A-Za-z])[1-9][0-9]{2} [0-9]{3}(?![0-9A-Za-z])")
_RE_UNIT_AFTER = re.compile(r"\s*(?:/|per\b|cells|lakh|mg|ml|iu|u/l|units?|rs|inr|₹|%|x\s*10)", re.I)
_RE_MONEY_BEFORE = re.compile(r"(?:rs\.?|inr|₹|amount|amt|total|paid|fee|charges?|cost|price|count|wbc|platelets?)[\s:=]*$", re.I)


def find_pins(text: str) -> List[Span]:
    """6-digit PIN codes after an address cue, a PIN label, or an address-line dash."""
    t = _to_ascii_digits(text)
    tl = t.lower()
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
          r"mmHg|mm\s*Hg|fl|fL|pg|sec|%|mm/hr|mm/1st\s*hr|gm/dl|gm%|g%)")
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
    r"(?<![A-Za-z])(?:(?:[A-Z][a-z]+[ \t]+){0,3}(?:Yojana|Yojna|Abhiyan|Abhiyaan)|Mission[ \t]+[A-Z][a-z]+(?:[ \t]+[A-Z][a-z]+)?|"
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


def _hist_follows(text: str, marker_end: int, kind: str) -> bool:
    w1, w2 = _word_after(text, marker_end)
    if not w1:
        return False
    if kind == "kco":
        return True
    if _is_clinical_word(w1):
        return True
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
    return _hist_follows(t, m.end(), kind)


def protected_spans(text: str) -> List[Span]:
    """Clinical stretches that must never be redacted, non-overlapping and sorted."""
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
