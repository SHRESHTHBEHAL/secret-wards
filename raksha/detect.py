"""Free-text PII detection for hospital records in English, Devanagari Hindi and Hinglish.

`detect(text, known, order)` returns non-overlapping, sorted Spans of identity evidence;
`text_facts(text, order)` folds them into a Facts sheet. Pure, deterministic, standard library only.
"""
from __future__ import annotations

import bisect
import re
import unicodedata
from dataclasses import dataclass
from typing import Dict, FrozenSet, List, Optional, Set, Tuple

from . import dates, lexicon, patterns, scripts
from .translit import GENERIC_NAME_PARTS, HONORIFICS, TITLES, name_key, name_tokens
from .types import Facts, Span

try:  # private helper; fall back to exact key equality when absent
    from .translit import _keys_match as _fuzzy_keys
except Exception:  # pragma: no cover
    def _fuzzy_keys(a: str, b: str) -> bool:
        return bool(a) and a == b


@dataclass
class Known:
    own_keys: FrozenSet[str] = frozenset()
    full_names: Tuple[Tuple[str, ...], ...] = ()
    id_values: FrozenSet[str] = frozenset()


# ---------------------------------------------------------------- kinds

ID_KINDS = frozenset({"PHONE", "AADHAAR", "AADHAAR_MASKED", "ABHA_NUMBER", "ABHA_ADDRESS", "EMAIL", "PAN",
                      "INSURANCE_ID", "MRN"})
NAME_KINDS = frozenset({"PATIENT_NAME", "RELATIVE_NAME", "PERSON"})

# ---------------------------------------------------------------- word lists


def _nfc(s: str) -> str:
    return unicodedata.normalize("NFC", s)


def _ws(s: str) -> FrozenSet[str]:
    return frozenset(_nfc(w.lower()) for w in s.split())


_EN_COMMON = _ws("""
a an the and or of in on at to for from with by as is was were be been are has have had not no yes
this that these those it its he she his her him they them their we our you your i my me
after before above below under over into onto upon off out up down then than also only same such
all any each every some other more most less few many much very well good bad new old next last first
second third day night morning evening noon today yesterday tomorrow week month year time date
mr mrs ms dr name age sex gender male female address mobile phone contact no number id
date admission discharge discharged admitted course hospital stay summary note notes nursing report
reports presenting complaint complaints history medications medication medicine medicines advice adv
review follow up visit visits diagnosis diagnoses procedure procedures treatment treated plan impression
investigation investigations finding findings result results remark remarks comment comments signature
signed sign consultant doctor ward bed unit department dept opd ipd icu emergency general
essential primary secondary type unspecified specified without with other others site not significant
past present family personal social known case continue continued stop stopped start started repeat
take taken given give daily weekly monthly low high normal salt diet diabetic soft liquid fluids rest
condition stable improved improving better worse fair poor patient patients attendant relative relatives
forwarded attachment message call karo please thanks thank regards dear sir madam team staff
total test tests sample samples collected received reported printed page end copy original verified
lab labs laboratory pathology diagnostics diagnostic centre center clinic hospital sadan charitable
multispeciality multispecialty super speciality specialty medical college institute trust foundation
district government govt community health primary phc chc nursing home care memorial city civil state
india uttar pradesh lucknow road street nagar
january february march april may june july august september october november december
jan feb mar apr jun jul aug sep sept oct nov dec monday tuesday wednesday thursday friday saturday sunday
mon tue wed thu fri sat sun am pm hrs hr min mins
rx tab tabs cap caps inj syp syr iv im
oral blood sugar serum random fasting urine stool count ratio level levels fever pain
cataract surgery medicine pulmonology cardiology nephrology neurology orthopaedics paediatrics gynaecology
obstetrics dermatology psychiatry oncology urology ent ophthalmology physician surgeon md ms mbbs dnb frcs
visitor log round rounds took took evening shift duty in-charge incharge sister nurse brother
ok okay hello hi namaste ji koi problem ho to lena hai bola diya
""")

_HEADER_WORDS = _ws("""
hospital hospitals sadan clinic clinics pathology lab labs laboratory diagnostics diagnostic centre center
summary notes nursing medical college institute trust foundation dispensary phc chc polyclinic nursinghome
multispeciality multispecialty charitable healthcare health prescription pharmacy chemist imaging scan
""")

_ORG_TAIL = _ws("""
hospital hospitals sadan clinic pathology lab labs laboratory diagnostics centre center trust foundation
college institute pharmacy chemist medicals nursing home bhawan bhavan mandir masjid school bank
""")

_LABEL_WORDS = _ws("""
name naam nam patient pt rogi mareez mariz marij age umar umr sex gender ling dob birth janm tithi
mob mobile phone ph tel cell contact whatsapp address addr pata uhid mrn reg regn registration ipd ip adm
village vill gram gaon tehsil distt dist district jila zila pin pincode father husband guardian mother wife
spouse son daughter relative relation attendant
नाम मरीज़ मरीज रोगी आयु उम्र उमर लिंग जन्म तिथि मोबाइल फोन फ़ोन संपर्क सम्पर्क पता पंजीकरण पंजीयन
आईपीडी सं सं. नं नं. ग्राम गांव गाँव तहसील जिला ज़िला पिन पिता पति पत्नी माता पुत्र पुत्री वर्ष पुरुष महिला
तारीख भर्ती छुट्टी निदान डिस्चार्ज सारांश ओपीडी पर्चा मकान नंबर मोहल्ला वार्ड पास पीछे सामने
""") | scripts.LABEL_WORDS

_HON_PATIENT = _ws("ji jee sahab saheb sahib didi bhai behenji behen bahen bahenji जी साहब दीदी भाई बहनजी बहन") \
    | scripts.HONORIFICS
_HON_KIN = _ws("""
bhaiya bhaiyya bhaiyaa amma ammi ammaji chacha chachi chachaji tai tau bua mausi mama mami bhabhi bhabhiji
dada dadi nana nani babuji papa mummy uncle aunty auntie baba kaka भैया अम्मा चाचा चाची ताई ताऊ बुआ मौसी मामा मामी भाभी
दादा दादी नाना नानी
""")
_HON_AFTER = _HON_PATIENT | _HON_KIN
_TITLE_BEFORE = _ws("""
mr mrs ms smt shri shree sri sh km kum kumari miss sushri master baby late swargiya janab mister srimati
shrimati श्री श्रीमती सुश्री कुमारी कु कुं स्व स्वर्गीय जनाब
""") | scripts.TITLES
_DROP = frozenset(_nfc(w.casefold()) for w in HONORIFICS | TITLES) | _TITLE_BEFORE | _HON_AFTER

# Devanagari verbs and pronouns that sit next to a mid-sentence name ("उनको रमेश जी लाए")
_HI_FUNC = _ws("""
आई आईं आए आये आया आयी आती आते आता लाए लाये लाई लाया लाईं गईं गये गई बताया बताई कहा कहें दिखाया दिखाई
उनको उन्हें उनकी उनके उनका इनको इन्हें इनकी इनके इनका उसको उसे उसकी उसके आप आपको आपकी आपके मरीज मरीज़ मरीजा
""")
_STOP = (frozenset(_nfc(w) for w in lexicon.CLINICAL_WORDS | lexicon.COMPLAINT_WORDS | lexicon.HINDI_COMMON_WORDS)
         | _EN_COMMON | _HI_FUNC | _LABEL_WORDS | _HEADER_WORDS | _HON_AFTER | _TITLE_BEFORE
         | frozenset(_nfc(w.casefold()) for w in TITLES))
# generic parts are fine inside names but never a name on their own
_GENERIC = frozenset(_nfc(w.lower()) for w in GENERIC_NAME_PARTS) | {"md", "mohd"}
_GENERIC_KEYS = frozenset(name_key(w) for w in GENERIC_NAME_PARTS) | {name_key("mohammad")}
_ABBR = frozenset({"md", "mohd", "mohd", "km", "smt", "sh", "sri", "mr", "mrs", "ms", "kum", "late"})

# ---------------------------------------------------------------- token regexes

# an apostrophe inside a word ("D'Souza") is kept; a possessive "'s" / "’s" is not part of the name
_POSS = r"['’](?![sS](?![A-Za-z]))(?=[A-Za-z])"
_LAT = r"[A-Za-z](?:[A-Za-z\-]|" + _POSS + r")*"
_DEV = r"[ऀ-ॣॱ-ॿ]+"
_TOK = re.compile(r"(" + _LAT + r"|" + _DEV + r")")
_IS_DEVA = re.compile(r"[ऀ-ॿ]")
_LINE = re.compile(r"[^\n]*")


def _is_dev(w: str) -> bool:
    return bool(_IS_DEVA.match(w))


def _low(w: str) -> str:
    return _nfc(w.lower().strip("'’-"))


def _is_name_tok(w: str, mode: str) -> bool:
    """mode 'any': after a name label; 'cap': free text, Latin must be Capitalised."""
    lw = _low(w)
    if not lw or lw in _STOP:
        return False
    if _is_dev(w):
        return len(lw) >= 2
    if len(lw) < 2:
        return False
    if mode == "cap" and not w[0].isupper():
        return False
    return True


def _take_name(text: str, pos: int, end: int, mode: str = "cap", max_tok: int = 4,
               skip_lead: bool = True) -> Optional[Tuple[int, int]]:
    """Name run starting at pos (after optional titles); (start, end) of the name tokens or None."""
    i = pos
    first = -1
    last = -1
    n = 0
    n_real = 0
    while i < end and n < max_tok:
        j = i
        while j < end and text[j] in " \t":
            j += 1
        if n and j - i > 1 and text[i] != ".":
            break                                   # 2+ spaces: next field
        if n and j == i:
            break
        m = _TOK.match(text, j)
        if not m or m.end() > end:
            break
        w = m.group(1)
        we = m.end()
        lw = _low(w)
        if we < len(text) and text[we] == "/" and len(w) <= 2:
            break                                   # S/o, C/O ...
        if skip_lead and first < 0 and (lw in _TITLE_BEFORE or lw in ("dr",)):
            if lw == "dr":
                return None
            i = we + 1 if we < len(text) and text[we] == "." else we
            continue
        if not _is_name_tok(w, mode):
            if lw in _GENERIC and (mode == "any" or w[:1].isupper() or _is_dev(w)):
                pass
            else:
                break
        if first < 0:
            first = j
        last = we
        n += 1
        if lw not in _GENERIC:
            n_real += 1
        i = we
        if i < end and text[i] == "." and lw in _ABBR | _GENERIC or (i < end and text[i] == "." and len(lw) == 1):
            i += 1
    if first < 0 or n_real == 0:
        return None
    return first, last


def _take_name_back(text: str, pos: int, mode: str = "cap", max_tok: int = 3,
                    allow_comma: bool = False) -> Optional[Tuple[int, int]]:
    ls = text.rfind("\n", 0, pos) + 1
    seg = text[ls:pos]
    toks = list(_TOK.finditer(seg))
    if not toks:
        return None
    cur = len(seg)
    first = -1
    last = -1
    n = 0
    n_real = 0
    for k in range(len(toks) - 1, -1, -1):
        m = toks[k]
        gap = seg[m.end():cur]
        if n == 0:
            ok = re.fullmatch(r"[ \t]*,?[ \t]*" if allow_comma else r"[ \t]*", gap) is not None
        else:
            ok = re.fullmatch(r"\.?[ \t]", gap) is not None
        if not ok:
            break
        w = m.group(1)
        lw = _low(w)
        if n and (lw in _TITLE_BEFORE or lw == "dr"):
            if lw == "dr":
                return None
            break
        if not _is_name_tok(w, mode) and not (lw in _GENERIC and (w[:1].isupper() or _is_dev(w))):
            break
        if last < 0:
            last = ls + m.end()
        first = ls + m.start()
        n += 1
        if lw not in _GENERIC:
            n_real += 1
        cur = m.start()
        if n >= max_tok:
            break
    if first < 0 or n_real == 0:
        return None
    return first, last


# ---------------------------------------------------------------- labels

_SEG_SPLIT = re.compile(r"[ \t]{2,}|\t|\|")
_LABEL_RE = re.compile(
    r"[ \t]*([A-Za-zऀ-ॿ][A-Za-zऀ-ॿ0-9 .'’/()#&_\-]{0,40}?)[ \t]*[:：][ \t]*")


def _lw(label: str) -> List[str]:
    t = _nfc(label.lower())
    t = re.sub(r"(?<![a-z])([sdwhcfm])\s*/\s*o(?![a-z])", r" \1/o ", t)
    t = re.sub(r"/(?!o(?![a-z]))", " ", t)
    t = re.sub(r"[^a-z0-9ऀ-ॿ/]+", " ", t)
    return [scripts.alias_label_word(w) for w in t.split()]


def _has(ws: List[str], stems: Tuple[str, ...], exact: Tuple[str, ...] = ()) -> bool:
    for w in ws:
        if w in exact:
            return True
        for s in stems:
            if w.startswith(s):
                return True
    return False


def _classify_label(label: str) -> str:
    ws = _lw(label)
    if not ws:
        return ""
    j = " ".join(ws)
    if _has(ws, ("address", "addr", "residen", "पता", "निवास"), ("add", "pata")):
        return "address"
    if _has(ws, ("dob", "birth", "janm", "जन्म", "d/o/b")) or j.startswith("d o b"):
        return "dob"
    if _has(ws, ("date", "time", "तारीख", "दिनांक", "समय"), ("dt", "dated", "on")):
        return "clinical"
    if _has(ws, ("doctor", "consult", "physician", "surgeon", "डॉ", "चिकित्सक"), ("dr", "by")):
        return "clinical"
    if _has(ws, ("father", "husband", "guardian", "mother", "wife", "spouse", "relative", "relation",
                 "पिता", "पति", "पत्नी", "माता", "अभिभावक", "संरक्षक", "kin"),
            ("son", "daughter", "mata", "nok", "pita", "pati", "patni", "s/o", "w/o", "d/o", "c/o", "h/o")):
        return "relative"
    if _has(ws, ("attend", "companion", "caller", "informant", "witness", "visitor", "escort", "परिजन")):
        return "attendant"
    if any(w in ("id", "no", "number", "#") for w in ws) and _has(ws, ("patient", "hosp", "rogi"), ("pt", "p")):
        return "uhid"
    if _has(ws, ("uhid", "mrn", "regis", "regn", "पंजीकरण", "पंजीयन", "यूएचआईडी", "crno"),
            ("reg", "cr", "mr", "uid", "hosp")):
        return "uhid"
    if _has(ws, ("ipd", "admission", "inpatient", "आईपीडी", "भर्ती"), ("ip", "adm", "ipno")):
        return "enc"
    if _has(ws, ("mob", "phone", "contact", "tele", "cell", "whatsapp", "मोबाइल", "फोन", "फ़ोन", "संपर्क",
                 "सम्पर्क"), ("ph", "tel")) and not _has(ws, ("name", "naam", "नाम")):
        if ws == ["no"] or ws == ["no."]:
            return ""
        return "phone"
    if _has(ws, ("vill", "gram", "gaon", "gaanv", "ग्राम", "गांव", "गाँव")):
        return "village"
    if _has(ws, ("tehsil", "tahsil", "taluk", "तहसील"), ("teh",)):
        return "tehsil"
    if _has(ws, ("distt", "district", "jila", "zila", "जिला", "ज़िला", "जनपद"), ("dist",)):
        return "district"
    if _has(ws, ("pin", "zip", "पिन")):
        return "pin"
    if _has(ws, ("age", "umar", "umr", "आयु", "उम्र", "उमर", "sex", "gender", "ling", "लिंग")):
        return "age"
    if _has(ws, ("diag", "complain", "histor", "course", "medic", "advi", "adv", "treat", "procedure",
                 "investig", "finding", "impression", "opd", "ward", "bed", "dept", "depart", "hospital",
                 "clinic", "test", "result", "plan", "follow", "review", "rx", "drug", "visit", "note",
                 "remark", "diet", "vital", "exam", "status", "condition", "report", "lab", "sample",
                 "निदान", "दवा", "सलाह", "विभाग", "अस्पताल", "वार्ड", "शिकायत", "जांच", "जाँच", "उपचार", "इलाज",
                 "डिस्चार्ज", "ओपीडी", "बिल", "ward", "c/o", "k/c/o", "h/o", "bill", "amount", "total",
                 "insur", "scheme", "policy", "abha", "aadhaar", "aadhar", "pan", "email"),
            ("dx", "bp", "temp")):
        return "clinical"
    if _has(ws, ("name", "naam", "patient", "rogi", "mareez", "mariz", "marij", "नाम", "मरीज", "रोगी",
                 "benefic"), ("pt", "nam")):
        return "name"
    return ""


# ---------------------------------------------------------------- address parts

_A_HOUSE = re.compile(
    r"(?:H\.?\s*No\.?|House(?:\s*No\.?)?|Makan(?:\s*No\.?)?|Flat(?:\s*No\.?)?|Plot(?:\s*No\.?)?|Qtr\.?(?:\s*No\.?)?|"
    r"Door\s*No\.?|मकान(?:\s*(?:नं|नंबर|न)\.?)?|म\.?\s*नं\.?|प्लॉट)\s*[:#\-]?\s*[0-9०-९A-Za-z/\-]*[0-9०-९]", re.I)
_A_LOC = re.compile(r"(?:Mohalla|Mohallah|Mohalla|Muhalla|Ward|Sector|Colony|Gali|Lane|Street|Block|Basti|"
                    r"मोहल्ला|मुहल्ला|वार्ड|गली|सेक्टर|कॉलोनी|बस्ती)(?![A-Za-z])", re.I)
_A_LOC_TAIL = re.compile(r"(?:Nagar|Colony|Basti|Bazar|Bazaar|Marg|Road|Chowk|Enclave|Puram|Vihar|Mohalla|Tola|"
                         r"नगर|कॉलोनी|बस्ती|बाजार|बाज़ार|मार्ग|रोड|चौक|विहार|टोला)\s*$", re.I)
_A_LAND = re.compile(r"(?:near|nr\.?|opp\.?|opposite|behind|beside|next\s+to|in\s+front\s+of|close\s+to)(?![A-Za-z])", re.I)
_A_LAND_TAIL = re.compile(r"के\s+(?:पास|पीछे|सामने|निकट|बगल)\s*$|(?:के\s+)?नज़दीक\s*$")
_A_VILL = re.compile(r"(?:Vill(?:age)?\.?|Gram|Gaon|Gaanv|Gaun|ग्राम|गांव|गाँव|ग्रा\.)[ \t]*[:.\-]?[ \t]*", re.I)
_A_TEH = re.compile(r"(?:Tehsil|Tahsil|Teh\.|Taluka|तहसील)[ \t]*[:.\-]?[ \t]*", re.I)
_A_DIST = re.compile(r"(?:Distt\.?|Dist\.?|District|Jila|Zila|जिला|ज़िला|जनपद)[ \t]*[:.\-]?[ \t]*", re.I)
_A_POST = re.compile(r"(?:P\.?\s*O\.?|Post|Thana|PS|डाक|पोस्ट|थाना)(?![A-Za-z])[ \t]*[:.\-]?[ \t]*", re.I)
_A_KIN = re.compile(r"(?:[CSDWH])[ \t]*/[ \t]*[Oo]\.?[ \t]*:?[ \t]*")
_A_PIN_TAIL = re.compile(r"[ \t]*[\-–][ \t]*([1-9][0-9]{5}|[१-९][०-९]{5})[ \t]*$")
_PIN_ONLY = re.compile(r"(?:pin(?:code)?\s*[:\-]?\s*)?([1-9][0-9]{5}|[१-९][०-९]{5})$", re.I)


def _clean(s: str) -> str:
    return s.strip(" \t.;:-–")


def _strip_span(text: str, s: int, e: int) -> Tuple[int, int]:
    while s < e and text[s] in " \t\r,;:-–.":
        s += 1
    while e > s and text[e - 1] in " \t\r,;:-–":
        e -= 1
    return s, e


def _addr_part_kind(part: str) -> str:
    if _A_KIN.match(part):
        return "kin"
    if _A_HOUSE.match(part):
        return "HOUSE"
    if _A_VILL.match(part) and len(part) > 4:
        return "VILLAGE"
    if _A_TEH.match(part):
        return "TEHSIL"
    if _A_DIST.match(part):
        return "DISTRICT"
    if _A_LAND.match(part) or _A_LAND_TAIL.search(part):
        return "LANDMARK"
    if _A_LOC.match(part) or _A_LOC_TAIL.search(part):
        return "LOCALITY"
    if _A_POST.match(part) and len(part) > 4:
        return "ADDRESS"
    if _PIN_ONLY.match(part):
        return "PIN"
    return ""


_PLACE_NAME = re.compile(r"(?:[A-Z][a-z]+|[ऀ-ॿ]+)(?:[ \t]+(?:[A-Z][a-z]+|[ऀ-ॿ]+)){0,2}")


def _is_stopish(part: str) -> bool:
    return all(_low(w) in _STOP for w in part.split())


def _strip_part(text: str, a: int, b: int) -> str:
    a, b = _strip_span(text, a, b)
    return text[a:b] if a < b else ""


def _parse_address(text: str, s: int, e: int, add, strict: bool = False) -> int:
    """Classify comma-separated parts of text[s:e]; returns number of classified parts."""
    parts = []
    i = s
    for m in re.finditer(r"[,;]", text[s:e]):
        parts.append((i, s + m.start()))
        i = s + m.end()
    parts.append((i, e))
    got = 0
    n = len(parts)
    for idx, (ps, pe) in enumerate(parts):
        ps, pe = _strip_span(text, ps, pe)
        if ps >= pe:
            continue
        pm = _A_PIN_TAIL.search(text, ps, pe)
        if pm and pm.end() == pe or (pm and text[pm.end():pe].strip() == ""):
            add(pm.start(1), pm.end(1), "PIN", patterns._digits(pm.group(1)), 1)
            pe = pm.start()
            ps, pe = _strip_span(text, ps, pe)
            if ps >= pe:
                continue
        part = text[ps:pe]
        k = _addr_part_kind(part)
        if k == "kin":
            m = _A_KIN.match(part)
            nm = _take_name(text, ps + m.end(), pe, "any")
            if nm:
                rel = part[:1].upper() + "/O"
                add(nm[0], nm[1], "RELATIVE_NAME", rel, 3)
                got += 1
            rest = text.find(" ", nm[1]) if nm else -1
            continue
        if k in ("VILLAGE", "TEHSIL", "DISTRICT"):
            rx = {"VILLAGE": _A_VILL, "TEHSIL": _A_TEH, "DISTRICT": _A_DIST}[k]
            m = rx.match(part)
            vs, ve = _strip_span(text, ps + m.end(), pe)
            if vs < ve:
                add(vs, ve, k, _clean(text[vs:ve]) if k == "DISTRICT" else "", 3)
                got += 1
            continue
        if k == "PIN":
            m = _PIN_ONLY.match(part)
            add(ps + m.start(1), ps + m.end(1), "PIN", patterns._digits(m.group(1)), 1)
            got += 1
            continue
        if k:
            add(ps, pe, k, "", 3)
            got += 1
            continue
        if strict:
            # an unlabelled name-like part between known address parts and a later district / tehsil /
            # PIN part ("H.No. 12, Pipariya, Distt. Dewas") is the village or locality
            if got and _PLACE_NAME.fullmatch(part) and not _is_stopish(part) and any(
                    _addr_part_kind(_strip_part(text, a, b)) in ("DISTRICT", "TEHSIL", "PIN") or
                    _A_PIN_TAIL.search(text, a, b) for a, b in parts[idx + 1:]):
                add(ps, pe, "VILLAGE", "", 3)
                got += 1
            continue
        if not re.search(r"[A-Za-zऀ-ॿ]", part):
            if re.search(r"[0-9०-९]", part):
                add(ps, pe, "ADDRESS", "", 3)
            continue
        if idx == n - 1 and got and not re.search(r"[0-9०-९]", part):
            add(ps, pe, "DISTRICT", _clean(part), 3)      # trailing town / district name: kept
            continue
        add(ps, pe, "ADDRESS", "", 3)
    return got


# ---------------------------------------------------------------- anchors

_KIN_RE = re.compile(r"(?<![A-Za-z/])([SDWHCFMBsdwhcfmb])[ \t]*/[ \t]*([Oo])(?![A-Za-z/])\.?[ \t]*:?[ \t]*")
_KIN_EN = re.compile(r"(?<![A-Za-z])(son|daughter|wife|husband|father|mother)\s+of\s+", re.I)
_KIN_HI = re.compile(r"(?<![ऀ-ॿ])(" + "|".join(scripts.KIN_WORDS) + r"|पिता|पति|पत्नी|पुत्र|पुत्री|माता)(?:[ \t]*(?:" + "|".join(scripts.POSSESSIVES) + r")[ \t]*नाम)?[ \t]*[:\-]?[ \t]*")
_HON_RE = re.compile(r"(?<![A-Za-zऀ-ॿ])(" + "|".join(sorted(
    (re.escape(w) for w in _HON_AFTER), key=len, reverse=True)) + r")(?![A-Za-zऀ-ॿ])", re.I)
_TITLE_RE = re.compile(
    r"(?<![A-Za-z])(?:Mr|Mrs|Ms|Smt|Shri|Shree|Sri|Km|Kum|Kumari|Miss|Sushri|Late|Janab|Srimati|Shrimati|"
    r"MR|MRS|MS|SMT|SHRI|SRI|KM)\.?[ \t]+"
    r"|(?<![ऀ-ॿ])(?:श्रीमती|श्री|सुश्री|कुमारी|स्वर्गीय|स्व\.|कु\.|"
    + "|".join(sorted((re.escape(w) for w in scripts.TITLES), key=len, reverse=True)) + r")[ \t]*")
_VERB_RE = re.compile(
    r"(?<![A-Za-z])(?:(?:called|raised|witnessed|brought|accompanied|referred|informed|signed|reported|visited|"
    r"received|attended|escorted|collected|verified|registered|requested|consented|consent|given|dropped|"
    r"handed\s+over|submitted|filed|lodged|booked)\s+(?:by|to)|informed|contacted|caller|attendant|attender|"
    r"companion|witness|visitor|guardian|relative|nok|spoke\s+(?:to|with)|met|per)[ \t]*[:(\-]?[ \t]*",
    re.I)
_OF_RE = re.compile(
    r"(?<![A-Za-z])(?:report|note|summary|prescription|slip|card|record|file|receipt|certificate|consent|"
    r"case|details|reports|form)\s+(?:of|for)[ \t]+(?:pt\.?[ \t]+|patient[ \t]+)?", re.I)
_CHAT_RE = re.compile(
    r"^[ \t]*(?:\[[^\]\n]{4,32}\]|[0-9]{1,2}/[0-9]{1,2}/[0-9]{2,4},?[ \t]+[0-9]{1,2}:[0-9]{2}(?:[ \t]*[apAP][mM])?"
    r"[ \t]*-)[ \t]*([^:\n]{1,40}?):", re.M)
_CASE_DEV = re.compile(
    r"(?:^|(?<=[।.!?|]))[ \t]*((?:" + _DEV + r"[ \t]+){0,2}" + _DEV + r")[ \t]+(?:को|की|का|के|ने)(?![ऀ-ॿ])",
    re.M)
_CASE_LAT = re.compile(
    r"(?:^|(?<=[.!?|])|(?<=-[ \t]))[ \t]*((?:[A-Z][a-z]+[ \t]+){0,2}[A-Z][a-z]+)[ \t]+(?:ko|ki|ka|ke|ne)(?![A-Za-z])",
    re.M)
_DOB_RE = re.compile(r"(?<![A-Za-z])(?:DOB|D\.O\.B\.?|Date\s+of\s+Birth|Birth\s*Date|B'?day|Janm\s*Tithi|"
                     r"Janam\s*Tithi|जन्म\s*(?:तिथि|तारीख|दिनांक))[ \t]*[:\-]?[ \t]*", re.I)
_GENDER_RE = re.compile(
    r"(?<![0-9०-९])[0-9०-९]{1,3}[ \t]*(?:Y|Yr|Yrs|Years?|yrs?|years?|वर्ष|साल)?\.?[ \t]*/[ \t]*"
    r"(F|M|Female|Male|FEMALE|MALE|महिला|पुरुष|स्त्री)(?![A-Za-zऀ-ॿ])")
_GENDER_WORD = re.compile(r"(?<![A-Za-zऀ-ॿ])(F|M|Female|Male|female|male|FEMALE|MALE|महिला|पुरुष|स्त्री)"
                          r"(?![A-Za-zऀ-ॿ])")
_ID_TOKEN = re.compile(r"(?<![A-Za-z0-9])[A-Za-z0-9०-९][A-Za-z0-9०-९/\-_.#]*[0-9०-९]")
_WORD_ANY = re.compile(r"[A-Za-z](?:[A-Za-z]|" + _POSS + r")*|" + _DEV)
_ENC_PREFIX = re.compile(r"^(?:IPD|IP|ADM|IN|INP|ADMN|ADMISSION)", re.I)


_THE_BEFORE = re.compile(r"(?<![A-Za-z])the[ \t]+$", re.I)


def _gender(s: str) -> str:
    g = s.lower()
    return "F" if g in ("f", "female", "महिला", "स्त्री") else "M"


# ---------------------------------------------------------------- engine

class _Ctx:
    def __init__(self, text: str):
        self.text = text
        self.cands = []  # type: List[Tuple[int, int, int, str, str]]
        self.enc_starts = set()  # type: Set[int]
        prot = patterns.protected_spans(text)
        self.prot = [(p.start, p.end) for p in prot if p.kind != "ASHA"]
        # "Asha" is also a common first name: an ASHA match only blocks the weak layers
        self.asha = [(p.start, p.end) for p in prot if p.kind == "ASHA"]
        # "ASHA worker", "ASHA didi", "the ASHA": the health worker role, never a person's name
        self.asha_hard = [(a, b) for a, b in self.asha
                          if re.search(r"\s", text[a:b]) or _THE_BEFORE.search(text, max(0, a - 6), a)]
        self.prot_starts = [p[0] for p in self.prot]

    def protected(self, s: int, e: int) -> bool:
        i = bisect.bisect_left(self.prot_starts, e)
        k = i - 1
        while k >= 0:
            ps, pe = self.prot[k]
            if pe > s:
                return True
            if pe <= s and k < i - 4:
                break
            k -= 1
        return False

    def add(self, s: int, e: int, kind: str, value: str = "", prio: int = 5) -> None:
        if s is None or e <= s:
            return
        if kind not in ID_KINDS and kind != "PIN" and self.protected(s, e):
            return
        if prio >= 6 and kind in NAME_KINDS and any(a < e and s < b for a, b in self.asha):
            return
        if kind in NAME_KINDS and any(a < e and s < b for a, b in self.asha_hard):
            return
        self.cands.append((prio, s, e, kind, value))


def _resolve(cands: List[Tuple[int, int, int, str, str]]) -> List[Span]:
    order = sorted(cands, key=lambda c: (c[0], -(c[2] - c[1]), c[1], c[3]))
    taken = []  # type: List[Tuple[int, int]]
    starts = []  # type: List[int]
    out = []  # type: List[Span]
    for prio, s, e, kind, value in order:
        i = bisect.bisect_left(starts, s)
        clash = False
        if i > 0 and taken[i - 1][1] > s:
            clash = True
        if i < len(taken) and taken[i][0] < e:
            clash = True
        if clash:
            continue
        taken.insert(i, (s, e))
        starts.insert(i, s)
        out.append(Span(s, e, kind, value))
    out.sort(key=lambda sp: (sp.start, sp.end))
    return out


def _lines(text: str):
    pos = 0
    for line in text.split("\n"):
        yield pos, line
        pos += len(line) + 1


def _layer_identifiers(cx: _Ctx) -> None:
    t = cx.text
    for sp in patterns.find_identifiers(t):
        cx.add(sp.start, sp.end, sp.kind, sp.value, 0)
    for sp in patterns.find_patient_ids(t):
        cx.add(sp.start, sp.end, "MRN", sp.value, 1)
        if _ENC_PREFIX.match(sp.value):
            cx.enc_starts.add(sp.start)
    for sp in patterns.find_pins(t):
        cx.add(sp.start, sp.end, "PIN", sp.value, 1)


def _name_value(cx: _Ctx, s: int, e: int, kind: str, value: str, prio: int, mode: str = "any") -> Optional[Tuple[int, int]]:
    t = cx.text
    km = _KIN_RE.match(t, s) if s < e else None
    if km and km.end() <= e:
        nm = _take_name(t, km.end(), e, mode)
        if nm:
            cx.add(nm[0], nm[1], "RELATIVE_NAME", km.group(1).upper() + "/o", prio)
        return nm
    nm = _take_name(t, s, e, mode, max_tok=5)
    if nm:
        cx.add(nm[0], nm[1], kind, value, prio)
    return nm


def _layer_labels(cx: _Ctx) -> None:
    t = cx.text
    for ls, line in _lines(t):
        if ":" not in line and "：" not in line:
            continue
        bounds = [0]
        for m in _SEG_SPLIT.finditer(line):
            bounds.append(m.end())
        bounds.append(len(line) + 1)
        for bi in range(len(bounds) - 1):
            ss = bounds[bi]
            se = min(bounds[bi + 1], len(line))
            m = _LABEL_RE.match(line, ss)
            if not m or m.end() > se:
                continue
            label = m.group(1)
            cls = _classify_label(label)
            vs = ls + m.end()
            ve = ls + se
            # a value that runs into the next segment's label is cut at a sub-label
            sub = re.search(r"[ \t]([A-Za-zऀ-ॿ][A-Za-zऀ-ॿ.'’/ ]{0,20}?)[ \t]*[:：]", t[vs:ve])
            if sub and _classify_label(sub.group(1)) not in ("", "clinical"):
                ve = vs + sub.start()
            _apply_label(cx, cls, label, vs, ve)


def _apply_label(cx: _Ctx, cls: str, label: str, vs: int, ve: int) -> None:
    t = cx.text
    if vs >= ve or not cls or cls == "clinical":
        return
    if cls == "name":
        _name_value(cx, vs, ve, "PATIENT_NAME", "", 2)
    elif cls == "relative":
        ws = _lw(label)
        rel = ""
        for w in ws:
            if w not in ("name", "naam", "nam", "का", "की", "नाम", "of", "s", "ka", "ki"):
                rel = w
                break
        rel = {"father": "Father", "husband": "Husband", "guardian": "Guardian"}.get(rel, rel)
        orig = re.search(r"[A-Za-zऀ-ॿ/]+", label)
        if orig and _nfc(orig.group().lower()) == rel:
            rel = orig.group()
        _name_value(cx, vs, ve, "RELATIVE_NAME", rel, 2)
    elif cls == "attendant":
        if "(" in label and _classify_label(label.split("(")[0]) == "address":
            _parse_address(t, vs, ve, cx.add)
            return
        _name_value(cx, vs, ve, "PERSON", "", 2)
    elif cls == "address":
        _parse_address(t, vs, ve, cx.add)
    elif cls == "village":
        s, e = _strip_span(t, vs, ve)
        e2 = t.find(",", s, e)
        if e2 > 0:
            e = e2
        s, e = _strip_span(t, s, e)
        if re.search(r"[A-Za-zऀ-ॿ]", t[s:e]):
            cx.add(s, e, "VILLAGE", "", 2)
    elif cls == "tehsil":
        s, e = _strip_span(t, vs, ve)
        if re.search(r"[A-Za-zऀ-ॿ]", t[s:e]):
            cx.add(s, e, "TEHSIL", "", 2)
    elif cls == "district":
        s, e = _strip_span(t, vs, ve)
        if re.search(r"[A-Za-zऀ-ॿ]", t[s:e]):
            cx.add(s, e, "DISTRICT", _clean(t[s:e]), 2)
    elif cls == "pin":
        m = re.search(r"[1-9१-९][0-9०-९]{5}(?![0-9०-९])", t[vs:ve])
        if m:
            cx.add(vs + m.start(), vs + m.end(), "PIN", patterns._digits(m.group()), 1)
    elif cls in ("uhid", "enc"):
        m = _ID_TOKEN.search(t, vs, ve)
        if m and len(patterns._digits(m.group())) >= 3:
            v = patterns.norm_id(m.group())
            cx.add(m.start(), m.end(), "MRN", v, 1)
            if cls == "enc":
                cx.enc_starts.add(m.start())
    elif cls == "phone":
        # a name in a phone field: "Contact: Ramesh 98...", or "Emergency contact (Name)"
        nm = _take_name(t, vs, ve, "cap")
        if nm:
            cx.add(nm[0], nm[1], "PERSON", "", 4)
    elif cls == "age":
        m = _GENDER_WORD.search(t, vs, ve)
        if m and re.search(r"sex|gender|ling|लिंग|/", label.lower() + t[vs:ve]):
            cx.add(m.start(1), m.end(1), "GENDER", _gender(m.group(1)), 3)


def _layer_dob(cx: _Ctx, order: str) -> None:
    t = cx.text
    for m in _DOB_RE.finditer(t):
        hits = dates.find_dates(t[m.end():m.end() + 40], order)
        if hits and hits[0].start == 0:
            h = hits[0]
            cx.add(m.end() + h.start, m.end() + h.end, "DOB", h.date.isoformat(), 2)


_PN = r"((?:[A-Z][a-z]+[ \t]+){0,2}[A-Z][a-z]+)"
_PND = r"((?:[ऀ-ॿ]+[ \t]+){0,2}[ऀ-ॿ]+)"
_PLACE_PHRASES = [
    # "ghar Khajuri Kalan mein hai", "ghar Bichhiya me", "ghar Raipura pe"
    re.compile(r"(?<![A-Za-z])(?:ghar|gaon|gaanv|mohalla|basti)[ \t]+" + _PN + r"[ \t]+(?:mein|me|main|mai|par|pe|ka|ki|ke|se)(?![A-Za-z])", re.I),
    # "Barkhera gaon", "Kanwas village", "Raipura mohalla"
    re.compile(_PN + r"[ \t]+(?:gaon|gaanv|gaun|village|mohalla|basti|colony|nagar)(?![A-Za-z])"),
    # "resident of Kanwas", "r/o Raipura", "from village Raipura", "nivasi Pipariya"
    re.compile(r"(?<![A-Za-z])(?:resident[ \t]+of|residing[ \t]+at|r/o|R/O|from[ \t]+village|native[ \t]+of|nivasi|niwasi|"
               r"village|vill\.)[ \t]*:?[ \t]*" + _PN, re.I),
    # Hindi: "खजूरी कलां गांव में", "घर बिछिया में"
    re.compile(r"(?<![ऀ-ॿ])घर[ \t]+" + _PND + r"[ \t]+(?:में|पर)(?![ऀ-ॿ])"),
    re.compile(_PND + r"[ \t]+(?:गांव|गाँव|ग्राम|मोहल्ला)[ \t]+(?:में|का|की|के|से)(?![ऀ-ॿ])"),
]
_ADDR_CONTEXT = re.compile(r"(?i)(?<![a-z])(?:ghar|house|h\.?\s*no|address|addr|village|vill|gaon|gram|mohalla|colony|"
                           r"resident|r/o|nivasi|tehsil|distt|district)(?![a-z])|घर|पता|ग्राम|गांव|गाँव|मोहल्ला")
_LANDMARK_PHRASE = re.compile(r"(?<![A-Za-z])((?:near|behind|opp\.?|opposite|beside|next[ \t]+to|in[ \t]+front[ \t]+of|"
                              r"close[ \t]+to)[ \t]+(?:the[ \t]+)?(?:[A-Z][A-Za-z.]*[ \t]*){1,4}(?:ki|ka|ke)?[ \t]*"
                              r"(?:[A-Z][A-Za-z]*)?)")


_PATH_NAME = re.compile(r"(?:(?<=[\\/])|^)((?:[A-Z][a-z]+[_ ]){1,3})([A-Z]{1,3}[_ ])?([0-9]{5,14})(?=[\\/_.\s\"]|$)", re.M)


def _layer_path_names(cx: _Ctx) -> None:
    """Export folders named after the patient: ".../Girija_NA_010607/visits.json"."""
    t = cx.text
    for m in _PATH_NAME.finditer(t):
        pieces = [p for p in re.split(r"[_ ]", m.group(1)) if p]
        if any(_low(p) in _STOP or _low(p) in patterns._UNDERSCORE_WORDS or _low(p) in _EN_COMMON for p in pieces):
            continue   # "Ward_Register_00123", "Lab_Results_202611": a folder label, not a person
        if len(pieces) == 1 and not m.group(2) and len(m.group(3)) < 6:
            continue
        pos = m.start(1)
        for piece in re.split(r"[_ ]", m.group(1)):
            if piece and _low(piece) not in _GENERIC:
                cx.add(pos, pos + len(piece), "PATIENT_NAME", "", 4)
            pos += len(piece) + 1


def _layer_places(cx: _Ctx) -> None:
    """Villages and landmarks written in sentences rather than address lines."""
    t = cx.text
    for rx in _PLACE_PHRASES:
        for m in rx.finditer(t):
            s, e = m.span(1)
            name = t[s:e]
            if _is_stopish(name) or any(_low(w) in _STOP for w in name.split()[:1]):
                continue
            cx.add(s, e, "VILLAGE", "", 4)
    for m in _LANDMARK_PHRASE.finditer(t):
        ss = max(t.rfind("\n", 0, m.start()) + 1, m.start() - 160)
        if not _ADDR_CONTEXT.search(t, ss, m.start()):
            continue   # "near normal", "behind the eye" in clinical prose stay
        s, e = m.span(1)
        cx.add(s, len(t[:e].rstrip(" \t.,")), "LANDMARK", "", 4)


def _layer_address_lines(cx: _Ctx) -> None:
    t = cx.text
    for ls, line in _lines(t):
        if line.count(",") < 1:
            continue
        cues = 0
        kin = False
        for part in line.split(","):
            k = _addr_part_kind(part.strip(" \t.;:-"))
            if k == "kin":
                kin = True
            elif k and k != "PIN":
                cues += 1
        if cues >= 2 or (kin and cues >= 1):
            # start after any leading label
            m = _LABEL_RE.match(line)
            st = ls + (m.end() if m else 0)
            _parse_address(t, st, ls + len(line), cx.add, strict=True)


def _layer_kinship(cx: _Ctx) -> None:
    t = cx.text
    for m in _KIN_RE.finditer(t):
        letter = m.group(1).upper()
        if letter in "CH" and patterns.is_complaint_of(t, m.start()):
            continue
        le = t.find("\n", m.end())
        le = len(t) if le < 0 else le
        nm = _take_name(t, m.end(), le, "cap")
        if not nm:
            # ALL CAPS guardian "S/O SHYAM PATEL" or lowercase after an explicit marker
            nm = _take_name(t, m.end(), le, "any", max_tok=3)
            if nm and not re.match(r"[A-Zऀ-ॿ]", t[nm[0]]):
                nm = None
        if not nm:
            continue
        cx.add(nm[0], nm[1], "RELATIVE_NAME", letter + "/o", 3)
        if letter != "C" and m.start() > 0 and t[m.start() - 1] != "(":
            bk = _take_name_back(t, m.start(), "cap", 3, allow_comma=True)
            if bk:
                cx.add(bk[0], bk[1], "PATIENT_NAME", "", 4)
    for m in _KIN_EN.finditer(t):
        le = t.find("\n", m.end())
        le = len(t) if le < 0 else le
        nm = _take_name(t, m.end(), le, "cap")
        if nm:
            cx.add(nm[0], nm[1], "RELATIVE_NAME", m.group(1).lower() + " of", 3)
    for m in _KIN_HI.finditer(t):
        le = t.find("\n", m.end())
        le = len(t) if le < 0 else le
        nm = _take_name(t, m.end(), le, "cap", max_tok=3)
        if nm and _is_dev(t[nm[0]]):
            cx.add(nm[0], nm[1], "RELATIVE_NAME", m.group(1), 3)


def _layer_honorifics(cx: _Ctx) -> None:
    t = cx.text
    chat_spans = []
    for m in _CHAT_RE.finditer(t):
        s, e = m.start(1), m.end(1)
        chat_spans.append((s, e))
        hm = None
        for h in _HON_RE.finditer(t, s, e):
            hm = h
        nm = _take_name(t, s, hm.start() if hm else e, "cap")
        if nm:
            if hm and _low(hm.group(1)) in _HON_KIN:
                cx.add(nm[0], nm[1], "RELATIVE_NAME", hm.group(1), 3)
            else:
                cx.add(nm[0], nm[1], "PERSON", "", 3)
    for m in _HON_RE.finditer(t):
        w = m.group(1)
        lw = _low(w)
        if not _is_dev(w) and m.start() > 0 and t[m.start() - 1] not in " \t":
            continue
        bk = _take_name_back(t, m.start(), "cap", 3)
        if not bk and not _is_dev(w) and lw in _HON_NAME_CUE:
            bk = _lower_name_back(t, m.start())
        if not bk:
            continue
        if lw in _HON_KIN and not (lw in _HON_RESPECT and _clinical_after(t, m.end())):
            cx.add(bk[0], bk[1], "RELATIVE_NAME", w, 4)
        else:
            # "Zarina amma ka BP ...": a respectful address word in a clinical sentence is the patient
            cx.add(bk[0], bk[1], "PATIENT_NAME", "", 4)
    for m in _DEVI_RE.finditer(t):
        cx.add(m.start(1), m.end(2), "PERSON", "", 4)
    for m in _TITLE_RE.finditer(t):
        le = t.find("\n", m.end())
        le = len(t) if le < 0 else le
        nm = _take_name(t, m.end(), le, "cap", skip_lead=False)
        if not nm and m.group().strip(" .").isupper():
            nm = _take_name(t, m.end(), le, "any", max_tok=3, skip_lead=False)
            if nm and not t[nm[0]].isupper():
                nm = None
        if nm:
            cx.add(nm[0], nm[1], "PERSON", "", 4)


_HON_RESPECT = _ws("""
amma didi bhai bhaiya bhaiyya sahab saheb ji jee behenji chacha chachi tai dadi nani baba kaka mausi bua
अम्मा दीदी भाई भैया साहब जी बहनजी चाचा चाची ताई दादी नानी बाबा काका मौसी बुआ
""")
# honorifics that follow a (possibly lower-case) given name: "asha ji", "ramesh sahab", "meera didi"
_HON_NAME_CUE = _ws("ji jee sahab saheb sahib didi behenji bhaiya bhaiyya")
_NOT_LOWER_NAME = _ws("""
aap aapki aapke aapka unki unka unke inki inka inke uski uska uske meri mera mere tumhari hamari mata pita
maa maaji papa bhai behen bahan beta beti bahu doctor dr sister nurse patient mareez mariz madam sir sahab
master baba amma didi ji haan nahi theek accha acha bilkul ok okay thank thanks please wife husband
""")
_CLIN_HINT = re.compile(r"[0-9]|\b(?:bp|sugar|pulse|temp|spo2|hb|bukhar|bukhaar|dawa|dawai|dava|khansi|dard|ulti|"
                        r"report|test|ilaj|ilaaj|tablet|injection|check|checkup|dose)\b", re.I)
_SENT_END = re.compile(r"[.!?।\n]")
_DEVI_RE = re.compile(r"(?<![ऀ-ॿ])(" + _DEV + r")[ \t]+(देवी|बाई|बेगम)(?![ऀ-ॿ])")


def _clinical_after(t: str, pos: int) -> bool:
    """The rest of the sentence after `pos` talks about the person's own health."""
    m = _SENT_END.search(t, pos)
    seg = t[pos:m.start() if m else len(t)][:80]
    if _CLIN_HINT.search(seg):
        return True
    return any(w.lower() in lexicon.CLINICAL_WORDS or w.lower() in lexicon.COMPLAINT_WORDS
               for w in re.findall(r"[A-Za-z]+", seg))


def _lower_name_back(t: str, pos: int) -> Optional[Tuple[int, int]]:
    """A single lower-case Latin word right before a name honorific ("asha ji")."""
    m = re.search(r"(?<![A-Za-z'’\-])([a-z]{3,})[ \t]+$", t[max(0, pos - 30):pos])
    if not m:
        return None
    w = m.group(1)
    if w in _STOP or w in _NOT_LOWER_NAME or w in lexicon.HINDI_COMMON_WORDS or w in lexicon.CLINICAL_WORDS:
        return None
    s = max(0, pos - 30) + m.start(1)
    return s, s + len(w)


def _layer_verbs(cx: _Ctx) -> None:
    t = cx.text
    for rx, kind in ((_VERB_RE, "PERSON"), (_OF_RE, "PATIENT_NAME")):
        for m in rx.finditer(t):
            le = t.find("\n", m.end())
            le = len(t) if le < 0 else le
            if re.match(r"(?:Dr|DR|dr|Doctor|डॉ)\b", t[m.end():m.end() + 8]):
                continue
            nm = _take_name(t, m.end(), le, "cap")
            if nm:
                cx.add(nm[0], nm[1], kind, "", 5)


def _layer_phone_proximity(cx: _Ctx) -> None:
    t = cx.text
    phones = sorted((c[1], c[2]) for c in cx.cands if c[3] == "PHONE")
    for ps, pe in phones:
        ls = t.rfind("\n", 0, ps) + 1
        ws = max(ls, ps - 90)
        toks = list(_WORD_ANY.finditer(t, ws, ps))[-9:]
        # candidate runs of capitalised name tokens, nearest to the phone first
        k = len(toks) - 1
        while k >= 0:
            m = toks[k]
            if not _is_name_tok(m.group(), "cap"):
                k -= 1
                continue
            e = m.end()
            s = m.start()
            n = 1
            j = k - 1
            while j >= 0 and n < 4:
                g = t[toks[j].end():s]
                if not re.fullmatch(r"\.?[ \t]", g) or not (_is_name_tok(toks[j].group(), "cap")
                                                           or _low(toks[j].group()) in _GENERIC):
                    break
                s = toks[j].start()
                n += 1
                j -= 1
            if n >= 2:
                cx.add(s, e, "PERSON", "", 7)
                break
            k = j


def _layer_dev_case(cx: _Ctx) -> None:
    t = cx.text
    for rx in (_CASE_DEV, _CASE_LAT):
        for m in rx.finditer(t):
            s, e = m.start(1), m.end(1)
            words = _WORD_ANY.findall(t[s:e])
            if not words or any(_low(w) in _STOP for w in words):
                # keep the trailing name words only
                good = []
                for w in reversed(words):
                    if _low(w) in _STOP:
                        break
                    good.append(w)
                if not good:
                    continue
                s = e - len(" ".join(reversed(good)))
                if t[s:e] != " ".join(reversed(good)):
                    continue
                words = list(reversed(good))
            if all(_low(w) in _GENERIC for w in words):
                continue
            cx.add(s, e, "PATIENT_NAME", "", 5)


_JOIN_AFTER = re.compile(r"_([A-Z][a-z]{2,})(?![A-Za-z])")
_JOIN_BEFORE = re.compile(r"(?<![A-Za-z])([A-Z][a-z]{2,})_$")


def _layer_known(cx: _Ctx, known: Known) -> None:
    t = cx.text
    own = sorted(k for k in known.own_keys if k and k not in _GENERIC_KEYS)
    own_set = frozenset(own)
    full = {}  # type: Dict[int, Set[Tuple[str, ...]]]
    for fn in known.full_names:
        ks = tuple(sorted(k for k in fn if k))
        if len(ks) >= 2:
            full.setdefault(len(ks), set()).add(ks)
    words = [(m.start(), m.end(), m.group()) for m in _WORD_ANY.finditer(t)]
    keys = []
    for s, e, w in words:
        toks = name_tokens(w)
        keys.append(name_key(toks[0]) if len(toks) == 1 else "")
    if own:
        for (s, e, w), k in zip(words, keys):
            if not k or k in _GENERIC_KEYS:
                continue
            if k in own_set or (len(k) >= 4 and any(_fuzzy_keys(k, o) for o in own)):
                cx.add(s, e, "PATIENT_NAME", "", 6)
                # "<Given>_<Surname>_<number>" export folder: the joined capitalised word is the surname
                for nm in (_JOIN_AFTER.match(t, e), _JOIN_BEFORE.search(t, max(0, s - 30), s)):
                    if nm and _is_name_tok(nm.group(1), "cap"):
                        cx.add(nm.start(1), nm.end(1), "PATIENT_NAME", "", 6)
    if full:
        n = len(words)
        for L in sorted(full):
            for i in range(0, n - L + 1):
                ok = True
                for j in range(i, i + L - 1):
                    if not re.fullmatch(r"\.?[ \t]+", t[words[j][1]:words[j + 1][0]]):
                        ok = False
                        break
                if not ok:
                    continue
                ks = tuple(sorted(keys[i:i + L]))
                if "" in ks:
                    continue
                if ks in full[L]:
                    cx.add(words[i][0], words[i + L - 1][1], "PERSON", "", 6)
    if known.id_values:
        for m in _ID_TOKEN.finditer(t):
            g = m.group()
            nid = patterns.norm_id(g)
            dg = patterns._digits(g)
            if nid in known.id_values or (len(dg) >= 5 and dg in known.id_values):
                cx.add(m.start(), m.end(), "MRN", nid, 1)


_HEADER_LINE = re.compile(r"(?<![A-Za-z])(?:" + "|".join(sorted(_HEADER_WORDS, key=len, reverse=True)) + r")(?![A-Za-z])",
                          re.I)
_PLACE_BEFORE = re.compile(r"(?:Distt|Dist|District|Tehsil|Tahsil|Jila|Zila|in|at|from|to|City|State)\.?[ \t]*$", re.I)
_CAP_TOK = re.compile(r"[A-Z](?:[A-Za-z]|" + _POSS + r")*\.?")


def _layer_unknown_pairs(cx: _Ctx) -> None:
    t = cx.text
    for ls, line in _lines(t):
        if not line.strip() or _HEADER_LINE.search(line):
            continue
        toks = [(ls + m.start(), ls + m.end(), m.group()) for m in _WORD_ANY.finditer(line)]
        run = []  # type: List[Tuple[int, int, str]]

        def flush():
            if len(run) >= 2:
                s, e = run[0][0], run[-1][1]
                real = [w for _, _, w in run if _low(w) not in _GENERIC]
                nxt = re.match(r"[ \t]*([A-Za-z]+)", t[e:e + 30])
                allcaps = all(w.isupper() and len(w) > 1 for _, _, w in run)
                if (real and not re.match(r"[ \t]*[:：]", t[e:e + 3])
                        and not _PLACE_BEFORE.search(t[ls:s])
                        and not (nxt and _low(nxt.group(1)) in _ORG_TAIL)
                        and (not allcaps or _name_context(t, ls, s))):
                    cx.add(s, e, "PERSON", "", 9)
            del run[:]

        prev_end = None
        for s, e, w in toks:
            ok = (not _is_dev(w) and w[0].isupper() and (_is_name_tok(w, "cap") or _low(w) in _GENERIC))
            if ok and run and not re.fullmatch(r"\.?[ \t]", t[prev_end:s]):
                flush()
            if ok:
                run.append((s, e, w))
            else:
                flush()
            prev_end = e
        flush()


def _name_context(t: str, ls: int, s: int) -> bool:
    before = t[ls:s]
    return bool(re.search(r"(?:name|naam|नाम|patient|[sdwhc]/o)[^:\n]{0,12}[:\-]?[ \t]*$", before, re.I))


def _layer_self_propagate(cx: _Ctx, spans: List[Span]) -> None:
    """Every other whole-word occurrence of a name token found by an anchor."""
    t = cx.text
    keymap = {}  # type: Dict[str, Tuple[str, str]]
    for sp in spans:
        if sp.kind not in NAME_KINDS:
            continue
        for w in _WORD_ANY.findall(t[sp.start:sp.end]):
            lw = _low(w)
            if lw in _STOP or lw in _GENERIC or len(lw) < 3:
                continue
            for tok in name_tokens(w):
                k = name_key(tok)
                if k and k not in _GENERIC_KEYS and len(k) >= 2:
                    prev = keymap.get(k)
                    if prev is None or (prev[0] == "PERSON" and sp.kind != "PERSON"):
                        keymap[k] = (sp.kind, sp.value)
    if not keymap:
        return
    for m in _WORD_ANY.finditer(t):
        w = m.group()
        lw = _low(w)
        if lw in _STOP or lw in _GENERIC:
            continue
        toks = name_tokens(w)
        if len(toks) != 1:
            continue
        k = name_key(toks[0])
        hit = keymap.get(k)
        if hit:
            cx.add(m.start(), m.end(), hit[0], hit[1], 10)


def _layer_ages(cx: _Ctx) -> None:
    t = cx.text
    for s, e, age in dates.find_ages(t):
        if not cx.protected(s, e):
            cx.add(s, e, "AGE", str(age), 3)
    for m in _GENDER_RE.finditer(t):
        cx.add(m.start(1), m.end(1), "GENDER", _gender(m.group(1)), 3)


def _reclassify(spans: List[Span], text: str) -> List[Span]:
    """PERSON spans that are the patient or a relative named elsewhere take that kind."""
    pat = set()  # type: Set[str]
    rel = {}  # type: Dict[str, str]
    for sp in spans:
        if sp.kind in ("PATIENT_NAME", "RELATIVE_NAME"):
            for tok in name_tokens(text[sp.start:sp.end]):
                k = name_key(tok)
                if k and k not in _GENERIC_KEYS:
                    if sp.kind == "PATIENT_NAME":
                        pat.add(k)
                    else:
                        rel.setdefault(k, sp.value)
    out = []
    for sp in spans:
        if sp.kind == "PERSON":
            ks = [name_key(x) for x in name_tokens(text[sp.start:sp.end])]
            ks = [k for k in ks if k and k not in _GENERIC_KEYS]
            if ks and all(k in rel for k in ks):
                sp = Span(sp.start, sp.end, "RELATIVE_NAME", rel[ks[0]])
            elif ks and all(k in pat for k in ks):
                sp = Span(sp.start, sp.end, "PATIENT_NAME", "")
        out.append(sp)
    return out


_GEN_LEFT = re.compile(r"(?:^|(?<=[^A-Za-zऀ-ॿ]))([A-Za-z]+|[ऀ-ॣॱ-ॿ]+)(\.?[ \t])$")
_GEN_RIGHT = re.compile(r"[ \t]([A-Za-z]+|[ऀ-ॣॱ-ॿ]+)(?![A-Za-zऀ-ॿ])")


def _generic_word(w: str) -> bool:
    return _low(w) in _GENERIC and (w[0].isupper() or _is_dev(w))


def _extend_generic(cx: _Ctx, spans: List[Span]) -> List[Span]:
    """Grow name spans over a neighbouring generic part (Mohd. X, X Bano, X Kaur)."""
    t = cx.text
    out = []  # type: List[Span]
    for idx, sp in enumerate(spans):
        if sp.kind in NAME_KINDS:
            lo = out[-1].end if out else 0
            hi = spans[idx + 1].start if idx + 1 < len(spans) else len(t)
            s, e = sp.start, sp.end
            m = _GEN_LEFT.search(t, max(lo, s - 12), s)
            if m and _generic_word(m.group(1)) and not cx.protected(m.start(1), s):
                s = m.start(1)
            m = _GEN_RIGHT.match(t, e)
            if m and m.end() <= hi and _generic_word(m.group(1)) and not cx.protected(e, m.end()):
                e = m.end()
            sp = Span(s, e, sp.kind, sp.value)
        out.append(sp)
    return out


def _run(text: str, known: Optional[Known], order: str) -> Tuple[List[Span], Set[int]]:
    if not text:
        return [], set()
    text = scripts.fold(text)  # 11 scripts -> Devanagari/Latin; same length, so spans index the original
    cx = _Ctx(text)
    _layer_identifiers(cx)
    _layer_labels(cx)
    _layer_dob(cx, order)
    _layer_address_lines(cx)
    _layer_places(cx)
    _layer_path_names(cx)
    _layer_kinship(cx)
    _layer_honorifics(cx)
    _layer_verbs(cx)
    _layer_dev_case(cx)
    if known is not None:
        _layer_known(cx, known)
    _layer_phone_proximity(cx)
    _layer_unknown_pairs(cx)
    _layer_ages(cx)
    first = _resolve(cx.cands)
    _layer_self_propagate(cx, first)
    spans = _extend_generic(cx, _reclassify(_resolve(cx.cands), text))
    return spans, cx.enc_starts


def detect(text: str, known: Optional[Known] = None, order: str = "dmy") -> List[Span]:
    """Non-overlapping identity spans of `text`, sorted by start."""
    return _run(text, known, order)[0]


# ---------------------------------------------------------------- facts

_ID_PREFIX = {"PHONE": "phone", "AADHAAR": "aadhaar", "AADHAAR_MASKED": "aadhaar", "ABHA_NUMBER": "abha",
              "ABHA_ADDRESS": "abhaaddr", "EMAIL": "email", "PAN": "pan", "INSURANCE_ID": "ins"}


def text_facts(text: str, order: str = "dmy") -> Facts:
    spans, enc = _run(text, None, order)
    f = Facts()
    seen_names = set()  # type: Set[str]
    seen_rel = set()  # type: Set[Tuple[str, str]]
    dob_spans = []
    for sp in spans:
        surf = text[sp.start:sp.end]
        k = sp.kind
        if k == "PATIENT_NAME":
            key = " ".join(name_tokens(surf))
            if key and key not in seen_names:
                seen_names.add(key)
                f.names.append(surf)
        elif k == "RELATIVE_NAME":
            key2 = (sp.value, " ".join(name_tokens(surf)))
            if key2[1] and key2 not in seen_rel:
                seen_rel.add(key2)
                f.relatives.append((sp.value, surf))
        elif k in _ID_PREFIX:
            if k == "AADHAAR_MASKED":
                continue
            tok = _ID_PREFIX[k] + ":" + sp.value
            if tok not in f.ids:
                f.ids.append(tok)
            if surf not in f.raw_ids:
                f.raw_ids.append(surf)
        elif k == "MRN":
            pref = "enc" if (sp.start in enc or _ENC_PREFIX.match(sp.value)) else "uhid"
            tok = pref + ":" + sp.value
            if tok not in f.ids:
                f.ids.append(tok)
            if surf not in f.raw_ids:
                f.raw_ids.append(surf)
        elif k == "DOB":
            d = dates.parse_one(surf, order)
            if d is not None and f.dob is None:
                f.dob = d
            dob_spans.append((sp.start, sp.end))
        elif k == "AGE":
            if f.age is None and sp.value.isdigit():
                f.age = int(sp.value)
        elif k == "GENDER":
            if not f.gender:
                f.gender = sp.value
        elif k == "VILLAGE":
            if not f.village:
                f.village = surf
        elif k == "TEHSIL":
            if not f.tehsil:
                f.tehsil = surf
        elif k == "DISTRICT":
            if not f.district:
                f.district = sp.value or surf
        elif k == "PIN":
            if not f.pin:
                f.pin = sp.value
        elif k in ("HOUSE", "LOCALITY", "LANDMARK"):
            if surf not in f.address_parts:
                f.address_parts.append(surf)
    for h in dates.find_dates(text, order):
        if any(s <= h.start < e for s, e in dob_spans):
            continue
        if f.dob is not None and h.date == f.dob:
            continue
        if h.has_year:
            f.ref_date = h.date
            break
    return f
