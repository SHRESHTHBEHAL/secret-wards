"""Record scrubbing: typed fields, identifiers, names, addresses, dates and ages.

One call per parsed file. Every value is handled defensively: an odd value is replaced by a
placeholder rather than raising, because an exception quarantines the whole file.
Standard library only, Python 3.9+.
"""
from __future__ import annotations

import base64
import bisect
import posixpath
import re
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Sequence, Set, Tuple

from . import dates, fields, privacy
from .detect import ID_KINDS, NAME_KINDS, Known, detect
from .lexicon import DISTRICTS
from .harvest import csv_view, harvest_file, keyed_record_id
from .ingest import dump_csv, dump_json
from .normalize import to_ascii_digits, try_b64_text
from .patterns import find_identifiers, norm_id, protected_spans
from .pseudo import Keys
from .translit import GENERIC_NAME_PARTS, name_key, name_tokens
from .types import KIND_CSV, KIND_FHIR, KIND_JSON, Facts, ParsedFile, Patient, Record, Span


@dataclass
class Env:
    keys: Keys
    assign: Dict[Tuple[str, str], Optional[str]]
    book: Dict[str, Patient]
    policy: Dict[str, Any]
    pseudonyms: Dict[str, str] = field(default_factory=dict)
    records: Dict[str, List[Record]] = field(default_factory=dict)   # rel -> harvested records
    shifts: Any = None                                                # pseudo.ShiftBook: collision-free offsets
    dob_watch: Any = None                                             # DobWatch: shifted dates that hit a DOB


class DobWatch:
    """Dates of birth seen in the input, and the shift keys whose shifted dates landed on one of them.

    A shifted clinical date equal to another person's removed DOB reads as a DOB leak; the pipeline moves
    every flagged key (its whole patient, so intervals stay exact) one day further and redoes its files."""

    def __init__(self, dobs: Any) -> None:
        self.dobs = frozenset(d for d in dobs if d is not None)
        self.hit = set()  # type: Set[str]

    def check(self, ctx: Any, src: str, out: str, order: str, default_year: Optional[int] = None) -> None:
        if not self.dobs or out == src or ctx.skey is None:
            return
        try:
            for h in dates.find_dates(src, order, default_year):
                if dates.shift_date(h.date, ctx.shift) in self.dobs:
                    self.hit.add(ctx.skey)
                    return
        except Exception:  # noqa: BLE001
            return

    def check_date(self, ctx: Any, new: Any) -> None:
        if self.dobs and ctx.skey is not None and new in self.dobs:
            self.hit.add(ctx.skey)


@dataclass
class Sanitized:
    out_rel: str
    content: str
    records: List[Tuple[str, Optional[str], str]]
    counts: Dict[str, int]


# ----------------------------------------------------------------------------- placeholders

_ID_PH = {
    "PHONE": "[PHONE]", "AADHAAR": "[AADHAAR]", "AADHAAR_MASKED": "[AADHAAR]", "ABHA_NUMBER": "[ABHA]",
    "ABHA_ADDRESS": "[ABHA-ADDRESS]", "EMAIL": "[EMAIL]", "PAN": "[PAN]", "INSURANCE_ID": "[INSURANCE-ID]",
}
_ADDR_KINDS = frozenset({"HOUSE", "LOCALITY", "LANDMARK", "VILLAGE", "TEHSIL", "ADDRESS"})
_COUNT_NAME = {
    "PATIENT_NAME": "PATIENT_NAME", "PERSON": "PATIENT_NAME", "RELATIVE_NAME": "RELATIVE_NAME",
    "PHONE": "PHONE", "AADHAAR": "AADHAAR", "AADHAAR_MASKED": "AADHAAR", "ABHA_NUMBER": "ABHA_NUMBER",
    "ABHA_ADDRESS": "ABHA_NUMBER", "PAN": "PAN", "INSURANCE_ID": "INSURANCE_ID", "EMAIL": "EMAIL",
    "MRN": "MRN", "DOB": "DOB", "PIN": "PIN",
    "HOUSE": "ADDRESS", "LOCALITY": "ADDRESS", "LANDMARK": "ADDRESS", "VILLAGE": "ADDRESS",
    "TEHSIL": "ADDRESS", "ADDRESS": "ADDRESS",
}
_FIELD_PH = {
    fields.PHONE: "[PHONE]", fields.AADHAAR: "[AADHAAR]", fields.ABHA: "[ABHA]",
    fields.ABHA_ADDR: "[ABHA-ADDRESS]", fields.PAN: "[PAN]", fields.INSURANCE: "[INSURANCE-ID]",
    fields.EMAIL: "[EMAIL]", fields.ENC_ID: "[ENC-ID]", fields.HOUSE: "[ADDRESS]",
    fields.LOCALITY: "[ADDRESS]", fields.VILLAGE: "[VILLAGE]", fields.TEHSIL: "[TEHSIL]",
}
_FIELD_COUNT = {
    fields.PHONE: "PHONE", fields.AADHAAR: "AADHAAR", fields.ABHA: "ABHA_NUMBER",
    fields.ABHA_ADDR: "ABHA_NUMBER", fields.PAN: "PAN", fields.INSURANCE: "INSURANCE_ID",
    fields.EMAIL: "EMAIL", fields.ENC_ID: "MRN", fields.HOUSE: "ADDRESS",
    fields.LOCALITY: "ADDRESS", fields.VILLAGE: "ADDRESS", fields.TEHSIL: "ADDRESS",
}
_NAME_FIELDS = frozenset({fields.NAME, fields.FIRST_NAME, fields.LAST_NAME, fields.LOCAL_NAME})
_KEEP_FIELDS = frozenset({fields.DISTRICT, fields.STATE, fields.GENDER, fields.DOCTOR, fields.HOSPITAL,
                          fields.CLINICAL, fields.OTHER_ID, fields.RELATION})
_ID_NUM_FIELDS = frozenset({fields.PHONE, fields.AADHAAR, fields.ABHA, fields.PATIENT_ID, fields.ENC_ID,
                            fields.INSURANCE, fields.PAN, fields.EMAIL, fields.ABHA_ADDR})

_REL_PREFIX = re.compile(
    r"^\s*(?:[SDWCHsdwch]\s*/\s*[Oo]|son\s+of|daughter\s+of|wife\s+of|husband\s+of|care\s+of)\.?\s*[:\-]?\s*")
_PATHLIKE = re.compile(r"\\|[A-Za-z0-9]_[A-Za-z0-9]|[A-Za-z0-9]/[A-Za-z0-9_]+/")
_PATH_SEP = str.maketrans({"_": " ", "\\": " ", "/": " "})
_UNDERSCORE = str.maketrans({"_": " "})
_NUMDATE = re.compile(r"(?<![0-9])[0-9]{1,2}[./\-][0-9]{1,2}[./\-](?:[0-9]{4}|[0-9]{2})(?![0-9])")
_DIGITS = re.compile(r"[0-9]+")
_GAP_JOIN = re.compile(r"^[ \t,;:/\-]*$")
_FHIR_DATE = re.compile(r"^[0-9]{4}-[0-9]{2}-[0-9]{2}(?:T[0-9:.]+(?:Z|[+\-][0-9]{2}:[0-9]{2})?)?$")
_GENERIC_KEYS = frozenset(name_key(w) for w in GENERIC_NAME_PARTS)


# ----------------------------------------------------------------------------- record context

class _Ctx:
    """Everything needed to scrub the values of one record."""

    def __init__(self, known: Known, psn: Optional[str], shift: int, order: str, default_year: Optional[int],
                 own_ids: frozenset, all_ids: frozenset, full_set: frozenset, policy: Dict[str, Any],
                 do_shift: bool, pol: Optional[privacy.Policy] = None,
                 dec: Optional[privacy.Decision] = None) -> None:
        self.known = known
        self.psn = psn
        self.shift = shift
        self.order = order
        self.default_year = default_year
        self.own_ids = own_ids
        self.all_ids = all_ids
        self.full_set = full_set
        self.pol = pol if pol is not None else privacy.Policy(policy)
        self.dec = dec if dec is not None else privacy.Decision(suppress_geo=self.pol.min_cell > 0)
        self.width = self.pol.width
        self.top = self.pol.top
        self.do_shift = do_shift
        self.has_pid = False          # the record has a patient-id slot (the pseudonym goes there)
        self.psn_placed = False
        self.name_slot_used = False
        self.generalized = False
        self.counts = {}  # type: Dict[str, int]
        self.skey = None  # type: Optional[str]   # the shift key (patient / record) this context uses
        self.watch = None  # type: Any             # Env.dob_watch

    def count(self, kind: str, n: int = 1) -> None:
        name = _COUNT_NAME.get(kind, kind)
        if name != "identifiers":
            self.counts[name] = self.counts.get(name, 0) + n
        if name in ("DOB", "PIN", "DISTRICT"):
            return
        self.counts["identifiers"] = self.counts.get("identifiers", 0) + n


def _int(v: Any, default: int) -> int:
    try:
        return int(v)
    except (TypeError, ValueError):
        return default


def _facts_empty(f: Facts) -> bool:
    if f is None:
        return True
    return not (f.names or f.relatives or f.ids or f.raw_ids or f.dob or f.age is not None or f.village
                or f.tehsil or f.pin or f.address_parts)


def _name_keys(name: str) -> List[str]:
    try:
        return [k for k in (name_key(t) for t in name_tokens(name)) if k]
    except Exception:  # noqa: BLE001
        return []


def _fact_names(f: Facts) -> List[str]:
    out = [n for n in (f.names or []) if isinstance(n, str)]
    for rel in f.relatives or []:
        try:
            if isinstance(rel[1], str):
                out.append(rel[1])
        except (IndexError, TypeError):
            pass
    return out


def _id_values(f: Facts) -> Set[str]:
    out = set()  # type: Set[str]
    vals = [str(tok).split(":", 1)[-1] for tok in (f.ids or [])] + [str(r) for r in (f.raw_ids or [])]
    for v in vals:
        nv = norm_id(v)
        if len(nv) >= 4 and any(c.isdigit() for c in nv):
            out.add(nv)
        d = "".join(_DIGITS.findall(to_ascii_digits(v)))
        if len(d) >= 5:
            out.add(d)
    return out


def _global(env: Env) -> Tuple[Tuple[Tuple[str, ...], ...], frozenset, frozenset, frozenset]:
    """(full_names, id_values, full-name key set, every own name key), built once per Env."""
    cached = getattr(env, "_raksha_global", None)
    if cached is not None:
        return cached
    facts = []  # type: List[Facts]
    for rel in sorted(env.records or {}):
        for r in env.records[rel] or []:
            facts.append(r.facts)
    for k in sorted(env.book or {}):
        facts.extend(env.book[k].facts or [])
    full = set()  # type: Set[Tuple[str, ...]]
    ids = set()  # type: Set[str]
    keys = set()  # type: Set[str]
    for f in facts:
        if f is None:
            continue
        for n in _fact_names(f):
            ks = _name_keys(n)
            if len(ks) >= 2:
                full.add(tuple(sorted(ks)))
                ng = [k for k in ks if k not in _GENERIC_KEYS]
                if len(ng) >= 2:
                    full.add(tuple(sorted(ng)))
            keys.update(k for k in ks if k not in _GENERIC_KEYS and len(k) >= 3)
        ids |= _id_values(f)
    res = (tuple(sorted(full)), frozenset(ids), frozenset(full), frozenset(keys))
    try:
        setattr(env, "_raksha_global", res)
    except Exception:  # noqa: BLE001
        pass
    return res


def _privacy(env: Env) -> Tuple[privacy.Policy, Dict[str, privacy.Decision]]:
    """Per-patient age band and geography decisions, built once per Env."""
    cached = getattr(env, "_raksha_privacy", None)
    if cached is not None:
        return cached
    res = privacy.build(env.book or {}, env.policy or {})
    try:
        setattr(env, "_raksha_privacy", res)
    except Exception:  # noqa: BLE001
        pass
    return res


def _own(facts: Sequence[Facts]) -> Tuple[frozenset, frozenset]:
    keys = set()  # type: Set[str]
    ids = set()  # type: Set[str]
    for f in facts:
        if f is None:
            continue
        for n in _fact_names(f):
            keys.update(k for k in _name_keys(n) if k not in _GENERIC_KEYS)
        ids |= _id_values(f)
    return frozenset(keys), frozenset(ids)


def _patient_own(env: Env, key: str, decisions: Dict[str, privacy.Decision],
                 pol: privacy.Policy) -> Tuple[frozenset, frozenset, Optional[privacy.Decision]]:
    """(own name keys, own id values, decision) of one patient, built once per Env and shared."""
    memo = getattr(env, "_raksha_patown", None)
    if memo is None:
        memo = {}
        try:
            setattr(env, "_raksha_patown", memo)
        except Exception:  # noqa: BLE001
            pass
    hit = memo.get(key)
    if hit is None:
        pat = (env.book or {}).get(key)
        keys, ids = _own(list(pat.facts) if pat is not None and pat.facts else [])
        hit = (keys, ids, decisions.get(key))
        memo[key] = hit
    return hit


def _intern(env: Env, fs: frozenset) -> frozenset:
    """One shared frozenset object per distinct content (so per-set caches in detect hit)."""
    memo = getattr(env, "_raksha_intern", None)
    if memo is None:
        memo = {}
        try:
            setattr(env, "_raksha_intern", memo)
        except Exception:  # noqa: BLE001
            pass
    return memo.setdefault(fs, fs)


class _File:
    """Per-file state: one context per record plus file-level contexts."""

    def __init__(self, pf: ParsedFile, env: Env, recs: List[Record], order: str,
                 default_year: Optional[int]) -> None:
        self.pf = pf
        self.env = env
        self.recs = recs
        self.full_names, self.all_ids, self.full_set, self.all_keys = _global(env)
        self.pol, self.decisions = _privacy(env)
        pol = env.policy or {}
        self.smax = _int(pol.get("date_shift_max_days"), 180)
        self.smin = _int(pol.get("date_shift_min_days"), 30)
        self.clean = all(_facts_empty(r.facts) for r in recs) if recs else True
        self.ctx = {}  # type: Dict[str, _Ctx]
        self.psns = {}  # type: Dict[str, Optional[str]]
        for r in recs:
            self.ctx[r.loc] = self._make(r, order, default_year)
        file_keys = set()  # type: Set[str]
        file_ids = set()  # type: Set[str]
        for r in recs:
            k, i = _own([r.facts])
            file_keys |= k
            file_ids |= i
        self.file_ctx = self._ctx_for(frozenset(file_keys), frozenset(file_ids), None,
                                      self._shift("rec:%s:@file" % pf.sha256), order, default_year,
                                      privacy.unlinked([r.facts for r in recs], self.pol))
        self.file_ctx.skey = "rec:%s:@file" % pf.sha256
        # headers, keys and file names: every known name token of the dataset
        self.label_ctx = self._ctx_for(self.all_keys, frozenset(), None, 0, order, default_year)
        self.label_ctx.do_shift = False

    def _shift(self, key: str) -> int:
        try:
            if self.env.shifts is not None:
                return self.env.shifts.get(key)
            return self.env.keys.shift_days(key, self.smax, self.smin)
        except Exception:  # noqa: BLE001
            return self.smin

    def _ctx_for(self, own_keys: frozenset, own_ids: frozenset, psn: Optional[str], shift: int, order: str,
                 default_year: Optional[int], dec: Optional[privacy.Decision] = None) -> _Ctx:
        known = Known(own_keys=own_keys, full_names=self.full_names, id_values=self.all_ids)
        c = _Ctx(known, psn, shift, order, default_year, own_ids, self.all_ids, self.full_set,
                 self.env.policy or {}, not self.clean, self.pol, dec)
        c.watch = self.env.dob_watch
        return c

    def _make(self, r: Record, order: str, default_year: Optional[int]) -> _Ctx:
        key = self.env.assign.get((self.pf.rel, r.loc)) if self.env.assign else None
        psn = self.env.pseudonyms.get(key) if key else None
        if key and psn:
            pk, pi, pdec = _patient_own(self.env, key, self.decisions, self.pol)
            rk, ri = _own([r.facts])
            # share the patient's frozensets; only union when the record adds something new
            own_keys = pk if rk <= pk else pk | rk
            own_ids = pi if ri <= pi else pi | ri
            own_keys, own_ids = _intern(self.env, own_keys), _intern(self.env, own_ids)
            skey = key
            shift = self._shift(key)
            if pdec is not None:
                dec = pdec
            else:
                pat = (self.env.book or {}).get(key)
                facts = list(pat.facts) if pat is not None and pat.facts else []
                facts.append(r.facts)
                dec = privacy.unlinked(facts, self.pol)
        else:
            psn = None
            facts = [r.facts]
            skey = "rec:%s:%s" % (self.pf.sha256, r.loc)
            shift = self._shift(skey)
            dec = privacy.unlinked(facts, self.pol)
            own_keys, own_ids = _own(facts)
        self.psns[r.loc] = psn
        c = self._ctx_for(own_keys, own_ids, psn, shift, order, default_year, dec)
        c.skey = skey
        return c

    def ctx_for_ptr(self, ptr: str) -> _Ctx:
        if ptr in self.ctx:
            return self.ctx[ptr]
        best = None
        for loc in self.ctx:
            if loc.startswith("/") and ptr.startswith(loc + "/") and (best is None or len(loc) > len(best)):
                best = loc
        if best is not None:
            return self.ctx[best]
        if "doc" in self.ctx:
            return self.ctx["doc"]
        return self.file_ctx

    def main_ctx(self) -> _Ctx:
        if "doc" in self.ctx:
            return self.ctx["doc"]
        if self.ctx:
            return self.ctx[sorted(self.ctx)[0]]
        return self.file_ctx

    def all_ctx(self) -> List[_Ctx]:
        return [self.ctx[loc] for loc in sorted(self.ctx)] + [self.file_ctx, self.label_ctx]


# ----------------------------------------------------------------------------- text scrub

_HOSP_LINE = re.compile(r"hospital|hosp\b|sadan|clinic|nursing|medical|charitable|multispecial|labs?\b|"
                        r"pathology|diagnostic|अस्पताल|चिकित्सालय", re.I)


def _suppress_district(surface: str, ctx: _Ctx, text: str = "", start: int = 0, end: int = 0) -> bool:
    """True when this district mention belongs to a patient whose geography is suppressed: the
    patient's own district anywhere, any other address-context district unless it sits on a
    hospital / lab line (letterheads keep the hospital's town)."""
    if not ctx.dec.suppress_geo:
        return False
    if not ctx.dec.districts or privacy.place_key(surface) in ctx.dec.districts:
        return True
    if not text:
        return True
    ls = text.rfind("\n", 0, start) + 1
    le = text.find("\n", end)
    line = text[ls:le if le >= 0 else len(text)]
    return not _HOSP_LINE.search(line)


def _detect(text: str, ctx: _Ctx) -> list:
    try:
        spans = list(detect(text, ctx.known, ctx.order))
    except Exception:  # noqa: BLE001
        spans = []
    if _PATHLIKE.search(text):
        try:
            alt = list(detect(text.translate(_PATH_SEP), ctx.known, ctx.order))
        except Exception:  # noqa: BLE001
            alt = []
        added = False
        for sp in alt:
            if sp.kind in ("DISTRICT", "GENDER", "AGE", "DOB"):
                continue
            if not any(o.start < sp.end and sp.start < o.end for o in spans):
                spans.append(sp)
                added = True
        if added:
            spans.sort(key=lambda s: (s.start, s.end))
    return spans


def _is_known_name(surface: str, ctx: _Ctx) -> bool:
    if sum(1 for c in surface if c.isalpha()) < 2:
        return False              # a lone initial ("K/C/O") is not a name
    ks = _name_keys(surface)
    if not ks:
        return False
    if any(k in ctx.known.own_keys for k in ks if k not in _GENERIC_KEYS):
        return True
    if len(ks) >= 2:
        if tuple(sorted(ks)) in ctx.full_set:
            return True
        ng = tuple(sorted(k for k in ks if k not in _GENERIC_KEYS))
        if len(ng) >= 2 and ng in ctx.full_set:
            return True
    return False


_WORD = re.compile(r"[A-Za-z]+|[\u0900-\u0963\u0971-\u097F]+")


class _Overlap:
    """O(log n) "does [s, e) overlap any of these intervals" (a per-word scan of every span was quadratic)."""

    def __init__(self, ivs) -> None:
        ivs = sorted(ivs)
        self.starts = [a for a, _b in ivs]
        self.maxend = []  # type: List[int]
        m = -1
        for _a, b in ivs:
            m = b if b > m else m
            self.maxend.append(m)

    def hit(self, s: int, e: int) -> bool:
        i = bisect.bisect_left(self.starts, e)
        return i > 0 and self.maxend[i - 1] > s


def _own_token_spans(text: str, ctx: _Ctx, spans: list) -> list:
    """Whole-word occurrences of the record's own name tokens that detect left (e.g. "Asha's")."""
    own = ctx.known.own_keys
    cands = []
    taken = None  # type: Optional[_Overlap]
    for m in _WORD.finditer(text):
        w = m.group()
        if len(w) < 3 or not (w[0].isupper() or "\u0900" <= w[0] <= "\u097F") or (w.isupper() and len(w) > 3):
            continue
        try:
            k = name_key(w)
        except Exception:  # noqa: BLE001
            continue
        if not k or k in _GENERIC_KEYS or k not in own:
            continue
        s, e = m.start(), m.end()
        if taken is None:
            taken = _Overlap((o.start, o.end) for o in spans)
        if taken.hit(s, e):
            continue
        cands.append((s, e))
    if not cands:
        return []
    try:
        prot = _Overlap((p.start, p.end) for p in protected_spans(text) if p.kind != "ASHA")
    except Exception:  # noqa: BLE001
        prot = _Overlap([])
    out = []
    for s, e in cands:
        if prot.hit(s, e):
            continue
        if re.search(r"(?:\bDr\.?|डॉ\.?)\s*(?:[A-Z][a-z]+\s+)?$", text[max(0, s - 30):s]):
            continue
        out.append(Span(s, e, "PATIENT_NAME", ""))
    return out


def _pin_mask(s: str, ctx: Optional[_Ctx] = None) -> str:
    if ctx is not None and ctx.dec.suppress_geo:
        return "[PIN]"
    d = "".join(_DIGITS.findall(to_ascii_digits(str(s))))
    if len(d) >= 3:
        return d[:3] + "XXX"
    return "[PIN]"


_NEG_LEAD = re.compile("^\\s*[-\u2212\u2013]\\s*$")   # "-5", "− 3": a negative number, not an age


def _age_band(age: int, ctx: _Ctx) -> str:
    age = int(age)
    if age < 0 or age > 120:      # not an age: a neutral token, never a negative / nonsense band
        return "[AGE]"
    return ctx.pol.band_for(age, ctx.dec)


def _band_text(text: str, ctx: _Ctx) -> str:
    """dates.band_age_text with the patient's band: every age form of a patient gets one band."""
    ages = dates.find_ages(text)
    if not ages:
        return text
    parts = []
    pos = 0
    for s, e, age in ages:
        parts.append(text[pos:s])
        band = _age_band(age, ctx)
        parts.append(dates._deva(band) if dates._has_deva_digit(text[s:e]) else band)
        pos = e
    parts.append(text[pos:])
    return "".join(parts)


def _band(surface: str, value: str, ctx: _Ctx) -> str:
    try:
        out = _band_text(surface, ctx)
        if out != surface:
            return out
        a = to_ascii_digits(surface)
        m = _DIGITS.search(a)
        if m is None:
            if value and str(value).isdigit():
                return _age_band(int(value), ctx)
            return surface
        if int(m.group()) > 120 or _NEG_LEAD.match(a[:m.start()]):
            return "[AGE]"
        band = _age_band(int(m.group()), ctx)
        return a[:m.start()] + band + a[m.end():]
    except Exception:  # noqa: BLE001
        return surface


def _dob(surface: str, ctx: _Ctx) -> str:
    """A date of birth under the policy's dob_mode: remove (default) / year / shift."""
    mode = ctx.pol.dob_mode
    if mode == "remove":
        return "[DOB]"
    if mode == "year":
        try:
            d = dates.parse_one(surface, ctx.order)
            if d is None:
                hits = dates.find_dates(surface, ctx.order)
                d = hits[0].date if hits else None
            if d is not None:
                return str(d.year)
            m = re.search(r"(?<![0-9])(?:19|20)[0-9]{2}(?![0-9])", to_ascii_digits(surface))
            return m.group() if m else "[DOB]"
        except Exception:  # noqa: BLE001
            return "[DOB]"
    return _shift_dob(surface, ctx)


def _compact_date(v: Any, d: Any, ftype: str, ctx: _Ctx) -> Any:
    """A compact yyyymmdd value under a date-typed field, shifted (or generalised for a DOB)."""
    as_int = isinstance(v, int)
    if ftype == fields.DOB:
        ctx.count("DOB")
        ctx.generalized = True
        mode = ctx.pol.dob_mode
        if mode == "remove":
            return "[DOB]"
        if mode == "year":
            return d.year if as_int else str(d.year)
    elif not ctx.do_shift:
        return v
    else:
        ctx.generalized = True
    nd = dates.shift_date(d, ctx.shift)
    if ctx.watch is not None:
        ctx.watch.check_date(ctx, nd)
    new = nd.strftime("%Y%m%d")
    if as_int:
        return int(new)
    sv = str(v)
    lead = sv[:len(sv) - len(sv.lstrip())]
    return lead + new + sv[len(lead) + 8:]


def _shift_dob(surface: str, ctx: _Ctx) -> str:
    try:
        d = dates.parse_one(surface, ctx.order)
        if d is not None:
            return dates.format_like(surface, dates.shift_date(d, ctx.shift), ctx.order)
        out = dates.shift_text(surface, ctx.shift, ctx.order, ctx.default_year)
        if out != surface:
            return out
        return "[DOB]"
    except Exception:  # noqa: BLE001
        return "[DOB]"


def _mrn(surface: str, value: str, ctx: _Ctx) -> str:
    if ctx.psn:
        nv = norm_id(value or surface)
        dg = "".join(_DIGITS.findall(to_ascii_digits(surface)))
        foreign = (nv in ctx.all_ids or dg in ctx.all_ids) and not (nv in ctx.own_ids or dg in ctx.own_ids)
        if not foreign:
            ctx.psn_placed = True
            return ctx.psn
    return "[ID]"


def _gap(text: str, ctx: _Ctx, dates_on: bool, ages_on: bool) -> str:
    if not text:
        return text
    out = text
    if dates_on and ctx.do_shift:
        try:
            out = dates.shift_text(out, ctx.shift, ctx.order, ctx.default_year)
            if ctx.watch is not None:
                ctx.watch.check(ctx, text, out, ctx.order, ctx.default_year)
        except Exception:  # noqa: BLE001
            pass
    if ages_on and ctx.do_shift:
        try:
            out = _band_text(out, ctx)
        except Exception:  # noqa: BLE001
            pass
    if out != text:
        ctx.generalized = True
    return out


def _institution_ranges(text: str) -> List[Tuple[int, int]]:
    if len(text) > 20000 or not _INST_HINT.search(text):
        return []
    return [(m.start(), m.end()) for m in fields.RE_INSTITUTION.finditer(text)]


_INST_HINT = re.compile(r"Hosp|Home|Clinic|College|Institute|Memorial|Trust|Mission|Cent|Diagnostic|Patholog|Lab|"
                        r"TPA|Insurance|Assurance|Ward|Wing|Block|Unit|OPD|ICU|Dispensary|Foundation|Society|"
                        r"अस्पताल|चिकित्सालय|हॉस्पिटल|क्लिनिक|होम|कॉलेज|ट्रस्ट|संस्थान|वार्ड")


def scrub_text(text: str, ctx: _Ctx, mode: str = "full", dates_on: bool = True, ages_on: bool = True,
               psn_fallback: bool = False, collapse: bool = False) -> str:
    """Replace identity spans, then shift dates and band ages in the text between them.

    mode "ids": only identifiers and known names; "label": identifiers and known names, no
    generalisation (headers, keys); "full": everything detect finds."""
    if not isinstance(text, str) or not text:
        return text
    spans = _detect(text, ctx)
    inst = _institution_ranges(text)
    keep = []
    for sp in spans:
        if inst and sp.kind in NAME_KINDS and any(a <= sp.start and sp.end <= b for a, b in inst):
            continue              # "<person> Memorial Hospital": the institution stays
        if sp.start < 0 or sp.end > len(text) or sp.end <= sp.start:
            continue
        if mode in ("ids", "label"):
            if sp.kind in ID_KINDS:
                keep.append(sp)
            elif sp.kind in NAME_KINDS and _is_known_name(text[sp.start:sp.end], ctx):
                keep.append(sp)
            continue
        keep.append(sp)
    if mode == "full" and ctx.known.own_keys:
        extra = _own_token_spans(text, ctx, keep)
        if extra:
            keep = sorted(keep + extra, key=lambda sp: (sp.start, sp.end))
    psn_name = None
    if psn_fallback and ctx.psn and not ctx.has_pid and not ctx.psn_placed:
        if not any(sp.kind == "MRN" for sp in keep):
            for sp in keep:
                if sp.kind == "PATIENT_NAME":
                    psn_name = sp
                    break
    reps = []  # type: List[Tuple[int, int, str, str]]
    for sp in keep:
        surf = text[sp.start:sp.end]
        k = sp.kind
        if k in NAME_KINDS:
            _note_name(surf)
        if k == "PATIENT_NAME":
            if sp is psn_name:
                r = ctx.psn or "[NAME]"
                ctx.psn_placed = True
            else:
                r = "[NAME]"
        elif k == "RELATIVE_NAME":
            r = "[RELATIVE]"
        elif k == "PERSON":
            r = "[PERSON]"
        elif k == "MRN":
            r = _mrn(surf, sp.value, ctx)
        elif k in _ID_PH:
            r = _ID_PH[k]
        elif k in _ADDR_KINDS:
            r = "[ADDRESS]"
            ctx.generalized = True
        elif k == "PIN":
            r = _pin_mask(surf, ctx)
            ctx.generalized = True
        elif k == "DOB":
            r = _dob(surf, ctx)
            ctx.generalized = True
        elif k == "DISTRICT":
            if mode != "full" or not _suppress_district(surf, ctx, text, sp.start, sp.end):
                continue
            r = "[DISTRICT]"
            ctx.generalized = True
        elif k == "AGE":
            if not ages_on and mode != "full":
                continue
            r = _band(surf, sp.value, ctx)
            if r == surf:
                continue
            ctx.generalized = True
            reps.append((sp.start, sp.end, r, ""))
            continue
        else:
            continue  # DISTRICT, GENDER and anything unknown stay
        reps.append((sp.start, sp.end, r, k))
    if collapse and reps:
        merged = [reps[0]]
        for s, e, r, k in reps[1:]:
            ps, pe, pr, pk = merged[-1]
            if r == "[ADDRESS]" and pr == "[ADDRESS]" and _GAP_JOIN.match(text[pe:s]):
                merged[-1] = (ps, e, pr, pk)
                ctx.count(k)
                continue
            merged.append((s, e, r, k))
        reps = merged
    parts = []
    pos = 0
    for s, e, r, k in reps:
        if s < pos:
            continue
        parts.append(_gap(text[pos:s], ctx, dates_on, ages_on))
        parts.append(r + "\n" * text.count("\n", s, e))
        if k:
            ctx.count(k)
        pos = e
    parts.append(_gap(text[pos:], ctx, dates_on, ages_on))
    res = "".join(parts)
    if mode == "full" and _KIN_HINT.search(res):
        res2 = _KIN_TAIL.sub(lambda m: m.group(1) + "[RELATIVE]", res)
        if res2 != res:
            ctx.count("RELATIVE_NAME")
            res = res2
    return res


# "<patient> ke parijan <relative>": the words after the kinship phrase name the relative.
_KIN_HINT = re.compile(r"parijan|परिजन|rishtedar|रिश्तेदार", re.I)
_KIN_WORD = r"(?:[A-Z][a-z]+\.?|[\u0900-\u097F]+|\[NAME\]|\[RELATIVE\]|\[PERSON\])"
_KIN_TAIL = re.compile(r"((?:\bke|\bki|के|की)\s+(?:parijan|rishtedar|परिजन|रिश्तेदार)\s*[:\-]?\s*)"
                       r"(?!(?:ko|ne|se|का|को|ने|से)\b)" + _KIN_WORD + r"(?:\s+" + _KIN_WORD + r"){0,3}(?=\s*(?:[:,.;|]|$))")


def _scrub_any(text: str, ctx: _Ctx, mode: str = "full", **kw: Any) -> str:
    """scrub_text, also looking inside a base64 payload."""
    if isinstance(text, str) and len(text) >= 24 and " " not in text.strip():
        dec = try_b64_text(text)
        if dec is not None:
            kw.pop("psn_fallback", None)
            clean = scrub_text(dec, ctx, "full", **kw)
            if clean == dec:
                return text
            return base64.b64encode(clean.encode("utf-8")).decode("ascii")
    return scrub_text(text, ctx, mode, **kw)


# ----------------------------------------------------------------------------- typed values

_RE_REF_TOKEN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9#/._\-]{0,30}$")
_RE_MONEY = re.compile(r"^(?:(?:rs\.?|inr|₹)\s*)?[0-9][0-9,]*(?:\.[0-9]{1,2})?\s*(?:/-)?$", re.I)


def _is_reference(v: str, ctx: _Ctx) -> bool:
    """A single reference-number token or an amount under a reference / quantity column: kept, unless
    it is an identifier already known for some patient (their phone, Aadhaar or hospital id)."""
    t = to_ascii_digits(v.strip())
    if _RE_MONEY.match(t):
        return True
    if not _RE_REF_TOKEN.match(t) or not any(c.isdigit() for c in t):
        return False
    nv = norm_id(t)
    dg = "".join(_DIGITS.findall(t))
    if nv in ctx.all_ids or (len(dg) >= 5 and dg in ctx.all_ids):
        return False
    return True


def _is_id_number(v: Any, ctx: _Ctx) -> bool:
    s = str(v)
    if len(s) >= 5 and s in ctx.all_ids:
        return True
    if len(s) < 10:
        return False
    try:
        return any(sp.start == 0 and sp.end == len(s) for sp in find_identifiers(s))
    except Exception:  # noqa: BLE001
        return False


_WARD_ADDR = re.compile(r"(?<![A-Za-z])(?:Ward|Wd)\.?\s*(?:No\.?\s*)?[0-9]+(?![0-9]|\s*\()", re.I)


_ADDR_SEG_KEEP = re.compile(r"^\[[A-Z\-]+\]$")


def _address_segments(v: str, out: str, ctx: _Ctx) -> str:
    """Address cell: every comma segment before the last is an address part, even an unclassified
    small town that no cue caught; only the last segment (district / city / state) may survive."""
    segs = v.split(",")
    if len(segs) < 2:
        return out
    for seg in segs[:-1]:
        w = seg.strip(" \t.;:-")
        if not w or not re.search(r"[A-Za-z\u0900-\u097F]", w) or _ADDR_SEG_KEEP.match(w):
            continue
        rx = re.compile(r"(?:(?<=^)|(?<=[,;]))([ \t]*)" + re.escape(w) + r"(?=[ \t.;:-]*(?:,|$))")
        new = rx.sub(lambda m: m.group(1) + "[ADDRESS]", out, count=1)
        if new != out:
            ctx.count("ADDRESS")
            ctx.generalized = True
            out = new
    return re.sub(r"\[ADDRESS\](?:[ \t]*,[ \t]*\[ADDRESS\])+", "[ADDRESS]", out)


_STATES = frozenset(privacy.place_key(x) for x in (
    "andhra pradesh", "arunachal pradesh", "assam", "bihar", "chhattisgarh", "goa", "gujarat", "haryana",
    "himachal pradesh", "jharkhand", "karnataka", "kerala", "madhya pradesh", "maharashtra", "manipur",
    "meghalaya", "mizoram", "nagaland", "odisha", "orissa", "punjab", "rajasthan", "sikkim", "tamil nadu",
    "telangana", "tripura", "uttar pradesh", "uttarakhand", "west bengal", "delhi", "new delhi",
    "jammu and kashmir", "ladakh", "puducherry", "chandigarh", "india", "mp", "up", "tn", "ap", "wb"))


def _area_segment(w: str, ctx: _Ctx) -> bool:
    """A comma segment that is only a district / state (with an optional PIN): it may stay."""
    core = re.sub(r"[\s\-:]*(?:pin\s*[:\-]?\s*)?[0-9०-९]{3}\s*[0-9०-९xX]{3}\s*$", "", w, flags=re.I).strip(" .;:-")
    if not core:
        return True
    pk = privacy.place_key(core)
    if pk in _STATES or pk in (getattr(ctx.dec, "districts", None) or ()):
        return True
    if core.casefold() in DISTRICTS or " ".join(core.casefold().split()) in DISTRICTS:
        return True
    try:
        sps = [sp for sp in _detect(core, ctx) if sp.kind == "DISTRICT"]
    except Exception:  # noqa: BLE001
        return False
    return any(sp.start <= 1 and sp.end >= len(core) - 1 for sp in sps)


_ADDR_PIN = re.compile(r"(?:pin\s*[:\-]?\s*)?[0-9\u0966-\u096F]{3}\s?[0-9\u0966-\u096F]{3}", re.I)
# a six-digit PIN at the end of a district / state segment ("Hyderabad 500036", "Rajkot - 360002")
_ADDR_PIN_TAIL = re.compile(r"(^|[\s\-:])([0-9\u0966-\u096F]{3}\s?[0-9\u0966-\u096F]{3})(?=[\s.;]*$)")


def _pin_count(pin: str, ctx: _Ctx) -> str:
    ctx.count("PIN")
    ctx.generalized = True
    return _pin_mask(pin, ctx)


def _address_cells(v: str, out: str, ctx: _Ctx) -> str:
    """Address cell (its own column / key): every comma segment that is not just a district or a
    state is an address part (house, street, landmark, locality, village), whatever its script."""
    segs = v.split(",")
    if len(segs) < 2:
        return out
    parts = []  # type: List[str]
    for seg in segs:
        w = seg.strip(" \t.;:-")
        lead = seg[:len(seg) - len(seg.lstrip())]
        if not w or _ADDR_SEG_KEEP.match(w):
            parts.append(seg)
        elif not re.search(r"[A-Za-z\u0900-\u097F]", w):
            if _ADDR_PIN.fullmatch(w):
                ctx.count("PIN")
                ctx.generalized = True
                parts.append(lead + _pin_mask(w, ctx))
            elif re.search(r"[0-9\u0966-\u096F]", w) and not re.search(r"\[[A-Z\-]+\]", w):
                # a letter-free segment with digits ("16-8-244/3", "#12"): a door / plot number
                ctx.count("ADDRESS")
                ctx.generalized = True
                parts.append(lead + "[ADDRESS]")
            else:
                parts.append(scrub_text(seg, ctx, "full"))
        elif _area_segment(w, ctx):
            parts.append(_ADDR_PIN_TAIL.sub(lambda m: m.group(1) + _pin_count(m.group(2), ctx),
                                            scrub_text(seg, ctx, "full")))
        else:
            ctx.count("ADDRESS")
            ctx.generalized = True
            parts.append(lead + "[ADDRESS]")
    res = ",".join(parts)
    return re.sub(r"\[ADDRESS\](?:[ \t]*,[ \t]*\[ADDRESS\])+", "[ADDRESS]", res)


def _address(v: str, ctx: _Ctx) -> str:
    out = scrub_text(v, ctx, "full", collapse=True)
    out = _address_segments(v, out, ctx)
    if "," in v and "\n" not in v and len(v) <= 300:
        out = _address_cells(v, out, ctx)
    out2 = _WARD_ADDR.sub("[ADDRESS]", out)
    if out2 != out:
        ctx.count("ADDRESS")
        ctx.generalized = True
        out = out2
    if out == v and v.strip():
        dist = [sp for sp in _detect(v, ctx) if sp.kind == "DISTRICT"]
        ctx.count("ADDRESS")
        ctx.generalized = True
        if dist:
            d = v[dist[0].start:dist[0].end]
            if _suppress_district(d, ctx):
                ctx.count("DISTRICT")
                return "[ADDRESS], [DISTRICT]"
            return "[ADDRESS], " + d
        return "[ADDRESS]"
    return out


def typed_value(v: Any, ftype: str, ctx: _Ctx, order: Optional[str] = None) -> Any:
    """Sanitised value of one structured slot of type `ftype`. Never raises."""
    saved = ctx.order
    if order:
        ctx.order = order
    try:
        return _typed(v, ftype, ctx)
    except Exception:  # noqa: BLE001
        if isinstance(v, str):
            return "[REDACTED]" if v.strip() else v
        if isinstance(v, (int, float)) and not isinstance(v, bool):
            return 0
        return v
    finally:
        ctx.order = saved


def _typed(v: Any, ftype: str, ctx: _Ctx) -> Any:
    if v is None or isinstance(v, (bool, dict, list)):
        return v
    if isinstance(v, str) and not v.strip():
        return v
    num = isinstance(v, (int, float))
    if not num and not isinstance(v, str):
        return v
    if ftype == fields.PATIENT_ID:
        ctx.count("MRN")
        if num:
            return 0
        return _mrn(v, "", ctx)
    if ftype in _NAME_FIELDS:
        ctx.count("PATIENT_NAME")
        if num:
            return 0
        if ctx.psn and not ctx.has_pid and not ctx.name_slot_used:
            ctx.name_slot_used = True
            ctx.psn_placed = True
            return ctx.psn
        return "[NAME]"
    if ftype == fields.RELATIVE:
        ctx.count("RELATIVE_NAME")
        if num:
            return 0
        m = _REL_PREFIX.match(v)
        return (m.group(0) if m else "") + "[RELATIVE]"
    if ftype in _FIELD_PH:
        ctx.count(_FIELD_COUNT.get(ftype, "identifiers"))
        if ftype in (fields.HOUSE, fields.LOCALITY, fields.VILLAGE, fields.TEHSIL):
            ctx.generalized = True
        if num:
            return 0
        return _FIELD_PH[ftype]
    if ftype == fields.ADDRESS:
        if num:
            return 0
        return _address(v, ctx)
    if ftype == fields.PIN:
        ctx.count("PIN")
        ctx.generalized = True
        if num:
            s = str(int(v))
            if ctx.dec.suppress_geo:
                return 0
            return int(s[:3] + "0" * (len(s) - 3)) if len(s) > 3 else 0
        return _pin_mask(v, ctx)
    if ftype in (fields.DOB, fields.DATE):
        cd = dates.compact_ymd(v) if (not num or isinstance(v, int)) and not isinstance(v, bool) else None
        if cd is not None:
            return _compact_date(v, cd, ftype, ctx)
    if ftype == fields.DOB:
        if num:
            if ctx.pol.dob_mode == "remove":
                ctx.count("DOB")
                ctx.generalized = True
                return "[DOB]"
            return v
        ctx.count("DOB")
        ctx.generalized = True
        return _dob(v, ctx)
    if ftype == fields.DATE:
        if num:
            return v
        if not ctx.do_shift:
            return scrub_text(v, ctx, "ids", dates_on=False, ages_on=False)
        out = dates.shift_text(v, ctx.shift, ctx.order, ctx.default_year)
        if out != v:
            ctx.generalized = True
            if ctx.watch is not None:
                ctx.watch.check(ctx, v, out, ctx.order, ctx.default_year)
            return out
        return scrub_text(v, ctx, "ids", ages_on=False)
    if ftype in (fields.AGE, fields.AGE_SEX):
        if num:
            if isinstance(v, float) and v != int(v):
                return v
            ctx.generalized = True
            return _age_band(int(v), ctx)
        r = _band(v, "", ctx)
        if r != v:
            ctx.generalized = True
        return r
    if num:
        if ftype in _ID_NUM_FIELDS or (ftype not in _KEEP_FIELDS and isinstance(v, int) and _is_id_number(v, ctx)):
            ctx.count("identifiers")
            return 0
        return v
    if ftype == fields.DISTRICT and ctx.dec.suppress_geo:
        ctx.count("DISTRICT")
        ctx.generalized = True
        return "[DISTRICT]"
    if ftype == fields.HOSPITAL and fields.is_institution(v):
        return v                  # an institution named after a person is still an institution
    if ftype in (fields.DISTRICT, fields.STATE, fields.GENDER, fields.RELATION, fields.DOCTOR, fields.HOSPITAL):
        return scrub_text(v, ctx, "ids", dates_on=False, ages_on=False)
    if ftype in (fields.CLINICAL, fields.OTHER_ID) and _is_reference(v, ctx):
        return v                  # batch / sample / call / bill number or an amount: not a person's id
    if ftype in (fields.CLINICAL, fields.OTHER_ID):
        return _scrub_any(v, ctx, "ids", ages_on=False)
    return _scrub_any(v, ctx, "full", psn_fallback=True)


# ----------------------------------------------------------------------------- labels

_LABEL_NEEDS = re.compile(r"[A-Z]|[0-9]{4,}|@|[ऀ-ॿ]")


def _scrub_label(s: str, fs: _File) -> str:
    """A CSV header or JSON key, changed only when it holds an identifier or a known name."""
    if not isinstance(s, str) or not s or not _LABEL_NEEDS.search(s):
        return s
    u = s.translate(_UNDERSCORE)
    # a title cell ("Chart: Mr <name> (IP <no>) Ph <no>") is free text, not a column name
    mode = "full" if (":" in u or len(u.split()) > 4) and len(u) > 24 else "label"
    out = scrub_text(u, fs.label_ctx, mode, dates_on=False, ages_on=False)
    return out if out != u else s


def _unique(name: str, used: Set[str]) -> str:
    base, n = name, 2
    while name in used:
        name = "%s_%d" % (base, n)
        n += 1
    return name


# ----------------------------------------------------------------------------- CSV

def _csv(pf: ParsedFile, fs: _File) -> str:
    labels, rows, hl = csv_view(pf)
    rows = [list(r) for r in rows]
    raw_header = list(pf.header)
    head_rows = [raw_header, list(pf.rows[0]) if pf.rows else []][:hl]
    ncol = max([len(labels)] + [len(r) for r in rows]) if (labels or rows) else 0
    types = []  # type: List[str]
    orders = []  # type: List[str]
    for i in range(ncol):
        label = labels[i] if i < len(labels) else ""
        vals = [r[i] for r in rows if i < len(r)]
        try:
            t = fields.classify_column(label, vals)
        except Exception:  # noqa: BLE001
            t = fields.OTHER
        types.append(t)
        try:
            orders.append(dates.infer_order(vals, label))
        except Exception:  # noqa: BLE001
            orders.append("dmy")
    if any(not str(x or "").strip() for x in (labels or [""] * ncol)) or len(labels) < ncol:
        try:
            types = fields.refine_unlabelled(labels, types, [[r[i] for r in rows if i < len(r)] for i in range(ncol)])
        except Exception:  # noqa: BLE001
            pass
    new_heads = []  # type: List[List[str]]
    for hr in head_rows:
        new_header = []  # type: List[str]
        used = set()  # type: Set[str]
        for h in hr:
            nh = _scrub_label(h, fs)
            if nh != h:
                nh = _unique(nh, used | set(hr))
            used.add(nh)
            new_header.append(nh)
        new_heads.append(new_header)
    out_rows = []
    for ri, row in enumerate(rows):
        ctx = fs.ctx.get("row:%d" % ri) or fs.file_ctx
        ctx.has_pid = any(i < len(row) and types[i] == fields.PATIENT_ID and row[i].strip()
                          for i in range(ncol))
        new = []
        for i, v in enumerate(row):
            t = types[i] if i < len(types) else fields.OTHER
            x = typed_value(v, t, ctx, orders[i] if i < len(orders) else None)
            new.append(x if isinstance(x, str) else str(x))
        out_rows.append(new)
    lines = new_heads + out_rows
    copy = ParsedFile(rel=pf.rel, sha256=pf.sha256, kind=pf.kind, delimiter=pf.delimiter,
                      header=lines[0] if lines else [], rows=lines[1:])
    return dump_csv(copy)


# ----------------------------------------------------------------------------- JSON

def _esc(k: str) -> str:
    return k.replace("~", "~0").replace("/", "~1")


def _has_pid(node: Any, keys: List[str]) -> bool:
    stack = [(node, keys, 0)]
    while stack:
        x, ks, d = stack.pop()
        if d > 300:
            continue
        if isinstance(x, dict):
            for k, y in x.items():
                stack.append((y, ks + [str(k)], d + 1))
        elif isinstance(x, list):
            for y in x:
                stack.append((y, ks, d + 1))
        elif isinstance(x, str) and x.strip():
            try:
                if fields.json_key_type(ks, x) == fields.PATIENT_ID:
                    return True
            except Exception:  # noqa: BLE001
                pass
    return False


def _json(data: Any, fs: _File) -> Any:
    def walk(node: Any, keys: List[str], ptr: str, depth: int) -> Any:
        loc = ptr if ptr else "doc"
        if loc in fs.ctx and isinstance(node, (dict, list)):
            fs.ctx[loc].has_pid = _has_pid(node, keys) or bool(keyed_record_id(loc))
        ctx = fs.ctx_for_ptr(ptr) if ptr else fs.main_ctx() if "doc" in fs.ctx else fs.file_ctx
        if depth > 400:
            return "[REDACTED]" if isinstance(node, str) else node
        if isinstance(node, dict):
            out = {}  # type: Dict[str, Any]
            orig = set(str(k) for k in node)
            for k, v in node.items():
                ks = str(k)
                cptr = ptr + "/" + _esc(ks)
                if cptr in fs.ctx and isinstance(v, dict) and keyed_record_id(cptr):
                    # record collection keyed by patient id: the key is the record's hospital id
                    nk = _unique(fs.psns.get(cptr) or "[ID]", set(out) | orig)
                    fs.ctx[cptr].count("MRN")
                    out[nk] = walk(v, keys, cptr, depth + 1)
                    continue
                nk = _scrub_label(ks, fs)
                if nk != ks:
                    nk = _unique(nk, set(out) | orig)
                elif nk in out:
                    nk = _unique(nk, set(out))
                out[nk] = walk(v, keys + [ks], cptr, depth + 1)
            return out
        if isinstance(node, list):
            return [walk(v, keys, ptr + "/%d" % i, depth + 1) for i, v in enumerate(node)]
        try:
            t = fields.json_key_type(keys, node)
        except Exception:  # noqa: BLE001
            t = fields.OTHER
        order = None
        if t in (fields.DATE, fields.DOB) and isinstance(node, str):
            try:
                order = dates.infer_order([node], keys[-1] if keys else "")
            except Exception:  # noqa: BLE001
                order = None
            if order == "dmy" and ctx.order == "mdy":
                order = None
        return typed_value(node, t, ctx, order)

    return walk(data, [], "", 0)


# ----------------------------------------------------------------------------- FHIR

_FHIR_KEEP = frozenset({"resourceType", "id", "fullUrl", "reference", "system", "code", "status", "use",
                        "unit", "url", "profile", "meta", "contentType", "language", "gender", "country",
                        "versionId", "class", "valueQuantity", "referenceRange", "interpretation",
                        "intent", "category", "priority", "dosageInstruction", "coding"})
_FHIR_FULL = frozenset({"div", "valueString", "conclusion", "description", "comment", "text"})
_FHIR_UNTOUCHED = frozenset({"Practitioner", "Organization", "Location", "PractitionerRole"})


class _Fhir:
    def __init__(self, ctx: _Ctx, data: Any) -> None:
        self.ctx = ctx
        self.person_refs = set()  # type: Set[str]
        try:
            for e in data.get("entry") or []:
                if not isinstance(e, dict):
                    continue
                r = e.get("resource") or {}
                if isinstance(r, dict) and r.get("resourceType") in ("Patient", "RelatedPerson"):
                    if e.get("fullUrl"):
                        self.person_refs.add(str(e["fullUrl"]))
                    if r.get("id"):
                        self.person_refs.add("%s/%s" % (r["resourceType"], r["id"]))
        except Exception:  # noqa: BLE001
            pass

    def bundle(self, data: Dict[str, Any]) -> Dict[str, Any]:
        out = {}  # type: Dict[str, Any]
        for k, v in data.items():
            if k == "entry" and isinstance(v, list):
                out[k] = [self.entry(e) for e in v]
            elif k == "meta":
                out[k] = self._meta(v)
            elif k == "timestamp" and isinstance(v, str):
                out[k] = self._shift_instant(v)     # bundle assembly time tracks the real visit
            elif k in ("timestamp", "type") or k in _FHIR_KEEP:
                out[k] = v
            else:
                out[k] = self.generic(v, [k], "Bundle")
        return out

    def entry(self, e: Any) -> Any:
        if not isinstance(e, dict):
            return e
        out = {}  # type: Dict[str, Any]
        for k, v in e.items():
            out[k] = self.resource(v) if k == "resource" and isinstance(v, dict) else v
        return out

    def resource(self, r: Dict[str, Any]) -> Dict[str, Any]:
        rt = r.get("resourceType")
        try:
            if rt in _FHIR_UNTOUCHED:
                return r
            if rt == "Patient":
                return self.person(r, "[NAME]", True)
            if rt == "RelatedPerson":
                return self.person(r, "[RELATIVE]", False)
            return self.generic(r, [], str(rt or ""))
        except Exception:  # noqa: BLE001
            return _redact_strings(r)

    def _name(self, n: Any, ph: str) -> Any:
        if isinstance(n, list):
            return [self._name(x, ph) for x in n]
        if isinstance(n, str):
            return ph if n.strip() else n
        if not isinstance(n, dict):
            return n
        out = {}  # type: Dict[str, Any]
        for k, v in n.items():
            if k in ("text", "family", "given", "suffix"):
                if isinstance(v, list):
                    out[k] = [ph if isinstance(x, str) and x.strip() else x for x in v]
                else:
                    out[k] = ph if isinstance(v, str) and v.strip() else v
            elif k in ("use", "prefix", "period"):
                out[k] = v
            else:
                out[k] = self.generic(v, [k], "")
        self.ctx.count("PATIENT_NAME" if ph == "[NAME]" else "RELATIVE_NAME")
        return out

    def _telecom(self, t: Any) -> Any:
        if isinstance(t, list):
            return [self._telecom(x) for x in t]
        if not isinstance(t, dict):
            return t
        out = dict(t)
        v = t.get("value")
        if isinstance(v, str) and v.strip():
            em = str(t.get("system", "")).lower() == "email" or "@" in v
            out["value"] = "[EMAIL]" if em else "[PHONE]"
            self.ctx.count("EMAIL" if em else "PHONE")
        return out

    def _address(self, a: Any) -> Any:
        if isinstance(a, list):
            return [self._address(x) for x in a]
        if not isinstance(a, dict):
            return a
        out = {}  # type: Dict[str, Any]
        for k, v in a.items():
            if k == "line":
                if isinstance(v, list):
                    out[k] = ["[ADDRESS]" if isinstance(x, str) and x.strip() else x for x in v]
                else:
                    out[k] = "[ADDRESS]" if isinstance(v, str) and v.strip() else v
                self.ctx.count("ADDRESS")
            elif k in ("city", "text"):
                out[k] = "[ADDRESS]" if isinstance(v, str) and v.strip() else v
                self.ctx.count("ADDRESS")
            elif k == "postalCode":
                out[k] = _pin_mask(v, self.ctx) if isinstance(v, str) and v.strip() else v
                self.ctx.count("PIN")
            elif k == "district" and isinstance(v, str) and v.strip() and self.ctx.dec.suppress_geo:
                out[k] = "[DISTRICT]"
                self.ctx.count("DISTRICT")
            elif k in ("district", "state", "country", "use", "type", "period"):
                out[k] = v
            else:
                out[k] = self.generic(v, [k], "")
        self.ctx.generalized = True
        return out

    def _patient_ids(self, ids: Any) -> Any:
        if not isinstance(ids, list):
            return ids
        out = []
        for ident in ids:
            if not isinstance(ident, dict):
                out.append(ident)
                continue
            n = dict(ident)
            v = ident.get("value")
            if isinstance(v, str) and v.strip():
                sysv = str(ident.get("system", "")).lower()
                codes = []
                try:
                    for c in (ident.get("type") or {}).get("coding") or []:
                        codes.append(str(c.get("code", "")).upper())
                except Exception:  # noqa: BLE001
                    pass
                if "MR" in codes or any(w in sysv for w in ("uhid", "mrn", "/mr", "patient", "registration")):
                    if self.ctx.psn:
                        n["value"] = self.ctx.psn
                        self.ctx.psn_placed = True
                    else:
                        n["value"] = "[ID]"
                    self.ctx.count("MRN")
                else:
                    spans = [sp for sp in _detect(v, self.ctx) if sp.kind in _ID_PH]
                    if spans:
                        ph, kind = _ID_PH[spans[0].kind], spans[0].kind
                    elif "abha" in sysv or "healthid" in sysv or "abdm" in sysv:
                        ph, kind = "[ABHA]", "ABHA_NUMBER"
                    elif "aadhaar" in sysv or "aadhar" in sysv or "uidai" in sysv:
                        ph, kind = "[AADHAAR]", "AADHAAR"
                    elif "pmjay" in sysv or "insur" in sysv or "policy" in sysv:
                        ph, kind = "[INSURANCE-ID]", "INSURANCE_ID"
                    else:
                        ph, kind = "[ID]", "MRN"
                    n["value"] = ph
                    self.ctx.count(kind)
            out.append(n)
        return out

    def person(self, r: Dict[str, Any], ph: str, is_patient: bool) -> Dict[str, Any]:
        out = {}  # type: Dict[str, Any]
        for k, v in r.items():
            if k == "meta":
                out[k] = self._meta(v)
            elif k in ("resourceType", "id", "gender", "active", "deceasedBoolean", "communication",
                     "managingOrganization", "generalPractitioner", "maritalStatus", "relationship"):
                out[k] = v
            elif k == "name":
                out[k] = self._name(v, ph)
            elif k == "identifier":
                if is_patient:
                    out[k] = self._patient_ids(v)
                else:
                    out[k] = [dict(x, value="[ID]") if isinstance(x, dict) and isinstance(x.get("value"), str)
                              and x["value"].strip() else x for x in v] if isinstance(v, list) else v
            elif k == "telecom":
                out[k] = self._telecom(v)
            elif k == "address":
                out[k] = self._address(v)
            elif k == "birthDate" and isinstance(v, str):
                mode = self.ctx.pol.dob_mode
                if not v.strip():
                    out[k] = v
                    continue
                self.ctx.count("DOB")
                self.ctx.generalized = True
                if mode == "remove":
                    continue  # a FHIR date cannot hold a placeholder: drop the element
                if mode == "year":
                    m = re.match(r"\s*([0-9]{4})", v)
                    if m:
                        out[k] = m.group(1)
                    continue
                out[k] = dates.shift_text(v, self.ctx.shift, "dmy")
            elif k == "_birthDate" and self.ctx.pol.dob_mode != "shift":
                continue
            elif k == "contact" and isinstance(v, list):
                out[k] = [self._contact(c) for c in v]
            elif k == "text" and isinstance(v, dict):
                out[k] = self.narrative(v)
            else:
                out[k] = self.generic(v, [k], "Patient")
        return out

    def _contact(self, c: Any) -> Any:
        if not isinstance(c, dict):
            return c
        out = {}  # type: Dict[str, Any]
        for k, v in c.items():
            if k == "name":
                out[k] = self._name(v, "[RELATIVE]")
            elif k == "telecom":
                out[k] = self._telecom(v)
            elif k == "address":
                out[k] = self._address(v)
            elif k in ("relationship", "gender", "period"):
                out[k] = v
            else:
                out[k] = self.generic(v, [k], "")
        return out

    def narrative(self, t: Dict[str, Any]) -> Dict[str, Any]:
        out = dict(t)
        div = t.get("div")
        if isinstance(div, str):
            out["div"] = scrub_text(div, self.ctx, "full")
        return out

    def _display(self, parent: Dict[str, Any], v: str) -> str:
        ref = str(parent.get("reference", ""))
        if v.lstrip().lower().startswith(("dr", "डॉ")):
            return v
        if ref and (ref in self.person_refs or ref.startswith(("Patient/", "RelatedPerson/"))):
            self.ctx.count("PATIENT_NAME")
            return "[NAME]"
        return scrub_text(v, self.ctx, "ids", ages_on=False)

    def generic(self, node: Any, keys: List[str], rt: str) -> Any:
        ctx = self.ctx
        if isinstance(node, dict):
            out = {}  # type: Dict[str, Any]
            is_coding = "code" in node and "system" in node
            for k, v in node.items():
                if k == "meta":
                    out[k] = self._meta(v)
                elif k in _FHIR_KEEP:
                    out[k] = v
                elif k == "identifier":
                    out[k] = self._other_ids(v, rt == "Encounter")
                elif k == "display" and isinstance(v, str):
                    out[k] = v if is_coding else self._display(node, v)
                elif k == "text" and isinstance(v, dict) and "div" in v:
                    out[k] = self.narrative(v)
                elif k == "data" and isinstance(v, str):
                    out[k] = self._b64(v)
                else:
                    out[k] = self.generic(v, keys + [k], rt)
            return out
        if isinstance(node, list):
            return [self.generic(x, keys, rt) for x in node]
        if isinstance(node, str):
            if not node.strip():
                return node
            if _FHIR_DATE.match(node):
                try:
                    nv = dates.shift_text(node, ctx.shift, "dmy")
                except Exception:  # noqa: BLE001
                    nv = node
                if nv != node:
                    ctx.generalized = True
                    if ctx.watch is not None:
                        ctx.watch.check(ctx, node, nv, "dmy")
                return nv
            last = keys[-1] if keys else ""
            if last in _FHIR_FULL or len(node) > 60:
                return _scrub_any(node, ctx, "full")
            return _scrub_any(node, ctx, "ids", ages_on=False)
        if isinstance(node, int) and not isinstance(node, bool) and _is_id_number(node, ctx):
            ctx.count("identifiers")
            return 0
        return node

    def _shift_instant(self, v: str) -> str:
        """A FHIR date / dateTime / instant moved by the record's shift (same syntax, so R4 stays valid)."""
        if not v.strip() or not _FHIR_DATE.match(v.strip()) or not self.ctx.do_shift:
            return v
        try:
            nv = dates.shift_text(v, self.ctx.shift, "dmy")
        except Exception:  # noqa: BLE001
            return v
        if nv != v:
            self.ctx.generalized = True
            if self.ctx.watch is not None:
                self.ctx.watch.check(self.ctx, v, nv, "dmy")
        return nv

    def _meta(self, v: Any) -> Any:
        if not isinstance(v, dict):
            return v
        out = dict(v)
        if isinstance(v.get("lastUpdated"), str):
            out["lastUpdated"] = self._shift_instant(v["lastUpdated"])
        src = v.get("source")
        if isinstance(src, str) and src.strip():
            out["source"] = scrub_text(src, self.ctx, "ids", dates_on=False, ages_on=False)
        return out

    def _other_ids(self, v: Any, encounter: bool) -> Any:
        if isinstance(v, list):
            return [self._other_ids(x, encounter) for x in v]
        if isinstance(v, dict):
            out = dict(v)
            val = v.get("value")
            if isinstance(val, str) and val.strip():
                if encounter:
                    out["value"] = "[ENC-ID]"
                    self.ctx.count("MRN")
                else:
                    out["value"] = scrub_text(val, self.ctx, "ids", dates_on=False, ages_on=False)
            return out
        return v

    def _b64(self, v: str) -> str:
        dec = try_b64_text(v)
        if dec is None:
            return v
        clean = scrub_text(dec, self.ctx, "full")
        if clean == dec:
            return v
        return base64.b64encode(clean.encode("utf-8")).decode("ascii")


def _redact_strings(v: Any) -> Any:
    if isinstance(v, dict):
        return {k: (x if k in _FHIR_KEEP else _redact_strings(x)) for k, x in v.items()}
    if isinstance(v, list):
        return [_redact_strings(x) for x in v]
    if isinstance(v, str) and v.strip():
        return "[REDACTED]"
    return v


def _fhir(data: Any, fs: _File) -> Any:
    if not isinstance(data, dict):
        return _json(data, fs)
    ctx = fs.main_ctx()
    out = _Fhir(ctx, data).bundle(data)
    if ctx.psn and not ctx.psn_placed:
        try:
            for e in out.get("entry") or []:
                r = e.get("resource") or {}
                if r.get("resourceType") == "Patient" and isinstance(r.get("name"), list) and r["name"]:
                    n0 = r["name"][0]
                    if isinstance(n0, dict):
                        n0["text"] = ctx.psn
                        ctx.psn_placed = True
                        break
        except Exception:  # noqa: BLE001
            pass
    return out


# ----------------------------------------------------------------------------- text documents

def _text(pf: ParsedFile, fs: _File) -> str:
    ctx = fs.main_ctx()
    text = pf.text or ""
    out = scrub_text(text, ctx, "full", psn_fallback=True)
    if ctx.psn and ctx.psn not in out:
        lines = out.split("\n")
        for i, line in enumerate(lines):
            if line.strip():
                body = line.rstrip()
                lines[i] = body + " (" + ctx.psn + ")" + line[len(body):]
                ctx.psn_placed = True
                break
        out = "\n".join(lines)
    return out


# ----------------------------------------------------------------------------- file names

_SEG = re.compile(r"[^_ ]+|[_ ]+")


# Name words replaced in the content of the file being sanitised (for its output file name).
_SEEN_NAMES = set()  # type: Set[str]
_FILE_WORDS = frozenset({"family", "group", "report", "note", "notes", "letter", "summary", "card", "chat",
                         "export", "query", "reply", "patient", "record", "records", "request", "thread",
                         "consent", "form", "scan", "page", "copy", "final", "draft", "home", "visit",
                         "ward", "night", "shift", "round", "referral", "discharge", "admission", "baby",
                         "mother", "father", "wife", "husband", "son", "daughter", "doctor", "nurse",
                         "hospital", "clinic", "general", "case", "file", "list", "data", "diary"})


def _note_name(surface: str) -> None:
    if len(_SEEN_NAMES) > 5000:
        return
    for w in re.findall(r"[A-Za-z]{4,}", surface):
        lw = w.casefold()
        if lw not in _FILE_WORDS and lw not in _GENERIC_KEYS:
            _SEEN_NAMES.add(lw)


def _out_rel(pf: ParsedFile, fs: _File) -> str:
    rel = pf.rel
    folder, base = posixpath.split(rel)
    stem, ext = posixpath.splitext(base)
    if not stem:
        return rel
    ctx = fs.label_ctx
    bad = [False] * len(stem)
    variants = [stem.translate(_UNDERSCORE), stem.replace("-", " ").replace("_", " ")]
    for var in variants:
        try:
            spans = detect(var, ctx.known, "dmy")
        except Exception:  # noqa: BLE001
            spans = []
        for sp in spans:
            ok = sp.kind in ID_KINDS or sp.kind == "PIN"
            if sp.kind in NAME_KINDS and _is_known_name(var[sp.start:sp.end], ctx):
                ok = True
            if ok:
                for i in range(max(0, sp.start), min(len(stem), sp.end)):
                    bad[i] = True
    own = set()  # type: Set[str]
    for c in fs.ctx.values():
        own |= c.known.own_keys
    for m in re.finditer(r"[A-Za-z]{4,}", stem):
        w = m.group().casefold()
        if w in _FILE_WORDS:
            continue
        hit = w in _SEEN_NAMES
        if not hit and own:
            ks = [k for k in _name_keys(w) if k not in _GENERIC_KEYS]
            hit = bool(ks) and all(k in own for k in ks)
        if hit:
            for i in range(m.start(), m.end()):
                bad[i] = True
    for m in re.finditer(r"[^_ ]+", stem):
        seg = m.group()
        nv = norm_id(seg)
        dg = "".join(_DIGITS.findall(to_ascii_digits(seg)))
        if (len(nv) >= 4 and nv in fs.all_ids) or (len(dg) >= 5 and dg in fs.all_ids):
            for i in range(m.start(), m.end()):
                bad[i] = True
    if not any(bad):
        return rel
    psns = [fs.psns[k] for k in sorted(fs.psns)]
    tag = psns[0] if len(psns) == 1 and psns[0] else fs.env.keys.opaque(pf.sha256 or pf.rel)
    out = []  # type: List[str]
    last_bad = False
    for m in _SEG.finditer(stem):
        seg = m.group()
        if not seg.strip("_ "):
            out.append(seg)
            continue
        if any(bad[m.start():m.end()]):
            if last_bad:
                if out and not out[-1].strip("_ "):
                    out.pop()
                continue
            out.append(tag)
            last_bad = True
        else:
            out.append(seg)
            last_bad = False
    new_base = "".join(out) + ext
    return posixpath.join(folder, new_base) if folder else new_base


# ----------------------------------------------------------------------------- entry point

def _default_year(text: str, order: str) -> Optional[int]:
    try:
        for h in dates.find_dates(text[:200000], order):
            if h.has_year:
                return h.date.year
    except Exception:  # noqa: BLE001
        pass
    return None


def _sample_text(pf: ParsedFile) -> str:
    if pf.kind == KIND_CSV:
        return "\n".join(",".join(r) for r in pf.rows[:200])
    if pf.kind in (KIND_JSON, KIND_FHIR):
        try:
            return dump_json(pf.data)[:200000]
        except Exception:  # noqa: BLE001
            return ""
    return pf.text or ""


def sanitize_file(pf: ParsedFile, env: Env) -> Sanitized:
    if env.records and pf.rel in env.records:
        recs = list(env.records[pf.rel])
    else:
        try:
            recs = list(harvest_file(pf))
        except Exception:  # noqa: BLE001
            recs = []
    sample = _sample_text(pf)
    order = "dmy"
    try:
        order = dates.infer_order(_NUMDATE.findall(to_ascii_digits(sample)))
    except Exception:  # noqa: BLE001
        pass
    fs = _File(pf, env, recs, order, _default_year(sample, order))
    _SEEN_NAMES.clear()

    if pf.kind == KIND_CSV:
        content = _csv(pf, fs)
    elif pf.kind == KIND_FHIR:
        content = dump_json(_fhir(pf.data, fs))
    elif pf.kind == KIND_JSON:
        content = dump_json(_json(pf.data, fs))
    else:
        content = _text(pf, fs)
    try:
        out_rel = _out_rel(pf, fs)
    except Exception:  # noqa: BLE001
        out_rel = pf.rel

    counts = {"identifiers": 0}  # type: Dict[str, int]
    for c in fs.all_ctx():
        for k in sorted(c.counts):
            counts[k] = counts.get(k, 0) + c.counts[k]
    out_recs = []
    gen = 0
    for r in recs:
        c = fs.ctx.get(r.loc)
        status = "generalized" if (c is not None and c.generalized) else "sanitized"
        gen += status == "generalized"
        out_recs.append((r.loc, fs.psns.get(r.loc), status))
    counts["generalized"] = gen
    return Sanitized(out_rel=out_rel, content=content, records=out_recs, counts=counts)
