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

Key = Tuple[str, str]

_DEMOTABLE = (ID_PHONE, ID_PAN, ID_INS, ID_EMAIL, ID_AADHAAR, ID_ABHA)
_RULE3 = (ID_AADHAAR, ID_ABHA, ID_ABHA_ADDR, ID_PAN, ID_INS, ID_EMAIL)
_STRONG_OWN = (ID_UHID, ID_ENC, ID_AADHAAR, ID_ABHA, ID_PAN, ID_INS)
_CONFLICT_TYPES = (ID_AADHAAR, ID_ABHA, ID_PAN)
_KEY_PREF = (ID_ENC, ID_AADHAAR, ID_ABHA, ID_ABHA_ADDR, ID_PAN, ID_INS, ID_EMAIL, ID_PHONE)


def _norm_token(tok: str) -> Optional[str]:
    if not tok or ":" not in tok:
        return None
    typ, val = tok.split(":", 1)
    typ = typ.strip().lower()
    val = val.strip()
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
    __slots__ = ("i", "key", "facts", "names", "fullkeys", "firstkeys", "ids", "rels",
                 "relfirst", "dob", "age", "byear", "village", "gender", "fragment")

    def __init__(self, i: int, key: Key, f: Facts) -> None:
        self.i = i
        self.key = key
        self.facts = f
        self.names = sorted({n.strip() for n in f.names if n and n.strip() and name_tokens(n)})
        self.fullkeys = sorted({full_name_key(n) for n in self.names} - {""})
        fk = set()
        for n in self.names:
            toks = name_tokens(n)
            if toks:
                fk.add(name_key(toks[0]))
        self.firstkeys = sorted(fk - {""})
        self.ids = sorted({t for t in (_norm_token(x) for x in f.ids) if t})
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
        elif f.age is not None and f.ref_date is not None:
            self.byear = f.ref_date.year - f.age
        else:
            self.byear = None
        self.village = _place_key(f.village)
        self.gender = (f.gender or "").upper()
        self.fragment = bool(self.names) and all(len(name_tokens(n)) == 1 for n in self.names) \
            and bool(self.rels)


_SAME_CACHE: Dict[Tuple[str, str], bool] = {}


def _same(x: str, y: str) -> bool:
    k = (x, y) if x <= y else (y, x)
    v = _SAME_CACHE.get(k)
    if v is None:
        if len(_SAME_CACHE) > 500000:
            _SAME_CACHE.clear()
        v = bool(same_name(x, y))
        _SAME_CACHE[k] = v
    return v


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
        if fragment_rule and not r.fragment:
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
                    if j == r.i or j in seen:
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
    mapping: Dict[Key, Optional[str]] = {}
    recs: List[_Rec] = []
    for rec in ordered:
        k = (rec.rel, rec.loc)
        mapping[k] = None
        if rec.facts is None or not rec.facts.is_patient:
            continue
        recs.append(_Rec(len(recs), k, rec.facts))
    if not recs:
        return mapping, {}

    demoted = _demoted_tokens(recs)
    lk = _Linker(recs, demoted)

    # Rules 1-4: exact identifier blocks.
    by_tok: Dict[str, List[int]] = {}
    for r in recs:
        for t in r.ids:
            by_tok.setdefault(t, []).append(r.i)

    def id_rule(types: Tuple[str, ...], need_names: bool = False) -> None:
        for t in sorted(by_tok):
            if t.split(":", 1)[0] not in types or t in demoted:
                continue
            members = by_tok[t]
            for idx in range(1, len(members)):
                j = members[idx]
                for b in members[:idx]:
                    if need_names:
                        ga, gb = lk.groups[lk.find(b)], lk.groups[lk.find(j)]
                        if ga.names and gb.names and not _names_compat(ga.names, gb.names):
                            continue
                    if lk.union(b, j):
                        break

    id_rule((ID_UHID,))
    id_rule((ID_ENC,))
    id_rule(_RULE3)
    id_rule((ID_PHONE,), need_names=True)

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

    # Patient book.
    candidates: List[Tuple[str, Key, _Group]] = []
    for root in sorted(lk.groups):
        g = lk.groups[root]
        members = [recs[i] for i in sorted(g.members)]
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
