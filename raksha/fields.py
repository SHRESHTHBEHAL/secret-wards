"""Decide what a structured slot (CSV column, JSON key path, text label) holds.

Works from keyword stems (English, Hinglish, Hindi in Devanagari), tolerant of
misspelling, plus a shape vote over sample values. Never relies on exact header names.
Pure functions, deterministic, standard library only, Python 3.9+.
"""
from __future__ import annotations

import re
import unicodedata
from functools import lru_cache
from typing import Any, Dict, List, Optional, Sequence, Tuple

from .dates import parse_one
from .lexicon import CLINICAL_WORDS
from .normalize import to_ascii_digits
from .scripts import fold
from .translit import deva_to_latin, is_deva

# ---------------------------------------------------------------- type constants
NAME = "name"
FIRST_NAME = "first_name"
LAST_NAME = "last_name"
LOCAL_NAME = "local_name"
RELATIVE = "relative"
RELATION = "relation"
PATIENT_ID = "patient_id"
ENC_ID = "enc_id"
PHONE = "phone"
AADHAAR = "aadhaar"
ABHA = "abha"
ABHA_ADDR = "abha_addr"
PAN = "pan"
INSURANCE = "insurance"
EMAIL = "email"
ADDRESS = "address"
HOUSE = "house"
LOCALITY = "locality"
VILLAGE = "village"
TEHSIL = "tehsil"
DISTRICT = "district"
STATE = "state"
PIN = "pin"
DOB = "dob"
AGE = "age"
AGE_SEX = "age_sex"
GENDER = "gender"
DATE = "date"
DOCTOR = "doctor"
HOSPITAL = "hospital"
CLINICAL = "clinical"
FREE_TEXT = "free_text"
OTHER_ID = "other_id"
OTHER = "other"

_PII = frozenset({
    NAME, FIRST_NAME, LAST_NAME, LOCAL_NAME, RELATIVE, PATIENT_ID, ENC_ID, PHONE, AADHAAR,
    ABHA, ABHA_ADDR, PAN, INSURANCE, EMAIL, ADDRESS, HOUSE, LOCALITY, VILLAGE, TEHSIL, PIN,
    DOB, AGE, AGE_SEX,
})


def is_pii_type(t: str) -> bool:
    """True for types whose values must be removed, replaced or generalised.

    DATE (shifted), GENDER, DISTRICT, STATE, RELATION, DOCTOR, HOSPITAL, CLINICAL,
    FREE_TEXT (scrubbed as text), OTHER_ID and OTHER are not PII slots.
    """
    return t in _PII


# ---------------------------------------------------------------- label normalising
def _squash(t: str) -> str:
    """Collapse transliteration vowel doubling so Devanagari and Hinglish spellings meet."""
    t = t.replace("aa", "a").replace("ee", "i").replace("ii", "i").replace("oo", "u").replace("uu", "u")
    return t


_CAMEL = re.compile(r"(?<=[a-z])(?=[A-Z])|(?<=[A-Z])(?=[A-Z][a-z])")
_NON_WORD = re.compile(r"[^a-z0-9]+")


@lru_cache(maxsize=4096)
def _tokens(label: str) -> Tuple[str, ...]:
    s = unicodedata.normalize("NFKC", str(label or ""))
    s = fold(to_ascii_digits(s))
    if is_deva(s):
        s = deva_to_latin(s)
    s = _CAMEL.sub(" ", s)
    s = unicodedata.normalize("NFKD", s)
    s = "".join(c for c in s if not unicodedata.combining(c))
    s = s.lower()
    s = re.sub(r"(?<![a-z])([sdwch])\s*/\s*o(?![a-z])", r" \1o ", s)  # s/o, w/o ... -> so, wo
    s = s.replace("#", " no ")
    raw = [t for t in _NON_WORD.split(s) if t]
    merged: List[str] = []
    i = 0
    while i < len(raw):                      # "d o b" -> "dob", "h no" stays
        j = i
        while j < len(raw) and len(raw[j]) == 1 and raw[j].isalpha():
            j += 1
        if j - i >= 2:
            merged.append("".join(raw[i:j]))
            i = j
        else:
            merged.append(raw[i])
            i += 1
    out: List[str] = []
    for t in merged:
        out.extend(_segment(_squash(t)))
    return tuple(out)


# ---------------------------------------------------------------- stems
# Each stem is compared after _squash. Stems of length >= 5 tolerate small typos.
_S = {
    "name": ("naav", "nav", "peyar", "per", "naw", "nam", "name", "naam", "nam", "fullname", "mareez", "mariz", "marij", "rogi", "beneficiary",
             "labharthi", "nme", "naem", "nmae"),
    "patient": ("rogi", "mariz", "mareez", "ptnt", "pts", "patnt", "patient", "pt", "pat", "pnt", "patiant"),
    "first": ("fn", "pratham", "pehla", "fst", "frst", "first", "fname", "given", "forename", "firstname"),
    "last": ("sirname", "surnam", "kulnam", "kulnaam", "ln", "lst", "last", "lname", "surname", "family", "lastname", "upnam", "upnaam"),
    "local": ("local", "hindi", "devanagari", "regional", "vernacular"),
    "relative": ("attender", "informer", "rishtedar", "parijan", "sambandhi", "fh", "fhname", "gardian", "pitashri", "patidev", "nextofkin", "husbnd", "fathr", "hus", "father", "husband", "guardian", "relative", "attendant", "kin", "pita", "pati",
                 "mata", "mother", "spouse", "wife", "parent", "nok", "so", "do", "wo", "co", "ho",
                 "caretaker", "informant", "escort", "bystander", "pitaji", "abhibhavak", "vali", "wali",
                 "guardain", "gaurdian", "son", "daughter", "putra", "putri", "patni", "beta", "beti"),
    "relation": ("relation", "relationship", "rishta", "rishtaa", "sambandh", "rel"),
    "doctor": ("dctr", "drname", "doctor", "dr", "doc", "consultant", "physician", "surgeon", "practitioner", "doktar",
               "chikitsak", "referred", "referring", "reviewed", "treating", "clinician", "consultan",
               "examined"),
    "uhid": ("hosp", "hospno", "mrd", "mrdno", "uhidno", "crn", "hn", "hin", "ptid", "patientid", "regd", "regno", "regdno", "registrationno", "hospid", "medrec", "uhid", "mrn", "mr", "crno", "cr", "regn", "reg", "registration", "panjikran", "panjikaran",
             "pid", "uid_hosp"),
    "idhost": ("hosp", "hospital", "card", "file", "case", "folder", "chart", "record", "enrol", "enroll",
               "enrolment", "enrollment", "member", "beneficiary", "registration", "regd", "mrd", "patient", "pt",
               "rogi", "marij", "mariz", "panjikaran", "panjikrit", "nondani", "pravesh_no"),
    "enc": ("ipd", "ip", "adm", "admission", "admit", "encounter", "inpatient", "aipidi", "bharti",
            "ipno", "ipdno", "opd", "opdno"),
    "other_id": ("bill", "invoice", "receipt", "sample", "specimen", "trip", "ticket", "order", "utr", "bank",
                 "machine", "vehicle", "call", "scan", "template", "dlt", "preauth", "gate", "pass",
                 "accession", "barcode", "visit", "voucher", "token", "txn", "transaction", "claim",
                 "request", "booking", "package", "lot", "batch", "serial", "sl", "sno",
                 "row", "index", "page", "version", "room", "opd", "odo", "odometer", "expiry", "exp",
                 "gatepass", "preauth", "auth", "approval", "authorisation", "authorization", "scn",
                 "reagent", "kit", "consignment", "dispatch",
                 # blood-bank / lab / stores objects: a bag, issue or slide number is not the patient's
                 "bag", "issue", "segment", "crossmatch", "component", "cartridge", "slide",
                 "requisition", "indent", "challan"),
    "idword": ("id", "no", "num", "number", "nbr", "ref", "code", "identifier", "san", "sankhya",
               "kramank", "kod", "key"),
    "aadhaar": ("aadhaar", "aadhar", "adhar", "adhaar", "aadhr", "uidai", "uid", "aadhaarno", "aadharno",
                "adhar"),
    "abha": ("abha", "abhaid", "healthid", "ndhm", "abdm", "pmjayid_abha"),
    "health": ("health",),
    "pan": ("pan", "pancard", "panno"),
    "insurance": ("pmjay", "pmjy", "ayushman", "policy", "insurance", "insurer", "tpa", "bima", "cghs",
                  "esic", "echs", "mediclaim", "beema"),
    "email": ("email", "mail", "emel", "imel", "emailid", "gmail"),
    "phone": ("sampark", "samprk", "sampark_no", "durbhash", "durabhash", "dural", "mobno", "mb", "phno", "cont", "cntct", "contct", "whtsapp", "mobileno", "fon", "cel", "mobno", "mob", "mobile", "mobil", "mobail", "phone", "ph", "phn", "tel", "telephone", "contact",
              "callback", "whatsapp", "cell", "fone", "phon", "fon", "mno", "landline", "cellphone"),
    "address": ("niwas", "nivas", "niwasi", "nivasi", "patta", "vilasam", "thikana", "thikaana", "residance", "addrs", "adrs", "address", "addr", "adress", "addres", "pata", "street", "residence", "resi",
                "residential", "adres", "pta"),
    "line": ("line", "line1", "line2"),
    "house": ("house", "hno", "flat", "makan", "ghar", "plot", "door", "building", "apartment"),
    "locality": ("mohalla", "muhalla", "mohala", "locality", "colony", "landmark", "area", "basti",
                 "sector", "ward_no", "galli", "gali", "lane", "para", "leikai", "tola", "veng", "patti",
                 "pada", "chawl", "wada", "khangpa"),
    "govid": ("voter", "epic", "ration", "rashan", "licence", "license", "dl", "passport", "vid",
              "kyc", "idproof"),
    "village": ("mauza", "mauja", "mouza", "mouja", "place", "gaun", "panchayat", "grampanchayat", "ooru", "graam", "gaam", "gamv", "gav", "wadi", "dhani", "majra", "thana", "postoffice", "dakghar", "gram", "village", "vill", "vil", "gaon", "gav", "ganv", "gaanv", "gram", "city", "town",
                "kasba", "qasba", "shahar", "nagar", "gramm"),
    "tehsil": ("tahasil", "tehesil", "taluq", "thaluk", "pargana", "upazila", "upzila", "mandalam", "tahsel", "tehsil", "tahsil", "tehseel", "tahseel", "taluk", "taluka", "block", "mandal",
               "subdistrict", "tehsel"),
    "district": ("janpad", "janapad", "jilha", "zillah", "jela", "mavattam", "zilah", "jilah", "district", "distt", "dist", "jila", "zila", "zilla", "jilla", "distric"),
    "state": ("state", "rajy", "rajya", "pradesh", "province"),
    "pin": ("pin", "pincode", "zip", "zipcode", "postal", "postcode", "pinkod"),
    "dob": ("jnm", "janmtithi", "janmdin", "janamdin", "birthdt", "pirantha", "jonmo", "janmatarikh", "dateofbirth", "brth", "dob", "birth", "birthdate", "janm", "janam", "born", "bday", "birthday", "dateofbirth"),
    "age": ("umer", "umir", "vayas", "vayasu", "vayah", "boyos", "boyosh", "varsh", "varsha", "age", "umar", "umr", "umra", "ayu", "aayu", "yrs", "years", "vay", "agee"),
    "gender": ("linga", "linag", "lingo", "jender", "jendar", "gndr", "lingbhed", "paal", "gendre", "sx", "sex", "gender", "ling", "gendr", "jinsi", "mf", "gendar"),
    "date": ("dd", "mm", "yyyy", "yy", "ddmmyyyy", "mmddyyyy", "yyyymmdd", "ddmmyy", "tareekh", "dinaank", "tarikh", "date", "dt", "dated", "tithi", "tarikh", "tarik", "dinank", "datetime", "timestamp",
             "dte"),
    "dateverb": ("enrolled", "joined", "booked", "seen", "registered", "collected", "reported", "admitted", "discharged", "generated",
                 "exported", "created", "updated", "visited", "received", "issued", "printed",
                 "discharge", "on", "at", "when"),
    "hospital": ("hospital", "facility", "clinic", "lab", "laboratory", "centre", "center",
                 "institution", "organization", "organisation", "org", "aspatal", "chikitsalay",
                 "nursing_home", "dispensary", "phc", "chc", "provider"),
    "free": ("note", "notes", "remark", "remarks", "comment", "comments", "observation",
             "observations", "narrative", "tippani", "tipni", "summary", "description", "freetext",
             "message", "msg", "text", "path", "filename", "file", "source", "body"),
    "clinical": ("diagnosis", "diagnoses", "dx", "icd", "complaint", "complaints", "history", "hx",
                 "rx", "drug", "medicine", "medication", "dawa", "dava", "strength", "dose", "dosage",
                 "frequency", "freq", "duration", "route", "form", "category", "schedule", "test",
                 "investigation", "result", "results", "value", "unit", "units", "range", "reference",
                 "loinc", "vitals", "vital", "bp", "pulse", "spo2", "temp", "temperature", "weight",
                 "height", "bmi", "procedure", "package", "surgery", "operation", "ward", "bed", "beds",
                 "department", "dept", "speciality", "specialty", "status", "amount", "inr", "cost",
                 "charges", "charge", "fee", "panel", "panels", "nidan", "shikayat", "jaanch", "janch",
                 "parinam", "vibhag", "vard", "display", "occupied", "cases", "rate", "rr", "hr",
                 "symptom", "symptoms", "treatment", "advice", "findings", "impression", "condition",
                 "allergy", "allergies", "qty", "quantity", "price", "total", "paid", "balance",
                 "dosha", "outcome", "triage", "severity", "specimen_type", "method", "flag", "score",
                 "scores", "scale", "access", "rent", "estimate", "mrp", "tariff", "deposit", "discount",
                 "copay", "km"),
}

_VOCAB = frozenset(_squash(w) for ws in _S.values() for w in ws) | frozenset({"of", "ka", "ki", "ke", "s"})


@lru_cache(maxsize=4096)
def _segment(t: str) -> Tuple[str, ...]:
    """Split glued words ('patientname', 'dateofbirth', 'aadharno') into known vocabulary."""
    if len(t) < 5 or t in _VOCAB or any(c.isdigit() for c in t):
        return (t,)
    n = len(t)
    best: List[Optional[Tuple[str, ...]]] = [None] * (n + 1)
    best[0] = ()
    for i in range(1, n + 1):
        for j in range(max(0, i - 14), i):
            if best[j] is not None and t[j:i] in _VOCAB and (i - j >= 2 or t[j:i] == "s"):
                cand = best[j] + (t[j:i],)
                if best[i] is None or len(cand) < len(best[i]):
                    best[i] = cand
    return best[n] if best[n] is not None and len(best[n]) > 1 else (t,)


try:   # optional C++ backend: same capped OSA distance (stdlib fallback below)
    from rapidfuzz.distance import OSA as _RF_OSA
except Exception:  # noqa: BLE001
    _RF_OSA = None


def _osa(a: str, b: str, cap: int) -> int:
    """Optimal string alignment distance (transposition counts 1), capped."""
    if _RF_OSA is not None:
        return _RF_OSA.distance(a, b, score_cutoff=cap)
    if abs(len(a) - len(b)) > cap:
        return cap + 1
    prev2: List[int] = []
    prev = list(range(len(b) + 1))
    for i in range(1, len(a) + 1):
        cur = [i] + [0] * len(b)
        for j in range(1, len(b) + 1):
            cost = 0 if a[i - 1] == b[j - 1] else 1
            cur[j] = min(prev[j] + 1, cur[j - 1] + 1, prev[j - 1] + cost)
            if i > 1 and j > 1 and a[i - 1] == b[j - 2] and a[i - 2] == b[j - 1]:
                cur[j] = min(cur[j], prev2[j - 2] + 1)
        prev2, prev = prev, cur
    return prev[len(b)]


_SQ = {k: tuple(sorted(set(_squash(w) for w in v))) for k, v in _S.items()}
# Stems that must match exactly (too short or too confusable for fuzzy matching).
_EXACT_GROUPS = frozenset({"dateverb", "relation"})
_EXACT_ONLY = frozenset({"fullname", "firstname", "lastname", "forename", "patientid", "registrationno", "hospid", "uhidno", "regdno", "mrdno", "hospno", "nextofkin", "drname", "fhname", "filename", "freetext", "card", "file", "case", "chart", "record", "member",
                         "place", "jela", "paal", "varsha", "cont", "seen", "joined", "booked", "batch", "serial",
                         "index", "version", "pati", "pita", "mata", "pata", "pin", "pan", "state", "on", "at", "line",
                         "form", "test", "rate", "inpatient", "apartment", "temp", "case", "note", "text", "file", "fee", "flag",
                         "exp", "odo", "auth", "kit", "rent", "km", "scale", "access", "score"})


@lru_cache(maxsize=65536)
def _tok_is(tok: str, group: str) -> bool:
    if _tok_is1(tok, group):
        return True
    if len(tok) > 3 and tok.endswith("s"):
        return _tok_is1(tok[:-1], group)
    return False


def _tok_is1(tok: str, group: str) -> bool:
    exact = group in _EXACT_GROUPS
    for st in _SQ[group]:
        if tok == st:
            return True
        if exact or st in _EXACT_ONLY or len(st) < 5 or len(tok) < 5 or tok[0] != st[0]:
            continue
        cap = 2 if len(st) >= 8 else 1
        if _osa(tok, st, cap) <= cap:
            return True
    return False


def _has(toks: Sequence[str], group: str) -> bool:
    return any(_tok_is(t, group) for t in toks if not t.isdigit())


# ---------------------------------------------------------------- label vote
_BY_DOCTOR = frozenset({"reviewed", "referred", "examined", "treated", "attended", "signed", "verified",
                        "prescribed", "consulted", "operated", "dictated", "diagnosed", "admitted"})
_BY_RELATIVE = frozenset({"accompanied", "brought", "escorted"})
_BY_PRIVATE = frozenset({"raised", "requested", "submitted", "called", "complained", "booked", "filed",
                         "lodged", "reported", "logged", "registered", "enquired", "informed", "made", "sent",
                         "initiated", "opened", "created_for", "paid", "claimed", "accompanied_by_patient"})

_MEMO_LABEL_TYPE = {}  # type: Dict[Any, Any]
_VISIT_WORDS = frozenset({"enc", "encounter", "episode", "epi", "visit", "encid", "visitid", "episodeid"})
_ADMIT_WORDS = frozenset({"ipd", "ip", "adm", "admn", "admission", "admit", "inpatient", "bharti", "ipno", "ipdno"})


def _label_type(toks: Tuple[str, ...]) -> str:
    key = tuple(toks)
    hit = _MEMO_LABEL_TYPE.get(key)
    if hit is None:
        if len(_MEMO_LABEL_TYPE) > 200000:
            _MEMO_LABEL_TYPE.clear()
        hit = _MEMO_LABEL_TYPE[key] = _label_type_impl(toks)
    return hit


def _label_type_impl(toks: Tuple[str, ...]) -> str:
    t = _label_type1(toks)
    if t == OTHER and len(toks) > 1 and not any(c.isdigit() for c in "".join(toks)):
        t = _label_type1(("".join(toks),))      # "Whats App" -> "whatsapp"
        if t == OTHER:
            seg = _segment("".join(toks))        # "Pre Auth No" -> "preauth", "no"
            if seg != toks and len(seg) > 1:
                t = _label_type1(seg)
    return t


def _label_type1(toks: Tuple[str, ...]) -> str:
    if not toks:
        return OTHER
    h = lambda g: _has(toks, g)  # noqa: E731
    is_id = h("idword")

    if "by" in toks[1:]:
        if h("doctor") or any(t in _BY_DOCTOR for t in toks):
            return DOCTOR
        if any(t in _BY_RELATIVE for t in toks):
            return RELATIVE
        if any(t in _BY_PRIVATE for t in toks):
            return NAME
        return FREE_TEXT
    if is_id and any(t in ("lab", "labs", "laboratory", "path", "pathology", "radiology") for t in toks) and not (
            h("uhid") or h("patient") or h("idhost")):
        return OTHER_ID        # "Lab Ref", "Lab No": the laboratory's own reference, not the patient's id
    if is_id and any(t in _VISIT_WORDS for t in toks) and not any(t in _ADMIT_WORDS for t in toks) and not (
            h("uhid") or h("idhost") or h("name")):
        return OTHER_ID
    if is_id and h("idhost") and not (h("other_id") or h("name") or h("phone") or h("aadhaar") or h("abha")
                                      or h("pan") or h("insurance") or h("email") or h("date") or h("dob")):
        if h("enc"):
            return ENC_ID
        return PATIENT_ID      # "Hosp. No", "Card No", "File No", "Case ID", "Enrolment No", "MRD No"
    if h("free") and not (h("name") or h("phone") or h("address")):
        return FREE_TEXT
    if h("relation") and not h("name"):
        return RELATION
    # ABHA before address ("ABHA address") and before email.
    if h("abha") or (h("health") and is_id):
        if h("address") or "phr" in toks or h("email"):
            return ABHA_ADDR
        return ABHA
    if h("aadhaar"):
        return AADHAAR
    if h("pan") and not h("pin"):
        return PAN
    if h("govid") and not (h("name") or h("date") or h("dob")):
        return PAN             # voter id (EPIC), ration card, driving licence, passport, VID: a government id
    if h("insurance"):
        return INSURANCE
    if h("email"):
        return EMAIL
    # Dates (before ids: "Reg Date", "admission_date", "visit_date").
    if h("dob"):
        return DOB
    if h("age") and h("gender"):
        return AGE_SEX
    datey = h("date") or (h("dateverb") and not is_id and not h("name") and not h("phone"))
    if datey and not (h("doctor") and not h("date")):
        if h("relative") and h("name"):
            return RELATIVE
        if not (is_id and not h("date")):
            return DATE
    if h("doctor") and not h("patient"):
        return DOCTOR
    if h("relative") and not (h("phone") and not h("name")):
        return RELATIVE
    if h("phone"):
        if h("name") and not is_id:      # "contact person name", "emergency contact name"
            return RELATIVE
        return PHONE
    if h("pin"):
        return PIN
    # Identifiers. An encounter / visit / episode id is the visit's own reference, not the patient's.
    if any(t in _VISIT_WORDS for t in toks) and not any(t in _ADMIT_WORDS for t in toks) and not h("name"):
        return OTHER_ID
    if h("enc") and not h("name"):
        return ENC_ID
    if h("other_id") and (is_id or len(toks) == 1) and not h("name"):
        return OTHER_ID
    if h("uhid") or (h("patient") and is_id):
        return PATIENT_ID
    if h("hospital") and is_id:
        return PATIENT_ID   # "hospital_uhid", "hospital no"
    if h("age"):
        return AGE
    if h("gender"):
        return GENDER
    if h("house"):
        return HOUSE
    if h("village"):
        return VILLAGE
    if h("locality"):
        return LOCALITY
    if h("tehsil"):
        return TEHSIL
    if h("district"):
        return DISTRICT
    if h("state"):
        return STATE
    if h("address") or (h("line") and len(toks) > 1 and any(_tok_is(t, "address") for t in toks)):
        return ADDRESS
    if h("hospital"):
        return HOSPITAL
    if h("local") and h("name"):
        return LOCAL_NAME
    if h("first") and (h("name") or len(toks) == 1 and toks[0] != "first"):
        return FIRST_NAME
    if h("last") and (h("name") or len(toks) == 1 and toks[0] not in ("last", "family")):
        return LAST_NAME
    if h("clinical"):
        if any(t in ("code", "id", "no", "number", "num") for t in toks) and not any(
                t in ("diagnosis", "dx", "icd", "loinc", "nidan") for t in toks):
            return OTHER_ID     # package_code, test code, drug id: kept as-is
        return CLINICAL
    if h("name") or h("patient"):
        return NAME
    if is_id and len(toks) == 1:
        return OTHER_ID
    return OTHER


def classify_label(label: str) -> str:
    """Type of a slot from its label alone. OTHER when unsure."""
    return _label_type(_tokens(str(label or "")))


# ---------------------------------------------------------------- value vote
_RE_EMAIL = re.compile(r"^[A-Za-z0-9._%+\-]+@[A-Za-z0-9\-]+(\.[A-Za-z0-9\-]+)+$")
_RE_ABHA_ADDR = re.compile(r"^[A-Za-z0-9._\-]{3,}@[A-Za-z]{2,10}$")
_RE_PAN = re.compile(r"^[A-Za-z]{5}[0-9]{4}[A-Za-z]$")
_RE_AADHAAR_MASK = re.compile(r"^(?:[xX*]{4}[ \-]?){2}[0-9]{4}$")
_RE_PHONE_CHARS = re.compile(r"^[+0-9 ()\-.]+$")
_RE_PIN = re.compile(r"^[1-9][0-9]{5}$")
_RE_DOCTOR = re.compile(r"^(?:dr\b\.?|डॉ|डा\.)", re.IGNORECASE)
_RE_AGE = re.compile(r"^[0-9]{1,3}\s*(?:y|yr|yrs|years?|yo|वर्ष|साल|saal|sal|baras|m|mo|months?|d|days?)\.?$",
                     re.IGNORECASE)
_RE_AGE_SEX = re.compile(r"^[0-9]{1,3}\s*(?:y|yr|yrs|years?)?\.?\s*[/,\- ]\s*(?:m|f|t|o|male|female|पु|म|स्त्री|महिला|पुरुष)\.?$",
                         re.IGNORECASE)
_RE_SEX_AGE = re.compile(r"^(?:m|f|male|female)\s*[/,\- ]\s*[0-9]{1,3}\s*(?:y|yr|yrs|years?)?$", re.IGNORECASE)
_RE_RELATION = re.compile(r"^(?:[sdwch]\s*/\s*o|son of|wife of|daughter of|husband of|father|mother|"
                          r"husband|wife|son|daughter|पुत्र|पत्नी|पुत्री|पति|पिता|माता)\.?$", re.IGNORECASE)
_GENDER_WORDS = frozenset({"m", "f", "o", "t", "male", "female", "other", "trans", "transgender", "man",
                           "woman", "पुरुष", "महिला", "स्त्री", "पु", "म", "mahila", "purush", "stri",
                           "ladka", "ladki", "boy", "girl", "unknown", "u"})
_NAME_TOKEN = re.compile(r"^(?:[A-Za-z][A-Za-z'.\-]*|[ऀ-ॿ]+\.?)$")


CODE = "code"          # internal value shape: an identifier-like code (never returned as a slot type)
_RE_CODE_CHARS = re.compile(r"^[A-Za-z0-9][A-Za-z0-9#/.\-_: ()]*[A-Za-z0-9)]$")
_RE_NOT_CODE = re.compile(r"^(?:\d{4}-?W\d{1,2}|v?\d+(?:\.\d+){1,3}|\d+(?:\.\d+)?\s*[-/]\s*\d+(?:\.\d+)?)$", re.I)
_RE_ENC_VALUE = re.compile(r"^\W*(?:ipd?|adm|admn|enc|epi?|in|ip[a-z]{0,2})[\W_]*[0-9]", re.I)


def _is_code(s: str) -> bool:
    """An identifier-looking code: >= 5 digits, few letters, no spaces inside words, not a
    date / version / range / BP. Phones, Aadhaar, PINs are classified before this."""
    t = to_ascii_digits(s.strip())
    if len(t) > 28 or len(t) < 5 or not _RE_CODE_CHARS.match(t) or _RE_NOT_CODE.match(t):
        return False
    d = sum(c.isdigit() for c in t)
    letters = sum(c.isalpha() for c in t)
    if d < 5 or letters > 8 or " " in t.strip() and not re.match(r"^[A-Za-z]{1,6}[ #.:\-]+[0-9]", t):
        return False
    if t.isdigit():
        return 5 <= len(t) <= 14
    try:
        if parse_one(t) is not None:
            return False
    except Exception:  # noqa: BLE001
        return False
    return True


def _digits(s: str) -> str:
    return "".join(c for c in to_ascii_digits(s) if c.isdigit())


_MEMO_VALUE_SHAPE = {}  # type: Dict[Any, Any]


def _value_shape(v: str) -> str:
    key = v
    hit = _MEMO_VALUE_SHAPE.get(key)
    if hit is None:
        if len(_MEMO_VALUE_SHAPE) > 200000:
            _MEMO_VALUE_SHAPE.clear()
        hit = _MEMO_VALUE_SHAPE[key] = _value_shape_impl(v)
    return hit


_INST_SUFFIX = (r"Hospitals?|Hosp\.?|Nursing\s+Home|Clinics?|Polyclinic|Medical\s+College|Institute|Memorial|Trust|"
                r"Mission|Centre|Center|Diagnostics|Pathology|Labs?|Laborator(?:y|ies)|TPA|Insurance|Assurance|"
                r"Ward|Wing|Block|Unit|OPD|ICU|Dispensary|Sanatorium|Foundation|Society|Health\s+Services|"
                r"अस्पताल|चिकित्सालय|हॉस्पिटल|क्लिनिक|नर्सिंग\s+होम|मेडिकल\s+कॉलेज|ट्रस्ट|संस्थान|वार्ड|औषधालय")
_INST_WORD = r"(?:[A-Z][A-Za-z.'&\-]*|[ऀ-ॿ]+|of|and|&|the|for|de|St\.?)"
# A capitalised (or Devanagari) run ending in an institution word, optionally followed by a short
# department name ("... Block Microbiology"): an institution, even when named after a person.
RE_INSTITUTION = re.compile(r"(?<![A-Za-z0-9ऀ-ॿ])(?:[A-Z][A-Za-z.'&\-]*|[ऀ-ॿ]+)(?:\s+%s){0,7}?\s+(?:%s)"
                            r"(?:\s+[A-Z][a-z]+){0,2}(?![A-Za-z0-9ऀ-ॿ])" % (_INST_WORD, _INST_SUFFIX))
# Unit-like suffixes that also name places ("<name> Block" is a tehsil, "Ward 5" a locality).
_PLACE_SUFFIX = re.compile(r"(?:^|\s)(?:Ward|Wing|Block|Unit|वार्ड)(?:\s+[A-Z][a-z]+){0,2}$")


def is_institution(v: Any) -> bool:
    """A whole value that names a hospital, clinic, lab, insurer, TPA or a ward / block of one."""
    if not isinstance(v, str):
        return False
    s = v.strip()
    if not s or len(s) > 90 or any(c.isdigit() for c in to_ascii_digits(s)) or "," in s or "@" in s:
        return False
    if not RE_INSTITUTION.fullmatch(s):
        return False
    pm = _PLACE_SUFFIX.search(s)
    if pm and len(s[:pm.start()].split()) < 2:
        return False             # "<village> Block" is a tehsil, not an institution
    return True


def is_place_unit(v: Any) -> bool:
    return isinstance(v, str) and bool(_PLACE_SUFFIX.search(v.strip()))


_MED_TAIL = frozenset({"scale", "score", "syndrome", "disease", "sign", "test", "repair", "procedure",
                       "operation", "criteria", "index", "classification", "reflex", "phenomenon", "manoeuvre",
                       "maneuver", "triad", "fracture", "palsy", "tumour", "tumor", "ulcer", "abdomen", "law",
                       "staging", "grading", "regimen", "protocol", "point", "tenderness"})


def _value_shape_impl(v: str) -> str:
    s = v.strip()
    if not s:
        return ""
    if is_institution(s):
        return HOSPITAL
    low = s.casefold()
    if _RE_EMAIL.match(s):
        return EMAIL
    if _RE_ABHA_ADDR.match(s):
        return ABHA_ADDR
    if _RE_PAN.match(s):
        return PAN
    if _RE_AADHAAR_MASK.match(s):
        return AADHAAR
    if _RE_PHONE_CHARS.match(to_ascii_digits(s)):
        d = _digits(s)
        groups = [len(g) for g in re.findall(r"[0-9]+", to_ascii_digits(s))]
        if len(d) == 12 and d.startswith("91") and d[2] in "6789" and groups != [4, 4, 4]:
            return PHONE      # "(+91) 98765 43210", "91-98765-43210", "+91.98765.43210"
        if len(d) == 12 and d[0] in "23456789" and groups in ([12], [4, 4, 4]) and not s.lstrip().startswith(("+", "(")):
            return AADHAAR    # "3972 0583 9628", "3972.0583.9628", "397205839628"
        if len(d) == 12 and d[0] in "23456789" and not s.lstrip().startswith("+") and not d.startswith("91"):
            return AADHAAR
        if len(d) == 12 and d.startswith("91") and d[2] in "6789" and (" " not in s.strip() or s.startswith("+")):
            return PHONE
        if len(d) == 12 and d[0] in "23456789":
            return AADHAAR
        if len(d) == 14 and re.match(r"^[0-9]{2}[ \-]?[0-9]{4}[ \-]?[0-9]{4}[ \-]?[0-9]{4}$", s):
            return ABHA
        nd = d
        if len(nd) == 13 and nd.startswith("091"):
            nd = nd[3:]
        elif len(nd) == 12 and nd.startswith("91"):
            nd = nd[2:]
        elif len(nd) == 11 and nd.startswith("0"):
            nd = nd[1:]
        if len(nd) == 10 and nd[0] in "6789":
            return PHONE
        if _RE_PIN.match(to_ascii_digits(s)):
            return PIN
    if _RE_DOCTOR.match(s):
        return DOCTOR
    if _is_code(s):
        return CODE
    if low in _GENDER_WORDS:
        return GENDER
    if _RE_AGE_SEX.match(s) or _RE_SEX_AGE.match(s):
        return AGE_SEX
    if _RE_AGE.match(s):
        return AGE
    if _RE_RELATION.match(s):
        return RELATION
    if any(c.isdigit() for c in to_ascii_digits(s)):
        try:
            if parse_one(s) is not None:
                return DATE
        except Exception:  # noqa: BLE001 - shape vote must never raise
            return ""
        return ""
    toks = s.split()
    if 2 <= len(toks) <= 4 and len(s) <= 48 and all(_NAME_TOKEN.match(t) for t in toks):
        words = [t.strip(".'-").casefold() for t in toks]
        cased = all(t[0].isupper() or is_deva(t) for t in toks) or s.islower() and len(toks) <= 3
        if cased and not any(w in CLINICAL_WORDS for w in words) and sum(1 for w in words if len(w) >= 2) >= 2 \
                and words[-1] not in _MED_TAIL:
            return NAME
    return ""


def _shares(values: Sequence[Any]) -> Tuple[int, dict]:
    counts: dict = {}
    n = 0
    for v in values:
        if v is None or isinstance(v, (dict, list, bool)):
            continue
        s = str(v).strip()
        if not s:
            continue
        n += 1
        t = _value_shape(s)
        if t:
            counts[t] = counts.get(t, 0) + 1
    return n, counts


_VALUE_ORDER = (EMAIL, ABHA_ADDR, PAN, AADHAAR, ABHA, PHONE, PIN, DATE, AGE_SEX, AGE, GENDER,
                RELATION, DOCTOR, HOSPITAL, NAME)


def _code_vote(values: Sequence[Any], threshold: float = 0.8) -> str:
    """PATIENT_ID / ENC_ID when most values are identifier-like codes; pure digit codes must also
    share one length (amounts and counts do not)."""
    vals = [str(v).strip() for v in values if v is not None and not isinstance(v, (dict, list, bool, float))
            and str(v).strip()]
    if len(vals) < 2:
        return ""
    codes = [v for v in vals if _value_shape(v) == CODE]
    if len(codes) < threshold * len(vals):
        return ""
    pure = [v for v in codes if to_ascii_digits(v).isdigit()]
    if pure:
        lens: dict = {}
        for v in pure:
            lens[len(v)] = lens.get(len(v), 0) + 1
        if max(lens.values()) < 0.9 * len(pure) or len(pure) > 0.5 * len(codes) and min(len(v) for v in pure) < 6:
            return ""
    if sum(1 for v in codes if _RE_ENC_VALUE.match(v)) >= 0.6 * len(codes):
        return ENC_ID
    return PATIENT_ID


def classify_values(values: Sequence[Any], threshold: float = 0.6) -> str:
    """Shape vote over non-empty values. OTHER when no shape reaches `threshold`."""
    n, counts = _shares(values)
    if n == 0:
        return OTHER
    best = OTHER
    best_n = 0
    for t in _VALUE_ORDER:
        c = counts.get(t, 0)
        if t == AGE:
            c += counts.get(AGE_SEX, 0) * 0  # kept separate on purpose
        if c > best_n:
            best, best_n = t, c
    return best if best_n >= threshold * n else OTHER


# ---------------------------------------------------------------- combine
_STRONG = frozenset({PHONE, AADHAAR, ABHA, ABHA_ADDR, PAN, EMAIL, PIN})
_PROTECTED = frozenset({CLINICAL, DOCTOR, HOSPITAL, FREE_TEXT})
_IDS = frozenset({PATIENT_ID, ENC_ID, OTHER_ID, INSURANCE})


def _combine(lt: str, vt: str) -> str:
    if vt in _STRONG:
        if vt == PIN and (lt in _PROTECTED or lt in _IDS or lt in (DATE, DOB, AGE, AGE_SEX, OTHER)):
            return lt if lt != OTHER else PIN
        if lt == FREE_TEXT or lt == HOSPITAL:
            return lt
        return vt
    if vt == DATE:
        if lt in (DOB, DATE, CLINICAL, FREE_TEXT, AGE):
            return lt
        return DATE
    if vt == HOSPITAL:
        if lt in (NAME, FIRST_NAME, LAST_NAME, LOCAL_NAME, OTHER, PATIENT_ID, INSURANCE, CLINICAL, RELATIVE,
                  FREE_TEXT, OTHER_ID, DOCTOR):
            return HOSPITAL
        return lt
    if lt == OTHER:
        return vt
    if lt in (NAME, FIRST_NAME, LAST_NAME) and vt == DOCTOR:
        return DOCTOR
    if lt in (AGE, GENDER) and vt == AGE_SEX:
        return AGE_SEX
    return lt


_NOT_PATIENT_CODE_LABEL = frozenset({"bill", "invoice", "receipt", "sample", "specimen", "visit", "package",
                                     "claim", "token", "bed", "order", "trip", "ticket", "voucher", "txn",
                                     "transaction", "accession", "barcode", "batch", "lot", "serial", "loinc",
                                     "icd", "code", "sku", "item", "drug", "test", "bag", "issue", "donation",
                                     "segment", "crossmatch", "component", "cartridge", "slide", "requisition",
                                     "indent", "challan", "kit"})


def code_column_type(label: str, values: Sequence[Any]) -> str:
    """PATIENT_ID / ENC_ID for an unlabelled (OTHER) column whose values look like identifier codes;
    '' otherwise. Labels naming bills, samples, visits, packages, claims, tokens, beds ... never qualify."""
    toks = _tokens(str(label or ""))
    if any(_tok_is(t, "other_id") or t in _NOT_PATIENT_CODE_LABEL for t in toks) or _has(toks, "clinical"):
        return ""
    v = _code_vote(values)
    if v == PATIENT_ID and (_has(toks, "enc") or any(t in ("ipd", "ip", "adm", "admission", "encounter",
                                                            "episode", "inpatient") for t in toks)):
        return ENC_ID
    return v


_RE_REL_VALUE = re.compile(r"^\s*(?:[SDWCH]\s*/\s*O|son\s+of|daughter\s+of|wife\s+of|husband\s+of)\b\.?\s*\S", re.I)
_RE_PLACE_VALUE = re.compile(r"^(?:[A-Z][a-z'.\-]+|[ऀ-ॿ]+)(?:\s+(?:[A-Z][a-z'.\-]+|[ऀ-ॿ]+)){0,2}$")


def _share(values: Sequence[Any], rx: "re.Pattern[str]") -> float:
    vals = [str(v).strip() for v in values if v is not None and str(v).strip()]
    if not vals:
        return 0.0
    return sum(1 for v in vals if rx.match(v)) / float(len(vals))


def refine_unlabelled(labels: Sequence[str], types: List[str], columns: Sequence[Sequence[Any]]) -> List[str]:
    """Columns with no header, typed by value shape and neighbours: "S/o <name>" values are a
    RELATIVE; of two short place-like columns just before a PIN column the first is the VILLAGE."""
    out = list(types)
    blank = lambda i: i < 0 or i >= len(labels) or not str(labels[i] or "").strip()  # noqa: E731
    for i, t in enumerate(out):
        if blank(i) and t in (OTHER, NAME) and i < len(columns) and _share(columns[i], _RE_REL_VALUE) >= 0.6:
            out[i] = RELATIVE
    for j, t in enumerate(out):
        if t != PIN:
            continue
        run = []
        k = j - 1
        while k >= 0 and len(run) < 2 and blank(k) and out[k] in (OTHER, NAME) and k < len(columns) \
                and _share(columns[k], _RE_PLACE_VALUE) >= 0.6:
            run.append(k)
            k -= 1
        if len(run) == 2:
            out[run[1]] = VILLAGE      # the column next to the PIN (the district) is left as it is
    return out


def classify_column(label: str, values: Sequence[Any]) -> str:
    """Type of a column from its label and sample values."""
    lt = classify_label(label)
    if lt == OTHER:
        ct = code_column_type(label, values)
        if ct:
            return ct
    vt = classify_values(values)
    if vt in (PHONE, AADHAAR) and lt in (OTHER_ID, ENC_ID, PATIENT_ID, INSURANCE):
        # a 10 / 12 digit number under a label that names a document, admission or registration number
        # (barcode, bill no, IP no) is that number, not a mobile or an Aadhaar
        toks = _tokens(str(label or ""))
        if lt != OTHER_ID and vt == PHONE or any(t in _NOT_PATIENT_CODE_LABEL for t in toks):
            return lt
    return _combine(lt, vt)


# ---------------------------------------------------------------- JSON paths
_OWNER_RELATIVE = ("relative",)
_ACTOR_PRIVATE = ("raised", "caller", "requester", "reporter", "submitted", "applicant", "complainant",
                  "visitor", "user", "customer", "member", "subject", "person", "patient", "beneficiary")
_NAME_PART_FIRST = ("first", "given", "fname", "forename", "middle")
_NAME_PART_LAST = ("last", "family", "surname", "lname")
_NAME_PART_LOCAL = ("local", "hindi", "devanagari", "regional", "vernacular")


_MEMO_OWNER = {}  # type: Dict[Any, Any]


def _owner(keys: Sequence[str]) -> str:
    key = tuple(str(k) for k in keys)
    hit = _MEMO_OWNER.get(key)
    if hit is None:
        if len(_MEMO_OWNER) > 200000:
            _MEMO_OWNER.clear()
        hit = _MEMO_OWNER[key] = _owner_impl(keys)
    return hit


def _owner_impl(keys: Sequence[str]) -> str:
    """Who a name/ID under these ancestor keys belongs to: RELATIVE, DOCTOR, HOSPITAL, CLINICAL,
    PATIENT or '' (unknown). Nearest ancestor wins."""
    for k in reversed(list(keys)):
        toks = _tokens(str(k))
        if not toks:
            continue
        if _has(toks, "relative") or (_has(toks, "phone") and not _has(toks, "patient")):
            # 'contact' as a container of a name is a private person (relative/caller)
            return RELATIVE if _has(toks, "relative") else "PRIVATE"
        if _has(toks, "doctor") or any(t in ("author", "performer", "reviewer", "prescriber", "staff",
                                             "consultant", "practitioner", "physician") for t in toks):
            return DOCTOR
        if _has(toks, "hospital"):
            return HOSPITAL
        if any(t.startswith(a) for t in toks for a in _ACTOR_PRIVATE) or _has(toks, "patient"):
            return "PRIVATE"
        if _has(toks, "clinical") or any(t in ("medication", "item", "service", "panel", "drug")
                                         for t in toks):
            return CLINICAL
        if _has(toks, "address"):
            return ADDRESS
        if _has(toks, "other_id"):
            return OTHER_ID
        if _has(toks, "enc"):
            return ENC_ID
        if _has(toks, "insurance"):
            return INSURANCE
    return ""


def _is_bare_name(toks: Tuple[str, ...]) -> bool:
    return bool(toks) and all(_tok_is(t, "name") or t in ("full", "display", "s") for t in toks)


def _is_bare_id(toks: Tuple[str, ...]) -> bool:
    return bool(toks) and all(_tok_is(t, "idword") or t in ("value", "s") for t in toks)


def _value_hint(value: Any) -> str:
    if value is None or isinstance(value, (bool, dict, list)):
        return ""
    if isinstance(value, float):
        return ""
    return _value_shape(str(value))


_GENERIC_CLIN_KEYS = frozenset({"category", "categories", "status", "form", "type", "kind", "state", "mode",
                                "flag", "class", "group", "stage"})
_CLIN_ANCESTOR = frozenset({"visit", "visits", "encounter", "encounters", "opd", "ipd", "admission",
                            "admissions", "test", "tests", "lab", "labs", "investigation", "investigations",
                            "observation", "observations", "order", "orders", "prescription", "prescriptions"})


def _clinical_ancestor(parents: Sequence[str]) -> bool:
    for k in parents:
        toks = _tokens(str(k))
        if not toks:
            continue
        if _owner([k]) == CLINICAL or any(t in _CLIN_ANCESTOR for t in toks):
            return True
        lt = _label_type(toks)
        if lt == CLINICAL and not all(t in _GENERIC_CLIN_KEYS for t in toks):
            return True
    return False


_RE_MEASURE = re.compile(r"\d\s*(?:/\s*(?:cumm|cmm|mm3|ul|µl|hpf|lpf|min)|(?:g|mg|ng|pg|µg|mcg|meq|mmol|iu|miu|u)\s*/\s*(?:dl|l|ml|ul)"
                         r"|mm\s*hg|%)(?![a-z])", re.I)


_META_VERB = frozenset({"printed", "exported", "requested", "prepared", "generated", "issued", "sent",
                        "downloaded", "released", "handed", "collected"})
_RE_META_PERSON = re.compile(r"(?:^|\s)[A-Z][a-z]{2,}\s+[A-Z][a-z]{2,}")
_RE_NAMEISH = re.compile(r"^[A-Z][a-z]+(?:\s+(?:[A-Z]\.?|[A-Z][a-z]+)){1,3}$")


_JOB_WORDS = frozenset({"occupation", "profession", "job", "designation", "employment", "vyavsay", "pesha"})
_COMPANION_WORDS = frozenset({"companion", "attendant", "escort", "bystander", "caretaker", "caregiver"})


_KIN_KEY_WORDS = frozenset({"father", "mother", "husband", "wife", "guardian", "son", "daughter", "relative",
                            "relation", "kin", "nok", "spouse", "parent", "pita", "pati", "patni", "mata"})


def json_key_type(path_keys: Sequence[str], value: Any = None) -> str:
    """Type of a JSON leaf from its key path (array indexes skipped) and its value."""
    keys = [str(k) for k in path_keys if not isinstance(k, int)]
    if not keys:
        return _combine(OTHER, _value_hint(value) or OTHER)
    last = keys[-1]
    parents = keys[:-1]
    toks = _tokens(last)
    lt = _label_type(toks)
    vh = _value_hint(value)
    owner = _owner(parents)
    # "attending": "Dr. Ketan Vyas" - a value written as a doctor is a doctor, unless the key names a relative
    if isinstance(value, str) and _RE_DOCTOR.match(value.strip()) and not any(
            t in _KIN_KEY_WORDS for t in toks + tuple(x for p in parents for x in _tokens(p))):
        return DOCTOR

    # A job title is not a name; a companion / attendant / escort is a private person, not a date.
    if any(t in _JOB_WORDS for t in toks):
        return OTHER
    if any(t in _COMPANION_WORDS for t in toks) and isinstance(value, str) and not re.search(r"[0-9]", value):
        return RELATIVE

    # Export metadata naming a person ("printedFor": "Name (phone)"); a login like "clerk07" is not one.
    if isinstance(value, str) and (len(toks) == 2 and toks[0] in _META_VERB and toks[1] in ("for", "by", "to")
                                   or toks in (("operator",), ("printedfor",), ("requestedby",))):
        if _RE_META_PERSON.search(value):
            return NAME

    # Name parts: patients/name/first, guardian/name/given, ...
    if parents and _is_bare_name(_tokens(parents[-1])) and lt in (OTHER, FIRST_NAME, LAST_NAME, LOCAL_NAME,
                                                                      NAME, CLINICAL):
        up = _owner(parents[:-1])
        if up == DOCTOR:
            return DOCTOR
        if up == HOSPITAL:
            return HOSPITAL
        if up == CLINICAL:
            return CLINICAL
        if up == RELATIVE:
            return RELATIVE
        if any(t in _NAME_PART_FIRST for t in toks):
            return FIRST_NAME
        if any(t in _NAME_PART_LAST for t in toks):
            return LAST_NAME
        if any(t in _NAME_PART_LOCAL for t in toks) or (isinstance(value, str) and is_deva(value)):
            return LOCAL_NAME
        return NAME

    # Bare "name" leaf: owner decides.
    if _is_bare_name(toks) or (lt == NAME and len(toks) == 1):
        if owner == RELATIVE:
            return RELATIVE
        if owner == DOCTOR:
            return DOCTOR
        if owner == HOSPITAL:
            return HOSPITAL
        if owner == CLINICAL:
            return CLINICAL
        if vh == DOCTOR:
            return DOCTOR
        if vh == HOSPITAL:
            return HOSPITAL
        if isinstance(value, str) and is_deva(value) and _has(toks, "local"):
            return LOCAL_NAME
        return NAME

    # Bare id/ref/no/code leaf: owner decides, value breaks ties.
    if _is_bare_id(toks) or lt == OTHER_ID and len(toks) == 1 and _has(toks, "idword"):
        if vh in (AADHAAR, PHONE, ABHA, PAN, EMAIL):
            return vh
        if owner == "PRIVATE":
            return PATIENT_ID
        if owner in (CLINICAL, DOCTOR, HOSPITAL):
            return owner
        if owner in (ENC_ID, INSURANCE, OTHER_ID):
            return owner
        if owner == RELATIVE:
            return OTHER_ID
        if any(_has(_tokens(p), "uhid") for p in parents):
            return PATIENT_ID
        return OTHER_ID

    # Address parts: address/line, address/text, address/street1.
    if owner == ADDRESS and lt in (OTHER, CLINICAL, FREE_TEXT) and not isinstance(value, (int, float)):
        return ADDRESS

    # Generic keys ("category", "status", "form", "type") are clinical only under a clinical ancestor:
    # "category": "billing query" or "form": "surgical consent" at the top level are not.
    if lt == CLINICAL and toks and all(t in _GENERIC_CLIN_KEYS for t in toks) and not _clinical_ancestor(parents):
        if vh in _STRONG:
            return vh
        return OTHER

    # Under a clinical container everything that is not strongly shaped stays clinical.
    if owner == CLINICAL and lt in (OTHER, FREE_TEXT, CLINICAL):
        if vh in (PHONE, AADHAAR, EMAIL, PAN):
            return vh
        return CLINICAL

    # Values under a relative container: guardian/mobile stays PHONE (lt), guardian/relation RELATION.
    if owner == RELATIVE and lt == OTHER and vh == NAME:
        return RELATIVE
    # Key ancestry: a name-shaped scalar under a patient object ("pt": {"n": ...}) is the patient's name.
    if owner == "PRIVATE" and lt == OTHER and len(last) <= 3 and (vh == NAME or isinstance(value, str)
                                                                 and _RE_NAMEISH.match(value.strip())):
        return NAME
    # A number with a measurement unit is a result, never an identifier ("TLC 13400 /cumm").
    if lt == OTHER and isinstance(value, str) and _RE_MEASURE.search(value):
        return CLINICAL

    if lt in (OTHER, OTHER_ID, PATIENT_ID) and vh in (AADHAAR, PHONE) and isinstance(value, (int, str)):
        if lt == OTHER or vh == AADHAAR and len(_digits(str(value))) == 12:
            return vh
    if lt == OTHER and isinstance(value, str):
        if vh in (_STRONG | {DOCTOR, NAME, DATE}):
            return vh
        try:
            from .patterns import find_patient_ids
            sp = find_patient_ids(value)
            if len(sp) == 1 and sp[0].start == 0 and sp[0].end == len(value):
                return ENC_ID if _RE_ENC_VALUE.match(value) else PATIENT_ID
        except Exception:  # noqa: BLE001
            pass
        if vh == CODE and owner in ("", "PRIVATE") and not any(
                _tok_is(t, "other_id") or t in _NOT_PATIENT_CODE_LABEL for t in toks) and not _has(toks, "clinical"):
            return ENC_ID if _RE_ENC_VALUE.match(value) or _has(toks, "enc") else PATIENT_ID
        return OTHER
    if lt == OTHER:
        return vh if vh in _STRONG else OTHER
    return _combine(lt, vh if vh in (_STRONG | {DATE, DOCTOR, AGE_SEX, HOSPITAL}) else "")
