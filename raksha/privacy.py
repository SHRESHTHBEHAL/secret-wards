"""Per-patient quasi-identifier decisions: one age band and one geography decision per patient.

Built once per sanitisation Env from the patient book, so every record of a patient gets the
same band and the same district / PIN treatment (pooling records by pseudonym adds nothing).
Standard library only, Python 3.9+.
"""
from __future__ import annotations

import datetime as dt
import re
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Sequence, Tuple

from .translit import name_key
from .types import Facts

_TOKEN = re.compile(r"[A-Za-z]+|[ऀ-ॿ]+")


def _int(v: Any, default: int) -> int:
    try:
        return int(v)
    except (TypeError, ValueError):
        return default


def place_key(s: str) -> str:
    """Comparable, script-neutral form of a place name ("Sitapur", "सीतापुर" -> "sitapur")."""
    out = []
    for t in _TOKEN.findall(str(s or "")):
        try:
            k = name_key(t)
        except Exception:  # noqa: BLE001
            k = ""
        out.append(k or t.casefold())
    return " ".join(out)


@dataclass
class Decision:
    """What the sanitiser does with one patient's (or one unlinked record's) quasi-identifiers."""
    band: Optional[Tuple[int, int]] = None     # inclusive age range used for every age form, or None
    suppress_geo: bool = False                  # district -> [DISTRICT], PIN -> [PIN]
    districts: Tuple[str, ...] = ()             # place_key of the patient's own district(s)


class Policy:
    """Numbers from config/policy.yaml with safe defaults."""

    def __init__(self, policy: Dict[str, Any]) -> None:
        p = policy or {}
        self.width = max(1, _int(p.get("age_band_years"), 10))
        self.top = _int(p.get("age_top"), 85)
        self.min_cell = _int(p.get("geo_min_cell"), 3)
        mode = str(p.get("dob_mode", "remove")).strip().lower()
        self.dob_mode = mode if mode in ("remove", "shift", "year") else "remove"

    def aligned(self, age: int) -> Tuple[int, int]:
        if age >= self.top:
            return (self.top, 999)
        lo = (age // self.width) * self.width
        return (lo, min(lo + self.width - 1, self.top - 1))

    def fmt(self, rng: Tuple[int, int]) -> str:
        lo, hi = rng
        if hi >= self.top:
            return "%d+" % lo
        return "%d-%d" % (lo, hi)

    def band_for(self, age: int, dec: Optional[Decision]) -> str:
        """The band text for one stated age: the patient band when it contains the age, else the
        aligned band of that age (a band never excludes the age written in the record)."""
        if dec is not None and dec.band is not None and dec.band[0] <= age <= dec.band[1]:
            return self.fmt(dec.band)
        return self.fmt(self.aligned(age))


def _age_at(dob: dt.date, ref: dt.date) -> Optional[int]:
    try:
        a = ref.year - dob.year - ((ref.month, ref.day) < (dob.month, dob.day))
    except Exception:  # noqa: BLE001
        return None
    return a if 0 <= a <= 120 else None


def patient_band(facts: Sequence[Facts], pol: Policy) -> Optional[Tuple[int, int]]:
    """One age range for the patient: the union of the aligned bands of every stated age (DOB +
    record date when no age is stated). At most two adjacent bands are joined; wider spreads
    (inconsistent data) give None, so each age then gets its own aligned band."""
    ages = sorted(set(f.age for f in facts if f is not None and isinstance(f.age, int) and 0 <= f.age <= 120))
    if not ages:
        derived = []  # type: List[int]
        for f in facts:
            if f is not None and isinstance(f.dob, dt.date) and isinstance(f.ref_date, dt.date):
                a = _age_at(f.dob, f.ref_date)
                if a is not None:
                    derived.append(a)
        ages = sorted(set(derived))
    if not ages:
        return None
    bands = sorted(set(pol.aligned(a) for a in ages))
    lo, hi = bands[0][0], bands[-1][1]
    if len(bands) > 2:
        return None
    if len(bands) == 2 and bands[1][0] != bands[0][1] + 1:
        return None
    return (lo, hi)


def _mode(vals: List[str]) -> str:
    vals = [v for v in vals if v]
    if not vals:
        return ""
    counts = {}  # type: Dict[str, int]
    for v in vals:
        counts[v] = counts.get(v, 0) + 1
    return sorted(counts, key=lambda v: (-counts[v], v))[0]


def build(book: Dict[str, Any], policy: Dict[str, Any]) -> Tuple[Policy, Dict[str, Decision]]:
    """(policy numbers, {patient key: Decision}) for the whole release."""
    pol = Policy(policy)
    rows = {}  # type: Dict[str, Tuple[Optional[Tuple[int, int]], Tuple[str, str, str], Tuple[str, ...]]]
    for key in sorted(book or {}):
        facts = [f for f in (getattr(book[key], "facts", None) or []) if f is not None]
        band = patient_band(facts, pol)
        dists = tuple(sorted(set(place_key(f.district) for f in facts if f.district and place_key(f.district))))
        dist = _mode([place_key(f.district) for f in facts if f.district])
        gender = _mode([str(f.gender or "") for f in facts])
        rows[key] = (band, (dist, gender, pol.fmt(band) if band else ""), dists)
    sizes = {}  # type: Dict[Tuple[str, str, str], int]
    for key in sorted(rows):
        cell = rows[key][1]
        sizes[cell] = sizes.get(cell, 0) + 1
    out = {}  # type: Dict[str, Decision]
    for key in sorted(rows):
        band, cell, dists = rows[key]
        suppress = pol.min_cell > 0 and sizes.get(cell, 0) < pol.min_cell
        out[key] = Decision(band=band, suppress_geo=suppress, districts=dists)
    return pol, out


def unlinked(facts: Sequence[Facts], pol: Policy) -> Decision:
    """An unlinked record is its own cell of size 1."""
    fs = [f for f in facts if f is not None]
    dists = tuple(sorted(set(place_key(f.district) for f in fs if f.district and place_key(f.district))))
    return Decision(band=patient_band(fs, pol), suppress_geo=pol.min_cell > 0, districts=dists)
