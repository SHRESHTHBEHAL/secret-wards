"""Identity-fact harvesting (PRD Stage 3). One Record per patient-bearing record.

Standard library only, Python 3.9+. Never raises on odd input.
"""
from __future__ import annotations

import datetime as dt
import re
from typing import Any, Dict, List, Optional, Sequence, Set, Tuple

from . import dates, fields as F, patterns
from .normalize import to_ascii_digits, try_b64_text
from .types import (
    ID_AADHAAR, ID_ABHA, ID_ABHA_ADDR, ID_EMAIL, ID_ENC, ID_INS, ID_PAN, ID_PHONE, ID_UHID,
    KIND_CSV, KIND_FHIR, KIND_JSON, KIND_QUARANTINE, KIND_TEXT, Facts, ParsedFile, Record,
)

try:
    from .translit import same_name as _translit_same_name
except Exception:  # noqa: BLE001
    _translit_same_name = None

try:
    from .detect import text_facts as _detect_text_facts
except Exception:  # noqa: BLE001 - detect may be mid-edit; degrade to pattern-only facts
    _detect_text_facts = None


MAX_DEPTH = 60

# Column / leaf types that mark a record as describing a patient.
# (CLINICAL is too loose: "category": "billing query" or "form": "surgical consent" type as clinical.)
_PATIENT_SIGNAL = frozenset({F.PATIENT_ID, F.ENC_ID, F.AADHAAR, F.ABHA, F.ABHA_ADDR, F.DOB, F.AGE,
                             F.AGE_SEX, F.GENDER})
# Leaf types that make a list element a record (used to find JSON record arrays).
_RECORD_SIGNAL = frozenset({F.PATIENT_ID, F.ENC_ID, F.AADHAAR, F.ABHA, F.DOB, F.AGE, F.AGE_SEX})
_STRONG_ID_TYPES = (ID_UHID, ID_ENC, ID_AADHAAR, ID_ABHA)
# Array keys that name a collection of patient records even when an element carries no id.
_RECORD_KEY = re.compile(r"^(?:visits?|patients?|results?|records?|admissions?|encounters?|reports?|"
                         r"registrations?|opd|ipd|cases?|samples?|discharges?|claims?|bills?)$")

_ENC_RX = re.compile(r"(?:^|[^A-Z])(?:IPD|IP|ADM|ADMN|INP|ADMISSION)(?=[^A-Z]|$)")
_REL_RX = re.compile(
    r"^\s*(?:([SDWHCG])\s*/\s*[Oo]|(son|daughter|wife|husband|care|ward)\s+of"
    r"|(पुत्र|पुत्री|पत्नी|पति|पिता|माता))\.?\s*[:\-]?\s*(.*)$", re.I | re.S)
_DATEISH = re.compile(r"(?<![0-9])[0-9०-९]{1,4}[./\-][0-9०-९]{1,2}[./\-][0-9०-९]{2,4}(?![0-9])")
_TAG_RX = re.compile(r"<[^>]+>")
_LETTER = re.compile(r"[A-Za-zऀ-ॿ]")
_EMPTY = frozenset({"", "-", "--", "na", "n/a", "nil", "none", "null", "nan", "not available", "unknown"})
_MALE = frozenset({"m", "male", "man", "boy", "पुरुष", "पुरूष", "पु", "purush", "purus", "mard", "ladka"})
_FEMALE = frozenset({"f", "female", "woman", "girl", "महिला", "स्त्री", "mahila", "aurat", "ladki"})
_DOC_WORDS = frozenset("""
discharge summary report reports note notes nursing lab labs final copy scan scanned rx opd ipd
prescription record records file export draft new old patient patients case sheet form letter
referral consent bill invoice receipt claim ds dr doc document visit admission
""".split())
_IDPREF = {"PHONE": ID_PHONE, "AADHAAR": ID_AADHAAR, "ABHA_NUMBER": ID_ABHA, "ABHA_ADDRESS": ID_ABHA_ADDR,
           "EMAIL": ID_EMAIL, "PAN": ID_PAN, "INSURANCE_ID": ID_INS}


# ---------------------------------------------------------------- small helpers

def _ptr(key: str) -> str:
    return key.replace("~", "~0").replace("/", "~1")


def _s(v: Any) -> str:
    if v is None or isinstance(v, (bool, dict, list)):
        return ""
    if isinstance(v, float):
        if v != v or v in (float("inf"), float("-inf")):
            return ""
        return repr(v)
    try:
        return str(v).strip()
    except Exception:  # noqa: BLE001
        return ""


def _same_name(a: str, b: str) -> bool:
    if a.strip().lower() == b.strip().lower():
        return True
    try:
        return bool(_translit_same_name(a, b)) if _translit_same_name else False
    except Exception:  # noqa: BLE001
        return False


def _blank(s: str) -> bool:
    return s.strip().lower() in _EMPTY


def gender_of(s: str) -> str:
    """'M', 'F' or '' for a gender word in English, Hindi or Hinglish."""
    t = to_ascii_digits(s or "").strip().lower().strip(".")
    if t in _MALE:
        return "M"
    if t in _FEMALE:
        return "F"
    return ""


def split_relative(s: str) -> Tuple[str, str]:
    """'S/O SHYAM PATEL' -> ('S/o', 'SHYAM PATEL'); a bare name -> ('', name)."""
    m = _REL_RX.match(s or "")
    if not m:
        return "", (s or "").strip()
    if m.group(1):
        rel = m.group(1).upper() + "/o"
    elif m.group(2):
        rel = m.group(2).lower() + " of"
    else:
        rel = m.group(3) or ""
    return rel, m.group(4).strip(" ,;:-")


class _FB:
    """Facts builder with de-duplication and per-group name / relative pairing."""

    def __init__(self) -> None:
        self.f = Facts()
        self.signal = False
        self.first: Dict[str, str] = {}
        self.last: Dict[str, str] = {}
        self.relation: Dict[str, str] = {}
        self.relnames: Dict[str, List[str]] = {}

    def name(self, s: str) -> None:
        s = " ".join((s or "").split())
        if not s or _blank(s) or not _LETTER.search(s):
            return
        if s not in self.f.names:
            self.f.names.append(s)

    def rel(self, relation: str, name: str) -> None:
        name = " ".join((name or "").split())
        if not name or _blank(name) or not _LETTER.search(name):
            return
        if any(n == name for _r, n in self.f.relatives):
            return
        self.f.relatives.append((relation or "", name))

    def raw(self, s: str) -> None:
        s = (s or "").strip()
        if s and s not in self.f.raw_ids:
            self.f.raw_ids.append(s)

    def tok(self, typ: str, val: str, raw: str = "") -> None:
        if not val:
            return
        t = typ + ":" + val
        if t not in self.f.ids:
            self.f.ids.append(t)
        if raw:
            self.raw(raw)

    def ref(self, d: Optional[dt.date]) -> None:
        if d is not None and self.f.ref_date is None:
            self.f.ref_date = d

    def merge(self, g: Optional[Facts]) -> None:
        if g is None:
            return
        for n in g.names:
            self.name(n)
        for r in g.relatives:
            if r and len(r) > 1:
                self.rel(r[0], r[1])
        for t in g.ids:
            if t and t not in self.f.ids:
                self.f.ids.append(t)
        for r in g.raw_ids:
            self.raw(r)
        f = self.f
        if f.dob is None:
            f.dob = g.dob
        if f.age is None:
            f.age = g.age
        if not f.gender:
            f.gender = g.gender
        for a in ("village", "tehsil", "district", "pin"):
            if not getattr(f, a) and getattr(g, a):
                setattr(f, a, getattr(g, a))
        for p in g.address_parts:
            if p not in f.address_parts:
                f.address_parts.append(p)
        if f.ref_date is None:
            f.ref_date = g.ref_date

    def finish(self) -> Facts:
        for grp in sorted(set(self.first) | set(self.last)):
            full = " ".join(x for x in (self.first.get(grp, ""), self.last.get(grp, "")) if x)
            if full:
                self.name(full)
        # labelled relatives come first and win over ones found in free text (C/O ...)
        found = self.f.relatives
        self.f.relatives = []
        for grp in sorted(self.relnames):
            relation = self.relation.get(grp, "")
            for n in self.relnames[grp]:
                r, nm = split_relative(n)
                self.rel(r or relation, nm)
        for r, n in found:
            # "Asha amma ka BP ..." comes back from detect as a relative named Asha: a
            # kin/honorific word (not X/o) whose name is the patient's own name is the patient.
            if not re.search(r"/", r or "") and any(_same_name(n, m) for m in self.f.names):
                continue
            self.rel(r, n)
        return self.f


def _stray_ids(fb: _FB, text: str, labelled_mrn: bool = True) -> None:
    """Pattern identifiers in an untyped string."""
    try:
        for sp in patterns.find_identifiers(text):
            surf = text[sp.start:sp.end]
            if sp.kind == "AADHAAR_MASKED":
                fb.raw(surf)
            elif sp.kind in _IDPREF:
                fb.tok(_IDPREF[sp.kind], sp.value, surf)
        for sp in patterns.find_patient_ids(text, after_label_only=labelled_mrn):
            surf = text[sp.start:sp.end]
            fb.tok(ID_ENC if _ENC_RX.search(sp.value.upper()) else ID_UHID, sp.value, surf)
    except Exception:  # noqa: BLE001
        pass


def _text_facts(text: str, order: str = "dmy") -> Optional[Facts]:
    if not text or not text.strip():
        return None
    if _detect_text_facts is not None:
        try:
            return _detect_text_facts(text, order)
        except Exception:  # noqa: BLE001
            pass
    fb = _FB()          # fallback: identifiers only
    _stray_ids(fb, text)
    return fb.f


def _date_order(values: Sequence[Any], label: str = "") -> str:
    try:
        return dates.infer_order([v for v in values if isinstance(v, str)], label)
    except Exception:  # noqa: BLE001
        return "dmy"


def _parse_date(s: str, order: str) -> Optional[dt.date]:
    s = (s or "").strip()
    if not s:
        return None
    try:
        d = dates.parse_one(s, order)
        if d is None:
            m = re.match(r"^(\d{4}-\d{2}-\d{2})[T ]", s)
            if m:
                d = dates.parse_one(m.group(1), order)
        return d
    except Exception:  # noqa: BLE001
        return None


def _age_of(s: str) -> Optional[int]:
    t = to_ascii_digits(s or "")
    m = re.match(r"^\s*([0-9]{1,3})(?![0-9.])", t)
    if not m:
        return None
    a = int(m.group(1))
    if a > 120:
        return None
    rest = t[m.end():].strip().lower()
    if re.match(r"^(?:mo|mon|months?|mths?|d|days?|wk|wks|weeks?|महीने|माह|दिन)(?![a-z])", rest):
        return 0
    return a


def _gender_in(s: str) -> str:
    m = re.search(r"([A-Za-zऀ-ॿ]+)\.?\s*$", s or "")
    if m:
        g = gender_of(m.group(1))
        if g:
            return g
    m = re.match(r"^\s*([A-Za-zऀ-ॿ]+)", s or "")
    return gender_of(m.group(1)) if m else ""


def put(fb: _FB, typ: str, value: Any, order: str = "dmy", group: str = "") -> None:
    """Fold one typed value into the facts."""
    if isinstance(value, float) and typ != F.AGE:
        return
    s = _s(value)
    if not s or _blank(s):
        return
    if typ in _PATIENT_SIGNAL:
        fb.signal = True
    f = fb.f
    if typ in (F.NAME, F.LOCAL_NAME):
        fb.name(s)
    elif typ == F.FIRST_NAME:
        fb.first[group] = (fb.first.get(group, "") + " " + s).strip()
    elif typ == F.LAST_NAME:
        fb.last[group] = (fb.last.get(group, "") + " " + s).strip()
    elif typ == F.RELATIVE:
        fb.relnames.setdefault(group, []).append(s)
    elif typ == F.RELATION:
        fb.relation[group] = s
    elif typ in (F.PATIENT_ID, F.ENC_ID):
        v = patterns.norm_id(s)
        if len(re.sub(r"[^0-9]", "", v)) >= 3:
            enc = typ == F.ENC_ID or bool(_ENC_RX.search(v))
            fb.tok(ID_ENC if enc else ID_UHID, v, s)
    elif typ == F.AADHAAR:
        d = re.sub(r"[^0-9]", "", to_ascii_digits(s))
        if len(d) == 12 and not re.search(r"[xX*]", s):
            fb.tok(ID_AADHAAR, d, s)
        else:
            fb.raw(s)
    elif typ == F.ABHA:
        d = re.sub(r"[^0-9]", "", to_ascii_digits(s))
        if len(d) == 14:
            fb.tok(ID_ABHA, d, s)
        else:
            fb.raw(s)
    elif typ == F.ABHA_ADDR:
        fb.tok(ID_ABHA_ADDR, s.lower(), s)
    elif typ == F.PAN:
        fb.tok(ID_PAN, re.sub(r"\s", "", s).upper(), s)
    elif typ == F.INSURANCE:
        fb.tok(ID_INS, patterns.norm_id(s), s)
    elif typ == F.EMAIL:
        fb.tok(ID_EMAIL, s.lower(), s)
    elif typ == F.PHONE:
        p = patterns.norm_phone(s)
        if p:
            fb.tok(ID_PHONE, p, s)
        else:
            _stray_ids(fb, s)
    elif typ == F.DOB:
        d = _parse_date(s, order)
        if d is not None and f.dob is None:
            f.dob = d
    elif typ == F.AGE:
        a = _age_of(s)
        if a is not None and f.age is None:
            f.age = a
    elif typ == F.AGE_SEX:
        a = _age_of(s)
        if a is None:
            m = re.search(r"([0-9]{1,3})", to_ascii_digits(s))
            a = int(m.group(1)) if m and int(m.group(1)) <= 120 else None
        if a is not None and f.age is None:
            f.age = a
        g = _gender_in(s)
        if g and not f.gender:
            f.gender = g
    elif typ == F.GENDER:
        g = gender_of(s)
        if g and not f.gender:
            f.gender = g
    elif typ == F.VILLAGE:
        if not f.village:
            f.village = s
    elif typ == F.TEHSIL:
        if not f.tehsil:
            f.tehsil = s
    elif typ == F.DISTRICT:
        if not f.district:
            f.district = s
    elif typ == F.PIN:
        d = re.sub(r"[^0-9]", "", to_ascii_digits(s))
        if len(d) == 6 and not f.pin:
            f.pin = d
    elif typ in (F.HOUSE, F.LOCALITY):
        if s not in f.address_parts:
            f.address_parts.append(s)
    elif typ == F.ADDRESS:
        g = _text_facts(s, order)
        if g is not None:
            g.names = []          # an address never names the patient; keep C/O relatives, places
            g.ref_date = None
            fb.merge(g)
        if s not in f.address_parts:
            f.address_parts.append(s)
    elif typ == F.DATE:
        fb.ref(_parse_date(s, order))
    elif typ in (F.FREE_TEXT, F.OTHER, F.OTHER_ID):
        dec = try_b64_text(s) if " " not in s else None
        if dec:
            fb.merge(_text_facts(dec, order))
        elif typ == F.FREE_TEXT:
            fb.merge(_text_facts(s, order))
        elif typ == F.OTHER:
            _stray_ids(fb, s)


# ---------------------------------------------------------------- JSON structure

def _leaves(node: Any, keys: List[Any], depth: int = 0):
    """(path keys incl. list indexes, value) of every scalar leaf; bounded depth."""
    if depth > MAX_DEPTH:
        return
    if isinstance(node, dict):
        for k in list(node.keys()):
            for x in _leaves(node[k], keys + [str(k)], depth + 1):
                yield x
    elif isinstance(node, list):
        for i, v in enumerate(node):
            for x in _leaves(v, keys + [i], depth + 1):
                yield x
    else:
        yield keys, node


def _ktype(keys: Sequence[Any], value: Any) -> str:
    try:
        return F.json_key_type([k for k in keys if not isinstance(k, int)], value)
    except Exception:  # noqa: BLE001
        return F.OTHER


def _is_record(elem: Any, prefix: List[Any]) -> bool:
    if not isinstance(elem, dict):
        return False
    for n, (keys, v) in enumerate(_leaves(elem, list(prefix))):
        if n > 400:
            break
        if _s(v) and _ktype(keys, v) in _RECORD_SIGNAL:
            return True
    return False


def _record_arrays(node: Any, ptr: str, keys: List[Any], out: List[Tuple[str, List[Any], Any]],
                   depth: int = 0) -> None:
    """Find lists of record objects; arrays nested inside a record are not split."""
    if depth > MAX_DEPTH:
        return
    if isinstance(node, list):
        named = bool(keys) and not isinstance(keys[-1], int) and \
            _RECORD_KEY.search(str(keys[-1]).lower()) is not None
        if node and (any(_is_record(e, keys) for e in node[:50])
                     or ((named or (depth == 0 and not ptr)) and all(isinstance(e, dict) for e in node))):
            for i, e in enumerate(node):
                out.append(("%s/%d" % (ptr, i), keys, e))
            return
        for i, e in enumerate(node):
            if isinstance(e, (dict, list)):
                _record_arrays(e, "%s/%d" % (ptr, i), keys, out, depth + 1)
    elif isinstance(node, dict):
        for k in list(node.keys()):
            v = node[k]
            if isinstance(v, (dict, list)):
                _record_arrays(v, "%s/%s" % (ptr, _ptr(str(k))), keys + [str(k)], out, depth + 1)


def _single_record(d: dict) -> bool:
    """A top-level object that itself describes one patient (identity leaves outside any array)."""
    for k in list(d.keys()):
        v = d[k]
        if isinstance(v, list):
            continue
        for keys, x in _leaves(v, [str(k)]):
            if any(isinstance(p, int) for p in keys):
                continue
            if _s(x) and _ktype(keys, x) in (F.PATIENT_ID, F.AADHAAR, F.ABHA, F.DOB):
                return True
    return False


def _json_units(pf: ParsedFile) -> List[Tuple[str, List[Any], Any]]:
    data = pf.data
    if pf.kind != KIND_JSON or not isinstance(data, (dict, list)):
        return []
    try:
        if isinstance(data, dict) and _single_record(data):
            return []
        out: List[Tuple[str, List[Any], Any]] = []
        _record_arrays(data, "", [], out)
        return out
    except Exception:  # noqa: BLE001
        return []


def record_locs(pf: ParsedFile) -> List[str]:
    """Input locators of the records of a parsed file."""
    if pf.kind == KIND_QUARANTINE:
        return []
    if pf.kind == KIND_CSV:
        return ["row:%d" % i for i in range(len(pf.rows))]
    units = _json_units(pf)
    if units:
        return [u[0] for u in units]
    return ["doc"]


# ---------------------------------------------------------------- per kind

def _csv_records(pf: ParsedFile) -> List[Record]:
    header = list(pf.header or [])
    rows = pf.rows or []
    width = max([len(header)] + [len(r or []) for r in rows])
    types: List[str] = []
    orders: List[str] = []
    for c in range(width):
        label = header[c] if c < len(header) else ""
        col = [r[c] for r in rows if r and c < len(r) and r[c] is not None]
        try:
            t = F.classify_column(label or "", col[:500])
        except Exception:  # noqa: BLE001
            t = F.OTHER
        t = _override(pf).get(c, t)
        types.append(t)
        orders.append(_date_order(col, label or "") if t in (F.DATE, F.DOB) else "")
    file_patient = any(t in _PATIENT_SIGNAL for t in types)
    text_order = _date_order([v for r in rows[:300] for v in (r or []) if isinstance(v, str)
                              and _DATEISH.search(v)])
    out: List[Record] = []
    for i, row in enumerate(rows):
        fb = _FB()
        for c, v in enumerate(row or []):
            if c < len(types):
                put(fb, types[c], v, orders[c] or text_order)
        f = fb.finish()
        f.is_patient = file_patient
        out.append(Record(rel=pf.rel, loc="row:%d" % i, facts=f))
    return out


def _json_orders(data: Any) -> Dict[str, str]:
    by_key: Dict[str, List[str]] = {}
    for keys, v in _leaves(data, []):
        if isinstance(v, str) and _DATEISH.search(v):
            k = next((str(x) for x in reversed(keys) if not isinstance(x, int)), "")
            by_key.setdefault(k, []).append(v)
    return {k: _date_order(vs, k) for k, vs in sorted(by_key.items())}


def _harvest_tree(fb: _FB, node: Any, prefix: List[Any], orders: Dict[str, str],
                  ov: Optional[Dict[Any, str]] = None) -> None:
    for n, (keys, v) in enumerate(_leaves(node, list(prefix))):
        if n > 20000:
            break
        if _s(v) == "":
            continue
        last = next((str(x) for x in reversed(keys) if not isinstance(x, int)), "")
        group = "/".join(str(x) for x in keys[:-1])
        t = _ktype(keys, v)
        if ov:
            t = ov.get(_sig(keys), t)
        put(fb, t, v, orders.get(last, "dmy"), group)


def _json_records(pf: ParsedFile) -> List[Record]:
    data = pf.data
    orders = _json_orders(data)
    units = _json_units(pf)
    out: List[Record] = []
    if units:
        for loc, keys, elem in units:
            fb = _FB()
            _harvest_tree(fb, elem, keys, orders, _override(pf))
            f = fb.finish()
            f.is_patient = fb.signal or _has_patient_facts(f)
            out.append(Record(rel=pf.rel, loc=loc, facts=f))
        return out
    fb = _FB()
    _harvest_tree(fb, data, [], orders)
    _file_name_facts(fb, pf.rel)
    f = fb.finish()
    f.is_patient = fb.signal or _has_patient_facts(f)
    if _mixed_patients(f):
        # an index / roster keyed by several patients: scrub every id and name, link to nobody
        for t in f.ids:
            raw = t.split(":", 1)[-1]
            if raw and raw not in f.raw_ids:
                f.raw_ids.append(raw)
        f.ids = []
        f.is_patient = False
    return [Record(rel=pf.rel, loc="doc", facts=f)]


def _mixed_patients(f: Facts) -> bool:
    """Facts that name two or more different patients (two UHIDs, or unrelated full names)."""
    uh = sorted({t for t in f.ids if t.split(":", 1)[0] == ID_UHID})
    if len(uh) >= 2:
        return True
    full = [n for n in f.names if len(n.split()) >= 2]
    for i in range(len(full)):
        for j in range(i + 1, len(full)):
            if not _same_name(full[i], full[j]):
                return True
    return False


def _has_patient_facts(f: Facts) -> bool:
    """Demographics or a patient-owned identifier: a caller's name + phone is not enough."""
    if f.dob is not None or f.age is not None or f.gender:
        return True
    return any(t.split(":", 1)[0] in _STRONG_ID_TYPES for t in f.ids)


def _looks_patient(f: Facts) -> bool:
    """Text documents: detect only reports PATIENT_NAME / kinship in patient context."""
    return _has_patient_facts(f) or bool(f.names) or bool(f.relatives)


def _text_records(pf: ParsedFile) -> List[Record]:
    text = pf.text or ""
    order = _date_order(_DATEISH.findall(text))
    fb = _FB()
    fb.merge(_text_facts(text, order))
    _file_name_facts(fb, pf.rel)
    f = fb.finish()
    f.is_patient = _looks_patient(f)
    return [Record(rel=pf.rel, loc="doc", facts=f)]


# ---------------------------------------------------------------- FHIR

def _lst(v: Any) -> list:
    return v if isinstance(v, list) else ([v] if isinstance(v, dict) else [])


def _fhir_name(n: Any) -> str:
    if isinstance(n, str):
        return n.strip()
    if not isinstance(n, dict):
        return ""
    if _s(n.get("text")):
        return _s(n.get("text"))
    given = n.get("given")
    parts = [g for g in given if isinstance(g, str)] if isinstance(given, list) else []
    if isinstance(given, str):
        parts = [given]
    if _s(n.get("family")):
        parts.append(_s(n.get("family")))
    return " ".join(parts)


def _fhir_patient(fb: _FB, r: dict) -> None:
    fb.signal = True
    for n in _lst(r.get("name")):
        fb.name(_fhir_name(n))
        if isinstance(n, dict) and _s(n.get("text")):
            fb.name(_fhir_name({"given": n.get("given"), "family": n.get("family")}))
    for ident in _lst(r.get("identifier")):
        if not isinstance(ident, dict):
            continue
        v = _s(ident.get("value"))
        if not v:
            continue
        system = _s(ident.get("system")).lower()
        typ = ident.get("type") if isinstance(ident.get("type"), dict) else {}
        codes = [_s(c.get("code")).upper() for c in _lst(typ.get("coding")) if isinstance(c, dict)]
        digits = re.sub(r"[^0-9]", "", to_ascii_digits(v))
        if "MR" in codes or "uhid" in system or "mrn" in system:
            fb.tok(ID_UHID, patterns.norm_id(v), v)
        elif "abdm" in system or "healthid" in system or "abha" in system:
            if "@" in v:
                fb.tok(ID_ABHA_ADDR, v.lower(), v)
            elif len(digits) == 14:
                fb.tok(ID_ABHA, digits, v)
            else:
                fb.raw(v)
        elif "aadhaar" in system or "uidai" in system:
            if len(digits) == 12 and not re.search(r"[xX*]", v):
                fb.tok(ID_AADHAAR, digits, v)
            else:
                fb.raw(v)
        else:
            before = len(fb.f.ids)
            _stray_ids(fb, v, labelled_mrn=False)
            if len(fb.f.ids) == before:
                fb.raw(v)
    for t in _lst(r.get("telecom")):
        if isinstance(t, dict):
            v = _s(t.get("value"))
            put(fb, F.EMAIL if (_s(t.get("system")).lower() == "email" or "@" in v) else F.PHONE, v)
    g = gender_of(_s(r.get("gender")))
    if g:
        fb.f.gender = g
    d = _parse_date(_s(r.get("birthDate")), "dmy")
    if d is not None:
        fb.f.dob = d
    for a in _lst(r.get("address")):
        if not isinstance(a, dict):
            continue
        lines = a.get("line") if isinstance(a.get("line"), list) else [a.get("line")]
        for line in lines + [a.get("text")]:
            if isinstance(line, str) and line.strip():
                put(fb, F.ADDRESS, line)
        if _s(a.get("city")):
            fb.f.village = _s(a.get("city"))
        if _s(a.get("district")):
            fb.f.district = _s(a.get("district"))
        pc = re.sub(r"[^0-9]", "", _s(a.get("postalCode")))
        if len(pc) == 6:
            fb.f.pin = pc


def _fhir_records(pf: ParsedFile) -> List[Record]:
    fb = _FB()
    data = pf.data if isinstance(pf.data, dict) else {}
    res = [e.get("resource") for e in _lst(data.get("entry"))
           if isinstance(e, dict) and isinstance(e.get("resource"), dict)]
    texts: List[str] = []
    enc_date = comp_date = None
    for r in res:
        rt = _s(r.get("resourceType"))
        if rt == "Patient":
            _fhir_patient(fb, r)
        elif rt == "Encounter":
            for ident in _lst(r.get("identifier")):
                v = _s(ident.get("value")) if isinstance(ident, dict) else ""
                if v:
                    fb.tok(ID_ENC, patterns.norm_id(v), v)
            per = r.get("period") if isinstance(r.get("period"), dict) else {}
            enc_date = enc_date or _parse_date(_s(per.get("start")), "dmy")
        elif rt == "RelatedPerson":
            relw = ""
            for c in _lst(r.get("relationship")):
                if isinstance(c, dict):
                    relw = _s(c.get("text")) or relw
            for n in _lst(r.get("name")):
                fb.rel(relw, _fhir_name(n))
        elif rt == "Composition":
            comp_date = comp_date or _parse_date(_s(r.get("date")), "dmy")
        tx = r.get("text")
        if isinstance(tx, dict) and isinstance(tx.get("div"), str):
            texts.append(_TAG_RX.sub(" ", tx["div"]))
        for keys, v in _leaves(r, []):
            if isinstance(v, str) and keys and keys[-1] == "data":
                dec = try_b64_text(v)
                if dec:
                    texts.append(dec)
    fb.f.ref_date = enc_date or comp_date
    for t in texts:
        g = _text_facts(t, "dmy")
        if g is not None:
            g.ref_date = None
            fb.merge(g)
    _file_name_facts(fb, pf.rel)
    f = fb.finish()
    f.is_patient = True
    return [Record(rel=pf.rel, loc="doc", facts=f)]


# ---------------------------------------------------------------- file names

def _file_name_facts(fb: _FB, rel: str) -> None:
    """Names and identifiers carried by the file name of a single-record file."""
    base = re.sub(r"\.[A-Za-z0-9]{1,5}$", "", (rel or "").rsplit("/", 1)[-1])
    base = base.replace("_", " ")     # '_' joins words, '-' may sit inside an identifier
    if not base:
        return
    spans: List[Tuple[int, int]] = []
    try:
        for sp in patterns.find_identifiers(base):
            if sp.kind in _IDPREF and sp.kind != "INSURANCE_ID":
                fb.tok(_IDPREF[sp.kind], sp.value, base[sp.start:sp.end])
                spans.append((sp.start, sp.end))
        for sp in patterns.find_patient_ids(base):
            if any(s < sp.end and sp.start < e for s, e in spans) or not re.search(r"[A-Z]", sp.value):
                continue
            fb.tok(ID_ENC if _ENC_RX.search(sp.value) else ID_UHID, sp.value, base[sp.start:sp.end])
            spans.append((sp.start, sp.end))
    except Exception:  # noqa: BLE001
        pass
    rest = base
    for s, e in sorted(spans, reverse=True):
        rest = rest[:s] + " " + rest[e:]
    # a run of 2-4 capitalised words that are not document words is a name
    run: List[str] = []
    best: List[str] = []
    for t in [t for t in re.split(r"[_\-\s.]+", rest) if t] + [""]:
        if re.fullmatch(r"[A-Z][a-z]+|[ऀ-ॿ]+", t) and t.lower() not in _DOC_WORDS:
            run.append(t)
            continue
        if 2 <= len(run) <= 4 and len(run) > len(best):
            best = run
        run = []
    if best:
        fb.name(" ".join(best))


# ---------------------------------------------------------------- cross-file id evidence
# A column / key whose label says nothing ("Kramank", "ref", "hosp_no" in a new language) but whose
# values are hospital ids already known from OTHER files of the same dataset is a patient-id slot.
_OVERRIDES: Dict[str, Dict[Any, str]] = {}
_UPGRADABLE = frozenset({F.OTHER, F.OTHER_ID, F.FREE_TEXT, F.CLINICAL, F.HOSPITAL})


def _okey(pf: ParsedFile) -> str:
    return pf.sha256 or pf.rel


def _override(pf: ParsedFile) -> Dict[Any, str]:
    return _OVERRIDES.get(_okey(pf), {})


def _sig(keys: Sequence[Any]) -> Tuple[str, ...]:
    return tuple(str(k) for k in keys if not isinstance(k, int))


def _slots(pf: ParsedFile) -> Dict[Any, Tuple[str, List[str]]]:
    """slot (CSV column index / JSON key signature) -> (current type, string values)."""
    out: Dict[Any, Tuple[str, List[str]]] = {}
    if pf.kind == KIND_CSV:
        header = list(pf.header or [])
        rows = pf.rows or []
        width = max([len(header)] + [len(r or []) for r in rows])
        for c in range(width):
            col = [r[c] for r in rows if r and c < len(r) and r[c] is not None]
            try:
                t = F.classify_column(header[c] if c < len(header) else "", col[:500])
            except Exception:  # noqa: BLE001
                t = F.OTHER
            out[c] = (t, [_s(v) for v in col if _s(v)])
    elif pf.kind == KIND_JSON:
        for n, (keys, v) in enumerate(_leaves(pf.data, [])):
            if n > 20000:
                break
            sv = _s(v)
            if not sv or isinstance(v, float):
                continue
            sg = _sig(keys)
            t = _ktype(keys, v)
            cur = out.get(sg)
            if cur is None:
                out[sg] = (t, [sv])
            else:
                cur[1].append(sv)
                if cur[0] != t and t not in _UPGRADABLE:
                    out[sg] = (t, cur[1])
    return out


def _id_key(v: str) -> str:
    k = patterns.norm_id(v)
    return k if len(re.sub(r"[^0-9]", "", k)) >= 3 else ""


def reset() -> None:
    """Forget cross-file typing state (called at the start and end of every pipeline run)."""
    _OVERRIDES.clear()


def has_override(pf: ParsedFile) -> bool:
    return bool(_OVERRIDES.get(_okey(pf)))


def prepare(pfs: Sequence[ParsedFile]) -> Dict[str, List[Record]]:
    """Two-pass typing: harvest every file once, collect the hospital / admission ids typed by
    label or shape, then mark slots of other files whose values overlap them (>= half of the
    distinct values) as PATIENT_ID / ENC_ID for the following harvest_file calls."""
    _OVERRIDES.clear()
    owners: Dict[str, Set[str]] = {}
    first: Dict[str, List[Record]] = {}
    for pf in pfs:
        try:
            recs = list(harvest_file(pf))
            first[_okey(pf)] = recs
            for r in recs:
                for t in (r.facts.ids if r.facts else []):
                    typ, _, val = t.partition(":")
                    if typ in (ID_UHID, ID_ENC):
                        owners.setdefault(typ + ":" + patterns.norm_id(val), set()).add(_okey(pf))
        except Exception:  # noqa: BLE001
            continue
    for pf in pfs:
        try:
            ov: Dict[Any, str] = {}
            me = _okey(pf)
            for slot, (t, vals) in _slots(pf).items():
                if t not in _UPGRADABLE:
                    continue
                distinct = {k for k in (_id_key(v) for v in vals) if k}
                if not distinct or len(distinct) < 0.6 * len(set(vals)):
                    continue
                hits = {}
                for typ in (ID_UHID, ID_ENC):
                    hits[typ] = sum(1 for k in distinct if owners.get(typ + ":" + k, set()) - {me})
                best = max(hits, key=lambda x: hits[x])
                if hits[best] and hits[best] >= 0.5 * len(distinct):
                    ov[slot] = F.ENC_ID if best == ID_ENC else F.PATIENT_ID
            if ov:
                _OVERRIDES[me] = ov
        except Exception:  # noqa: BLE001
            continue
    return first


def harvest_all(pfs: Sequence[ParsedFile]) -> Dict[str, List[Record]]:
    """harvest_file for every file, with cross-file id evidence (see prepare)."""
    prepare(pfs)
    return {pf.rel: harvest_file(pf) for pf in pfs}


# ---------------------------------------------------------------- entry point

def harvest_file(pf: ParsedFile) -> List[Record]:
    """One Record (input locator + identity facts) per record of a parsed file."""
    try:
        if pf.kind == KIND_QUARANTINE:
            return []
        if pf.kind == KIND_CSV:
            return _csv_records(pf)
        if pf.kind == KIND_JSON:
            return _json_records(pf)
        if pf.kind == KIND_FHIR:
            return _fhir_records(pf)
        if pf.kind == KIND_TEXT:
            return _text_records(pf)
    except Exception:  # noqa: BLE001 - never raise; empty facts per locator instead
        pass
    try:
        return [Record(rel=pf.rel, loc=loc, facts=Facts()) for loc in record_locs(pf)]
    except Exception:  # noqa: BLE001
        return [Record(rel=pf.rel, loc="doc", facts=Facts())]
