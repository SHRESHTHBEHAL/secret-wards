"""Date finding, format-preserving date shifting, and age banding. Standard library only."""
from __future__ import annotations

import datetime as dt
import re
from dataclasses import dataclass
from typing import Dict, Iterable, List, Optional, Tuple

from . import scripts as _scripts

MIN_YEAR = 1900
MAX_YEAR = 2100

_DEVA_ZERO = 0x0966
_TO_ASCII = {chr(_DEVA_ZERO + i): str(i) for i in range(10)}
_TO_DEVA = {str(i): chr(_DEVA_ZERO + i) for i in range(10)}

_D = "[0-9०-९]"
_LET = "A-Za-zऀ-॥॰-ॿ"  # letters and signs, excluding Devanagari digits


def _ascii(s: str) -> str:
    return "".join(_TO_ASCII.get(c, c) for c in s)


def _deva(s: str) -> str:
    return "".join(_TO_DEVA.get(c, c) for c in s)


def _has_deva_digit(s: str) -> bool:
    return any(c in _TO_ASCII for c in s)


# ---------------------------------------------------------------- month names
_EN_FULL = ["january", "february", "march", "april", "may", "june", "july",
            "august", "september", "october", "november", "december"]
_EN_ABBR = [m[:3] for m in _EN_FULL]
_HI = [["जनवरी"], ["फरवरी", "फ़रवरी"], ["मार्च"], ["अप्रैल", "अप्रेल"], ["मई"], ["जून"],
       ["जुलाई"], ["अगस्त"], ["सितंबर", "सितम्बर"], ["अक्टूबर", "अक्तूबर"],
       ["नवंबर", "नवम्बर"], ["दिसंबर", "दिसम्बर"]]

# lowercase name -> (month, kind, variant) where kind in en_full, en_abbr, en_sept, hi
_MONTHS: Dict[str, Tuple[int, str, int]] = {}
for _i, _n in enumerate(_EN_FULL):
    _MONTHS[_n] = (_i + 1, "en_full", 0)
for _i, _n in enumerate(_EN_ABBR):
    _MONTHS.setdefault(_n, (_i + 1, "en_abbr", 0))
_MONTHS["sept"] = (9, "en_sept", 0)
for _i, _vs in enumerate(_HI):
    for _j, _n in enumerate(_vs):
        _MONTHS[_n] = (_i + 1, "hi", _j)

_MON_ALT = "|".join(re.escape(n) for n in sorted(_MONTHS, key=lambda x: (-len(x), x)))
_MON = "(?:%s)" % _MON_ALT

# ---------------------------------------------------------------- patterns
_ANY_D = re.compile(_D)
_PRE = r"(?<![A-Za-z0-9०-९/\-+_])(?<![0-9०-९]\.)"
_ISO_RE = re.compile(
    _PRE + r"(?P<y>%s{4})(?P<s>[-/.])(?P<m>%s{1,2})(?P=s)(?P<d>%s{1,2})" % (_D, _D, _D)
    + r"(?P<t>T%s{2}:%s{2}(?::%s{2}(?:\.%s+)?)?(?:Z|[+-]%s{2}:?%s{2})?)?" % ((_D,) * 6)
    + r"(?![%s0-9०-९/]|[.\-:]%s)" % (_LET, _D))
_NUM_RE = re.compile(
    _PRE + r"(?P<a>%s{1,2})(?P<s>[./-])(?P<b>%s{1,2})(?P=s)(?P<y>%s{4}|%s{2})" % (_D, _D, _D, _D)
    + r"(?![%s0-9०-९/]|[.\-:]%s)" % (_LET, _D))
_NUM_SP_RE = re.compile(
    _PRE + r"(?P<a>%s{2}) (?P<b>%s{2}) (?P<y>(?:19|20)%s{2})(?![%s0-9०-९/]|[.\-:]%s| %s)" % (_D, _D, _D, _LET, _D, _D))
_DMY_NAME_RE = re.compile(
    r"(?<![%s0-9०-९/.\-+:_])(?P<d>%s{1,2})(?P<ord>st|nd|rd|th|ST|ND|RD|TH)?(?P<s1>[ \-]|\s*-\s*)"
    % (_LET, _D)
    + r"(?P<mon>%s)(?P<dot>\.)?(?:(?P<s2>,\s?|\s|-|/|\.\s?)(?P<y>%s{4}|(?<=[\-/. ])%s{2}))?(?![%s0-9०-९])"
    % (_MON, _D, _D, _LET), re.IGNORECASE)
_MDY_NAME_RE = re.compile(
    r"(?<![%s])(?P<mon>%s)(?P<dot>\.)?(?P<s1>\s|-|/)(?P<d>%s{1,2})(?P<ord>st|nd|rd|th)?(?P<s2>,\s?|\s|-|/)"
    % (_LET, _MON, _D)
    + r"(?P<y>%s{4})(?![%s0-9०-९])" % (_D, _LET), re.IGNORECASE)

# necessary for _MDY_NAME_RE (separator, day, separator, four-digit year): a cheap scan before the month alternation
_MDY_HINT = re.compile(r"(?:\s|-|/)%s{1,2}(?:st|nd|rd|th)?(?:,\s?|\s|-|/)%s{4}" % (_D, _D), re.IGNORECASE)


@dataclass
class DateHit:
    start: int
    end: int
    date: dt.date
    fmt: str
    has_year: bool
    has_time: bool


PIVOT_YY = 30   # two-digit years up to 30 are 20yy, later ones 19yy: a date never lands after 2030


def compact_date(s: str, order: str = "dmy") -> Optional[dt.date]:
    """Eight compact digits after a date-of-birth label: ddmmyyyy (mmddyyyy under order 'mdy') or
    yyyymmdd. None unless exactly one reading is a real date."""
    t = _ascii(str(s).strip())
    if len(t) != 8 or not t.isdigit():
        return None
    a, b = (t[2:4], t[:2]) if order == "mdy" else (t[:2], t[2:4])
    cands = {x for x in (_mk(int(t[4:]), int(b), int(a)), _mk(int(t[:4]), int(t[4:6]), int(t[6:]))) if x}
    return cands.pop() if len(cands) == 1 else None


def _year2(yy: int) -> int:
    return 2000 + yy if yy <= PIVOT_YY else 1900 + yy


def _mk(y: int, m: int, d: int) -> Optional[dt.date]:
    if not (MIN_YEAR <= y <= MAX_YEAR):
        return None
    try:
        return dt.date(y, m, d)
    except ValueError:
        return None


def _num_tok(raw: str, other: str, name: str) -> str:
    """Token for a day/month component, preserving zero-padding style."""
    if len(raw) == 1:
        return "{%s}" % name
    if raw.startswith(("0", "०")):
        return "{%s%s}" % (name, name)
    if len(other) == 1:
        return "{%s}" % name
    return "{%s%s}" % (name, name)


def _mon_style(word: str) -> str:
    low = word.lower()
    _m, kind, var = _MONTHS[low]
    if kind == "en_full" and len(low) == 3:
        kind = "en_abbr"            # "May" written as an abbreviation shifts to "Jun", not "June"
    if kind == "hi":
        return "hi%d" % var
    if word.isupper() and len(word) > 1:
        case = "U"
    elif word.islower():
        case = "L"
    else:
        case = "T"
    return "%s%s" % (kind, case)


def _ord(n: int) -> str:
    if 10 <= n % 100 <= 20:
        return "th"
    return {1: "st", 2: "nd", 3: "rd"}.get(n % 10, "th")


def _render(fmt: str, d: dt.date) -> str:
    deva = fmt.startswith("deva|")
    body = fmt[5:] if deva else fmt

    def mon(style: str) -> str:
        if style.startswith("hi"):
            vs = _HI[d.month - 1]
            v = int(style[2:])
            return vs[v] if v < len(vs) else vs[0]
        kind, case = style[:-1], style[-1]
        if kind == "en_full":
            w = _EN_FULL[d.month - 1]
        elif kind == "en_sept" and d.month == 9:
            w = "sept"
        else:
            w = _EN_ABBR[d.month - 1]
        return w.upper() if case == "U" else (w if case == "L" else w.capitalize())

    def rep(m: "re.Match[str]") -> str:
        t = m.group(1)
        if t == "d":
            return str(d.day)
        if t == "dd":
            return "%02d" % d.day
        if t == "m":
            return str(d.month)
        if t == "mm":
            return "%02d" % d.month
        if t == "yyyy":
            return "%04d" % d.year
        if t == "yy":
            return "%02d" % (d.year % 100)
        if t == "ord":
            return _ord(d.day)
        if t == "ORD":
            return _ord(d.day).upper()
        if t.startswith("mon:"):
            return mon(t[4:])
        return m.group(0)

    out = re.sub(r"\{([^{}]+)\}", rep, body)
    return _deva(out) if deva else out


def _esc(s: str) -> str:
    return s.replace("{", "(").replace("}", ")")


def _hits_iso(text: str) -> List[DateHit]:
    out = []
    for m in _ISO_RE.finditer(text):
        y, mo, d = int(_ascii(m.group("y"))), int(_ascii(m.group("m"))), int(_ascii(m.group("d")))
        date = _mk(y, mo, d)
        if date is None:
            continue
        s = m.group("s")
        mraw, draw = m.group("m"), m.group("d")
        mt = _num_tok(mraw, draw, "m")
        dtk = _num_tok(draw, mraw, "d")
        if s == "." and (len(mraw) == 1 or len(draw) == 1) and not m.group("t"):
            # "2026.1.5" could be a version / lab value; only padded dotted dates count
            continue
        fmt = "{yyyy}%s%s%s%s%s" % (s, mt, s, dtk, _esc(m.group("t") or ""))
        if _has_deva_digit(m.group(0)):
            fmt = "deva|" + fmt
        out.append(DateHit(m.start(), m.end(), date, fmt, True, bool(m.group("t"))))
    return out


def _hits_num(text: str, order: str) -> List[DateHit]:
    out = []
    for m in _NUM_RE.finditer(text):
        a, b, yr = m.group("a"), m.group("b"), m.group("y")
        if order == "mdy":
            mo_raw, d_raw = a, b
        else:
            d_raw, mo_raw = a, b
        y = int(_ascii(yr))
        if len(yr) == 2:
            y = _year2(y)
        date = _mk(y, int(_ascii(mo_raw)), int(_ascii(d_raw)))
        if date is None:
            continue
        dt_tok = _num_tok(d_raw, mo_raw, "d")
        mo_tok = _num_tok(mo_raw, d_raw, "m")
        s = m.group("s")
        ytok = "{yyyy}" if len(yr) == 4 else "{yy}"
        if order == "mdy":
            fmt = mo_tok + s + dt_tok + s + ytok
        else:
            fmt = dt_tok + s + mo_tok + s + ytok
        if _has_deva_digit(m.group(0)):
            fmt = "deva|" + fmt
        out.append(DateHit(m.start(), m.end(), date, fmt, True, False))
    return out


def _hits_num_sp(text: str, order: str) -> List[DateHit]:
    out = []
    for m in _NUM_SP_RE.finditer(text):
        a, b, y = m.group("a"), m.group("b"), int(_ascii(m.group("y")))
        mo_raw, d_raw = (a, b) if order == "mdy" else (b, a)
        date = _mk(y, int(_ascii(mo_raw)), int(_ascii(d_raw)))
        if date is None:
            continue
        fmt = "{mm} {dd} {yyyy}" if order == "mdy" else "{dd} {mm} {yyyy}"
        if _has_deva_digit(m.group(0)):
            fmt = "deva|" + fmt
        out.append(DateHit(m.start(), m.end(), date, fmt, True, False))
    return out


def _partial_ok(word: str) -> bool:
    low = word.lower()
    kind = _MONTHS[low][1]
    if kind in ("en_full", "hi"):
        return True
    return word[:1].isupper()


def _hits_name(text: str, default_year: Optional[int]) -> List[DateHit]:
    out = []
    for m in _DMY_NAME_RE.finditer(text):
        word = m.group("mon")
        mo = _MONTHS[word.lower()][0]
        d_raw = m.group("d")
        has_year = m.group("y") is not None
        if has_year:
            y = int(_ascii(m.group("y")))
            if len(m.group("y")) == 2:
                if m.group("s1").strip() != m.group("s2").strip() or (
                        m.group("s2") == " " and re.match(r"\s*[A-Za-z%ऀ-ॿ]", text[m.end():])):
                    continue          # "12 May 26 mg" / "12-May 26": not a two-digit-year date
                y = _year2(y)
        else:
            if default_year is None or not _partial_ok(word):
                continue
            y = default_year
        date = _mk(y, mo, int(_ascii(d_raw)))
        if date is None:
            continue
        ordr = m.group("ord")
        ordtok = "" if not ordr else ("{ORD}" if ordr.isupper() else "{ord}")
        fmt = ("{dd}" if len(d_raw) == 2 and d_raw[0] in "0०" else "{d}") + ordtok
        fmt += m.group("s1") + "{mon:%s}" % _mon_style(word) + (m.group("dot") or "")
        if has_year:
            fmt += m.group("s2") + ("{yyyy}" if len(m.group("y")) == 4 else "{yy}")
        if _has_deva_digit(m.group(0)):
            fmt = "deva|" + fmt
        out.append(DateHit(m.start(), m.end(), date, fmt, has_year, False))
    for m in (_MDY_NAME_RE.finditer(text) if _MDY_HINT.search(text) else ()):
        word = m.group("mon")
        mo = _MONTHS[word.lower()][0]
        d_raw = m.group("d")
        date = _mk(int(_ascii(m.group("y"))), mo, int(_ascii(d_raw)))
        if date is None:
            continue
        ordr = m.group("ord")
        ordtok = "" if not ordr else ("{ORD}" if ordr.isupper() else "{ord}")
        fmt = "{mon:%s}" % _mon_style(word) + (m.group("dot") or "") + m.group("s1")
        fmt += ("{dd}" if len(d_raw) == 2 and d_raw[0] in "0०" else "{d}") + ordtok
        fmt += m.group("s2") + "{yyyy}"
        if _has_deva_digit(m.group(0)):
            fmt = "deva|" + fmt
        out.append(DateHit(m.start(), m.end(), date, fmt, True, False))
    return out


_FCACHE = {}  # type: dict
_FCACHE_MAX = 20000


def reset_cache() -> None:
    _FCACHE.clear()
    _ACACHE.clear()


def find_dates(text: str, order: str = "dmy", default_year: Optional[int] = None) -> List[DateHit]:
    """All non-overlapping dates in `text`, sorted by position.

    Partial dates without a year ("5 September") are only returned when `default_year` is given.
    Memoised per (text, order, default_year); callers get fresh DateHit objects.
    """
    if not _ANY_D.search(text):
        return []                         # every date shape has a digit
    key = (text, order, default_year)
    hit = _FCACHE.get(key)
    if hit is None:
        hit = tuple((h.start, h.end, h.date, h.fmt, h.has_year, h.has_time)
                    for h in _find_dates(text, order, default_year))
        while len(_FCACHE) >= _FCACHE_MAX:
            del _FCACHE[next(iter(_FCACHE))]
        _FCACHE[key] = hit
    return [DateHit(*h) for h in hit]


def _find_dates(text: str, order: str, default_year: Optional[int]) -> List[DateHit]:
    cands = _hits_iso(text) + _hits_num(text, order) + _hits_name(text, default_year) + _hits_num_sp(text, order)
    cands.sort(key=lambda h: (h.start, -(h.end - h.start)))
    out: List[DateHit] = []
    last = -1
    for h in cands:
        if h.start >= last:
            out.append(h)
            last = h.end
    return out


def _date_len(iso_like: str) -> int:
    """Length of the date part of 'yyyy-mm-ddThh:mm...' (the time part starts at 'T')."""
    i = iso_like.find("T")
    return i if i > 0 else len(iso_like)


def shift_date(d: dt.date, days: int) -> dt.date:
    return d + dt.timedelta(days=days)


_WD_FULL = ("monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday")
_WD_ABBR = ("mon", "tue", "wed", "thu", "fri", "sat", "sun")
_WD_BEFORE = re.compile(r"(?<![A-Za-z])(monday|tuesday|wednesday|thursday|friday|saturday|sunday|"
                        r"tues|thurs|mon|tue|wed|thu|fri|sat|sun)(\.?,?[ \t]*)$", re.IGNORECASE)


def _fix_weekday(before: str, new_date: dt.date) -> str:
    """`before` with a weekday name right before a shifted date recomputed in the same style
    ("Mon, " -> "Wed, ", "MONDAY " -> "FRIDAY ")."""
    m = _WD_BEFORE.search(before[-16:])
    if not m:
        return before
    word = m.group(1)
    i = new_date.weekday()
    lw = word.lower()
    w = _WD_FULL[i] if lw in _WD_FULL else _WD_ABBR[i]
    if lw in ("tues", "thurs"):
        w = _WD_ABBR[i]
    if word.isupper():
        w = w.upper()
    elif word[0].isupper():
        w = w.capitalize()
    start = len(before) - len(before[-16:]) + m.start(1)
    return before[:start] + w + before[start + len(word):]


def compact_ymd(s: object) -> Optional[dt.date]:
    """The date of a compact 8-digit yyyymmdd value ('20260124'), else None. Only for fields
    already typed as dates."""
    t = str(s).strip()
    if len(t) != 8 or not t.isdigit() or not t.isascii() or t[:2] not in ("19", "20"):
        return None
    return _mk(int(t[:4]), int(t[4:6]), int(t[6:]))


def shift_text(text: str, days: int, order: str = "dmy", default_year: Optional[int] = None) -> str:
    """Shift every date in `text` by `days`, keeping each date's exact original format."""
    hits = find_dates(text, order, default_year)
    if not hits:
        return text
    parts = []
    pos = 0
    for h in hits:
        parts.append(_fix_weekday(text[pos:h.start], shift_date(h.date, days)))
        new = _render(h.fmt, shift_date(h.date, days))
        if h.has_time:
            # keep time/offset byte-identical: replace only the date characters
            orig = text[h.start:h.end]
            new = new[:len(new) - len(orig) + _date_len(orig)] + orig[_date_len(orig):]
        parts.append(new)
        pos = h.end
    parts.append(text[pos:])
    return "".join(parts)


def format_like(original: str, new_date: dt.date, order: str = "dmy") -> str:
    """Render `new_date` in the same format as the single date string `original`."""
    hits = find_dates(original, order, new_date.year)
    if not hits:
        return new_date.isoformat()
    h = hits[0]
    new = _render(h.fmt, new_date)
    if h.has_time:
        orig = original[h.start:h.end]
        new = new[:len(new) - len(orig) + _date_len(orig)] + orig[_date_len(orig):]
    return _fix_weekday(original[:h.start], new_date) + new + original[h.end:]


def parse_one(s: str, order: str = "dmy") -> Optional[dt.date]:
    """The date if `s` (stripped) is exactly one full date, else None."""
    t = s.strip()
    hits = find_dates(t, order)
    if len(hits) == 1 and hits[0].start == 0 and hits[0].end == len(t):
        return hits[0].date
    return None


_HINT_MDY = re.compile(r"mm\s*[/.\-]\s*dd|\bmdy\b", re.IGNORECASE)
_HINT_DMY = re.compile(r"dd\s*[/.\-]\s*mm|\bdmy\b", re.IGNORECASE)
_INFER_RE = re.compile(r"^\s*(\d{1,2})[./-](\d{1,2})[./-](\d{2}|\d{4})(?!\d)")


def infer_order(values: Iterable[str], label: str = "") -> str:
    """'mdy' or 'dmy' for a column: label hint, then any part > 12, else 'dmy'."""
    if label:
        if _HINT_MDY.search(label):
            return "mdy"
        if _HINT_DMY.search(label):
            return "dmy"
    firsts = False
    seconds = False
    for v in values:
        if not isinstance(v, str):
            continue
        m = _INFER_RE.match(_ascii(v))
        if not m:
            continue
        if int(m.group(1)) > 12:
            firsts = True
        if int(m.group(2)) > 12:
            seconds = True
    if firsts:
        return "dmy"
    if seconds:
        return "mdy"
    return "dmy"


# ---------------------------------------------------------------- ages
def age_band(age: int, width: int = 5, top: int = 85) -> str:
    if age >= top:
        return "%d+" % top
    lo = (age // width) * width
    return "%d-%d" % (lo, lo + width - 1)


_N = r"(?P<n>%s{1,3})" % _D
_NUM_END = r"(?![0-9०-९+.]|\s*-\s*%s)" % _D
_GEN = r"(?:F|M|Female|Male|female|male|महिला|पुरुष|स्त्री)(?![A-Za-zऀ-ॿ])"
_NOPRE = r"(?<![0-9०-९\-/.+:])"

_AGE_LABEL_RE = re.compile(
    r"(?:\b(?:Age|AGE|age)(?:\s*/\s*(?:Sex|SEX|sex|Gender|gender))?|आयु|उम्र|उमर|" + "|".join(_scripts.AGE_WORDS) + r")\s*[:：\-]?\s*"
    + _N + _NUM_END
    + r"(?!\s*(?:days?|months?|mths?|mo\b|weeks?|wks?|दिन|माह|महीने|महीना|सप्ताह|हफ्ते))")
_AGE_GENDER_RE = re.compile(
    _NOPRE + _N + r"\s*(?:(?:Yrs|Yr|Years|Year|yrs|yr|years|year|Y|y|वर्ष|साल)\.?\s*)?/\s*" + _GEN)
_AGE_YRS_RE = re.compile(_NOPRE + _N + r"\s*(?:Yrs|Years|Yr)\b\.?")
_AGE_OLD_RE = re.compile(_NOPRE + _N + r"[\s\-]*(?:years?|yrs?|Years?|Yrs?)[\s\-]*old\b", re.IGNORECASE)
_AGE_HI_RE = re.compile(_NOPRE + _N + r"\s*वर्ष(?![ऀ-ॿ])")
# "27 yrs, female" / "45 years, M" (FHIR narratives): lower-case unit, then a gender word
_AGE_SEXWORD_RE = re.compile(
    _NOPRE + _N + r"\s*(?i:yrs|yr|years|year|y)\.?(?:\s*,\s*|\s+)(?:F|M|Female|Male|female|male|FEMALE|MALE)"
    r"(?![A-Za-z])")

_DUR_PREFIX = re.compile(
    r"(?:\bx|×|\bsince|\bfor|\bfrom|\blast|\bpast|\bover|\bwithin|\bin)\s*$", re.IGNORECASE)
_DUR_SUFFIX = re.compile(
    r"^\s*(?:back|ago|before|duration|से|पहले|पूर्व|तक|का\s+इतिहास)", re.IGNORECASE)


_ACACHE = {}  # type: dict


def find_ages(text: str) -> List[Tuple[int, int, int]]:
    """(start, end, age) of each age number written in an age form; durations are skipped.
    Memoised per text; callers get a fresh list."""
    if not _ANY_D.search(text):
        return []                         # every age shape has a digit
    hit = _ACACHE.get(text)
    if hit is None:
        hit = tuple(_find_ages(text))
        while len(_ACACHE) >= _FCACHE_MAX:
            del _ACACHE[next(iter(_ACACHE))]
        _ACACHE[text] = hit
    return list(hit)


def _find_ages(text: str) -> List[Tuple[int, int, int]]:
    cands: List[Tuple[int, int, int]] = []

    def add(m: "re.Match[str]", check_duration: bool) -> None:
        s, e = m.span("n")
        if check_duration:
            if _DUR_PREFIX.search(text[max(0, s - 10):s]):
                return
            if _DUR_SUFFIX.match(text[m.end():m.end() + 16]):
                return
        if e < len(text) and text[e] in "+-" or (s > 0 and text[s - 1] in "-+"):
            return
        age = int(_ascii(m.group("n")))
        if age > 120:
            return
        cands.append((s, e, age))

    for m in _AGE_LABEL_RE.finditer(text):
        add(m, False)
    for m in _AGE_GENDER_RE.finditer(text):
        add(m, False)
    for rx in (_AGE_YRS_RE, _AGE_OLD_RE, _AGE_HI_RE, _AGE_SEXWORD_RE):
        for m in rx.finditer(text):
            add(m, True)
    cands.sort()
    out: List[Tuple[int, int, int]] = []
    last = -1
    for c in cands:
        if c[0] >= last:
            out.append(c)
            last = c[1]
    return out


def band_age_text(text: str, width: int = 5, top: int = 85) -> str:
    """Replace each age number in an age form with its band ("48 Yrs/F" -> "45-49 Yrs/F")."""
    ages = find_ages(text)
    if not ages:
        return text
    parts = []
    pos = 0
    for s, e, age in ages:
        parts.append(text[pos:s])
        band = age_band(age, width, top)
        parts.append(_deva(band) if _has_deva_digit(text[s:e]) else band)
        pos = e
    parts.append(text[pos:])
    return "".join(parts)
