"""Record linkage into patients (PRD R4.1-R4.8, R4.10). Standard library only, Python 3.9+."""
from __future__ import annotations

import re
from typing import Dict, List, Optional, Set, Tuple

from .types import (
    ID_AADHAAR, ID_ABHA, ID_ABHA_ADDR, ID_EMAIL, ID_ENC, ID_INS, ID_PAN, ID_PHONE, ID_UHID,
    Facts, Patient, Record,
)

try:
    from .translit import full_name_key, name_key, name_tokens, same_name, same_token
except ImportError:  # pragma: no cover - fallback until translit lands
    def name_tokens(name: str) -> List[str]:
        return [t for t in re.split(r"[^\w]+", (name or "").lower()) if t]

    def name_key(token: str) -> str:
        return (token or "").strip().lower()

    def full_name_key(name: str) -> str:
        return " ".join(sorted(name_key(t) for t in name_tokens(name)))

    def same_token(a: str, b: str) -> bool:
        return name_key(a) == name_key(b)

    def same_name(a: str, b: str) -> bool:
        ta, tb = name_tokens(a), name_tokens(b)
        if not ta or not tb:
            return False
        if len(ta) > len(tb):
            ta, tb = tb, ta
        pool = list(tb)
        for t in ta:
            for i, u in enumerate(pool):
                if same_token(t, u):
                    del pool[i]
                    break
            else:
                return False
        return True


# ---------------------------------------------------------------- name compatibility
_REL_WORDS = frozenset({"wife", "husband", "son", "daughter", "father", "mother", "brother", "sister",
                        "w", "h", "of", "patni", "pati", "beta", "beti", "putra", "putri", "pita", "mata",
                        "bhai", "behen", "maa", "parijan", "attendant", "informant"})
_NASAL_STOP = (("ng", "nk"), ("nd", "nt"), ("mb", "mp"), ("nj", "nc"))
try:
    from .translit import GENERIC_NAME_PARTS as _GEN_WORDS
except ImportError:  # pragma: no cover
    _GEN_WORDS = frozenset()
_GEN_KEYS = frozenset(name_key(w) for w in _GEN_WORDS) - {""}


_IDENT_CACHE: Dict[str, Tuple[str, ...]] = {}
_TOK_CACHE: Dict[Tuple[str, str], int] = {}
_ST_CACHE: Dict[Tuple[str, str], bool] = {}


def _st(a: str, b: str) -> bool:
    k = (a, b)
    v = _ST_CACHE.get(k)
    if v is None:
        if len(_ST_CACHE) > 400000:
            _ST_CACHE.clear()
        v = _ST_CACHE[k] = bool(same_token(a, b))
    return v


def _ident_tokens(name: str) -> List[str]:
    hit = _IDENT_CACHE.get(name)
    if hit is None:
        if len(_IDENT_CACHE) > 200000:
            _IDENT_CACHE.clear()
        hit = _IDENT_CACHE[name] = tuple(_ident_tokens_impl(name))
    return list(hit)


def _ident_tokens_impl(name: str, keep_generic: bool = False) -> List[str]:
    """Identifying name tokens: titles dropped, a relation phrase cut off ("X's wife Y" -> Y,
    "Y wife of X" -> Y), generic parts dropped unless nothing else is left."""
    toks = name_tokens(name)
    for i, t in enumerate(toks):
        if t in _REL_WORDS and t not in ("of", "w", "h") and 0 < i:
            if i + 1 < len(toks) and toks[i + 1] == "of":
                toks = toks[:i]
            else:
                toks = [x for x in toks[i + 1:] if x != "of"]
            break
    toks = [t for t in toks if t != "s" or len(toks) <= 1]
    if keep_generic:
        return toks
    ident = [t for t in toks if name_key(t) not in _GEN_KEYS]
    return ident or toks


def _tok_eq(a: str, b: str) -> int:
    """0 no match, 1 initial match, 2 full match."""
    k = (a, b)
    v = _TOK_CACHE.get(k)
    if v is None:
        if len(_TOK_CACHE) > 400000:
            _TOK_CACHE.clear()
        v = _TOK_CACHE[k] = _tok_eq_impl(a, b)
    return v


def _tok_eq_impl(a: str, b: str) -> int:
    if len(a) == 1 or len(b) == 1:
        return 1 if a[0] == b[0] else 0
    if _st(a, b):
        return 2
    fa, fb = a, b
    for x, y in _NASAL_STOP:
        fa, fb = fa.replace(x, y), fb.replace(x, y)
    if (fa, fb) != (a, b) and min(len(a), len(b)) >= 5 and same_token(fa, fb):
        return 2
    return 0


def _cover(short: List[str], long_: List[str]) -> bool:
    """Every token of `short` is matched by a distinct token (or a joined pair) of `long_`,
    with at least one full (non-initial) match."""
    n = len(long_)

    def rec(i: int, used: int, full: bool) -> bool:
        if i == len(short):
            return full
        s = short[i]
        for j in range(n):
            if used >> j & 1:
                continue
            m = _tok_eq(s, long_[j])
            if m and rec(i + 1, used | 1 << j, full or m == 2):
                return True
        if len(s) >= 5:
            for j in range(n):
                if used >> j & 1 or len(long_[j]) < 2:
                    continue
                if long_[j][0] != s[0]:
                    continue
                for k in range(n):
                    if k == j or used >> k & 1 or len(long_[k]) < 2:
                        continue
                    if abs(len(long_[j]) + len(long_[k]) - len(s)) > 3:
                        continue
                    if _st(s, long_[j] + long_[k]) and rec(i + 1, used | 1 << j | 1 << k, True):
                        return True
        if i + 1 < len(short) and len(s) >= 2 and len(short[i + 1]) >= 2:
            joined = s + short[i + 1]
            for j in range(n):
                if not used >> j & 1 and len(long_[j]) >= 5 and long_[j][0] == joined[0] \
                        and abs(len(long_[j]) - len(joined)) <= 3 and _st(joined, long_[j]) \
                        and rec(i + 2, used | 1 << j, True):
                    return True
        return False

    return rec(0, 0, False)


def _same_tokens(a: List[str], b: List[str]) -> bool:
    """Same full tokens both ways (no initials)."""
    if any(len(t) < 2 for t in a + b):
        return False
    return len(a) == len(b) and _cover(a, b) and _cover(b, a)


def _strip_patronymic(name: str, rels: List[str]) -> List[str]:
    """Identifying tokens of `name` without a token that is a relative's given name (the father's /
    husband's name written as a middle name)."""
    toks = _ident_tokens(name)
    firsts = [t[0] for t in (_ident_tokens(r) for r in rels) if t and len(t[0]) > 1]
    out = [t for t in toks if not any(len(t) > 1 and same_token(t, f) for f in firsts)]
    return out if len(out) >= 2 else toks


def same_person_name(a: List[str], ra: List[str], b: List[str], rb: List[str]) -> bool:
    """Same identifying tokens both ways, after dropping a relative's given name used as a middle name."""
    for x in a:
        for y in b:
            tx, ty = _ident_tokens(x), _ident_tokens(y)
            if len(tx) < 2 or len(ty) < 2:
                continue
            if _same_tokens(tx, ty) or _same_tokens(_strip_patronymic(x, rb), ty) \
                    or _same_tokens(tx, _strip_patronymic(y, ra)):
                return True
    return False


def names_compatible(a: str, b: str) -> bool:
    """Two names are compatible when the identifying tokens of the shorter are each matched in the
    longer in any order (an initial matches a token starting with it, a joined token matches its
    split form, generic parts ignored, scripts compared through the phonetic key)."""
    ta, tb = _ident_tokens(a), _ident_tokens(b)
    if not ta or not tb or len(ta) > 7 or len(tb) > 7:
        return bool(ta and tb) and bool(same_name(a, b))
    if _cover2(ta, tb):
        return True
    # a generic-looking part may be half of a split name ("Rama Rao" ~ "Ramarao"): retry with all tokens
    fa, fb = _ident_tokens_impl(a, keep_generic=True), _ident_tokens_impl(b, keep_generic=True)
    return (fa, fb) != (ta, tb) and len(fa) <= 7 and len(fb) <= 7 and _cover2(fa, fb)


def _cover2(ta: List[str], tb: List[str]) -> bool:
    if not ta or not tb:
        return False
    if len(ta) > len(tb):
        ta, tb = tb, ta
    if _cover(ta, tb):
        return True
    return len(ta) == len(tb) and _cover(tb, ta)

Key = Tuple[str, str]

_DEMOTABLE = (ID_PHONE, ID_PAN, ID_INS, ID_EMAIL)
_RULE3 = (ID_AADHAAR, ID_ABHA, ID_ABHA_ADDR, ID_PAN, ID_INS, ID_EMAIL)
_STRONG_OWN = (ID_UHID, ID_ENC, ID_AADHAAR, ID_ABHA, ID_PAN, ID_INS)
_CONFLICT_TYPES = (ID_AADHAAR, ID_ABHA, ID_PAN)
_KEY_PREF = (ID_ENC, ID_AADHAAR, ID_ABHA, ID_ABHA_ADDR, ID_PAN, ID_INS, ID_EMAIL, ID_PHONE)


# Values filed as a patient's hospital number that are not one. A bank IFSC and an event number (lab
# accession, image, batch / lot, claim, UTR / UPI / transaction, bill, receipt, protocol) never link;
# a government-scheme / insurance / ration card is household-level: linked only as insurance (with
# compatible names), never as the canonical id.
_IFSC = re.compile(r"^[A-Z]{4}0[A-Z0-9]{6}$")
_EVENT_NO = re.compile(r"^(?:[A-Z]{2}LAB|LAB|LB|LIS|ACCN?|IMG|BATCH|LOT|CLM|CLAIM|UTR|UPI|TXN|BILL|INV|RCPT|RCT|PROT)"
                       r"[A-Z]{0,4}[0-9]{4,}[A-Z0-9]*$")
_SCHEME_NO = re.compile(r"^(?:BSKY|PMJAY|ABPMJAY|ABPMJ|MJPJAY|CMCHIS|RSBY|BSBY|AAROGYASRI|ESIC|CGHS|ECHS|SS|NHIS|"
                        r"MEDISEP|TPA|RC|RATION)[A-Z]{0,6}[0-9]{6,}[A-Z0-9]*$")
# a combined "ID proof" cell filed as a PAN: typed by the document word inside it
_PROOF_AADHAAR = re.compile(r"^(?:AADHAAR|AADHAR|ADHAAR|UID)([0-9X]{12})$")
_PROOF_PAN = re.compile(r"^PAN([A-Z]{5}[0-9]{4}[A-Z])$")


def _retype(typ: str, val: str) -> Optional[Tuple[str, str]]:
    if typ in (ID_UHID, ID_ENC):
        if _IFSC.match(val) or _EVENT_NO.match(val):
            return None
        if _SCHEME_NO.match(val):
            return ID_INS, val
    elif typ == ID_PAN:
        m = _PROOF_AADHAAR.match(val)
        if m:
            return (ID_AADHAAR, m.group(1)) if m.group(1).isdigit() else None   # masked: never linked
        m = _PROOF_PAN.match(val)
        if m:
            return ID_PAN, m.group(1)
    return typ, val


def _norm_token(tok: str) -> Optional[str]:
    if not tok or ":" not in tok:
        return None
    typ, val = tok.split(":", 1)
    typ = typ.strip().lower()
    val = val.strip()
    if typ in (ID_UHID, ID_ENC, ID_PAN):
        got = _retype(typ, re.sub(r"[\W_]", "", val).upper())
        if got is None:
            return None
        typ, val = got
    if typ == ID_EMAIL:
        val = val.lower()
    elif typ == ID_PHONE:
        val = re.sub(r"\D", "", val)[-10:]
    elif typ in (ID_AADHAAR, ID_ABHA):
        val = re.sub(r"\D", "", val)
    elif typ == ID_ABHA_ADDR:
        val = val.lower()
    else:
        val = re.sub(r"[\W_]", "", val).upper()
    if not val:
        return None
    return typ + ":" + val


_CORE_RX = re.compile(r"^(?:[A-Z]{1,6})?([0-9]{6,12})$")


def _uhid_core(tok: str) -> str:
    """Hospital number without its hospital prefix ("uhid:KMH4471902" and "uhid:4471902" -> "4471902")."""
    if not tok.startswith(ID_UHID + ":"):
        return ""
    m = _CORE_RX.match(tok.split(":", 1)[1])
    return "core:" + m.group(1) if m else ""


_CANON_RX = re.compile(r"^([A-Z]{0,6}?)([0-9]{4,14})(R|[A-Z])?$")


def _uhid_canon(tok: str) -> Optional[Tuple[str, str, bool]]:
    """(serial, prefix, relaxed) of a hospital number: separators already gone, a trailing letter or
    re-registration 'R', a leading 4-digit year segment and leading zeros removed. `relaxed` is True
    when anything beyond the prefix had to be dropped."""
    if not tok.startswith(ID_UHID + ":"):
        return None
    m = _CANON_RX.match(tok.split(":", 1)[1])
    if not m:
        return None
    pre, dig, suf = m.group(1), m.group(2), m.group(3)
    relaxed = bool(suf)
    if len(dig) >= 8 and dig[:2] == "20" and dig[2:4] <= "39":
        dig = dig[4:]
        relaxed = True
    dig = dig.lstrip("0")
    if len(dig) < 3:
        return None
    return dig, pre, relaxed


def _place_key(s: str) -> str:
    """Script-independent village key: phonetic key per word with inner vowels dropped
    (Devanagari vowel signs are kept inside words so the transliteration sees them)."""
    out = []
    for t in re.split(r"[^\w\u0900-\u0963\u0971-\u097F]+", (s or "").lower()):
        k = name_key(t) if t else ""
        if k:
            out.append(k[0] + re.sub(r"[aeiou]", "", k[1:]))
    return " ".join(out)


class _Rec:
    __slots__ = ("i", "key", "facts", "names", "fullkeys", "firstkeys", "ids", "cores", "rels",
                 "relfirst", "dob", "age", "byear", "village", "gender", "fragment", "sat", "canon")

    def __init__(self, i: int, key: Key, f: Facts) -> None:
        self.i = i
        self.key = key
        self.facts = f
        skip = set(getattr(f, "link_skip", None) or ())
        self.names = sorted({n.strip() for n in f.names
                             if n and n not in skip and n.strip() and name_tokens(n)})
        self.fullkeys = sorted({full_name_key(n) for n in self.names} - {""})
        fk = set()
        for n in self.names:
            toks = name_tokens(n)
            if toks:
                fk.add(name_key(toks[0]))
        self.firstkeys = sorted(fk - {""})
        ids = {t for t in (_norm_token(x) for x in f.ids) if t}
        phones = {t.split(":", 1)[1] for t in ids if t.startswith(ID_PHONE + ":")}
        # "+91 98xxxxxxxx" written without separators reads as twelve digits: not an Aadhaar
        ids = {t for t in ids if not (t.startswith(ID_AADHAAR + ":") and t[len(ID_AADHAAR) + 1:].startswith("91")
                                      and t[len(ID_AADHAAR) + 3:] in phones)}
        self.ids = sorted(ids)
        self.cores = sorted({c for c in (_uhid_core(t) for t in self.ids) if c})
        self.canon = sorted({c for c in (_uhid_canon(t) for t in self.ids) if c})
        self.sat = not f.is_patient
        self.rels = sorted({r[1].strip() for r in f.relatives
                            if r and len(r) > 1 and r[1] and name_tokens(r[1])})
        rf = set()
        for r in self.rels:
            rf.add(name_key(name_tokens(r)[0]))
        self.relfirst = sorted(rf - {""})
        self.dob = f.dob
        self.age = f.age
        if f.dob is not None:
            self.byear = f.dob.year
        elif f.age is not None and f.ref_date is not None and _NOW[0] and f.age >= 5 \
                and f.ref_date.year < _NOW[0] - 10 and abs(f.ref_date.year + f.age - _NOW[0]) <= 1:
            # an "event" date a lifetime old that plus the age lands on the collection's own year is
            # the birth date ("Born: ...") the text did not label
            self.byear = f.ref_date.year
        elif f.age is not None and f.ref_date is not None and f.ref_date.year >= _MIN_EVENT_YEAR:
            # an "event" date decades old is most likely an unlabelled birth date ("Born: ..."):
            # age minus that date would invent a birth year a lifetime too early
            self.byear = f.ref_date.year - f.age
        else:
            self.byear = None
        self.village = _place_key(f.village)
        self.gender = (f.gender or "").upper()
        self.fragment = bool(self.names) and all(len(name_tokens(n)) == 1 for n in self.names) \
            and bool(self.rels)


_SHAPE_RX = re.compile(r"^([A-Z]*)([0-9]+)([A-Z]*)$")


def _multi_patient(r: "_Rec") -> bool:
    """A whole text that carries two different patient numbers of one shape (same prefix, same digit
    count) or two different Aadhaar numbers holds more than one patient: it is never one record."""
    shapes: Dict[tuple, Set[str]] = {}
    for t in r.ids:
        typ, val = t.split(":", 1)
        if typ == ID_UHID:
            m = _SHAPE_RX.match(val)
            if m and len(m.group(2)) >= 4:
                shapes.setdefault((typ, m.group(1), len(m.group(2)), m.group(3)), set()).add(m.group(2).lstrip("0"))
        elif typ == ID_AADHAAR and len(val) == 12 and not _CC_MOBILE.match(val):
            shapes.setdefault((typ,), set()).add(val)
    return any(len(v) >= 2 for v in shapes.values())


_MIN_EVENT_YEAR = 1995
# The collection's own year: the most common event-date year over all records (set by link()).
_NOW = [0]


def _collection_year(records: List[Record]) -> int:
    cnt: Dict[int, int] = {}
    for rec in records:
        f = rec.facts
        d = getattr(f, "ref_date", None) if f is not None else None
        if d is not None and 1900 < d.year < 2100:
            cnt[d.year] = cnt.get(d.year, 0) + 1
    if not cnt:
        return 0
    return max(sorted(cnt), key=lambda y: (cnt[y], y))
_PAN_SHAPE = re.compile(r"^[A-Z]{5}[0-9]{4}[A-Z]$")
_CC_MOBILE = re.compile(r"^91[6-9][0-9]{9}$")


_SAME_CACHE: Dict[Tuple[str, str], bool] = {}


def _same(x: str, y: str) -> bool:
    k = (x, y) if x <= y else (y, x)
    v = _SAME_CACHE.get(k)
    if v is None:
        if len(_SAME_CACHE) > 500000:
            _SAME_CACHE.clear()
        v = names_compatible(x, y)
        _SAME_CACHE[k] = v
    return v


def _distinct_names(lists) -> List[List[str]]:
    """The distinct non-empty name lists (pairwise checks over thousands of identical holders of one
    shared number were quadratic; equal lists are always compatible with each other)."""
    seen = set()  # type: Set[Tuple[str, ...]]
    out = []  # type: List[List[str]]
    for n in lists:
        if not n:
            continue
        t = tuple(sorted(set(n)))
        if t not in seen:
            seen.add(t)
            out.append(list(t))
    return out


def _names_compat(a: List[str], b: List[str]) -> bool:
    for x in a:
        for y in b:
            if x == y or _same(x, y):
                return True
    return False


class _Group:
    __slots__ = ("genders", "dobs", "cids", "rels", "bmin", "bmax", "names", "anchored",
                 "members", "nonfrag")

    def __init__(self, r: _Rec, demoted: Set[str]) -> None:
        self.genders = {r.gender} if r.gender else set()
        self.dobs = {r.dob} if r.dob is not None else set()
        self.cids: Dict[str, Set[str]] = {}
        for t in r.ids:
            typ = t.split(":", 1)[0]
            if typ == ID_PAN and not _PAN_SHAPE.match(t[4:]):
                continue   # a voter / ration / visit code filed as a government id: not a PAN to conflict on
            if typ == ID_AADHAAR and _CC_MOBILE.match(t[len(ID_AADHAAR) + 1:]):
                continue   # "91" + a mobile number: as likely a phone with its country code as an Aadhaar
            if typ in _CONFLICT_TYPES and t not in demoted:
                self.cids.setdefault(typ, set()).add(t)
        self.rels = list(r.rels)
        self.bmin = self.bmax = r.byear
        self.names = list(r.names)
        self.anchored = any(t.split(":", 1)[0] in _STRONG_OWN and t not in demoted for t in r.ids)
        self.members = [r.i]
        self.nonfrag = not r.fragment


class _Linker:
    def __init__(self, recs: List[_Rec], demoted: Set[str]) -> None:
        self.recs = recs
        self.parent = list(range(len(recs)))
        self.groups: Dict[int, _Group] = {r.i: _Group(r, demoted) for r in recs}

    def find(self, x: int) -> int:
        p = self.parent
        while p[x] != x:
            p[x] = p[p[x]]
            x = p[x]
        return x

    def conflict(self, a: _Group, b: _Group, soft: bool) -> bool:
        if a.genders and b.genders and a.genders != b.genders:
            return True
        if a.dobs and b.dobs and a.dobs != b.dobs:
            return True
        for typ in _CONFLICT_TYPES:
            sa, sb = a.cids.get(typ), b.cids.get(typ)
            if sa and sb and sa != sb:
                return True
        if a.bmin is not None and b.bmin is not None:
            if max(a.bmax, b.bmax) - min(a.bmin, b.bmin) > 2:
                return True
        if soft and a.rels and b.rels and not _names_compat(a.rels, b.rels):
            return True
        return False

    def union(self, x: int, y: int, soft: bool = False) -> bool:
        rx, ry = self.find(x), self.find(y)
        if rx == ry:
            return True
        ga, gb = self.groups[rx], self.groups[ry]
        if self.conflict(ga, gb, soft):
            return False
        if ry < rx:
            rx, ry, ga, gb = ry, rx, gb, ga
        self.parent[ry] = rx
        ga.genders |= gb.genders
        ga.dobs |= gb.dobs
        for typ, s in gb.cids.items():
            ga.cids.setdefault(typ, set()).update(s)
        ga.rels = sorted(set(ga.rels) | set(gb.rels))
        if gb.bmin is not None:
            ga.bmin = gb.bmin if ga.bmin is None else min(ga.bmin, gb.bmin)
            ga.bmax = gb.bmax if ga.bmax is None else max(ga.bmax, gb.bmax)
        ga.names = sorted(set(ga.names) | set(gb.names))
        ga.anchored = ga.anchored or gb.anchored
        if len(gb.members) > len(ga.members):   # extend the shorter into the longer (sorted when read)
            ga.members, gb.members = gb.members, ga.members
        ga.members.extend(gb.members)
        ga.nonfrag = ga.nonfrag or gb.nonfrag
        del self.groups[ry]
        return True


def _demoted_tokens(recs: List[_Rec]) -> Set[str]:
    by_tok: Dict[str, List[_Rec]] = {}
    for r in recs:
        if not r.names:
            continue
        for t in r.ids:
            if t.split(":", 1)[0] in _DEMOTABLE:
                by_tok.setdefault(t, []).append(r)
    out: Set[str] = set()
    for t in sorted(by_tok):
        name_sets = sorted({tuple(r.names) for r in by_tok[t]})
        bad = False
        for i in range(len(name_sets)):
            for j in range(i + 1, len(name_sets)):
                if not _names_compat(list(name_sets[i]), list(name_sets[j])):
                    bad = True
                    break
            if bad:
                break
        if bad:
            out.add(t)
    return out


def _match5(r: _Rec, s: _Rec) -> bool:
    return r.dob is not None and r.dob == s.dob and _names_compat(r.names, s.names)


def _match6(r: _Rec, s: _Rec) -> bool:
    return bool(r.rels) and bool(s.rels) and _names_compat(r.names, s.names) \
        and _names_compat(r.rels, s.rels)


def _match7(r: _Rec, s: _Rec) -> bool:
    if not r.village or r.village != s.village:
        return False
    if r.byear is not None and s.byear is not None:
        ok = abs(r.byear - s.byear) <= 1
    elif r.age is not None and s.age is not None:
        ok = abs(r.age - s.age) <= 1
    else:
        return False
    return ok and _names_compat(r.names, s.names)


def _match9(r: _Rec, s: _Rec) -> bool:
    return r.facts.ref_date is not None and r.facts.ref_date == s.facts.ref_date \
        and same_person_name(r.names, [], s.names, [])


def _match10(r: _Rec, s: _Rec) -> bool:
    if r.key[1] != "doc" or s.key[1] != "doc" or r.age is None or r.age != s.age:
        return False
    if r.names and s.names:
        return False
    if r.gender and s.gender and r.gender != s.gender:
        return False
    return _names_compat(r.rels, s.rels)


def _match8(r: _Rec, s: _Rec) -> bool:
    if s.fragment:
        return False
    ft = name_tokens(r.names[0])[0]
    if not any(same_token(ft, name_tokens(n)[0]) for n in s.names):
        return False
    rft = [name_tokens(x)[0] for x in r.rels]
    sft = [name_tokens(x)[0] for x in s.rels]
    return any(same_token(a, b) for a in rft for b in sft)


def _soft_rule(lk: _Linker, recs: List[_Rec], blocks: Dict[tuple, List[int]],
               keys_of, match, fragment_rule: bool = False) -> None:
    """Rules 5-8: link a record only when the evidence points to exactly one group."""
    found: List[Tuple[int, int, Dict[int, int]]] = []
    blocked: Set[int] = set()
    # unions are applied only after the scan, so group roots are fixed while it runs: each block is
    # split once into its groups (members in block order) and a record skips whole groups that are
    # its own or already matched, instead of walking every member (a big patient's block).
    by_root: Dict[tuple, List[Tuple[int, List[int]]]] = {}

    def groups_of(bk: tuple) -> List[Tuple[int, List[int]]]:
        hit = by_root.get(bk)
        if hit is None:
            od: Dict[int, List[int]] = {}
            for j in blocks.get(bk, ()):
                od.setdefault(lk.find(j), []).append(j)
            hit = by_root[bk] = list(od.items())
        return hit

    for r in recs:
        if r.sat or (fragment_rule and not r.fragment):
            continue
        own = lk.find(r.i)
        cand: Dict[int, int] = {}
        seen: Set[int] = set()
        for bk in keys_of(r):
            if bk not in blocks:
                continue
            for rj, members in groups_of(bk):
                if rj == own or rj in cand:
                    continue
                for j in members:
                    if j == r.i or j in seen or recs[j].sat:
                        continue
                    seen.add(j)
                    if match(r, recs[j]):
                        cand[rj] = j
                        break
        if not cand:
            continue
        if fragment_rule:
            roots = [x for x in sorted(cand) if lk.groups[x].nonfrag]
            if len(roots) != 1:
                continue
            cand = {roots[0]: cand[roots[0]]}
        elif sum(1 for x in cand if lk.groups[x].anchored) >= 2:
            if not lk.groups[own].anchored:
                blocked.add(own)   # ambiguous: nobody may pull this group in either
            continue
        found.append((r.i, own, cand))
    plans: List[Tuple[int, List[int]]] = []
    for i, own, cand in found:
        if own in blocked:
            continue
        targets = [cand[x] for x in sorted(cand) if x not in blocked]
        if targets:
            plans.append((i, targets))
    for i, targets in plans:
        for j in targets:
            lk.union(i, j, soft=True)


def link(records: List[Record]) -> Tuple[Dict[Key, Optional[str]], Dict[str, Patient]]:
    ordered = sorted(records, key=lambda r: (r.rel, r.loc))
    _NOW[0] = _collection_year(ordered)
    mapping: Dict[Key, Optional[str]] = {}
    recs: List[_Rec] = []
    for rec in ordered:
        k = (rec.rel, rec.loc)
        mapping[k] = None
        if rec.facts is None:
            continue
        if not rec.facts.is_patient:
            # a caller / visitor / sales line: joins a patient only on a hard key with a compatible name
            f = rec.facts
            if not (f.ids and any(n and name_tokens(n) for n in f.names)):
                continue
        r = _Rec(len(recs), k, rec.facts)
        if rec.loc == "doc" and _multi_patient(r):
            continue   # a log / letter batch / register printed as one text: ids scrubbed, never linked
        recs.append(r)
    if not recs:
        return mapping, {}

    demoted = _demoted_tokens(recs)
    lk = _Linker(recs, demoted)

    # Rules 1-4: exact identifier blocks.
    by_tok: Dict[str, List[int]] = {}
    for r in recs:
        for t in r.ids:
            by_tok.setdefault(t, []).append(r.i)

    def id_rule(types: Tuple[str, ...], need_names: bool = False, both_named: bool = False) -> None:
        for t in sorted(by_tok):
            if t.split(":", 1)[0] not in types or t in demoted:
                continue
            members = by_tok[t]
            for idx in range(1, len(members)):
                j = members[idx]
                for b in members[:idx]:
                    if need_names:
                        ga, gb = lk.groups[lk.find(b)], lk.groups[lk.find(j)]
                        if both_named and not (ga.names and gb.names):
                            continue
                        if ga.names and gb.names and not _names_compat(ga.names, gb.names):
                            continue
                    if lk.union(b, j):
                        break

    id_rule((ID_UHID,))
    id_rule((ID_ENC,))
    id_rule(tuple(t for t in _RULE3 if t != ID_INS))
    id_rule((ID_INS,), need_names=True, both_named=True)   # a scheme / insurance card is household-level

    # A shared phone is demoted (a family / attendant number) only when the groups holding it, after
    # the identifier rules, carry incompatible names.
    for t in sorted(by_tok):
        if not t.startswith(ID_PHONE + ":"):
            continue
        roots = sorted({lk.find(i) for i in by_tok[t]})
        named = _distinct_names(lk.groups[x].names for x in roots)
        bad = any(not _names_compat(named[i], named[j])
                  for i in range(len(named)) for j in range(i + 1, len(named)))
        if bad:
            demoted.add(t)
        else:
            demoted.discard(t)
    id_rule((ID_PHONE,), need_names=True)

    # A family phone still joins two holders whose names are the same person's (both ways, a
    # patronymic middle name allowed), e.g. a surname-first insurer form and the registration row.
    for t in sorted(by_tok):
        if not t.startswith(ID_PHONE + ":") or t not in demoted:
            continue
        mem = by_tok[t]
        for x in range(len(mem)):
            for y in range(x + 1, len(mem)):
                a, b = lk.find(mem[x]), lk.find(mem[y])
                if a == b:
                    continue
                ga, gb = lk.groups[a], lk.groups[b]
                if ga.names and gb.names and same_person_name(ga.names, ga.rels, gb.names, gb.rels):
                    lk.union(mem[x], mem[y])

    # Same hospital number written with and without its prefix: only with a compatible name.
    by_core: Dict[str, List[int]] = {}
    for r in recs:
        for c in r.cores:
            by_core.setdefault(c, []).append(r.i)
    for c in sorted(by_core):
        members = by_core[c]
        roots = sorted({lk.find(i) for i in members})
        named = _distinct_names(lk.groups[x].names for x in roots)
        one = all(_names_compat(named[i], named[j])
                  for i in range(len(named)) for j in range(i + 1, len(named)))
        for idx in range(1, len(members)):
            j = members[idx]
            for b in members[:idx]:
                ga, gb = lk.groups[lk.find(b)], lk.groups[lk.find(j)]
                if ga.names and gb.names:
                    ok = _names_compat(ga.names, gb.names)
                else:   # one side unnamed: only when every named holder of this number is one person
                    ok = one and (bool(ga.names) or bool(gb.names))
                if ok and lk.union(b, j):
                    break

    # Canonical hospital numbers (year segment, trailing letter / -R, leading zeros dropped): whole
    # serial and prefix equal; a relaxed match needs compatible names on both sides.
    by_canon: Dict[str, List[Tuple[int, str, bool]]] = {}
    for r in recs:
        for dig, pre, rel in r.canon:
            by_canon.setdefault(dig, []).append((r.i, pre, rel))
    for dig in sorted(by_canon):
        ms = by_canon[dig]
        for x in range(len(ms)):
            for y in range(x + 1, len(ms)):
                (i, pa, ra), (j, pb, rb) = ms[x], ms[y]
                if pa and pb and pa != pb:
                    continue
                if not (ra or rb) and not (pa and pb):
                    continue   # prefix-only difference: handled by the core rule above
                if lk.find(i) == lk.find(j):
                    continue
                ga, gb = lk.groups[lk.find(i)], lk.groups[lk.find(j)]
                if not (ga.names and gb.names and _names_compat(ga.names, gb.names)):
                    continue
                lk.union(i, j)

    # One hospital number filed as the patient's number in one record and as a visit / admission
    # number in another (an "UHID/IP" column): the same code with compatible names on both sides.
    by_val: Dict[str, List[int]] = {}
    for r in recs:
        for t in r.ids:
            typ, val = t.split(":", 1)
            if typ in (ID_UHID, ID_ENC) and t not in demoted and len(val) >= 6 and re.search(r"[0-9]{4}", val):
                by_val.setdefault(val, []).append(r.i)
    for val in sorted(by_val):
        ms = by_val[val]
        if not (ID_UHID + ":" + val in by_tok and ID_ENC + ":" + val in by_tok):
            continue
        for x in range(len(ms)):
            for y in range(x + 1, len(ms)):
                i, j = ms[x], ms[y]
                if lk.find(i) == lk.find(j):
                    continue
                ga, gb = lk.groups[lk.find(i)], lk.groups[lk.find(j)]
                if ga.names and gb.names and _names_compat(ga.names, gb.names):
                    lk.union(i, j)

    # Blocking indexes for rules 5-8 (first-name key and full-name key based).
    def name_keys(r: _Rec) -> List[str]:
        return sorted(set(["f:" + x for x in r.firstkeys] + ["n:" + x for x in r.fullkeys]))

    def build(keys_of) -> Dict[tuple, List[int]]:
        b: Dict[tuple, List[int]] = {}
        for r in recs:
            for bk in keys_of(r):
                b.setdefault(bk, []).append(r.i)
        return b

    k5 = lambda r: [(n, r.dob) for n in name_keys(r)] if r.dob is not None else []
    k6 = lambda r: [(n, rf) for n in name_keys(r) for rf in r.relfirst]
    # Village + birth-year (or age) buckets; names are compared in _match7 so that a
    # Devanagari and a Latin spelling of the same name still meet in one block.
    # The first-name consonant skeleton keeps blocks small and survives transliteration.
    def k7(r: _Rec) -> list:
        if not r.village or not r.firstkeys:
            return []
        sk = sorted({(k[0] + re.sub(r"[aeiouy]", "", k[1:]))[:3] for k in r.firstkeys})
        out = []
        for s3 in sk:
            if r.byear is not None:
                out += [(r.village, s3, "y", r.byear + d) for d in (-1, 0, 1)]
            if r.age is not None:
                out += [(r.village, s3, "a", r.age + d) for d in (-1, 0, 1)]
        return out
    k8 = lambda r: [(fk, rf) for fk in r.firstkeys for rf in r.relfirst]

    _soft_rule(lk, recs, build(k5), k5, _match5)
    _soft_rule(lk, recs, build(k6), k6, _match6)
    _soft_rule(lk, recs, build(k7), k7, _match7)
    _soft_rule(lk, recs, build(k8), k8, _match8, fragment_rule=True)

    # Same full name (two or more identifying tokens, any order) on the same event date.
    def k9(r: _Rec) -> list:
        if r.facts.ref_date is None:
            return []
        return [("d", fk, r.facts.ref_date) for n, fk in zip(r.names, [full_name_key(x) for x in r.names])
                if fk and len(_ident_tokens(n)) >= 2]
    _soft_rule(lk, recs, build(k9), k9, _match9)

    # A text document that never names the patient: the same relative (given name) and the same age
    # as exactly one other document's patient.
    k10 = lambda r: [("r", rf, r.age) for rf in r.relfirst] if r.key[1] == "doc" and r.age is not None else []
    _soft_rule(lk, recs, build(k10), k10, _match10)

    # Patient book.
    candidates: List[Tuple[str, Key, _Group]] = []
    for root in sorted(lk.groups):
        g = lk.groups[root]
        members = [recs[i] for i in sorted(g.members)]
        if all(m.sat for m in members):
            continue
        toks = sorted({t for m in members for t in m.ids})
        if len(members) == 1:
            if not any(t.split(":", 1)[0] in _STRONG_OWN for t in toks):
                continue
        key = _canonical(members, toks, demoted)
        if key is None:
            continue
        candidates.append((key, min(m.key for m in members), g))
    candidates.sort(key=lambda c: (c[0], c[1]))
    book: Dict[str, Patient] = {}
    for key, _first, g in candidates:
        final = key
        n = 2
        while final in book:
            final = "%s~%d" % (key, n)
            n += 1
        members = sorted((recs[i] for i in g.members), key=lambda m: m.key)
        book[final] = Patient(key=final, records=[m.key for m in members],
                              facts=[m.facts for m in members])
        for m in members:
            mapping[m.key] = final
    return mapping, book


def _canonical(members: List[_Rec], toks: List[str], demoted: Set[str]) -> Optional[str]:
    uh = [t for t in toks if t.startswith(ID_UHID + ":")]
    if uh:
        return uh[0]
    for typ in _KEY_PREF:
        live = [t for t in toks if t.startswith(typ + ":") and t not in demoted]
        if live:
            return live[0]
    for typ in _KEY_PREF:
        dead = [t for t in toks if t.startswith(typ + ":")]
        if dead:
            fks = sorted({k for m in members for k in m.fullkeys})
            return dead[0] + "|name:" + (fks[0] if fks else "")
    fks = sorted({k for m in members for k in m.fullkeys})
    if not fks:
        return None
    dobs = sorted({m.dob for m in members if m.dob is not None})
    if dobs:
        clue = dobs[0].isoformat()
    else:
        rels = sorted({full_name_key(x) for m in members for x in m.rels} - {""})
        if rels:
            clue = rels[0]
        else:
            vil = sorted({m.village for m in members if m.village})
            clue = vil[0] if vil else ""
    return "name:" + fks[0] + "|" + clue
