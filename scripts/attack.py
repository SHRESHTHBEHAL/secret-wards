#!/usr/bin/env python3
"""Dev-only replica of the organisers' re-identification attacker (docs/ATTACKS.md).

Measures a release (A1-A7) against the practice attacker knowledge and answer key.
NEVER imported by the pipeline: it reads the practice truth to score guesses.

  python3 scripts/attack.py --release OUT --dev TOOLKIT/dev [--raw] [--release2 OUT2]
                            [--raw-json raw.json] [--json out.json] [--verbose]
"""
import argparse
import base64
import collections
import csv
import hashlib
import io
import json
import os
import re
import sys
import unicodedata
from datetime import date, timedelta

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
try:
    from raksha.translit import deva_to_latin, name_key  # transliteration tables (public knowledge)
except Exception:  # pragma: no cover - fallback keeps the tool standalone
    def deva_to_latin(s):
        return s

    def name_key(t):
        t = re.sub("[^a-z]", "", t.casefold())
        t = re.sub(r"(.)\1+", r"\1", t)
        return t[:-1] if len(t) > 1 and t.endswith("a") else t

csv.field_size_limit(10 ** 9)
sys.setrecursionlimit(20000)
DEVA_DIGITS = str.maketrans("०१२३४५६७८९", "0123456789")
ORG_REF = {"A3": 0.277, "A4": 0.167, "A5": 0.401}
NAME_MISS = float(os.environ.get('ATTACK_NAME_MISS', '0'))
WEIGHTS = {"A1": 0.20, "A3": 0.20, "A4": 0.20, "A5": 0.20, "A6": 0.10, "A7": 0.10}
MONTHS = {m: i + 1 for i, m in enumerate(
    ["jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"])}
HOSP_ALIASES = {
    "arogya": "Arogya Seva Sadan", "ass": "Arogya Seva Sadan", "uhid-": "Arogya Seva Sadan",
    "sanjeevani": "Sanjeevani Multispeciality Hospital", "snj": "Sanjeevani Multispeciality Hospital",
    "jeevanjyoti": "Jeevan Jyoti Charitable Hospital", "jjh": "Jeevan Jyoti Charitable Hospital",
    "dhh": "District Hospital Hardoi", "dhhardoi": "District Hospital Hardoi",
}
HOSPITALS = sorted(set(HOSP_ALIASES.values()))


# ----------------------------------------------------------------------------- reading
def read_text(path):
    b = open(path, "rb").read()
    if b[:2] in (b"\xff\xfe", b"\xfe\xff"):
        return b.decode("utf-16", "replace")
    if len(b) > 4 and b[1:2] == b"\x00" and b[3:4] == b"\x00":
        return b.decode("utf-16-le", "replace")
    try:
        return b.decode("utf-8-sig")
    except UnicodeDecodeError:
        return b.decode("latin-1")


def leaves(obj, key="", out=None, skip=None, ptr=""):
    """(key, value) leaf pairs of a JSON value; given/family name parts also joined."""
    if out is None:
        out = []
    if skip and ptr in skip:
        return out
    if isinstance(obj, dict):
        if "given" in obj or "family" in obj:
            g = obj.get("given", "")
            g = " ".join(g) if isinstance(g, list) else str(g or "")
            out.append(("name", (g + " " + str(obj.get("family", "") or "")).strip()))
        for k, v in obj.items():
            leaves(v, str(k), out, skip, ptr + "/" + str(k))
    elif isinstance(obj, list):
        for i, v in enumerate(obj):
            leaves(v, key, out, skip, ptr + "/" + str(i))
    elif obj is not None:
        out.append((key, str(obj)))
    return out


def json_ptr(obj, ptr):
    for part in ptr.strip("/").split("/"):
        if isinstance(obj, list):
            obj = obj[int(part)]
        else:
            obj = obj[part]
    return obj


class FileCache:
    def __init__(self):
        self.c = {}

    def get(self, path, fmt, delim):
        if path in self.c:
            return self.c[path]
        res = {"text": "", "rows": None, "json": None, "header": []}
        try:
            text = read_text(path)
        except OSError:
            self.c[path] = None
            return None
        res["text"] = text
        if fmt in ("csv", "tsv"):
            d = delim or ("\t" if fmt == "tsv" or text.count("\t") > text.count(",") else ",")
            rows = list(csv.reader(io.StringIO(text), delimiter=d))
            res["header"] = rows[0] if rows else []
            res["rows"] = rows[1:]
        elif fmt in ("json", "fhir"):
            try:
                res["json"] = json.loads(text)
            except (ValueError, RecursionError):
                res["json"] = None
        self.c[path] = res
        return res


def unit_pairs(fc, path, finfo, loc, all_locs):
    """(field, value) pairs + free text for one record unit of a (release) file."""
    fmt = finfo.get("format", "text")
    f = fc.get(path, fmt, finfo.get("delimiter"))
    if f is None:
        return None
    if loc == "@filename":
        return [("filename", os.path.basename(path))]
    if fmt in ("csv", "tsv"):
        if loc == "@header":
            return [("header", " | ".join(f["header"]))]
        if loc.startswith("row:"):
            i = int(loc[4:])
            if f["rows"] is None or i >= len(f["rows"]):
                return None
            row = f["rows"][i]
            return [(f["header"][j] if j < len(f["header"]) else "col%d" % j, v) for j, v in enumerate(row)]
        return [("text", f["text"])]
    if fmt in ("json", "fhir"):
        js = f["json"]
        if js is None:
            return [("text", f["text"])] if f["text"] else None
        if loc == "doc":
            return leaves(js)
        if loc == "@file":
            skip = set(l for l in all_locs if l.startswith("/"))
            return leaves(js, skip=skip)
        if loc.startswith("/"):
            try:
                return leaves(json_ptr(js, loc))
            except (KeyError, IndexError, ValueError, TypeError):
                return None
        return leaves(js)
    return [("text", f["text"])]


# ----------------------------------------------------------------------------- knowledge
def load_registry(dev):
    reg = []
    with open(os.path.join(dev, "attacker", "registry.csv"), encoding="utf-8-sig") as fh:
        for r in csv.DictReader(fh):
            r["age"] = int(r["age"]) if r["age"].strip().isdigit() else None
            r["phone"] = re.sub(r"\D", "", r["phone"])[-10:]
            r["email"] = r["email"].strip().casefold()
            toks = [name_key(t) for t in re.findall(r"[A-Za-z]+", r["name"])]
            r["gkey"] = toks[0] if toks else ""
            r["skey"] = toks[-1] if len(toks) > 1 else ""
            r["nkeys"] = toks
            r["rkeys"] = [name_key(t) for t in re.findall(r"[A-Za-z]+", r["relative_name"])]
            reg.append(r)
    return reg


class Gazetteer:
    def __init__(self, reg):
        self.place = {}  # kind -> {key tuple: canonical}
        for kind in ("district", "tehsil", "village"):
            d = {}
            for r in reg:
                v = r[kind].strip()
                if v:
                    d[tuple(name_key(t) for t in re.findall(r"[A-Za-z]+", v))] = v
            self.place[kind] = d
        self.maxlen = max(len(k) for d in self.place.values() for k in d)
        self.name_keys = set()
        for r in reg:
            self.name_keys.update(k for k in r["nkeys"] + r["rkeys"] if k)
        self.pins = set(r["pin"] for r in reg if r["pin"])

    def find_places(self, keys):
        out = {"district": set(), "tehsil": set(), "village": set()}
        n = len(keys)
        for i in range(n):
            for L in range(self.maxlen, 0, -1):
                if i + L > n:
                    continue
                t = tuple(keys[i:i + L])
                for kind, d in self.place.items():
                    if t in d:
                        out[kind].add(d[t])
        return out


# ----------------------------------------------------------------------------- evidence
RE_DATE_ISO = re.compile(r"(?<!\d)(\d{4})-(\d{1,2})-(\d{1,2})(?!\d)")
RE_DATE_DMY = re.compile(r"(?<!\d)(\d{1,2})[/.\-](\d{1,2})[/.\-](\d{4})(?!\d)")
RE_DATE_DMONY = re.compile(r"(?<!\d)(\d{1,2})[\s\-]*([A-Za-z]{3,9})[\s\-,]*(\d{4})(?!\d)")
RE_DATE_MONDY = re.compile(r"\b([A-Za-z]{3,9})\s+(\d{1,2}),?\s+(\d{4})(?!\d)")
RE_DATE_YMD8 = re.compile(r"(?<!\d)(20\d{2}|19\d{2})(\d{2})(\d{2})(?!\d)")
RE_AGE_CTX = re.compile(r"(?:\bage\b|\bumar\b|\baayu\b|\bumr\b|उम्र|आयु|उमर)\s*[:\-=]?\s*(\d{1,3})(?:\s*(?:-|–|to)\s*(\d{1,3}))?(\+)?", re.I)
RE_AGE_FORM = re.compile(r"(?<![\dx/.\-])(\d{1,3})(?:\s*(?:-|–)\s*(\d{1,3}))?(\+)?\s*(?:(?:yrs?|years?|y/o|yo|y)\b\.?\s*(?:old)?\s*(?:/\s*([MFmf])\b)?|/\s*([MFmf])\b|\s*(?:वर्ष|साल|वर्षीय))", re.I)
RE_BRACKET_AGE = re.compile(r"\[(\d{1,3})\s*,\s*(\d{1,3})\)")
RE_PLUS_AGE = re.compile(r"(?<![\d.])(\d{2,3})\+")
RE_HIST = re.compile(r"(?:\bx\s*|since\s*|for\s*)$", re.I)
RE_PHONE = re.compile(r"(?<![\dA-Za-z])(?:\+?91[\s\-]?|0)?([6-9](?:[\s\-]?\d){9})(?!\d)")
RE_MPHONE = re.compile(r"(?<!\d)([6-9]\d)[Xx*•]{6}(\d{2})(?!\d)")
RE_MPHONE2 = re.compile(r"(?<!\d)([6-9]\d{0,4})[Xx*•\s\-]{4,}(\d{2,4})(?!\d)")
RE_AADHAAR_M = re.compile(r"[Xx*]{4}[\s\-]?[Xx*]{4}[\s\-]?(\d{4})(?!\d)")
RE_AADHAAR = re.compile(r"(?<!\d)([2-9]\d{3})[\s\-]?(\d{4})[\s\-]?(\d{4})(?!\d)")
RE_EMAIL = re.compile(r"[\w.+\-]+@[\w\-]+\.[\w.\-]+")
RE_HOUSE = re.compile(r"(?:\bH\.?\s*No\.?|\bHouse(?:\s*No\.?)?|\bMakan\s*(?:No\.?|Number)?|\bGhar\s*(?:No\.?|Sankhya)?|मकान\s*(?:नं\.?|नंबर|संख्या)?|मकान\s*नं)\s*[:#\-]?\s*(\d{1,4})", re.I)
RE_PIN = re.compile(r"(?<![\d])(\d{6})(?!\d)")
RE_PINPFX = re.compile(r"(?<![\d])(\d{3})(?:\*{3}|[Xx]{3}|•{3}|_{3})(?![\dA-Za-z])")
RE_PSN = re.compile(r"PSN-[0-9A-Z]{6,}")
RE_UHID = re.compile(r"\b(?:SNJ/\d{2}/\d{5,}|JJH-\d{6,}|UHID-\d{5,}|DHH[-/][\dA-Z/\-]{4,}|[A-Z]{2,5}[-/]\d{2}[-/]\d{4,})\b")
RE_ICD = re.compile(r"\b([A-TV-Z]\d{2}(?:\.\d{1,2})?)\b")
REL_RE = re.compile(r"(?<![A-Za-z])([SDWC])\s*/\s*[Oo](?![A-Za-z])\s*[:.\-]?\s*")
DR_RE = re.compile(r"\b(?:Dr|Doctor|डॉ|डा)\b\.?\s*$", re.I)
F_WORDS = re.compile(r"\b(female|f|mahila|stri|aurat|behenji|bahenji|smt|shrimati|mrs|ms|kumari|miss|beti|महिला|महिला|स्त्री|श्रीमती|बहनजी|कुमारी)\b", re.I)
M_WORDS = re.compile(r"\b(male|m|purush|sahab|saheb|bhaiya|mr|bhai|पुरुष|साहब|भैया)\b", re.I)
KEY_AGE = re.compile(r"\b(age|umar|umr|aayu|उम्र|आयु)", re.I)
KEY_GENDER = re.compile(r"(gender|\bsex\b|^sex|ling|लिंग)", re.I)
KEY_DOB = re.compile(r"(dob|birth|janm|जन्म)", re.I)
KEY_DIST = re.compile(r"(district|distt|jila|zila|जिला)", re.I)
KEY_TEH = re.compile(r"(tehsil|taluk|तहसील)", re.I)
KEY_VIL = re.compile(r"(village|gaon|gram|mohalla|गांव|गाँव|ग्राम)", re.I)
KEY_PIN = re.compile(r"(pin|postal|zip)", re.I)
KEY_NAME = re.compile(r"(^name$|patient.?name|^naam$|^naam|नाम|^given$|^family$|^patient$)", re.I)
KEY_REL = re.compile(r"(relative|father|husband|guardian|\bpita\b|pita.?pati|(?<![a-z])pati(?![a-z])|पिता|पति|attendant|next.?of.?kin|^relation.?name|kin)", re.I)
KEY_DR = re.compile(r"(doctor|consultant|physician|referred|practitioner|attending)", re.I)
KEY_REF = re.compile(r"(uhid|mrn|patient.?ref|patient.?id|reg.?no|registration.?no|hospital.?uhid|^ref$|patient$|^id$|identifier|subject|reference)", re.I)


def norm(s):
    s = unicodedata.normalize("NFC", s).translate(DEVA_DIGITS)
    return s


def mk_date(y, m, d):
    try:
        return date(int(y), int(m), int(d))
    except (ValueError, TypeError):
        return None


def find_dates(s):
    out = []
    for m in RE_DATE_ISO.finditer(s):
        out.append((m.start(), mk_date(*m.groups())))
    for m in RE_DATE_DMY.finditer(s):
        d, mo, y = m.groups()
        out.append((m.start(), mk_date(y, mo, d) or mk_date(y, d, mo)))
    for m in RE_DATE_DMONY.finditer(s):
        d, mo, y = m.groups()
        if mo[:3].lower() in MONTHS:
            out.append((m.start(), mk_date(y, MONTHS[mo[:3].lower()], d)))
    for m in RE_DATE_MONDY.finditer(s):
        mo, d, y = m.groups()
        if mo[:3].lower() in MONTHS:
            out.append((m.start(), mk_date(y, MONTHS[mo[:3].lower()], d)))
    for m in RE_DATE_YMD8.finditer(s):
        out.append((m.start(), mk_date(*m.groups())))
    return [(p, d) for p, d in out if d and 1900 <= d.year <= 2100]


def age_range(a, b=None, plus=None):
    a = int(a)
    if b:
        b = int(b)
        if b < a or b > 125:
            return None
        return (a, b)
    if plus:
        return (a, 125)
    return (a, a) if a <= 120 else None


def gender_val(v):
    v = v.strip().casefold()
    if v in ("m", "male", "purush", "पुरुष", "पु", "man", "boy", "1"):
        return "M"
    if v in ("f", "female", "mahila", "महिला", "स्त्री", "म", "woman", "girl", "2"):
        return "F"
    return None


class Evidence:
    FIELDS = ("ages", "bands", "birth_years", "genders", "districts", "tehsils", "villages", "pins",
              "pin_prefixes", "names", "relatives", "houses", "phones", "masked_phones", "last4",
              "emails", "conditions", "codes", "hospitals", "dates", "refs")

    def __init__(self):
        for f in self.FIELDS:
            setattr(self, f, set())
        self.intervals = set()
        self.text = ""

    def merge(self, o):
        for f in self.FIELDS:
            getattr(self, f).update(getattr(o, f))
        self.intervals |= o.intervals
        self.text += "\n" + o.text

    def age_ranges(self):
        return self.ages | self.bands


def tokens_with_spans(s):
    out = []
    for m in re.finditer(r"[A-Za-z]+|[ऀ-ॿ]+", s):
        t = m.group(0)
        lat = deva_to_latin(t) if "ऀ" <= t[0] <= "ॿ" else t
        for sub in re.findall("[a-z]+", lat.casefold()):
            out.append((m.start(), m.end(), sub))
    return out


def extract(pairs, gaz, hospital_ctx=None):
    ev = Evidence()
    texts = []
    for k, v in pairs:
        v = norm(v)
        if not v.strip():
            continue
        k0 = str(k)
        texts.append("%s: %s" % (k0, v))
        # key-aware
        if KEY_AGE.search(k0) and not KEY_DOB.search(k0):
            m = re.match(r"\s*(\d{1,3})\s*(?:(?:-|–|to)\s*(\d{1,3}))?\s*(\+)?", v)
            mb = RE_BRACKET_AGE.search(v)
            if mb:
                r = age_range(*mb.groups())
                if r:
                    ev.bands.add((r[0], r[1] - 1))
            elif m:
                r = age_range(m.group(1), m.group(2), m.group(3))
                if r:
                    (ev.ages if r[0] == r[1] else ev.bands).add(r)
        if KEY_GENDER.search(k0):
            g = gender_val(v)
            if g:
                ev.genders.add(g)
        if KEY_DOB.search(k0):
            for _, d in find_dates(v):
                ev.birth_years.add(d.year)
            m = re.fullmatch(r"\s*(19\d{2}|20\d{2})\s*", v)
            if m:
                ev.birth_years.add(int(m.group(1)))
        if KEY_PIN.search(k0) and not re.search("aadhaar|abha", k0, re.I):
            m = re.match(r"\s*(\d{3})(\d{3})?", v)
            if m:
                if m.group(2):
                    ev.pins.add(m.group(1) + m.group(2))
                else:
                    ev.pin_prefixes.add(m.group(1))
        if KEY_NAME.search(k0) and not KEY_DR.search(k0) and not v.strip().startswith(("Dr", "डॉ")):
            ks = [name_key(t) for _, _, t in tokens_with_spans(v)]
            ks = [x for x in ks if x in gaz.name_keys]
            if ks:
                ev.names.add(tuple(ks))
        if KEY_REL.search(k0):
            ks = [name_key(t) for _, _, t in tokens_with_spans(REL_RE.sub(" ", v))]
            ks = [x for x in ks if x in gaz.name_keys]
            if ks:
                ev.relatives.add(tuple(ks))
        if KEY_REF.search(k0) and re.search(r"\d", v) and len(v.strip()) >= 6 and "[" not in v:
            ev.refs.add(v.strip().upper())
        if re.search(r"(code|icd)", k0, re.I):
            for c in RE_ICD.findall(v):
                ev.codes.add(c)
        if re.search(r"(diagnos|display|condition|disease|procedure|impression|problem)", k0, re.I):
            ev.conditions.add(v.strip().casefold())
    text = "\n".join(texts)
    ev.text = text
    low = text.casefold()
    # ages in age forms
    for m in RE_AGE_CTX.finditer(text):
        r = age_range(m.group(1), m.group(2), m.group(3))
        if r:
            (ev.ages if r[0] == r[1] else ev.bands).add(r)
    for m in RE_AGE_FORM.finditer(text):
        pre = text[max(0, m.start() - 8):m.start()]
        post = text[m.end():m.end() + 12].casefold()
        if RE_HIST.search(pre) or re.match(r"\s*(back|ago|history|since|duration)", post):
            continue
        r = age_range(m.group(1), m.group(2), m.group(3))
        if r:
            (ev.ages if r[0] == r[1] else ev.bands).add(r)
        g = m.group(4) or m.group(5)
        if g:
            ev.genders.add(g.upper())
    for m in RE_BRACKET_AGE.finditer(text):
        r = age_range(*m.groups())
        if r and r[1] > r[0]:
            ev.bands.add((r[0], r[1] - 1))
    for m in RE_PLUS_AGE.finditer(text):
        if re.search(r"(age|yrs|years|umar|उम्र)", text[max(0, m.start() - 12):m.end() + 8], re.I):
            ev.bands.add((int(m.group(1)), 125))
    for m in re.finditer(r"\b(?:DOB|D\.O\.B|Date of Birth|जन्म\s*तिथि)\s*[:\-]?\s*([^\n,;]{6,20})", text, re.I):
        for _, d in find_dates(m.group(1)):
            ev.birth_years.add(d.year)
        m2 = re.match(r"\s*(19\d{2}|20\d{2})\b", m.group(1))
        if m2:
            ev.birth_years.add(int(m2.group(1)))
    # gender
    for m in REL_RE.finditer(text):
        c = m.group(1).upper()
        if c == "S":
            ev.genders.add("M")
        elif c in "DW":
            ev.genders.add("F")
    for m in F_WORDS.finditer(text):
        w = m.group(1).casefold()
        if w == "f" and not re.search(r"(sex|gender|ling)\s*:\s*$|/\s*$", text[max(0, m.start() - 10):m.start()], re.I):
            continue
        ev.genders.add("F")
    for m in M_WORDS.finditer(text):
        w = m.group(1).casefold()
        if w == "m" and not re.search(r"(sex|gender|ling)\s*:\s*$|/\s*$", text[max(0, m.start() - 10):m.start()], re.I):
            continue
        ev.genders.add("M")
    # places (Latin and Devanagari) + names
    toks = tokens_with_spans(text)
    keys = [name_key(t) for _, _, t in toks]
    pl = gaz.find_places(keys)
    ev.districts |= pl["district"]
    ev.tehsils |= pl["tehsil"]
    ev.villages |= pl["village"]
    # name phrases from free text
    i = 0
    n = len(toks)
    while i < n:
        if keys[i] in gaz.name_keys:
            j = i
            while j + 1 < n and keys[j + 1] in gaz.name_keys and toks[j + 1][0] - toks[j][1] <= 2:
                j += 1
            pre = text[max(0, toks[i][0] - 8):toks[i][0]]
            phrase = tuple(keys[i:j + 1])
            if DR_RE.search(pre):
                pass
            elif re.search(r"(?<![A-Za-z])[SDWC]\s*/\s*[Oo]\s*[:.\-]?\s*$", pre):
                ev.relatives.add(phrase)
            elif len(phrase) >= 1:
                ev.names.add(phrase)
            i = j + 1
        else:
            i += 1
    # identifiers
    for m in RE_PHONE.finditer(text):
        ev.phones.add(re.sub(r"\D", "", m.group(1)))
    for m in RE_MPHONE.finditer(text):
        ev.masked_phones.add((m.group(1), m.group(2)))
    for m in RE_AADHAAR_M.finditer(text):
        ev.last4.add(m.group(1))
    for m in RE_AADHAAR.finditer(text):
        ev.last4.add(m.group(3))
    for m in RE_EMAIL.finditer(text):
        ev.emails.add(m.group(0).casefold())
    for m in RE_HOUSE.finditer(text):
        ev.houses.add(m.group(1).lstrip("0") or "0")
    for m in RE_PIN.finditer(text):
        if m.group(1) in gaz.pins:
            ev.pins.add(m.group(1))
    for m in RE_PINPFX.finditer(text):
        ev.pin_prefixes.add(m.group(1))
    for m in RE_PSN.finditer(text):
        ev.refs.add(m.group(0))
    for m in RE_UHID.finditer(text):
        ev.refs.add(m.group(0).upper())
    for c in RE_ICD.findall(text):
        ev.codes.add(c)
    for h in HOSPITALS:
        if h.casefold() in low:
            ev.hospitals.add(h)
    if not ev.hospitals and hospital_ctx:
        ev.hospitals |= hospital_ctx
    # dates (excluding DOB-ish ones from visits)
    dob_spans = []
    for line in texts:
        pass
    ds = []
    for p, d in find_dates(text):
        ctx = text[max(0, p - 25):p].casefold()
        if re.search(r"(dob|birth|janm|जन्म)[^\n]*$", ctx):
            continue
        ds.append(d)
    ev.dates |= set(ds)
    ds = sorted(set(ds))
    for a in range(len(ds)):
        for b in range(a + 1, len(ds)):
            ev.intervals.add((ds[b] - ds[a]).days)
    return ev


# ----------------------------------------------------------------------------- linkage
def link(ev, reg, ref_year):
    """Filter + weight registry candidates. Returns ({idx: prob}, filtered idx list, applied filters)."""
    cands = list(range(len(reg)))
    applied = []

    def filt(name, pred, cond):
        nonlocal cands
        if not cond:
            return
        new = [i for i in cands if pred(reg[i])]
        if new:
            if len(new) < len(cands):
                applied.append(name)
            cands = new

    filt("phone", lambda r: r["phone"] and any(p[-10:] == r["phone"] for p in ev.phones), ev.phones)
    filt("email", lambda r: r["email"] and r["email"] in ev.emails, ev.emails)
    filt("last4", lambda r: r["aadhaar_last4"] and r["aadhaar_last4"] in ev.last4, ev.last4)
    filt("masked_phone", lambda r: r["phone"] and any(r["phone"].startswith(a) and r["phone"].endswith(b)
                                                      for a, b in ev.masked_phones), ev.masked_phones)
    filt("district", lambda r: r["district"] in ev.districts, ev.districts)
    filt("gender", lambda r: r["gender"] in ev.genders, len(ev.genders) == 1)
    ar = ev.age_ranges()
    filt("age", lambda r: r["age"] is not None and any(lo - 1 <= r["age"] <= hi + 2 for lo, hi in ar), ar)
    filt("birth_year", lambda r: r["age"] is not None and any(abs((ref_year - r["age"]) - y) <= 1
                                                              for y in ev.birth_years), ev.birth_years)
    filt("tehsil", lambda r: r["tehsil"] in ev.tehsils, ev.tehsils)
    filt("village", lambda r: r["village"] in ev.villages, ev.villages)
    filt("pin", lambda r: r["pin"] in ev.pins, ev.pins)
    filt("pin_prefix", lambda r: r["pin"][:3] in ev.pin_prefixes, ev.pin_prefixes)
    w = {}
    why = {}
    for i in cands:
        r = reg[i]
        x = 1.0
        tags = []
        full = given = sur = False
        for ph in ev.names:
            s = set(ph)
            if r["gkey"] and r["gkey"] in s and (not r["skey"] or r["skey"] in s):
                full = True
            elif r["gkey"] and r["gkey"] in s:
                given = True
            elif r["skey"] and r["skey"] in s:
                sur = True
        if full:
            x *= 60
            tags.append("full_name")
        else:
            if given:
                x *= 8
                tags.append("given")
            if sur:
                x *= 3
                tags.append("surname")
        rk = set(k for k in r["rkeys"] if k)
        if rk and any(rk <= set(ph) or (len(rk & set(ph)) >= 1 and r["rkeys"][0] in ph) for ph in ev.relatives):
            x *= 8
            tags.append("relative")
        if r["house_no"] and r["house_no"].lstrip("0") in ev.houses:
            x *= 2
            tags.append("house")
        w[i] = x
        why[i] = tags
    if any(why[i] and set(why[i]) - {"house"} for i in cands):
        for i in cands:
            if not (set(why[i]) - {"house"}):
                w[i] *= NAME_MISS
    tot = sum(w.values())
    probs = {i: v / tot for i, v in w.items()}
    return probs, cands, applied, why


# ----------------------------------------------------------------------------- main attack
def map_release_files(truth, release, raw):
    """input path -> release file path."""
    if raw:
        return {p: os.path.join(release, p) for p in truth["files"]}
    out = {}
    rep = os.path.join(release, "report.json")
    by_sha = collections.defaultdict(list)
    if os.path.exists(rep):
        for f in json.load(open(rep, encoding="utf-8")).get("files", []):
            if f.get("output"):
                by_sha[f.get("input_sha256")].append(os.path.join(release, f["output"]))
    inputs_by_sha = collections.defaultdict(list)
    for p, fi in sorted(truth["files"].items()):
        inputs_by_sha[fi.get("sha256")].append(p)
    for sha, ins in inputs_by_sha.items():
        outs = sorted(set(by_sha.get(sha, [])))
        for p in ins:
            same = os.path.join(release, "sanitized", p)
            if same in outs:
                out[p] = same
                outs.remove(same)
        for p in ins:
            if p not in out and outs:
                d = os.path.dirname(p)
                pick = next((o for o in outs if os.path.dirname(o).endswith(d)), outs[0])
                out[p] = pick
                outs.remove(pick)
    for p in truth["files"]:
        if p not in out:
            same = os.path.join(release, "sanitized", p)
            if os.path.exists(same):
                out[p] = same
    return out


def file_hospital(path, text):
    hs = set(h for h in HOSPITALS if h.casefold() in text.casefold())
    if len(hs) == 1:
        return hs
    b = os.path.basename(path).casefold()
    for a, h in HOSP_ALIASES.items():
        if b.startswith(a) or ("_" + a) in b:
            return {h}
    return hs if hs else set()


def attack(release, dev, raw=False, verbose=False):
    truth = json.load(open(os.path.join(dev, "truth", "truth.json"), encoding="utf-8"))
    reg = load_registry(dev)
    gaz = Gazetteer(reg)
    rid2idx = {r["rid"]: i for i, r in enumerate(reg)}
    ref_year = int(truth.get("ref_date", "2026-11-20")[:4])
    facts = [json.loads(l) for l in open(os.path.join(dev, "attacker", "known_facts.jsonl"), encoding="utf-8") if l.strip()]
    root = os.path.join(dev, "input") if raw else release
    fmap = map_release_files(truth, root, raw)
    fc = FileCache()
    patients = truth["patients"]
    records = []  # dicts
    for p, fi in sorted(truth["files"].items()):
        units = fi.get("units", {})
        rp = fmap.get(p)
        if not rp:
            continue
        hctx = None
        for loc, u in sorted(units.items()):
            pt = u.get("patient")
            if not pt:
                continue
            pairs = unit_pairs(fc, rp, fi, loc, units.keys())
            if pairs is None:
                continue
            if hctx is None:
                f = fc.get(rp, fi.get("format", "text"), fi.get("delimiter"))
                hctx = file_hospital(rp, f["text"] if f else "")
            ev = extract(pairs, gaz, hctx)
            records.append({"file": p, "rfile": rp, "loc": loc, "patient": pt,
                            "true": rid2idx.get(patients[pt]["rid"]), "ev": ev, "entities": u.get("entities", [])})
    sim = simulate(records)
    # pseudonyms from records.jsonl that are present in the content
    rec_psn = {}
    rj = os.path.join(release, "records.jsonl")
    if not raw and os.path.exists(rj):
        for l in open(rj, encoding="utf-8"):
            if l.strip():
                x = json.loads(l)
                rec_psn[(os.path.join(release, x["file"]), x["loc"])] = x.get("patient")
    # ---------------- A2/A3
    stats = collections.Counter()
    for r in records:
        probs, cands, applied, why = link(r["ev"], reg, ref_year)
        r["probs"], r["cands"], r["applied"], r["why"] = probs, cands, applied, why
        r["p"] = probs.get(r["true"], 0.0)
        r["top"] = max(probs, key=probs.get) if probs else None
    n = len(records) or 1
    a3 = sum(r["p"] for r in records) / n
    unique = sum(1 for r in records if r["p"] >= 0.999) / n
    conf_rec = sum(1 for r in records if r["p"] >= 0.5) / n
    # ---------------- A4 profiles via shared refs
    parent = list(range(len(records)))

    def find(x):
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x
    ref_owner = {}
    for i, r in enumerate(records):
        for ref in r["ev"].refs:
            if ref in ref_owner:
                a, b = find(i), find(ref_owner[ref])
                if a != b:
                    parent[a] = b
            else:
                ref_owner[ref] = i
    groups = collections.defaultdict(list)
    for i in range(len(records)):
        groups[find(i)].append(i)
    profiles = []
    for g, idx in groups.items():
        ev = Evidence()
        for i in idx:
            ev.merge(records[i]["ev"])
        # intervals stay per-record
        ev.intervals = set()
        for i in idx:
            ev.intervals |= records[i]["ev"].intervals
        probs, cands, applied, why = link(ev, reg, ref_year)
        owner = collections.Counter(records[i]["patient"] for i in idx).most_common(1)[0][0]
        prof = {"idx": idx, "ev": ev, "probs": probs, "cands": set(cands), "applied": applied, "why": why,
                "owner": owner}
        profiles.append(prof)
        for i in idx:
            r = records[i]
            r["prof"] = prof
            r["pp"] = probs.get(r["true"], 0.0)
            r["risk4"] = max(r["p"], r["pp"])
    pats_present = sorted(set(r["patient"] for r in records))
    reid = set(r["patient"] for r in records if r["risk4"] >= 0.5)
    a4 = len(reid) / (len(pats_present) or 1)
    a4_rec = sum(r["risk4"] for r in records) / n
    # ---------------- A5 targeted
    hosp_by_name = {h.casefold(): h for h in HOSPITALS}
    # condition share counts across profiles
    def prof_has_cond(prof, hint):
        h = hint.casefold()
        if h in prof["ev"].text.casefold():
            return True
        return any(h == c or h in c for c in prof["ev"].conditions)
    patient_rids = {v["rid"]: k for k, v in patients.items()}
    shift = 0
    offs = collections.defaultdict(set)
    for prof in profiles:
        if not prof["probs"]:
            continue
        top = max(prof["probs"], key=prof["probs"].get)
        if prof["probs"][top] < 0.9:
            continue
        for f in facts:
            if rid2idx.get(f["rid"]) == top:
                for vd in f.get("visit_dates", []):
                    kd = date.fromisoformat(vd)
                    for d in prof["ev"].dates:
                        o = (kd - d).days
                        if abs(o) <= 400:
                            offs[o].add(f["rid"])
    if offs:
        best = max(sorted(offs), key=lambda o: (len(offs[o]), o == 0, -abs(o)))
        if len(offs[best]) >= 2:
            shift = best
    hits = collections.Counter()
    hits_true = collections.Counter()
    tgt_results = []
    decoys = claims = 0
    for f in facts:
        ti = rid2idx.get(f["rid"])
        is_pat = f["rid"] in patient_rids
        kds = set(date.fromisoformat(v) for v in f.get("visit_dates", []))
        hint = f.get("condition_hint")
        cond_n = sum(1 for prof in profiles if prof_has_cond(prof, hint)) if hint else 0
        weights = {}
        sig = {}
        for k, prof in enumerate(profiles):
            if ti is None or ti not in prof["cands"]:
                continue
            ds = set(d + timedelta(days=shift) for d in prof["ev"].dates)
            dh = bool(kds & ds)
            ch = bool(hint) and prof_has_cond(prof, hint)
            sh = f.get("stay_days") is not None and f["stay_days"] in prof["ev"].intervals
            if not (dh or ch or sh):
                continue
            w = 1.0
            if dh:
                w *= 8
            if ch:
                w *= 8 if cond_n <= 3 else 2
            if sh:
                w *= 4
            if f.get("hospital") in prof["ev"].hospitals:
                w *= 2
            w *= max(prof["probs"].get(ti, 0.0), 1.0 / max(1, len(prof["cands"])))
            weights[k] = w
            sig[k] = (dh, ch, sh)
        tot = sum(weights.values())
        if not is_pat:
            decoys += 1
            if weights:
                claims += 1
            continue
        pt = patient_rids[f["rid"]]
        succ = sum(w for k, w in weights.items() if profiles[k]["owner"] == pt) / tot if tot else 0.0
        for k in weights:
            for name, flag in zip(("date", "condition", "stay"), sig[k]):
                if flag:
                    hits[name] += 1
                    if profiles[k]["owner"] == pt:
                        hits_true[name] += 1
        tgt_results.append({"rid": f["rid"], "patient": pt, "success": succ, "hint": hint,
                            "cond_profiles": cond_n,
                            "true_signals": sorted(set(n for k in weights if profiles[k]["owner"] == pt
                                                       for n, fl in zip(("date", "condition", "stay"), sig[k]) if fl))})
    a5 = sum(t["success"] for t in tgt_results) / (len(tgt_results) or 1)
    # ---------------- A1 direct exposure
    ftext = {}
    for r in records:
        if r["rfile"] not in ftext:
            f = fc.get(r["rfile"], truth["files"][r["file"]].get("format", "text"), None)
            ftext[r["rfile"]] = dnorm((f["text"] if f else "") + "\n" + os.path.basename(r["rfile"]))
    exposed = {}
    for p, fi in truth["files"].items():
        rp = fmap.get(p)
        if not rp:
            continue
        if rp not in ftext:
            f = fc.get(rp, fi.get("format", "text"), fi.get("delimiter"))
            ftext[rp] = dnorm((f["text"] if f else "") + "\n" + os.path.basename(rp))
        for loc, u in fi.get("units", {}).items():
            pt = u.get("patient")
            if not pt:
                continue
            for e in u.get("entities", []):
                if e.get("critical") and e.get("person") and e.get("role", "patient") == "patient":
                    s = dnorm(e["surface"])
                    if len(s) >= 5 and s in ftext[rp]:
                        exposed.setdefault(pt, set()).add(e["type"])
    a1 = len(exposed) / (len(patients) or 1)
    # ---------------- A6 pseudonym inversion
    psn_by_pt = collections.defaultdict(set)
    for r in records:
        for ref in r["ev"].refs:
            if ref.startswith("PSN-"):
                psn_by_pt[r["patient"]].add(ref)
        x = rec_psn.get((r["rfile"], r["loc"]))
        if x and x in r["ev"].text:
            psn_by_pt[r["patient"]].add(x)
    orig = collections.defaultdict(set)
    for pt, v in patients.items():
        for lst in v.get("uhids", {}).values():
            orig[pt].update(lst)
    for r in records:
        for e in r["entities"]:
            if e.get("role") == "patient" and e["type"] in ("AADHAAR", "PHONE", "ABHA_NUMBER", "MRN") or \
                    (e["type"] == "PATIENT_NAME" and e.get("script") == "latin" and e.get("full")):
                orig[r["patient"]].add(e["surface"])
    inverted = set()
    for pt, psns in psn_by_pt.items():
        tr = transforms(orig[pt])
        cores = set()
        for o in orig[pt]:
            dg = re.sub(r"\D", "", o)
            if len(dg) >= 5:
                cores.add(dg.lstrip("0") or dg)
                cores.add(dg[-10:])
        for psn in psns:
            c = psn[4:].casefold() if psn.startswith("PSN-") else psn.casefold()
            if len(c) >= 8 and any(t.startswith(c) for t in tr):
                inverted.add(pt)
            if any(core and len(core) >= 5 and core in re.sub(r"\D", "", psn) for core in cores):
                inverted.add(pt)
    a6 = (len(inverted) / len(psn_by_pt)) if psn_by_pt else None
    # ---------------- evidence census
    census = collections.Counter()
    for r in records:
        ev = r["ev"]
        for name, s in (("ages", ev.ages), ("bands", ev.bands), ("birth_years", ev.birth_years),
                        ("district", ev.districts), ("tehsil", ev.tehsils), ("village", ev.villages),
                        ("pin", ev.pins), ("pin_prefix", ev.pin_prefixes), ("gender", ev.genders),
                        ("names", ev.names), ("relative_names", ev.relatives), ("house_no", ev.houses),
                        ("phones", ev.phones), ("masked_phones", ev.masked_phones), ("last4", ev.last4),
                        ("emails", ev.emails), ("conditions", ev.conditions), ("icd_codes", ev.codes),
                        ("dates", ev.dates), ("refs", ev.refs)):
            if s:
                census[name] += 1
    res = {
        "records_attacked": len(records), "patients_present": len(pats_present),
        "direct_exposure": a1, "record_linkage_risk": a3, "unique_records": unique,
        "confident_record_reid": conf_rec, "patients_reidentified": a4, "profile_record_risk": a4_rec,
        "targeted_success": a5, "targets": len(tgt_results), "decoy_false_claims": claims / (decoys or 1),
        "recovered_global_shift_days": shift, "targeted_signal_hits": dict(hits),
        "targeted_signal_hits_true": dict(hits_true), "clusters": len(profiles),
        "pseudonym_inversion": {"rate": a6, "pseudonymised_patients": len(psn_by_pt), "inverted": sorted(inverted)},
        "exposed_patients": {k: sorted(v) for k, v in sorted(exposed.items())},
        "evidence_census": dict(census), "targets_detail": tgt_results, "simulation": sim,
    }
    if verbose:
        res["_records"] = records
        res["_reg"] = reg
    return res


def simulate(records):
    """What-if hooks (evidence-level edits, equivalent to editing the release):
    ATTACK_DROP=birth_years,pin_prefixes,...  drop evidence fields everywhere
    ATTACK_BAND=10                            coarsen every age/band to aligned N-year bands
    ATTACK_RARE_K=3                           suppress diagnosis strings/codes held by <= K patients
    """
    info = {}
    drop = [x for x in os.environ.get("ATTACK_DROP", "").split(",") if x]
    for r in records:
        for f in drop:
            getattr(r["ev"], f).clear()
    if drop:
        info["dropped"] = drop
    band = int(os.environ.get("ATTACK_BAND", "0") or 0)
    if band:
        for r in records:
            ev = r["ev"]
            new = set()
            for lo, hi in ev.ages | ev.bands:
                if hi >= 125:
                    new.add((lo, hi))
                    continue
                new.add((lo // band * band, hi // band * band + band - 1))
            ev.ages, ev.bands = set(), new
        info["band"] = band
    k = int(os.environ.get("ATTACK_RARE_K", "0") or 0)
    if k:
        holders = collections.defaultdict(set)
        for r in records:
            for c in r["ev"].conditions | r["ev"].codes:
                holders[c].add(r["patient"])
        rare = set(c for c, ps in holders.items() if len(ps) <= k)
        touched = total = recs = 0
        for r in records:
            ev = r["ev"]
            vals = ev.conditions | ev.codes
            total += len(vals)
            hit = vals & rare
            if hit:
                recs += 1
                touched += len(hit)
                ev.conditions -= hit
                ev.codes -= hit
                t = ev.text
                for c in sorted(hit, key=len, reverse=True):
                    t = re.sub(re.escape(c), "[DX]", t, flags=re.I)
                ev.text = t
        info["rare_k"] = {"k": k, "rare_strings": len(rare), "distinct_strings": len(holders),
                          "values_touched": touched, "values_total": total, "records_touched": recs,
                          "patients_touched": len(set(p for c in rare for p in holders[c]))}
    return info


def dnorm(s):
    s = norm(s).casefold()
    s = re.sub(r"(?<=\d)[\s\-](?=\d)", "", s)
    return re.sub(r"\s+", " ", s)


def transforms(origs):
    out = set()
    for o in origs:
        vs = {o, o.casefold(), o.upper(), re.sub(r"\D", "", o), re.sub(r"[^A-Za-z0-9]", "", o),
              re.sub(r"[^A-Za-z0-9]", "", o).casefold(), o[::-1]}
        vs.discard("")
        for v in list(vs):
            b = v.encode("utf-8")
            out.add(v.casefold())
            for h in (hashlib.md5, hashlib.sha1, hashlib.sha256, hashlib.sha512):
                out.add(h(b).hexdigest())
            out.add(base64.b64encode(b).decode().casefold())
            out.add(base64.b32encode(b).decode().casefold())
    return out


def cross_release(dev, rel1, rel2):
    truth = json.load(open(os.path.join(dev, "truth", "truth.json"), encoding="utf-8"))
    m1 = map_release_files(truth, rel1, False)
    m2 = map_release_files(truth, rel2, False)

    def recs(rel):
        d = {}
        for l in open(os.path.join(rel, "records.jsonl"), encoding="utf-8"):
            if l.strip():
                x = json.loads(l)
                d[(os.path.join(rel, x["file"]), x["loc"])] = x.get("patient")
        return d
    r1, r2 = recs(rel1), recs(rel2)
    fc1, fc2, fcr = FileCache(), FileCache(), FileCache()
    same_p = collections.defaultdict(set)
    eq = tot = eq_shift = tot_shift = 0
    for p, fi in truth["files"].items():
        if p not in m1 or p not in m2:
            continue
        units = fi.get("units", {})
        for loc, u in units.items():
            pt = u.get("patient")
            if not pt:
                continue
            a, b = r1.get((m1[p], loc)), r2.get((m2[p], loc))
            if a and b:
                same_p[pt].add(a == b)
            pa = unit_pairs(fc1, m1[p], fi, loc, units.keys())
            pb = unit_pairs(fc2, m2[p], fi, loc, units.keys())
            pr = unit_pairs(fcr, os.path.join(dev, "input", p), fi, loc, units.keys())
            if not pa or not pb:
                continue
            da = [d for _, d in sorted(find_dates("\n".join(v for _, v in pa)))]
            db = [d for _, d in sorted(find_dates("\n".join(v for _, v in pb)))]
            dr = [d for _, d in sorted(find_dates("\n".join(v for _, v in pr)))] if pr else []
            if len(da) != len(db):
                continue
            for i, (x, y) in enumerate(zip(da, db)):
                tot += 1
                eq += x == y
                if len(dr) == len(da) and dr[i] != x:
                    tot_shift += 1
                    eq_shift += x == y
    stable_psn = sum(1 for v in same_p.values() if True in v) / (len(same_p) or 1)
    stable_dates = eq / (tot or 1)
    return {"stable_pseudonyms": stable_psn, "stable_dates_all": stable_dates,
            "stable_dates_shifted_only": eq_shift / (tot_shift or 1), "date_pairs": tot,
            "risk": max(stable_psn, stable_dates)}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--release", default=None)
    ap.add_argument("--dev", required=True)
    ap.add_argument("--raw", action="store_true")
    ap.add_argument("--release2")
    ap.add_argument("--raw-json")
    ap.add_argument("--json")
    ap.add_argument("--verbose", action="store_true")
    a = ap.parse_args()
    if a.raw or not a.release:
        res = attack(a.dev, a.dev, raw=True, verbose=a.verbose)
    else:
        res = attack(a.release, a.dev, raw=False, verbose=a.verbose)
    raw = None
    if a.raw_json:
        raw = json.load(open(a.raw_json))
        raw = raw.get("result", raw)
    elif not a.raw and a.release:
        raw = attack(a.dev, a.dev, raw=True)
    if a.release2 and a.release:
        res["cross_release"] = cross_release(a.dev, a.release, a.release2)
    else:
        res["cross_release"] = None
    records = res.pop("_records", None)
    reg = res.pop("_reg", None)
    print("records attacked %d, patients present %d, clusters %d" % (res["records_attacked"], res["patients_present"], res["clusters"]))
    keys = ["direct_exposure", "record_linkage_risk", "unique_records", "confident_record_reid",
            "patients_reidentified", "targeted_success", "decoy_false_claims", "recovered_global_shift_days"]
    for k in keys:
        rv = raw.get(k) if raw else None
        print("  %-30s %8.4f%s" % (k, res[k], ("   raw %.4f" % rv) if isinstance(rv, (int, float)) else ""))
    print("  targeted_signal_hits (all/true-owner): %s / %s   targets %d" % (res["targeted_signal_hits"], res["targeted_signal_hits_true"], res["targets"]))
    if res.get("simulation"):
        print("  SIMULATION: %s" % res["simulation"])
    print("  pseudonym_inversion: %s" % {k: v for k, v in res["pseudonym_inversion"].items() if k != "inverted"})
    if res["cross_release"]:
        print("  cross_release: %s" % res["cross_release"])
    # final block
    comp = {"A1": res["direct_exposure"], "A3": res["record_linkage_risk"], "A4": res["patients_reidentified"],
            "A5": res["targeted_success"]}
    rawk = {"A1": "direct_exposure", "A3": "record_linkage_risk", "A4": "patients_reidentified", "A5": "targeted_success"}
    rel = {}
    for k, v in comp.items():
        base = raw.get(rawk[k]) if raw else None
        rel[k] = min(1.0, v / base) if base else (v if a.raw or not raw else v)
        if a.raw:
            rel[k] = 1.0 if v else 0.0
    if res["pseudonym_inversion"]["rate"] is not None:
        rel["A6"] = res["pseudonym_inversion"]["rate"]
    if res["cross_release"]:
        rel["A7"] = res["cross_release"]["risk"]
    risk = sum(WEIGHTS[k] * v for k, v in rel.items()) / sum(WEIGHTS[k] for k in rel)
    print("\nFINAL (relative to raw where applicable)")
    for k in ("A1", "A3", "A4", "A5", "A6", "A7"):
        if k in rel:
            print("  %-3s risk %.4f  rel %.4f  weight %.2f%s" % (
                k, comp.get(k, rel[k]), rel[k], WEIGHTS[k],
                ("   organiser reference %.1f%%" % (ORG_REF[k] * 100)) if k in ORG_REF else ""))
        else:
            print("  %-3s n/a (not applicable: weight dropped)" % k)
    print("  combined risk %.4f   privacy resistance = %.4f" % (risk, 1 - risk))
    res["relative"] = rel
    res["combined_risk"] = risk
    res["resistance"] = 1 - risk
    if a.verbose and records is not None:
        print("\nEVIDENCE CENSUS (records with >=1 extracted item, of %d)" % res["records_attacked"])
        for k, v in sorted(res["evidence_census"].items(), key=lambda kv: -kv[1]):
            print("  %-16s %5d" % (k, v))
        print("\nTARGETS")
        for t in res["targets_detail"]:
            print("  %s %s success %.3f true-signals %s hint=%s (shared by %d profiles)" % (
                t["patient"], t["rid"], t["success"], t["true_signals"], t["hint"], t["cond_profiles"]))
        best = {}
        for r in records:
            if r["patient"] not in best or r["risk4"] > best[r["patient"]]["risk4"]:
                best[r["patient"]] = r
        print("\nTOP-RISK PATIENTS (best record; record p / profile p; filters applied; weights)")
        for pt, r in sorted(best.items(), key=lambda kv: -kv[1]["risk4"])[:25]:
            prof = r["prof"]
            useprof = r["pp"] >= r["p"]
            src = prof if useprof else r
            ev = prof["ev"] if useprof else r["ev"]
            print("  %s risk %.3f (rec %.3f prof %.3f, %d cands) %s:%s" % (
                pt, r["risk4"], r["p"], r["pp"], len(src["cands"]), r["file"], r["loc"]))
            print("      filters %s  weights %s" % (src["applied"], src["why"].get(r["true"])))
            print("      evidence counts: ages %d bands %d birth-years %d genders %d districts %d tehsils %d villages %d "
                  "pins %d pin-prefixes %d houses %d" % (
                      len(ev.ages), len(ev.bands), len(ev.birth_years), len(ev.genders), len(ev.districts),
                      len(ev.tehsils), len(ev.villages), len(ev.pins), len(ev.pin_prefixes), len(ev.houses)))
            if ev.names or ev.relatives or ev.phones or ev.last4:   # counts only: never echo record content
                print("      names %d rel %d phones %d last4 %d" % (len(ev.names), len(ev.relatives),
                                                                  len(ev.phones), len(ev.last4)))
    if a.json:
        with open(a.json, "w") as fh:
            json.dump(res, fh, indent=1, default=str)


if __name__ == "__main__":
    main()
