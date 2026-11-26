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
                         r"registrations?|opd|ipd|cases?|samples?|discharges?|claims?|bills?|"
                         r"slips?|parchi(?:yan|yaan|ya)?|parche|rogi|mareez|marij)$")

_ENC_RX = re.compile(r"(?:^|[^A-Z])(?:IPD|IP|ADM|ADMN|INP|ADMISSION)(?=[^A-Z]|$)")
_REL_RX = re.compile(
    r"^\s*(?:([SDWHCG])\s*/\s*[Oo]|(son|daughter|wife|husband|care|ward)\s+of"
    r"|(पुत्री|पुत्र|पत्नी|पति|पिता|माता)(?![\u093e-\u094d]))\.?\s*[:\-]?\s*(.*)$", re.I | re.S)
_DATEISH = re.compile(r"(?<![0-9])[0-9०-९]{1,4}[./\-][0-9०-९]{1,2}[./\-][0-9०-९]{2,4}(?![0-9])")
_TAG_RX = re.compile(r"<[^>]+>")
_LETTER = re.compile(r"[A-Za-zऀ-ॿ]")
_EMPTY = frozenset({"", "-", "--", "na", "n/a", "nil", "none", "null", "nan", "not available", "unknown"})
_MALE = frozenset({"m", "male", "man", "boy", "पुरुष", "पुरूष", "पु", "purush", "purus", "mard", "ladka"})
_FEMALE = frozenset({"f", "female", "woman", "girl", "महिला", "स्त्री", "mahila", "aurat", "ladki"})
_DOC_WORDS = frozenset("""
discharge summary report reports note notes nursing lab labs final copy scan scanned rx opd ipd
prescription record records file export draft new old patient patients case sheet form letter
referral consent bill invoice receipt claim ds dr doc document visit admission card slip summary
छुट्टी कार्ड पर्ची रिपोर्ट पत्र सारांश नोट रसीद बिल जांच जाँच पंजीकरण रेफर पत्रक डिस्चार्ज पर्चा
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


_LABEL_TEXT: Dict[str, bool] = {}
# a label carries a field word; "Suresh Nagar" (a surname that also reads as a place label) does not
_LABEL_WORD = re.compile(r"(?i)(?:^|[\s_./(\-])(?:name|naam|uhid|mrn|id|no|number|mobile|phone|contact|"
                         r"aadhaar|aadhar|uid|village|address|age|sex|gender|dob|date|diagnosis|ward|"
                         r"district|pin|pincode|tehsil|relation|relative|guardian|husband|father)(?:$|[\s_.:)#\-])|"
                         r"नाम|मोबाइल|आधार|गाँव|गांव|पता|उम्र|लिंग")


def _is_label_text(s: str) -> bool:
    """A "name" that is a column label (a repeated header row, the label column of a transposed
    table): never a person, and never a forbidden surface for the whole release."""
    if len(s) > 40 or len(s.split()) > 4 or not _LABEL_WORD.search(s):
        return False
    hit = _LABEL_TEXT.get(s)
    if hit is None:
        try:
            hit = F.classify_label(s) not in ("", F.OTHER) and F.classify_label(s) is not None
        except Exception:  # noqa: BLE001
            hit = False
        if len(_LABEL_TEXT) < 50000:
            _LABEL_TEXT[s] = hit
    return hit


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
        if not s or _blank(s) or not _LETTER.search(s) or _is_label_text(s):
            return
        if s not in self.f.names:
            self.f.names.append(s)

    def rel(self, relation: str, name: str) -> None:
        name = " ".join((name or "").split())
        if not name or _blank(name) or not _LETTER.search(name) or _is_label_text(name):
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
        if not f.district or getattr(fb, "addr_district", False):
            f.district = s        # a district column beats a district guessed from an address line
            fb.addr_district = False
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
            had = bool(f.district)
            fb.merge(g)
            if not had and f.district:
                fb.addr_district = True
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


_PERSON_LEAF = frozenset({F.NAME, F.FIRST_NAME, F.LAST_NAME, F.PHONE, F.EMAIL, F.PATIENT_ID})


def _homogeneous(node: list, keys: List[Any]) -> bool:
    """Two or more objects of one shape (shared keys) of which some carry a person leaf."""
    if len(node) < 2 or not all(isinstance(e, dict) and e for e in node):
        return False
    common = set(node[0].keys())
    union = set(node[0].keys())
    for e in node[1:]:
        common &= set(e.keys())
        union |= set(e.keys())
    if len(common) < 2 or len(common) * 2 < len(union):
        return False
    for e in node[:50]:
        for n, (lk, v) in enumerate(_leaves(e, list(keys))):
            if n > 200:
                break
            if _s(v) and _ktype(lk, v) in _PERSON_LEAF:
                return True
    return False


def _record_arrays(node: Any, ptr: str, keys: List[Any], out: List[Tuple[str, List[Any], Any]],
                   depth: int = 0, homog: bool = False) -> None:
    """Find lists of record objects; arrays nested inside a record are not split."""
    if depth > MAX_DEPTH:
        return
    if isinstance(node, list):
        named = bool(keys) and not isinstance(keys[-1], int) and \
            _RECORD_KEY.search(str(keys[-1]).lower()) is not None
        if node and (any(_is_record(e, keys) for e in node[:50])
                     or (homog and _homogeneous(node, keys))
                     or ((named or (depth == 0 and not ptr)) and all(isinstance(e, dict) for e in node))):
            for i, e in enumerate(node):
                out.append(("%s/%d" % (ptr, i), keys, e))
            return
        for i, e in enumerate(node):
            if isinstance(e, (dict, list)):
                _record_arrays(e, "%s/%d" % (ptr, i), keys, out, depth + 1, homog)
    elif isinstance(node, dict):
        if _keyed_collection(node, keys):
            for k in list(node.keys()):
                out.append(("%s/%s" % (ptr, _ptr(str(k))), keys, node[k]))
            return
        for k in list(node.keys()):
            v = node[k]
            if isinstance(v, (dict, list)):
                _record_arrays(v, "%s/%s" % (ptr, _ptr(str(k))), keys + [str(k)], out, depth + 1, homog)


_ID_KEY = re.compile(r"^(?=[^0-9]*(?:[0-9][^0-9]*){4})[A-Za-z0-9][A-Za-z0-9/_.\-]{3,40}$")
_NOT_ID_KEY = re.compile(r"^(?:[A-Za-z]-?[0-9]{1,4}|[0-9]{4}[-/.][0-9]{1,2}(?:[-/.][0-9]{1,2})?.*|[0-9]{1,4})$")


def id_shaped_key(k: str) -> bool:
    """A JSON object key that is itself a hospital / patient number ("HN-771204", "MRD/2026/0042")."""
    k = str(k)
    return bool(_ID_KEY.match(k)) and not _NOT_ID_KEY.match(k)


_PHONE_KEY = re.compile(r"^\+?[0-9][0-9 ().\-]{8,18}$")
_NAME_KEY = re.compile(r"^(?:[A-Z][A-Za-z'.]*(?:[ \t]+[A-Z][A-Za-z'.]*){1,4}|[\u0900-\u097F]+(?:[ \t]+[\u0900-\u097F]+){1,3})$")
_NAME_PARENT = re.compile(r"name|naam|nm$|patient|mareez|person|^pts?$", re.I)
_ID_PARENT = re.compile(r"^by.?(?:id|uhid|mrn|reg|hosp|no)|patients?$|uhid|mrn|regist", re.I)
_INSTITUTION = re.compile(r"(?:^|\s)(?:ward|wing|block|hospital|college|centre|center|clinic|lab|"
                          r"laboratory|unit|dept|department|memorial|trust|mission|icu|ot|opd|ipd)(?:\s|$)", re.I)


_DOCNO_KEY = re.compile(r"^(?:LAB|LB|RPT|REP|REPORT|SMP|SAMPLE|SPEC|ACC|ACCN|INV|BILL|RCPT|RCT|CLM|CLAIM|ORD|ORDER|"
                        r"TKT|TICKET|SES|SESS|SESSION|BATCH|LOT|REQ|REF|APPT|PA|PREAUTH)[\-/_ ]?(?=[A-Z0-9\-/_]*[0-9]{3})",
                        re.IGNORECASE)


def key_kind(k: str) -> str:
    """What a JSON object key itself is: "phone", "id", "name", "doc" (a report / sample / bill /
    claim number: it keys a record but is not the patient's identifier) or ""."""
    k = str(k).strip()
    if _DOCNO_KEY.match(k) and id_shaped_key(k):
        return "doc"
    d = re.sub(r"[^0-9]", "", to_ascii_digits(k))
    if _PHONE_KEY.match(to_ascii_digits(k)) and (
            (len(d) == 10 and d[0] in "6789") or (len(d) == 12 and d.startswith("91") and d[2] in "6789")
            or (len(d) == 11 and d[0] == "0")):
        return "phone"
    if id_shaped_key(k):
        return "id"
    if _NAME_KEY.match(k) and not _INSTITUTION.search(k):
        return "name"
    return ""


def _keyed_collection(node: dict, keys: List[Any]) -> bool:
    """An object whose keys are all of one identifier kind and whose values are record objects: a
    record collection keyed by patient id, by mobile number or by patient name
    ({"patients": {"<id>": {...}}}, {"byMobile": {"<phone>": {...}}}, {"byName": {"<name>": {...}}})."""
    if not node or len(node) > 100000:
        return False
    ks = list(node.keys())
    if not all(isinstance(node[k], dict) for k in ks):
        return False
    kinds = {key_kind(k) for k in ks}
    if len(kinds) != 1 or "" in kinds:
        return False
    kind = kinds.pop()
    parent = str(keys[-1]) if keys and not isinstance(keys[-1], int) else ""
    if kind == "phone":
        return True
    if kind == "doc":
        kind = "id"
    if kind == "name":
        return bool(parent) and _NAME_PARENT.search(parent) is not None
    if parent and _ID_PARENT.search(parent) and len(ks) >= 2:
        return True
    sig = _RECORD_SIGNAL | {F.NAME, F.PHONE, F.FIRST_NAME, F.LAST_NAME}
    for k in ks[:50]:
        for n, (lk, v) in enumerate(_leaves(node[k], list(keys))):
            if n > 200:
                break
            if _s(v) and _ktype(lk, v) in sig:
                return True
    return False


def keyed_record_key(loc: str) -> Tuple[str, str]:
    """(kind, key) of a keyed-collection record locator ("/byMobile/98..." -> ("phone", "98...")),
    else ("", "")."""
    seg = loc.rsplit("/", 1)[-1] if loc.startswith("/") else ""
    seg = seg.replace("~1", "/").replace("~0", "~")
    if not seg or seg.isdigit() and key_kind(seg) != "phone":
        return "", ""
    kind = key_kind(seg)
    return (kind, seg) if kind else ("", "")


def keyed_record_id(loc: str) -> str:
    """The id key of a keyed-collection record locator ("/patients/HN-1" -> "HN-1"), else ''."""
    kind, seg = keyed_record_key(loc)
    return seg if kind == "id" else ""


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


def _root_person(d: dict) -> bool:
    for keys, x in _leaves(d, []):
        if any(isinstance(p, int) for p in keys):
            continue
        if _s(x) and _ktype(keys, x) in _PERSON_LEAF:
            return True
    return False


def _unit_patient_ids(units: List[Tuple[str, List[Any], Any]]) -> Set[str]:
    """Distinct patient-number values carried by the units themselves (one per unit at most)."""
    seen = set()  # type: Set[str]
    for _loc, keys, elem in units[:200]:
        if not isinstance(elem, dict):
            continue
        for n, (lk, v) in enumerate(_leaves(elem, list(keys))):
            if n > 200:
                break
            if _s(v) and _ktype(lk, v) == F.PATIENT_ID:
                seen.add(_s(v))
                break
    return seen


def _json_units(pf: ParsedFile) -> List[Tuple[str, List[Any], Any]]:
    data = pf.data
    if pf.kind != KIND_JSON or not isinstance(data, (dict, list)):
        return []
    try:
        out: List[Tuple[str, List[Any], Any]] = []
        if isinstance(data, dict) and _single_record(data) and not any(
                isinstance(v, dict) and _keyed_collection(v, [str(k)]) for k, v in data.items()):
            # export metadata naming one id ("requestedFor") does not make a visit list one record
            # when its entries carry two or more different patient numbers of their own
            _record_arrays(data, "", [], out)
            if len(_unit_patient_ids(out)) >= 2:
                return out
            return []
        _record_arrays(data, "", [], out)
        if not out and isinstance(data, dict) and not _root_person(data):
            # no id-bearing records and nobody named outside the arrays: a list of same-shaped
            # objects that carry names / phones (tickets, messages, slips) is the record list
            _record_arrays(data, "", [], out, homog=True)
        return out
    except Exception:  # noqa: BLE001
        return []


def record_locs(pf: ParsedFile) -> List[str]:
    """Input locators of the records of a parsed file."""
    if pf.kind == KIND_QUARANTINE:
        return []
    if pf.kind == KIND_CSV:
        return ["row:%d" % i for i in range(len(csv_view(pf)[1]))]
    units = _json_units(pf)
    if units:
        return [u[0] for u in units]
    return ["doc"]


# ---------------------------------------------------------------- CSV layout

_VAL_CELL = re.compile(r"[0-9]{4,}|^\s*[0-9]{1,3}\s*/\s*[MFmf]\s*$|^\s*[MFmf]\s*/\s*[0-9]{1,3}\s*$|@")


def _value_cell(c: Any) -> bool:
    """A cell whose shape never occurs in a column label: a long digit run, an age/sex pair, an e-mail."""
    s = to_ascii_digits(_s(c))
    return bool(s) and bool(_VAL_CELL.search(s.replace(" ", "").replace("-", "")) or _VAL_CELL.search(s))


def _shape_sig(c: Any) -> str:
    s = to_ascii_digits(_s(c))
    s = re.sub(r"[A-Za-z\u0900-\u097F]+", "a", s)
    s = re.sub(r"[0-9]+", lambda m: "9" if len(m.group(0)) < 4 else "9999", s)
    return re.sub(r"\s+", " ", s)


def _digit_free(row: Sequence[Any]) -> bool:
    return not any(re.search(r"[0-9]{2,}", to_ascii_digits(_s(c))) for c in row)


_CELL_CLASSES = (
    ("email", re.compile(r"^[^\s@]+@[^\s@]+$")),
    ("date", re.compile(r"^(?:\d{1,4}[./\-]\d{1,2}[./\-]\d{1,4}|\d{1,2}[ \-/.]?[A-Za-z]{3,9}[ \-/.,]*\d{2,4}|[A-Za-z]{3,9}\.? \d{1,2},? \d{4})(?:[ T]\d{1,2}:\d{2}(?::\d{2})?\s*(?:[AaPp][Mm])?)?$")),
    ("phone", re.compile(r"^(?:\+?\s*91[\s\-]?|0)?[6-9]\d{4}[\s\-]?\d{5}$|^\(?0\d{2,4}\)?[\s\-]?\d{6,8}$|^\+\d[\d\s\-]{8,15}$")),
    ("agesex", re.compile(r"^\d{1,3}\s*(?:y|yr|yrs|years?)?\s*[/,\- ]\s*[MFmfTt]$|^[MFmf]\s*[/,\- ]\s*\d{1,3}\s*(?:y|yrs?)?$")),
    ("age", re.compile(r"^\d{1,3}\s*(?:y|yr|yrs|years?|Y|M|D|mo|months?|days?)\.?$")),
    ("num", re.compile(r"^[+\-]?\d+(?:\.\d+)?$")),
    ("id", re.compile(r"^(?=[A-Za-z0-9/\-_. ]*\d{3})(?=[A-Za-z0-9/\-_. ]*[A-Za-z])[A-Za-z0-9][A-Za-z0-9/\-_.]*[A-Za-z0-9]$")),
)


def _cell_class(c: Any) -> str:
    """Value class of a cell: email / date / phone / agesex / age / num / id, or "" (text)."""
    s = to_ascii_digits(_s(c)).strip()
    if not s or len(s) > 40:
        return ""
    for name, rx in _CELL_CLASSES:
        if rx.match(s):
            return name
    return ""


def _label_cell(c: Any) -> bool:
    """A cell that reads as a column label: no digit runs and a known field label."""
    s = _s(c).strip()
    if not s or re.search(r"[0-9०-९]{2,}", s) or len(s) > 40:
        return False
    try:
        return F.classify_label(s) not in ("", F.OTHER)
    except Exception:  # noqa: BLE001
        return False


def _first_line_is_data(header: Sequence[Any], rows: Sequence[Sequence[Any]]) -> bool:
    """Line 1 is a data line when its cells have value shapes (dates, phones, ids, numbers, age/sex,
    e-mails) that agree with the column under them, and few of its cells read as labels.

    A header row almost never holds a date, a phone, an id-shaped code or a bare number; a data row
    has them in the same positions as the following lines."""
    sample = [r for r in rows[:50] if any(_s(x) for x in r)]
    agree = shaped = strong = 0
    labels = sum(1 for h in header if _label_cell(h))
    for c, h in enumerate(header):
        k = _cell_class(h)
        if not k:
            continue
        shaped += 1
        if k in ("date", "phone", "email", "agesex", "id"):
            strong += 1
        col = [_cell_class(r[c]) for r in sample if c < len(r) and _s(r[c])]
        if col and col.count(k) * 2 >= len(col):
            agree += 1
    if not sample:
        # one-line file: only the cell shapes speak
        return strong >= 2 and labels == 0
    if agree >= 2 and agree > labels:
        return True
    return agree >= 1 and strong >= 1 and labels == 0 and shaped * 3 >= len([h for h in header if _s(h)])


def _title_line(header: Sequence[Any], rows: Sequence[Sequence[Any]]) -> bool:
    """A title line above the header: one filled cell, and the next line is a row of labels."""
    if len(rows) < 2:
        return False
    filled = [h for h in header if _s(h)]
    sub = [x for x in rows[0] if _s(x)]
    if len(filled) != 1 or len(sub) < 3:
        return False
    nlab = sum(1 for x in sub if _label_cell(x))
    return nlab * 2 >= len(sub) and not any(_cell_class(x) for x in sub)


def csv_view(pf: ParsedFile) -> Tuple[List[str], List[List[str]], int]:
    """(column labels, data rows, header line count) of a parsed CSV.

    Header line count is 1 for a normal file, 0 for a headerless file (line 1 is data: its cells have
    the value shapes of the columns under them) and 2 for a title line or a sparse group row above
    the real header. Data row i always has the locator row:i."""
    header = list(pf.header or [])
    rows = [list(r or []) for r in (pf.rows or [])]
    filled = [c for c in header if _s(c)]
    if filled and _first_line_is_data(header, rows):
        return [""] * len(header), [header] + rows, 0
    if _title_line(header, rows):
        return [_s(x) for x in rows[0]], rows[1:], 2
    if rows and len(rows) >= 2 and header:
        sub = rows[0]
        sub_filled = [c for c in sub if _s(c)]
        if (len(filled) * 10 <= len(header) * 6 and len(sub_filled) > len(filled)
                and _digit_free(header) and _digit_free(sub) and not _digit_free(rows[1])):
            labels: List[str] = []
            group = ""
            width = max(len(header), len(sub))
            for c in range(width):
                g = _s(header[c]) if c < len(header) else ""
                group = g or group
                lb = _s(sub[c]) if c < len(sub) else ""
                labels.append(lb or (group if g else ""))
            return labels, rows[1:], 2
    return header, rows, 1


# ---------------------------------------------------------------- per kind

_HEAD_NAME = re.compile(r"\b(?:Mr|Mrs|Ms|Smt|Shri|Sri|Kum|Master|Baby)\.?\s+([A-Z][a-z]+(?:\s+[A-Z][a-z]+){0,3})")
_HEAD_SEP_NAME = re.compile(r"(?:^|[\-:\u2013\u2014|]\s+|\bfor\s+|\bof\s+)([A-Z][a-z]+(?:\s+[A-Z][a-z]+){1,3})\s*(?:[,(;|]|\s+[\-\u2013]\s)")
# "<label> - <Name Surname> <ID/2025/123>": a name run directly followed by an id-shaped token
_HEAD_NAME_ID = re.compile(r"(?:^|[\-:\u2013\u2014|]\s*)([A-Z][a-z]+(?:\s+[A-Z][a-z]+){1,3})\s+(?=[A-Z]{2,}[A-Z0-9]*[/\-]\d)")
_HEAD_ID = re.compile(r"\b(?:IP|OP|UHID|MRN|MR|CR|IPD|OPD|Reg)\.?\s*(?:No\.?|#)?\s*[:\-]?\s*"
                      r"([A-Z0-9][A-Z0-9/\-]{3,}[A-Z0-9])")


def _csv_records(pf: ParsedFile) -> List[Record]:
    header, rows, _hl = csv_view(pf)
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
    # A header cell that is a sentence about one patient ("Vitals chart: Mr X (IP ..) Ph ..") makes
    # every row that patient's.
    head_facts: List[Facts] = []
    if _hl == 1:
        for h in header:
            hs = _s(h)
            if len(hs) >= 20 and len(hs.split()) >= 3 and re.search(r"\d{3}", hs):
                try:
                    g = _text_facts(hs, "dmy")
                except Exception:  # noqa: BLE001
                    g = None
                if g is None:
                    continue
                for m in list(_HEAD_NAME.finditer(hs)) + list(_HEAD_SEP_NAME.finditer(hs)):
                    nm = m.group(1)
                    if nm in g.names or any(F.classify_label(w) not in ("", F.OTHER) for w in nm.split()):
                        continue
                    g.names.append(nm)
                if not g.names:
                    for m in _HEAD_NAME_ID.finditer(hs):
                        nm = m.group(1)
                        if not any(F.classify_label(w) not in ("", F.OTHER) for w in nm.split()):
                            g.names.append(nm)
                            break
                if g.names and not any(_HEAD_ID.finditer(hs)):
                    try:
                        for sp in patterns.find_patient_ids(hs):
                            if re.search(r"[A-Z]", sp.value) and re.search(r"\d{4}", sp.value):
                                t = ID_UHID + ":" + re.sub(r"[\W_]", "", sp.value).upper()
                                if t not in g.ids:
                                    g.ids.append(t)
                                    g.raw_ids.append(hs[sp.start:sp.end])
                    except Exception:  # noqa: BLE001
                        pass
                for m in _HEAD_ID.finditer(hs):
                    v = m.group(1)
                    if re.search(r"\d", v):
                        adm = re.match(r"I\.?P", m.group(0), re.I) is not None   # IP / IPD no: an admission
                        t = (ID_ENC if adm else ID_UHID) + ":" + re.sub(r"[\W_]", "", v).upper()
                        if t not in g.ids:
                            g.ids.append(t)
                        if v not in g.raw_ids:
                            g.raw_ids.append(v)
                if g.names and g.ids:
                    g.ref_date = None
                    head_facts.append(g)
    if head_facts:
        file_patient = True
    out: List[Record] = []
    for i, row in enumerate(rows):
        f = _row_facts(row, types, orders, text_order, [])
        # The file-level patient of a title line is given only to a row that carries identity
        # evidence of its own (a name, a relative, an id or a phone). A row with none (a bare vitals
        # line) stays unattributed: the organisers' key labels such rows "no patient", and a
        # stricter key counts attributing them as a false merge, so linking them can never gain.
        if head_facts and (f.names or f.relatives or f.ids):
            f = _row_facts(row, types, orders, text_order, head_facts)
        elif head_facts:
            # still scrubbed everywhere (raw surfaces, names hidden from the linker)
            skip = list(getattr(f, "link_skip", None) or [])
            for g in head_facts:
                for r in g.raw_ids + [t.split(":", 1)[-1] for t in g.ids]:
                    if r not in f.raw_ids:
                        f.raw_ids.append(r)
                for n in g.names:
                    if n not in f.names:
                        f.names.append(n)
                        skip.append(n)
            if skip:
                f.link_skip = skip
        f.is_patient = file_patient
        out.append(Record(rel=pf.rel, loc="row:%d" % i, facts=f))
    return out


def _row_facts(row: Sequence[Any], types: List[str], orders: List[str], text_order: str,
               head_facts: List[Facts]) -> Facts:
    fb = _FB()
    for g in head_facts:
        fb.merge(g)
    for c, v in enumerate(row or []):
        if c < len(types):
            put(fb, types[c], v, orders[c] or text_order)
    return fb.finish()


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
            kkind, kid = keyed_record_key(loc)
            if kkind == "id":
                put(fb, F.PATIENT_ID, kid)
            elif kkind == "phone":
                put(fb, F.PHONE, kid)
            elif kkind == "name":
                put(fb, F.NAME, kid)
            f = fb.finish()
            f.is_patient = fb.signal or _has_patient_facts(f) or bool(kkind)
            out.append(Record(rel=pf.rel, loc=loc, facts=f))
        return out
    fb = _FB()
    _harvest_tree(fb, data, [], orders)
    f = fb.finish()
    f.is_patient = fb.signal or _has_patient_facts(f)
    mixed = _mixed_patients(f)
    _merge_file_name(f, pf.rel)
    if mixed:
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
    # a short form ("Pu <name>", an initial) is not a second full name
    full = [n for n in f.names if len([w for w in n.split() if len(w.strip(".")) >= 3]) >= 2]
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
    f = fb.finish()
    _merge_file_name(f, pf.rel)
    f.is_patient = _looks_patient(f)
    if _multi_patient_text(text, f):
        # a census / register extract / roster: scrub every id and name, link to nobody
        for t in f.ids:
            raw = t.split(":", 1)[-1]
            if raw and raw not in f.raw_ids:
                f.raw_ids.append(raw)
        f.ids = []
        f.is_patient = False
    return [Record(rel=pf.rel, loc="doc", facts=f)]


_TABLE_SEP = re.compile(r"\||\t")
_LONG_RUN = re.compile(r"[0-9]{5,}")


def _multi_patient_text(text: str, f: Facts) -> bool:
    """A text that lists several people: a table with two or more rows that carry different contact
    numbers / ids, two unrelated full names, or two different relatives of one kind (two wives)."""
    rows = [ln for ln in text.splitlines()[:5000] if len(_TABLE_SEP.findall(ln)) >= 2]
    if len(rows) >= 3:
        runs = set()
        hits = 0
        for ln in rows[1:]:
            got = set(_LONG_RUN.findall(re.sub(r"(?<=[0-9])[ \-](?=[0-9])", "", to_ascii_digits(ln))))
            if got and not got <= runs:
                hits += 1
            runs |= got
        if hits >= 2:
            return True
    # a document may carry several own ids; a name taken from the file name only (hidden from the
    # linker: often the sender of a chat export) is no second patient of the text
    skip = set(getattr(f, "link_skip", None) or ())
    full = [n for n in f.names if len(n.split()) >= 2 and n not in skip]
    for i in range(len(full)):
        for j in range(i + 1, len(full)):
            if not _same_name(full[i], full[j]):
                return True
    by_rel: Dict[str, List[str]] = {}
    for r in f.relatives:
        if r and len(r) > 1 and r[0] and r[1]:
            by_rel.setdefault(str(r[0]).lower().strip(". "), []).append(r[1])
    for k in sorted(by_rel):
        if k in ("wife", "husband", "patni", "pati", "w/o", "h/o", "पत्नी", "पति"):
            ns = by_rel[k]
            for i in range(len(ns)):
                for j in range(i + 1, len(ns)):
                    if not _same_name(ns[i], ns[j]):
                        return True
    return False


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


def _fhir_ref_keys(e: dict, r: dict) -> List[str]:
    out = []
    if _s(e.get("fullUrl")):
        out.append(_s(e.get("fullUrl")))
    if _s(r.get("id")):
        out.append("Patient/" + _s(r.get("id")))
        out.append(_s(r.get("id")))
    return out


def _fhir_subject(r: dict) -> str:
    for k in ("subject", "patient", "beneficiary", "for"):
        v = r.get(k)
        if isinstance(v, dict) and _s(v.get("reference")):
            return _s(v.get("reference"))
    return ""


def _fhir_entry_records(pf: ParsedFile, entries: List[Any]) -> List[Record]:
    """A collection / batch bundle of several patients: one record per entry, each resource tied to
    the Patient its subject reference resolves to (unresolved resources belong to nobody)."""
    facts: Dict[str, Facts] = {}
    for e in entries:
        r = e.get("resource") if isinstance(e, dict) else None
        if isinstance(r, dict) and _s(r.get("resourceType")) == "Patient":
            fb = _FB()
            _fhir_patient(fb, r)
            f = fb.finish()
            f.is_patient = True
            for k in _fhir_ref_keys(e, r):
                facts.setdefault(k, f)
    out: List[Record] = []
    for i, e in enumerate(entries):
        r = e.get("resource") if isinstance(e, dict) else None
        f = None
        if isinstance(r, dict):
            if _s(r.get("resourceType")) == "Patient":
                keys = _fhir_ref_keys(e, r)
                f = facts.get(keys[0]) if keys else None
                if f is None:
                    fb = _FB()
                    _fhir_patient(fb, r)
                    f = fb.finish()
                    f.is_patient = True
            else:
                ref = _fhir_subject(r)
                f = facts.get(ref) or facts.get(ref.rsplit("/", 1)[-1]) if ref else None
        if f is None:
            f = Facts()
            f.is_patient = False
        out.append(Record(rel=pf.rel, loc="/entry/%d" % i, facts=f))
    return out


def _fhir_records(pf: ParsedFile) -> List[Record]:
    fb = _FB()
    data = pf.data if isinstance(pf.data, dict) else {}
    entries = _lst(data.get("entry"))
    n_pat = sum(1 for e in entries if isinstance(e, dict) and isinstance(e.get("resource"), dict)
                and _s(e["resource"].get("resourceType")) == "Patient")
    if n_pat >= 2 and _s(data.get("type")).lower() != "document":
        return _fhir_entry_records(pf, entries)
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
    f = fb.finish()
    _merge_file_name(f, pf.rel)
    f.is_patient = True
    return [Record(rel=pf.rel, loc="doc", facts=f)]


# ---------------------------------------------------------------- file names

def _merge_file_name(f: Facts, rel: str) -> None:
    """File-name names / ids are scrubbed everywhere but are identity evidence for the content only
    when they agree with it: a name that contradicts the content's names, and ids of a file whose
    content has hard ids of its own, are kept for scrubbing and hidden from the linker."""
    fb = _FB()
    _file_name_facts(fb, rel)
    fn = fb.finish()
    skip = list(getattr(f, "link_skip", None) or [])
    own = list(f.names)
    for n in fn.names:
        if n in f.names:
            continue
        f.names.append(n)
        if own and not any(_same_name(n, m) for m in own):
            skip.append(n)
    agree = not own or not fn.names or any(n not in skip for n in fn.names)
    hard = any(t.split(":", 1)[0] in _STRONG_ID_TYPES + (ID_PHONE,) for t in f.ids)
    for t in fn.ids:
        if t in f.ids:
            continue
        if agree and not hard:
            f.ids.append(t)
        raw = t.split(":", 1)[-1]
        if raw and raw not in f.raw_ids:
            f.raw_ids.append(raw)
    for r in fn.raw_ids:
        if r not in f.raw_ids:
            f.raw_ids.append(r)
    if skip:
        f.link_skip = skip


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
        header, rows, _hl = csv_view(pf)
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
