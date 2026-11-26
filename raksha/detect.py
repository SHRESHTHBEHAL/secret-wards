"""Free-text PII detection for hospital records in English, Devanagari Hindi and Hinglish.

`detect(text, known, order)` returns non-overlapping, sorted Spans of identity evidence;
`text_facts(text, order)` folds them into a Facts sheet. Pure, deterministic, standard library only.
"""
from __future__ import annotations

import bisect
import functools
import re
import unicodedata
from dataclasses import dataclass
from typing import Any, Dict, FrozenSet, List, Optional, Set, Tuple

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
anm aww mpw chw cho seen reviewed counselled counseled examined assessed
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
    if mode == "cap" and (lw in _ORG_STOP or (w.isupper() and not re.search(r"[AEIOUY]", w)) or w in ("ASHA", "ANM", "AWW")):
        return False                    # facility acronyms (SDH, PHC, GMCH) and ward / device words
    return True


_ORG_STOP = frozenset("""
hospital hospitals clinic nursing home institute college medical centre center lab labs laboratory diagnostics
sdh phc chc uphc dh ps sho mode add ward unit dept department casualty emergency icu micu sicu nicu picu ot
""".split())


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
        initial = (len(w) == 1 and w.isupper() and we + 1 < end and text[we] == "." and text[we + 1] in " \t"
                   and n < max_tok - 1)
        if initial:
            pass
        elif not _is_name_tok(w, mode):
            if lw in _GENERIC and (mode == "any" or w[:1].isupper() or _is_dev(w)):
                pass
            else:
                break
        if first < 0:
            first = j
        last = we
        n += 1
        if lw not in _GENERIC and not initial:
            n_real += 1
        i = we
        if i < end and text[i] == "." and lw in _ABBR | _GENERIC or (i < end and text[i] == "." and len(lw) == 1):
            i += 1
    if first < 0 or n_real == 0:
        return None
    return first, last


def _take_name_back(text: str, pos: int, mode: str = "cap", max_tok: int = 3,
                    allow_comma: bool = False) -> Optional[Tuple[int, int]]:
    # look back at most 256 characters; only when the walk reaches the window's first token (which
    # may be cut) is the whole line re-read, so the result equals the unbounded scan
    lo = max(0, pos - 256)
    nl = text.rfind("\n", lo, pos)
    if nl >= 0 or lo == 0:
        return _take_name_back1(text, nl + 1, pos, mode, max_tok, allow_comma)[0]
    res, hit0 = _take_name_back1(text, lo, pos, mode, max_tok, allow_comma)
    if not hit0:
        return res
    return _take_name_back1(text, text.rfind("\n", 0, pos) + 1, pos, mode, max_tok, allow_comma)[0]


def _take_name_back1(text: str, ls: int, pos: int, mode: str, max_tok: int,
                     allow_comma: bool) -> Tuple[Optional[Tuple[int, int]], bool]:
    seg = text[ls:pos]
    toks = list(_TOK.finditer(seg))
    if not toks:
        return None, True
    cur = len(seg)
    first = -1
    last = -1
    n = 0
    n_real = 0
    hit0 = False
    for k in range(len(toks) - 1, -1, -1):
        m = toks[k]
        if k <= 2:  # the first tokens of a cut window may be split differently
            hit0 = True
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
                return None, hit0
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
        return None, hit0
    return (first, last), hit0


# ---------------------------------------------------------------- labels

_SEG_SPLIT = re.compile(r"[ \t]{2,}|\t|\|")
_LABEL_RE = re.compile(
    r"[ \t]*([A-Za-zऀ-ॿ][A-Za-zऀ-ॿ0-9 .'’/()#&_\-]{0,40}?)[ \t]*[:：](?:[ \t]*[:：])?[ \t]*")


_LABEL_VOCAB = ("patient", "name", "mobile", "phone", "contact", "address", "father", "husband", "mother",
                "guardian", "relative", "village", "district", "gender", "birth", "registration", "aadhaar",
                "aadhar", "email", "attendant", "number")
_OCR_FIX = str.maketrans({"1": "i", "0": "o", "5": "s", "|": "l"})


def _fix_label_word(w: str) -> str:
    """'patinet' -> 'patient', 'nmae' -> 'name', 'pat1ent' -> 'patient', 'narne' -> 'name' (labels only)."""
    if len(w) < 4 or not w.isascii() or w in _LABEL_VOCAB or not re.search(r"[a-z]", w):
        return w
    o = w.translate(_OCR_FIX).replace("rn", "m")
    if o in _LABEL_VOCAB:
        return o
    for v in _LABEL_VOCAB:
        if v[0] == o[0] and abs(len(v) - len(o)) <= 1 and _osa1(o, v):
            return v
    return w


def _osa1(a: str, b: str) -> bool:
    """Optimal string alignment distance <= 1 (one substitution, insertion, deletion or swap)."""
    if a == b:
        return True
    if len(a) == len(b):
        d = [i for i in range(len(a)) if a[i] != b[i]]
        return len(d) == 1 or (len(d) == 2 and d[1] == d[0] + 1 and a[d[0]] == b[d[1]] and a[d[1]] == b[d[0]])
    s, l_ = (a, b) if len(a) < len(b) else (b, a)
    return any(l_[:i] + l_[i + 1:] == s for i in range(len(l_)))


def _lw(label: str) -> List[str]:
    t = _nfc(label.lower())
    t = re.sub(r"(?<![a-z])([sdwhcfmbr])\s*/\s*o(?![a-z])", r" \1/o ", t)
    t = re.sub(r"/(?!o(?![a-z]))", " ", t)
    t = re.sub(r"[^a-z0-9ऀ-ॿ/]+", " ", t)
    return [scripts.alias_label_word(_fix_label_word(w)) for w in t.split()]


def _has(ws: List[str], stems: Tuple[str, ...], exact: Tuple[str, ...] = ()) -> bool:
    for w in ws:
        if w in exact:
            return True
        for s in stems:
            if w.startswith(s):
                return True
    return False


@functools.lru_cache(maxsize=8192)
def _classify_label(label: str) -> str:
    ws = _lw(label)
    if not ws:
        return ""
    j = " ".join(ws)
    if all(w in ("mr", "mrs", "ms", "smt", "shri", "sri", "km", "miss", "master", "baby") for w in ws):
        return "name"                               # "Mr/Mrs:", "Smt.:" as the label itself
    if _has(ws, ("address", "addr", "residen", "पता", "निवास"), ("add", "pata", "r/o", "lives", "stays")):
        return "address"
    if _has(ws, ("dob", "birth", "janm", "जन्म", "d/o/b")) or j.startswith("d o b"):
        return "dob"
    if _has(ws, ("date", "time", "तारीख", "दिनांक", "समय"), ("dt", "dated", "on")):
        return "clinical"
    if _has(ws, ("witness", "गवाह", "साक्षी", "informant", "identified", "brought", "escort"), ("copy",)) and \
            not _has(ws, ("doctor", "consult", "physician", "डॉ", "चिकित्सक"), ("dr",)):
        return "attendant"
    if _has(ws, ("doctor", "consult", "physician", "surgeon", "डॉ", "चिकित्सक"), ("dr", "by")):
        return "clinical"
    if _has(ws, ("father", "husband", "guardian", "mother", "wife", "spouse", "relative", "relation",
                 "पिता", "पति", "पत्नी", "माता", "अभिभावक", "संरक्षक", "kin"),
            ("son", "daughter", "mata", "nok", "pita", "pati", "patni", "s/o", "w/o", "d/o", "c/o", "h/o", "f/o",
             "m/o", "b/o")):
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
                 "benefic", "victim", "client"), ("pt", "nam")):
        return "name"
    return ""


# ---------------------------------------------------------------- address parts

_A_HOUSE = re.compile(
    r"(?:H\.?\s*No\.?|D\.?\s*No\.?|#|Barrack|House(?:\s*No\.?)?|Makan(?:\s*No\.?)?|Flat(?:\s*No\.?)?|Plot(?:\s*No\.?)?|Qtr\.?(?:\s*No\.?)?|"
    r"Door\s*No\.?|मकान(?:\s*(?:नं|नंबर|न)\.?)?|म\.?\s*नं\.?|प्लॉट)\s*[:#\-]?\s*[0-9०-९A-Za-z/\-]*[0-9०-९]", re.I)
_A_LOC = re.compile(r"(?:Mohalla|Mohallah|Mohalla|Muhalla|Ward|Sector|Colony|Gali|Lane|Street|Block|Basti|"
                    r"मोहल्ला|मुहल्ला|वार्ड|गली|सेक्टर|कॉलोनी|बस्ती)(?![A-Za-z])", re.I)
_A_LOC_TAIL = re.compile(r"(?:Nagar|Colony|Basti|Bazar|Bazaar|Marg|Road|Chowk|Enclave|Puram|Vihar|Mohalla|Tola|Leikai|Veng|"
                         r"नगर|कॉलोनी|बस्ती|बाजार|बाज़ार|मार्ग|रोड|चौक|विहार|टोला)\s*$", re.I)
_A_LAND = re.compile(r"(?:near|nr\.?|opp\.?|opposite|behind|beside|next\s+to|in\s+front\s+of|close\s+to)(?![A-Za-z])", re.I)
_A_LAND_TAIL = re.compile(r"के\s+(?:पास|पीछे|सामने|निकट|बगल)\s*$|(?:के\s+)?नज़दीक\s*$")
_A_VILL = re.compile(r"(?:Vill(?:age)?\.?|Gram|Gaon|Gaanv|Gaun|ग्राम|गांव|गाँव|ग्रा\.)[ \t]*[:.\-]?[ \t]*", re.I)
_A_TEH = re.compile(r"(?:Tehsil|Tahsil|Teh\.|Taluka|तहसील)[ \t]*[:.\-]?[ \t]*", re.I)
_A_DIST = re.compile(r"(?:Distt\.?|Dist\.?|District|Jila|Zila|जिला|ज़िला|जनपद)[ \t]*[:.\-]?[ \t]*", re.I)
_A_POST = re.compile(r"(?:P\.?\s*O\.?|Post|डाक|पोस्ट|डाकघर)(?![A-Za-z])[ \t]*[:.\-]?[ \t]*", re.I)
# police station / block / panchayat-level administrative names are kept (not a home address)
_A_PS = re.compile(r"(?:Thana|P\.?S\.?|Police[ \t]+Station|थाना|प्रखंड)(?![A-Za-zऀ-ॿ])[ \t]*[:.\-]?[ \t]*")
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
    if _A_PS.match(part) and len(part) > 4:
        return "PS"
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


_FIELD_GAP = re.compile(r"[ \t]{2,}|\t")
_DIRECTION = frozenset("north south east west central upper lower new old".split())


def is_district(part: str) -> bool:
    """A known district, also with a direction word ("Imphal West", "West Tripura", "Lower Subansiri")."""
    ws = [_nfc(w.lower()) for w in part.split()]
    if not ws or len(ws) > 4:
        return False
    if " ".join(ws) in _DISTRICTS or (len(ws) == 1 and ws[0] in _DISTRICTS):
        return True
    core = [w for w in ws if w not in _DIRECTION]
    return 0 < len(core) < len(ws) and " ".join(core) in _DISTRICTS


def _parse_address(text: str, s: int, e: int, add, strict: bool = False, last_keep: bool = False) -> int:
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
            gap = _FIELD_GAP.search(text, vs, ve)
            if gap:
                ve = gap.start()                  # "Dist <X>      AWC code ...": the next field is not the place
            if vs < ve:
                add(vs, ve, k, _clean(text[vs:ve]) if k == "DISTRICT" else "", 3)
                got += 1
            continue
        if k == "PS":
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
        if strict and idx == n - 1 and got and _PLACE_NAME.fullmatch(part) and not _is_stopish(part):
            add(ps, pe, "DISTRICT", _clean(part), 3)      # "..., Gandhi Colony, Uttara Kannada - 581401"
            continue
        if strict:
            # an unlabelled name-like part between known address parts and a later district / tehsil /
            # PIN part ("H.No. 12, Pipariya, Distt. Dewas") is the village or locality
            if got and _PLACE_NAME.fullmatch(part) and not _is_stopish(part) and any(
                    _addr_part_kind(_strip_part(text, a, b)) in ("DISTRICT", "TEHSIL", "PIN") or
                    _A_PIN_TAIL.search(text, a, b) or re.search(r"(?<![0-9])[1-9][0-9]{5}[ \t]*$", text[a:b])
                    for a, b in parts[idx + 1:]):
                add(ps, pe, "VILLAGE", "", 3)
                got += 1
            continue
        if not re.search(r"[A-Za-zऀ-ॿ]", part):
            if re.search(r"[0-9०-९]", part):
                add(ps, pe, "ADDRESS", "", 3)
            continue
        if is_district(part):
            add(ps, pe, "DISTRICT", _clean(part), 3)
            continue
        if idx == n - 1 and (got or (last_keep and n > 1)) and not re.search(r"[0-9०-९]", part):
            add(ps, pe, "DISTRICT", _clean(part), 3)      # trailing town / district name: kept
            continue
        add(ps, pe, "ADDRESS", "", 3)
    return got


# ---------------------------------------------------------------- anchors

_KIN_RE = re.compile(r"(?<![A-Za-z/])([SDWHCFMBsdwhcfmb])[ \t]*/[ \t]*([Oo])(?![A-Za-z/])\.?[ \t]*:?[ \t]*")
_KIN_EN = re.compile(r"(?<![A-Za-z])(son|daughter|wife|husband|father|mother)\s+of\s+", re.I)
_KIN_HI = re.compile(r"(?<![ऀ-ॿ])(" + "|".join(scripts.KIN_WORDS) + r"|पिता|पति|पत्नी|पुत्र|पुत्री|माता|बेटा|बेटी|बहन|ससुर|सास|"
                     r"देवर|ननद|चाचा|चाची|मामा|मामी|बहू|दामाद|भाभी|जेठ|भतीजा|भतीजी|पोता|पोती|नाती|नातिन)(?:[ \t]*(?:" + "|".join(scripts.POSSESSIVES) + r")[ \t]*नाम)?[ \t]*[:\-]?[ \t]*")
_HON_RE = re.compile(r"(?<![A-Za-zऀ-ॿ])(" + "|".join(sorted(
    (re.escape(w) for w in _HON_AFTER), key=len, reverse=True)) + r")(?![A-Za-zऀ-ॿ])", re.I)
_TITLE_RE = re.compile(
    r"(?<![A-Za-z])(?:Mr|Mrs|Ms|Smt|Shri|Shree|Sri|Km|Kum|Kumari|Miss|Sushri|Late|Janab|Srimati|Shrimati|"
    r"MR|MRS|MS|SMT|SHRI|SRI|KM)\.?[ \t]+|(?<![A-Za-z])(?:Pu|Pi|Hav|Const|Sub|Nk|Sep|Insp|SI|ASI)\.?[ \t]+(?=[A-Z][a-z])"
    r"|(?<![ऀ-ॿ])(?:श्रीमती|श्री|सुश्री|कुमारी|स्वर्गीय|स्व\.|कु\.|"
    + "|".join(sorted((re.escape(w) for w in scripts.TITLES), key=len, reverse=True)) + r")[ \t]*")
_VERB_RE = re.compile(
    r"(?<![A-Za-z])(?:(?:called|raised|witnessed|brought|accompanied|referred|informed|signed|reported|visited|"
    r"received|attended|escorted|collected|verified|registered|requested|consented|consent|given|dropped|"
    r"handed\s+over|submitted|filed|lodged|booked|couriered|forwarded|identified|handed)\s+(?:by|to)|informed|contacted|caller|attendant|attender|"
    r"companion|witness|visitor|guardian|relative|nok|spoke\s+(?:to|with)|met|per)[ \t]*[:(\-]?[ \t]*",
    re.I)
_OF_RE = re.compile(
    r"(?<![A-Za-z])(?:report|note|summary|prescription|slip|card|record|file|receipt|certificate|consent|"
    r"case|details|reports|form)\s+(?:of|for)[ \t]+(?:pt\.?[ \t]+|patient[ \t]+)?", re.I)
_CHAT_RE = re.compile(
    r"^[ \t]*(?:\[[^\]\n]{4,32}\]|[0-9]{1,2}/[0-9]{1,2}/[0-9]{2,4},?[ \t]+[0-9]{1,2}:[0-9]{2}(?:[ \t]*[apAP][mM])?"
    r"[ \t]*-)[ \t]*([^:\n]{1,40}?):", re.M)
_CHAT_TILDE = re.compile(r"[ \t]*~[ \t]*([^:\n~]{1,40}?):")
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
        self.asha_iv = patterns.Intervals(self.asha)
        self.asha_hard_iv = patterns.Intervals(self.asha_hard)
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
        if prio >= 6 and kind in NAME_KINDS and self.asha_iv.hits(s, e):
            return
        if kind in NAME_KINDS and self.asha_hard_iv.hits(s, e):
            return
        if kind in NAME_KINDS and prio >= 4 and _ORG_NEXT.match(self.text, e):
            return                                  # "<X> SDH", "<X> Path Lab", "<X> Hospital": an institution
        self.cands.append((prio, s, e, kind, value))


_ORG_NEXT = re.compile(r"[ \t]*(?:(?:Path(?:ology)?|Diagnostic|Medical|Memorial|Charitable|General|Civil|District|"
                       r"Seva|Nursing)[ \t]+)?(?:Hospital|Hosp\.?|Clinic|Lab|Labs|Laboratory|Laboratories|Diagnostics|"
                       r"SDH|PHC|CHC|UPHC|CHC|Ward|Nursing[ \t]+Home|Medical[ \t]+College|Institute|Trust|Foundation|"
                       r"Yojana|अस्पताल|सीएचसी|पीएचसी|योजना)(?![A-Za-z])")


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


_SLASH_AGE = re.compile(r"[ \t]*[0-9]{1,3}[ \t]*(?:[YyMmDd][ \t]*)?[MFmf][ \t]*$|[ \t]*[MFmf][ \t]*/?[ \t]*[0-9]{1,3}[ \t]*[Yy]?[ \t]*$")
_SLASH_KEEP = re.compile(r"[ \t]*(?:OT|Bed|BED|Ward|Dr|DR|Unit|Rm|Room)(?![a-z])")


def _layer_slash_header(cx: _Ctx) -> None:
    """'<Name>/62F/<hospital id>/OT-4/Dr. X': a line of >= 4 slash fields, one an age-sex shape."""
    t = cx.text
    for ls, line in _lines(t):
        if line.count("/") < 3 or len(line) > 160:
            continue
        fields = line.split("/")
        k = next((i for i, f in enumerate(fields) if _SLASH_AGE.fullmatch(f) and i > 0), -1)
        if k < 0:
            continue
        off = [ls]
        for f in fields:
            off.append(off[-1] + len(f) + 1)
        a, b = _strip_span(t, off[k - 1], off[k - 1] + len(fields[k - 1]))
        nm = _take_name_back(t, b, "any", 4) if a < b else None
        if nm and nm[0] >= a:
            cx.add(nm[0], nm[1], "PATIENT_NAME", "", 2)
        if k + 1 < len(fields) and not _SLASH_KEEP.match(fields[k + 1]):
            c, d = _strip_span(t, off[k + 1], off[k + 1] + len(fields[k + 1]))
            if c < d and re.search(r"[0-9]", t[c:d]) and re.fullmatch(r"[A-Za-z0-9\-]{4,24}", t[c:d]):
                cx.add(c, d, "MRN", patterns.norm_id(t[c:d]), 0)


# patient-id labels in prose (any script); the id may mix Devanagari letters and digits ("<abbr>/२६/०७७१२")
_PID_LABEL = re.compile(
    r"(?<![A-Za-zऀ-ॿ])(?:UHID|MRD|MRN|CR[ \t]*No|IP[ \t]*No|IPD[ \t]*No|OPD[ \t]*No|Regn|Reg\.?[ \t]*No|Registration[ \t]*No|"
    r"Casualty[ \t]*No|Admission[ \t]*No|MCP[ \t]*card(?:[ \t]*no)?|"
    r"भर्ती[ \t]*(?:संख्या|क्रमांक|सं\.?|नं\.?)|पंजीयन[ \t]*(?:क्रमांक|संख्या|सं\.?)|पंजीकरण[ \t]*(?:क्रमांक|संख्या|सं\.?)|"
    r"नोंदणी[ \t]*(?:क्र\.?|क्रमांक)|ओपीडी[ \t]*(?:सं\.?|संख्या|क्रमांक|नं\.?)|आईपीडी[ \t]*(?:सं\.?|संख्या|क्रमांक)?|यूएचआईडी)"
    r"(?:[ \t]*(?:No\.?|is|->|[:.\-–=#]))*[ \t]*", re.I)
_PID_VALUE = re.compile(r"[A-Za-z0-9०-९ऀ-ॿ][A-Za-z0-9०-९ऀ-ॣॱ-ॿ/\-]*[0-9०-९]")


def _layer_pid_labels(cx: _Ctx) -> None:
    t = cx.text
    for m in _PID_LABEL.finditer(t):
        v = _PID_VALUE.match(t, m.end())
        if not v:
            continue
        g = v.group()
        if len(re.sub(r"[^0-9०-९]", "", g)) < 3 or not re.search(r"[0-9०-९]", g):
            continue
        cx.add(v.start(), v.end(), "MRN", patterns.norm_id(g), 1)


_REF_SHAPED = re.compile(r"(?<![A-Za-z0-9/#\-])[A-Z]{2,6}(?:[/#\-][0-9]{2,4})?[/#\-][0-9]{5,10}(?![A-Za-z0-9/\-])")


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
    # Hospital-shaped codes that the patient-id rules vetoed as reference numbers ("ref no NMC/25/137211"):
    # they may well be the patient's number, so they are redacted, but never used to link records.
    taken = sorted((c[1], c[2]) for c in cx.cands)
    t_starts = [a for a, _ in taken]
    t_maxend = []
    hi = -1
    for _, b in taken:
        hi = b if b > hi else hi
        t_maxend.append(hi)
    for m in _REF_SHAPED.finditer(t):
        k = bisect.bisect_left(t_starts, m.end())
        if not (k and t_maxend[k - 1] > m.start()) and not _document_ref(t, m.start(), m.group()):
            cx.add(m.start(), m.end(), "REF_ID", "", 7)


def _document_ref(t: str, s: int, tok: str) -> bool:
    """A claim / bill / lab / certificate / lot number named as such (label just before on the line,
    or a document prefix like LOT- / CLM-) is a reference value to keep; only a bare 'ref no' code,
    which may be the patient's own number, is redacted."""
    if re.match(r"[A-Z]+", tok).group() in patterns._NON_PATIENT_PREFIXES:
        return True
    ls = t.rfind("\n", 0, s) + 1
    seg = t[max(ls, s - 40):s].lower()
    return any(not m.group().startswith("ref") for m in patterns._RE_NON_PATIENT_LABEL.finditer(seg))


_DOSE_AFTER = re.compile(r"[ \t]+[0-9]{1,4}(?:\.[0-9]+)?[ \t]*(?:mg|mcg|ml|iu|units?|µg)?[ \t]*"
                         r"(?:[0-9]-[0-9]|one|two|three|puffs?|tabs?|caps?|bd|od|tds|bid|tid|twice|once|daily|x[ \t]*[0-9])",
                         re.I)


def _name_value(cx: _Ctx, s: int, e: int, kind: str, value: str, prio: int, mode: str = "any") -> Optional[Tuple[int, int]]:
    t = cx.text
    km = _KIN_RE.match(t, s) if s < e else None
    if km and km.end() <= e:
        nm = _take_name(t, km.end(), e, mode)
        if nm:
            cx.add(nm[0], nm[1], "RELATIVE_NAME", km.group(1).upper() + "/o", prio)
        return nm
    nm = _take_name(t, s, e, mode, max_tok=5)
    if nm and _DOSE_AFTER.match(t, nm[1]):
        return None                                 # "Caller: <Brand> 200 two puffs": a drug, not a name
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
            if m.group()[0] in " \t" and (line[m.end():m.end() + 1] in (":", "：") or
                                          line[m.start() - 1:m.start()] in (":", "：")):
                continue                            # OCR spacing around a colon: "Name  :  X"
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


_SPACED_ID = re.compile(r"(?<=[ \t:])[A-Z]{2,5}(?:[ ][0-9]{2,8}){2,4}(?![0-9A-Za-z])")
_LETTER_SPACED = re.compile(r"[ \t]*([A-Z](?: [A-Z]){2,9})(?![A-Za-z])")


_PERSON_COLS = ("name", "relative", "attendant", "address")
_KEEP_COL = re.compile(r"(?i)^(?:bed|sample|ref|range|ref\.?[ \t]*range|test|result|value|unit|day|dx|rx|dose|lab|"
                       r"specimen|accession|slide|block|bp|hr|rr|spo2|rbs|time|date|ward)(?![a-z])")
_CELL_EMPTY = _ws("vacant empty nil na none blank free khali")
_KIN_CELL = _ws("""wife husband son daughter father mother brother sister bro sis bro. w/o s/o d/o h/o f/o m/o c/o
uncle aunt nephew niece grandson granddaughter self guardian bhai behen pati patni beta beti""")


def _cell_names(cx: _Ctx, cs: int, ce: int, kind: str, value: str = "") -> None:
    """Capitalised name runs inside a person-column cell (kin words and phone digits around them)."""
    t = cx.text
    run = []  # type: List[Tuple[int, int]]
    for m in _TOK.finditer(t, cs, ce):
        w = m.group(1)
        lw = _low(w)
        if (w[0].isupper() or _is_dev(w)) and lw not in _KIN_CELL and _is_name_tok(w, "any"):
            run.append((m.start(), m.end()))
            continue
        if run:
            cx.add(run[0][0], run[-1][1], kind, value, 2)
            run = []
    if run:
        cx.add(run[0][0], run[-1][1], kind, value, 2)


def _table_cell(cx: _Ctx, cls: str, cs: int, ce: int) -> None:
    t = cx.text
    cs, ce = _strip_span(t, cs, ce)
    if ce <= cs or not re.search(r"[A-Za-zऀ-ॿ]", t[cs:ce]):
        return
    if cls == "name":
        if _low(t[cs:ce]) in _CELL_EMPTY:
            return
        if re.search(r"[0-9]", t[cs:ce]) or "/" in t[cs:ce]:
            _cell_names(cx, cs, ce, "PATIENT_NAME")    # "name / id": the name part only
        else:
            cx.add(cs, ce, "PATIENT_NAME", "", 2)
    elif cls in ("relative", "attendant"):
        _cell_names(cx, cs, ce, "RELATIVE_NAME" if cls == "relative" else "PERSON")
    elif cls == "address":
        _parse_address(t, cs, ce, cx.add)


def _layer_tables(cx: _Ctx) -> List[Tuple[int, int]]:
    """Tables drawn in text, by pipes or by aligned columns: the header row decides each column.
    Person columns (name, attendant, address) are removed; returns the keep-column cells (bed, sample,
    ref range ...) where id-shaped numbers are values, not identifiers."""
    t = cx.text
    keep = []  # type: List[Tuple[int, int]]
    if "\n" not in t or ("|" not in t and "  " not in t):
        return keep
    lines = list(_lines(t))
    i = 0
    while i < len(lines):
        ls, line = lines[i]
        piped = line.count("|") >= 2
        if piped:
            cells = line.split("|")
        else:
            cells = re.split(r"[ \t]{2,}", line.strip()) if ":" not in line else []
        heads = [c.strip() for c in cells]
        ok = (len([h for h in heads if h]) >= 3 and all(len(h) <= 30 and not re.search(r"[0-9]{3}", h) for h in heads)
              and sum(1 for h in heads if h and re.match(r"[A-Za-zऀ-ॿ]", h)) >= 3)
        classes = [_classify_label(h) if h else "" for h in heads]
        known_h = sum(1 for c, h in zip(classes, heads) if h and (c or _KEEP_COL.match(h)))
        ok = ok and known_h * 3 >= 2 * len([h for h in heads if h])
        if not ok or not any(c in _PERSON_COLS or _KEEP_COL.match(h) for c, h in zip(classes, heads)):
            i += 1
            continue
        if not piped:
            starts = [m.start() for m in re.finditer(r"(?:(?<=^)|(?<=[ \t]{2}))\S", line)]
            if len(starts) != len(heads):
                i += 1
                continue
        j = i + 1
        while j < len(lines):
            rs, row = lines[j]
            if not row.strip():
                break
            if piped:
                if row.count("|") < 2:
                    break
                pos = 0
                for k, cell in enumerate(row.split("|")):
                    if k < len(classes):
                        cs, ce = rs + pos, rs + pos + len(cell)
                        if classes[k] in _PERSON_COLS:
                            _table_cell(cx, classes[k], cs, ce)
                        elif _KEEP_COL.match(heads[k]):
                            keep.append((cs, ce))
                    pos += len(cell) + 1
            else:
                segs = [(m.start(), m.end()) for m in re.finditer(r"\S+(?:[ \t]\S+)*", row)]
                if len(segs) < 2 or ":" in row:
                    break
                for a, b in segs:
                    k = max([q for q, st in enumerate(starts) if st <= a + 2] or [0])
                    if classes[k] in _PERSON_COLS:
                        _table_cell(cx, classes[k], rs + a, rs + b)
                    elif _KEEP_COL.match(heads[k]):
                        keep.append((rs + a, rs + b))
            j += 1
        i = j
    return keep


def _layer_space_labels(cx: _Ctx) -> None:
    """Key / value forms without colons, columns kept apart by 2+ blanks ("Victim     <name>     M / 27")."""
    t = cx.text
    if "  " not in t and "|" not in t:
        return
    for ls, line in _lines(t):
        if ":" in line or ("  " not in line and "|" not in line):
            continue
        if "|" in line:
            segs = [(m.start(), m.end()) for m in re.finditer(r"[^|\s](?:[^|]*[^|\s])?", line)]
        else:
            segs = [(m.start(), m.end()) for m in re.finditer(r"\S+(?:[ \t]\S+)*", line)]
        k = 0
        while k + 1 < len(segs):
            a, b = segs[k]
            lab = line[a:b]
            if (re.match(r"[A-Z][A-Za-z./ ]{1,24}$", lab) and len(lab.split()) <= 3
                    and _classify_label(lab) in _PERSON_COLS):
                _apply_label(cx, _classify_label(lab), lab, ls + segs[k + 1][0], ls + segs[k + 1][1])
                k += 2
                continue
            k += 1


def _apply_label(cx: _Ctx, cls: str, label: str, vs: int, ve: int) -> None:
    t = cx.text
    if vs >= ve or not cls or cls == "clinical":
        return
    if cls == "name":
        ls_m = _LETTER_SPACED.match(t, vs, ve)
        if ls_m:
            cx.add(ls_m.start(1), ls_m.end(1), "PATIENT_NAME", "", 2)
            return
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
        m = _SPACED_ID.match(t, vs, ve)
        if not (m and len(patterns._digits(m.group())) >= 5 and re.search(r"[A-Z]", m.group())
                and " " in m.group()):
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


_PT_ANCHOR = re.compile(r"(?<![A-Za-z])(?:Pt\.?|PT\.?|Patient|PATIENT|patient|pt\.)[ \t]+(?=[A-Z])")


_NOT_NAME_SUFFIX = re.compile(r"(?:ed|ing|tion|sion|ment|ness|ity|ance|ence|ive|ous|ful|less|ics|ism|ally)$", re.I)
_ADMIN_WORDS = frozenset("""details detail education information info history profile summary record records care consent
primary secondary dietary category directory laboratory dispensary inventory mandatory voluntary temporary
counselling counseling stable unstable critical shifted referred discharged admitted transferred expired died reviewed
examined seen complains complained presented known came has was is had status condition id no number name list
""".split())


def _name_shaped(w: str) -> bool:
    return not (w.isupper() and len(w) > 1) and not _NOT_NAME_SUFFIX.search(w) and _low(w) not in _ADMIN_WORDS


_INITIALS_NAME = re.compile(r"((?:[A-Z]\.[ \t]*){1,3}[A-Z][a-z]{2,}(?:[ \t]+[A-Z][a-z]{2,})?)")


_SURNAME_FIRST = re.compile(r"([A-Z][A-Za-z'\-]+|[A-Z]{2,}),[ \t]*([A-Z][A-Za-z'\-]+|[A-Z]{2,})(?![A-Za-z])")


def _layer_surname_first(cx: _Ctx) -> None:
    t = cx.text
    for ls, line in _lines(t):
        m = _LABEL_RE.match(line)
        if not m:
            continue
        cls = _classify_label(m.group(1))
        if cls not in ("name", "relative"):
            continue
        sm = _SURNAME_FIRST.match(line, m.end())
        if sm and not _is_stopish(sm.group(1)) and not _is_stopish(sm.group(2)) and _name_shaped(sm.group(2).title()):
            cx.add(ls + sm.start(), ls + sm.end(), "PATIENT_NAME" if cls == "name" else "RELATIVE_NAME", "", 2)


def _layer_patient_anchor(cx: _Ctx) -> None:
    """"Pt Ravi", "Patient Ravi complains of ...": a capitalised name right after the patient word."""
    t = cx.text
    for m in _PT_ANCHOR.finditer(t):
        im = _INITIALS_NAME.match(t, m.end())
        if im and _name_shaped(im.group(1).split()[-1]) and not _is_stopish(im.group(1).split()[-1]):
            cx.add(im.start(1), im.end(1), "PATIENT_NAME", "", 6)    # "Pt S. Iyer", "Patient K. R. Nair"
            continue
        le = t.find("\n", m.end())
        nm = _take_name(t, m.end(), le if le >= 0 else len(t), "cap", 3)
        if not nm:
            continue
        words = [(w.start() + nm[0], w.end() + nm[0], w.group()) for w in re.finditer(r"\S+", t[nm[0]:nm[1]])]
        while words and not _name_shaped(words[-1][2]):
            words.pop()
        if words and all(_name_shaped(w) for _, _, w in words) and not _is_stopish(" ".join(w for _, _, w in words)):
            cx.add(words[0][0], words[-1][1], "PATIENT_NAME", "", 6)


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
        e = len(t[:e].rstrip(" \t.,"))
        if e > s:   # an address-context landmark wins over a protected word inside it ("opp. Gram Panchayat")
            cx.cands.append((4, s, e, "LANDMARK", ""))


_LM_NOUN = (r"(?:bridge|temple|mandir|masjid|mosque|church|gurudwara|dargah|school|ground|maidan|gate|chowk|chowraha|tank|"
            r"market|bazaar|bazar|park|tower|petrol[ \t]+pump|pump|dhaba|well|pond|talab|statue|circle|junction|bus[ \t]+stand|"
            r"stand|godown|mill|factory|garden|lake|teppakulam|kulam|kund|ghat|tree|peepal|post[ \t]+office)")
_LM_PREP = re.compile(r"(?<![A-Za-z])(?:near|nr\.?|behind|opp\.?|opposite|beside|next[ \t]+to|in[ \t]+front[ \t]+of|close[ \t]+to)"
                      r"[ \t]+((?:the[ \t]+)?(?:[A-Za-z][A-Za-z'\-]*[ \t]+){0,4}" + _LM_NOUN + r")(?![A-Za-z])", re.I)
_LM_POST_LAT = re.compile(r"(?<![A-Za-z])((?:[a-z][a-z'\-]+[ \t]+){0,3}[a-z][a-z'\-]+)[ \t]+ke[ \t]+(?:paas|pass|samne|saamne|peeche|piche|bagal)"
                          r"(?![A-Za-z])", re.I)
_LM_POST_DEV = re.compile(r"(?<![ऀ-ॿ])((?:[ऀ-ॿ]+[ \t]+){0,2}[ऀ-ॿ]+)[ \t]+के[ \t]+(?:सामने|पास|पीछे|बगल|निकट)(?![ऀ-ॿ])")


def _layer_landmarks(cx: _Ctx) -> None:
    t = cx.text
    for m in _LM_PREP.finditer(t):
        s, e = m.span(1)
        if _ORG_NEXT.match(t, e) or re.search(r"(?i)hospital|phc|chc|sdh|lab|ward", t[s:e]):
            continue
        cx.cands.append((4, s, e, "LANDMARK", ""))
    for rx in (_LM_POST_LAT, _LM_POST_DEV):
        for m in rx.finditer(t):
            s, e = m.span(1)
            ws = t[s:e].split()
            # keep only the trailing words that are not function / clinical words
            k = len(ws)
            while k > 0 and not (_low(ws[k - 1]) in _STOP or _low(ws[k - 1]) in _LOW_VERBISH or _low(ws[k - 1]) in _HI_FUNC):
                k -= 1
            if k == len(ws):
                continue
            s2 = s + len(" ".join(ws[:k])) + (1 if k else 0)
            s2 = t.find(ws[k], s2 - 1 if k else s)
            if re.search(r"(?i)hospital|phc|chc|sdh|अस्पताल|सीएचसी|पीएचसी", t[s2:e]):
                continue
            cx.add(s2, e, "LANDMARK", "", 5)


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
        if re.search(r"(?<![0-9])[1-9][0-9]{2}[ \t]?[0-9]{3}[ \t]*$", line) and not re.search(r"[0-9]{7,}", line):
            cues += 1
        if cues >= 2 or (kin and cues >= 1):
            # start after any leading label
            m = _LABEL_RE.match(line)
            st = ls + (m.end() if m else 0)
            _parse_address(t, st, ls + len(line), cx.add, strict=True)


# ---------------------------------------------------------------- reference-annotator rules

# residence trigger in running prose: "resident of 14/2 X Street, Y, Z dist.", "निवासी मकान सं. 27, ..."
_RESIDE_RE = re.compile(r"(?<![A-Za-z])(?:resident[ \t]+of|residing[ \t]+at|r/o|R/O|lives[ \t]+(?:at|in)|living[ \t]+at|"
                        r"stays[ \t]+at|staying[ \t]+at|resides[ \t]+at|(?:[Ww]e|I|i|[Tt]hey)[ \t]+(?:live|stay)[ \t]+(?:at|in)|"
                        r"address[ \t]+(?:is|for[ \t]+[a-z]+)|from[ \t]+(?=(?:Flat|House|Plot|H\.[ \t]*No|D\.[ \t]*No|Door)\b))[ \t]*[:\-]?[ \t]*"
                        r"|(?<![ऀ-ॿ])(?:निवासी|निवास|रहने[ \t]+वाले|रहने[ \t]+वाली)[ \t]*[:\-]?[ \t]*")
_DIST_WORD = re.compile(r"(?<![A-Za-zऀ-ॿ])(?:dist|distt|district|जिला|ज़िला|जनपद)(?![A-Za-zऀ-ॿ])", re.I)
_RESIDE_STOP = _ws("""
was is are has had her his who with aged age and since for presented presenting came come admitted so but which
अपने अपनी अपना जो की का के ने को है हैं था थी उम्र आयु
""")
_ABBR_DOT = _ws("dist distt no nr opp rd st teh vill p o po h sec sr sn ps सं नं म")
_STATES = _ws("""
andhra arunachal assam bihar chhattisgarh goa gujarat haryana himachal jharkhand karnataka kerala madhya
maharashtra manipur meghalaya mizoram nagaland odisha orissa punjab rajasthan sikkim tamil telangana tripura
uttarakhand uttaranchal bengal delhi jammu kashmir ladakh puducherry pondicherry chandigarh
""")


def _sentence_end(t: str, pos: int, limit: int) -> int:
    """End of the sentence that starts at pos: newline, danda, or a full stop after a real word."""
    i = pos
    while i < limit:
        c = t[i]
        if c in "\n।|":
            return i
        if c == "." and (i + 1 >= limit or t[i + 1] in " \t\n"):
            m = re.search(r"([A-Za-zऀ-ॿ]+)$", t[max(pos, i - 20):i])
            w = _low(m.group(1)) if m else ""
            if m and len(w) >= 2 and w not in _ABBR_DOT and not (len(w) == 1):
                return i
        i += 1
    return limit


_HOUSE_ANY = re.compile(
    r"(?<![A-Za-z0-9])(?:(?:H|D)\.?[ \t]*No\.?|House[ \t]*No\.?|House|Flat[ \t]*No\.?|Flat|Plot[ \t]*No\.?|Plot|Door[ \t]*No\.?|"
    r"Qtr\.?[ \t]*No\.?|Quarter[ \t]*No\.?|Barrack|#|Old[ \t]+No\.?|New[ \t]+No\.?|मकान[ \t]*(?:सं\.?|नं\.?|नंबर)?|फ्लैट|प्लॉट)"
    r"[ \t]*[:\-]?[ \t]*[0-9०-९][0-9०-९A-Za-z/\-]*(?:[ \t]+room[ \t]+[0-9]+)?(?![0-9A-Za-z])", re.I)
_LANE_ANY = re.compile(
    r"(?<![A-Za-z])(?:Sector|Bye-?lane|Lane|Gali|Street|Cross|Main|Block|Phase)[ \t]*(?:No\.?)?[ \t]*[0-9][0-9A-Za-z\-]*(?![0-9A-Za-z])"
    r"|(?<![ऀ-ॿ])(?:(?:[ऀ-ॿ]+[ \t]+){0,2}गली[ \t]*(?:नं\.?|नंबर|सं\.?)?[ \t]*[0-9०-९]+)")


def _layer_house_markers(cx: _Ctx) -> None:
    t = cx.text
    for rx, kind in ((_HOUSE_ANY, "HOUSE"), (_LANE_ANY, "LOCALITY")):
        for m in rx.finditer(t):
            g = m.group()
            if kind == "HOUSE" and g.startswith("#") and not re.match(r"#[ \t]*[0-9]{2,}", g):
                continue
            if re.match(r"(?:Block|Phase|Main|Cross)", g) and not _ADDR_CONTEXT.search(t, max(0, m.start() - 60), m.start()):
                continue
            cx.add(m.start(), m.end(), kind, "", 4)


def _layer_residence(cx: _Ctx) -> None:
    t = cx.text
    for m in _RESIDE_RE.finditer(t):
        s = m.end()
        if s >= len(t) or t[s] in "\n":
            continue
        le = t.find("\n", s)
        le = len(t) if le < 0 else le
        se = _sentence_end(t, s, min(le, s + 200))
        # comma segments: stop after a district / state segment, before a function-word segment
        end = s
        i = s
        nseg = 0
        while i < se:
            j = t.find(",", i, se)
            j = se if j < 0 else j
            for wm in _WORD_ANY.finditer(t, i, j):
                if _low(wm.group()) in _RESIDE_STOP:
                    j = wm.start()
                    se = j
                    break
            seg = t[i:j].strip(" \t.;:")
            words = _WORD_ANY.findall(seg)
            if not seg or len(seg) > 48:
                break
            end = j
            nseg += 1
            dm = _DIST_WORD.search(t, i, j)
            if dm:
                end = dm.end()
                break
            if words and _low(words[0]) in _STATES:
                break
            i = j + 1
        if nseg == 0:
            continue
        e = len(t[:end].rstrip(" \t.,;"))
        if e > s:
            # the trailing town is kept only when it is a known district / state or carries a district word
            lastw = _WORD_ANY.findall(t[max(s, t.rfind(",", s, e) + 1):e])
            keep = bool(_DIST_WORD.search(t, s, e)) or not lastw or nseg < 2 or any(
                _low(w) in _DISTRICTS for w in lastw)
            _parse_address(t, s, e, cx.add, last_keep=keep)


# ---------------------------------------------------------------- place phrases in running prose

_DISTRICTS = frozenset(_nfc(w) for w in lexicon.DISTRICTS) | _STATES
# words that follow a place-type word but are not a place ("Post Op", "via Email", "Para 2")
_PLACE_NEG = _ws("""
op ops operative operatively partum natal mortem procedure surgery surgical office box master graduate
email mail sms phone call courier ambulance referral hospital clinic road highway route
""")
_PT_PRE = re.compile(r"(?<![A-Za-z])(?:village|vill\.?|gaon|gaanv|gram|mauza|mouza|tola|basti|leikai|veng|sahi|wadi|"
                     r"pada|chawl|mohalla|hamlet|post|p\.[ \t]*o\.?|PO|via|tehsil|tahsil|taluka|taluk|tal\.|teh\.)[ \t]*[:\-]?[ \t]+", re.I)
_PT_TITLE = re.compile(r"[A-Z][a-z]+(?:-[A-Z]?[a-z]+)*(?![A-Za-z])")
_PT_LOWER = re.compile(r"[a-z]{3,}(?![A-Za-z])")
_PT_PART = re.compile(r"[ \t]*(?:Pt|Part|Ward[ \t]*No)\.?[ \t]*[\-:]?[ \t]*(?:[0-9]+|[IVX]+)(?![A-Za-z0-9])", re.I)
_PT_POST_TYPES = (r"(?:House(?=[ \t]*,)|Tola|Nagar|Colony|Basti|Pada|Wadi|Para|Patti|Khurd|Kalan|Buzurg|Gali|Chawl|Leikai|Veng|"
                  r"Mohalla|Gaon|Village)")
_PT_POST = re.compile(r"(?<![A-Za-z])((?:[A-Za-z][a-z]+[ \t]+){1,2})(" + _PT_POST_TYPES + r")(?![A-Za-z])", re.I)
_DEV_PRE = re.compile(r"(?<![ऀ-ॿ])(?:ग्राम|गाँव|गांव|गाव|टोला|मौजा|डाकघर|मोहल्ला|रा\.|पो\.|पोस्ट)[ \t]*[:\-]?[ \t]*")
_DEV_STOP = _ws("""
के का की में से को ने पर तक और व एवं तहसील ता. ता जिला ज़िला जनपद थाना प्रखंड ब्लॉक पोस्ट पिन मकान गली
नामक निवासी रहने रहते रहती वाले वाली है हैं था थी
""")
_DEV_POST = re.compile(r"(?<![ऀ-ॿ])((?:" + _DEV + r"[ \t]+)?" + _DEV + r")[ \t]+(गांव|गाँव|गाव|टोला|खुर्द|कलां|कलाँ|बुजुर्ग|डीह|पट्टी)"
                       r"(?![ऀ-ॿ])")
_DEV_SUFFIX = re.compile(r"(?<![ऀ-ॿ])(" + _DEV + r"(?:पुर|गाव|गांव|गंज|नगर|वाडी|वाड़ी))(?![ऀ-ॿ])")
_PLACE_SUFFIX = re.compile(r"(?i)(?:pur|pura|puram|gaon|ganj|garh|nagar|palli|pally|patti|halli|wadi|wada|pada|kheda|"
                           r"khurd|guda|gudem|peta|pet|kuppam|kulam|alli|ur|oor)$")
# strong travel / residence frames around a capitalised place name
_PT_CTX_BEFORE = re.compile(r"(?<![A-Za-z])(?:reached|shifted[ \t]+to|shifting[ \t]+to|moved[ \t]+to|native[ \t]+of|"
                            r"belongs?[ \t]+to|hails?[ \t]+from|house[ \t]+at|home[ \t]+(?:at|in)|stays?[ \t]+(?:at|in)|"
                            r"collected[ \t]+from[ \t]+home,?|from)[ \t]+", re.I)
_PT_CTX_AFTER = re.compile(r"[ \t]+(?:se[ \t]+(?:aaye|aayi|aaya|aaye|aate|aati|laaye|laye|laya|aa[ \t]+rahe|aa[ \t]+rahi)|"
                           r"ke[ \t]+(?:rehne|rahne)[ \t]+(?:wale|wali|vale|vali)|k[ai][ \t]+(?:niwasi|nivasi)|"
                           r"(?:me|mein|mai)[ \t]+(?:rehte|rehti|rahte|rahti)|shift[ \t]+ho[ \t]+(?:rahe|rahi|gaye|gaya|gayi)|"
                           r"side[ \t]+(?:hai|me|mein))(?![A-Za-z])", re.I)
_TRAVEL_WORDS = re.compile(r"(?i)(?<![a-z])(?:attendant|attender|relative|family|came|come|coming|brought|travel+ed|"
                           r"home|house|ghar|village|husband|wife|son|daughter|mother|father|lives?|living|"
                           r"resident|native|hails?|aaye|aayi|from[ \t]+home)(?![a-z])")


def _place_tok_ok(w: str, lower_ok: bool = False) -> bool:
    lw = _low(w)
    if len(lw) < 3 or lw in _STOP or lw in _DISTRICTS or lw in _PLACE_NEG or lw in _NOT_LOWER_NAME:
        return False
    if lw in lexicon.CLINICAL_WORDS or lw in lexicon.HINDI_COMMON_WORDS or lw in _LOW_VERBISH:
        return False
    if not lower_ok and not w[:1].isupper() and not _is_dev(w):
        return False
    return True


_DIR_WORDS = _ws("uttar dakshin purba purab paschim pashchim purbi north south east west new old naya purana bada chhota")


def _take_place_fwd(t: str, pos: int, lower: bool, max_tok: int = 3) -> Optional[Tuple[int, int]]:
    """1..max_tok name-like tokens from pos, separated by single spaces / tabs."""
    i, end, n = pos, None, 0
    rx = _PT_LOWER if lower else _PT_TITLE
    while n < max_tok:
        m = rx.match(t, i)
        if m and n == 0 and _low(m.group()) in _DIR_WORDS:
            m2 = rx.match(t, m.end() + 1) if t[m.end():m.end() + 1] == " " else None
            if m2 and _place_tok_ok(m2.group(), lower):
                end, n, i = m.end(), 1, m.end() + 1
                continue
        if not m or not _place_tok_ok(m.group(), lower):
            break
        end = m.end()
        n += 1
        sp = re.match(r"[ \t]+", t[end:end + 3])
        if not sp:
            break
        i = end + sp.end()
    if end is None:
        return None
    pm = _PT_PART.match(t, end)
    if pm:
        end = pm.end()
    return pos, end


def _layer_place_words(cx: _Ctx) -> None:
    t = cx.text
    lower_text = not re.search(r"[A-Z][a-z]+[ \t]+[A-Z][a-z]+", t) or sum(c.isupper() for c in t) < len(t) / 80
    # 1. place-type word before the name: "village Kanwas", "PO Ramnagar", "tola Bhitri"
    for m in _PT_PRE.finditer(t):
        s = m.end()
        if _ORG_NEXT.match(t, s) or _ORG_NEXT.match(t, s + (len(t[s:].split(" ", 1)[0]) if t[s:] else 0)):
            continue
        r = _take_place_fwd(t, s, False)
        if r is None and lower_text and m.group().strip().lower().rstrip(":-. \t") in ("gaon", "gaanv", "gram", "tola", "basti",
                                                                                      "mohalla", "village", "vill"):
            r = _take_place_fwd(t, s, True, 2)
        if r is None or _ORG_NEXT.match(t, r[1]):
            continue
        cx.add(r[0], r[1], "VILLAGE", "", 4)
    # 2. place-type word after the name: "Majhi Tola", "Sahakar Nagar", "bhainsa patti", "Maruti Mandir gali"
    for m in _PT_POST.finditer(t):
        ws = m.group(1).split()
        typ = m.group(2)
        if typ.islower() and not lower_text and typ not in ("gali", "patti", "tola", "gaon", "basti", "mohalla"):
            continue
        k = len(ws)
        while k > 0 and _place_tok_ok(ws[k - 1], lower_ok=True) and (ws[k - 1][:1].isupper() or lower_text or typ.islower()):
            k -= 1
        if k == len(ws):
            continue
        st = m.start(1) + len(" ".join(ws[:k])) + (1 if k else 0)
        st = t.find(ws[k], st - 1 if k else m.start(1))
        if any(_low(w) in _DISTRICTS for w in ws[k:]) and typ.lower() in ("nagar",):
            continue
        e = m.end(2)
        pm = _PT_PART.match(t, e)
        cx.add(st, pm.end() if pm else e, "LOCALITY", "", 4)
    # 3. Devanagari: "ग्राम X Y के", "रा. X खुर्द", "X गांव", "X-पुर"
    for m in _DEV_PRE.finditer(t):
        i, end, n = m.end(), None, 0
        while n < 3:
            w = re.match(_DEV, t[i:])
            if not w or _low(w.group()) in _DEV_STOP or _low(w.group()) in _DISTRICTS:
                break
            end = i + w.end()
            n += 1
            sp = re.match(r"[ \t]+", t[end:end + 3])
            if not sp:
                break
            i = end + sp.end()
        if end is not None and not _ORG_NEXT.match(t, end):
            cx.add(m.end(), end, "VILLAGE", "", 4)
    for m in _DEV_POST.finditer(t):
        ws = m.group(1).split()
        k = len(ws)
        while k > 0 and _low(ws[k - 1]) not in _DEV_STOP and _low(ws[k - 1]) not in _STOP and _low(ws[k - 1]) not in _DISTRICTS:
            k -= 1
        if k == len(ws):
            continue
        st = m.end(1) - len(" ".join(ws[k:]))
        cx.add(st, m.end(2), "VILLAGE", "", 4)
    for m in _DEV_SUFFIX.finditer(t):
        w = m.group(1)
        if _low(w) in _DISTRICTS or _low(w) in _STOP:
            continue
        b = t[max(0, m.start() - 12):m.start()]
        if re.search(r"(?:ग्राम|गांव|गाँव|रा\.|निवासी|पता)[ \t:]*$", b):
            cx.add(m.start(1), m.end(1), "VILLAGE", "", 4)
    # 4. travel / residence frames: "reached X", "shifted to X", "X se aayi", "Paddhari shift ho rahe"
    for m in _PT_CTX_BEFORE.finditer(t):
        s = m.end()
        r = _take_place_fwd(t, s, False, 2)
        if r is None:
            if lower_text and m.group().strip().lower() == "reached":
                r = _take_place_fwd(t, s, True, 1)
            if r is None:
                continue
        if _ORG_NEXT.match(t, r[1]) or re.match(r"[ \t]*(?:hospital|phc|chc|sdh|opd|ward|icu|micu|sicu|nicu|picu|hdu|ccu|"
                                                 r"iccu|ot|theatre|unit|dept|department|labour|lr|room|bed)(?![a-z])", t[r[1]:], re.I):
            continue
        word = t[r[0]:r[1]]
        trig = _low(m.group().split()[0])
        if trig == "from" or trig == "collected":
            ls = t.rfind("\n", 0, m.start()) + 1
            nxt = t[r[1]:r[1] + 2]
            # "from X" only as a residence: X ends the clause and the sentence is about the family / home
            if trig == "from" and not (_TRAVEL_WORDS.search(t, ls, m.start()) and (not nxt or nxt[0] in ".,;)\n" or
                                                                             _PLACE_SUFFIX.search(word.split()[-1]))):
                continue
        cx.add(r[0], r[1], "VILLAGE", "", 5)
    for m in _PT_CTX_AFTER.finditer(t):
        e = m.start()
        b = t[max(0, e - 40):e]
        bm = re.search(r"((?:[A-Za-z][a-z]+[ \t]+)?[A-Za-z][a-z]+)$", b)
        if not bm:
            continue
        ws = bm.group(1).split()
        k = len(ws)
        while k > 0 and _place_tok_ok(ws[k - 1], lower_ok=True) and (ws[k - 1][:1].isupper() or lower_text):
            k -= 1
        if k == len(ws):
            continue
        st = e - len(" ".join(ws[k:]))
        cx.add(st, e, "VILLAGE", "", 5)
    # 5. "of X-pur", "X-pur, Y" in a sentence about the patient: a suffix-shaped place after "of"
    for m in re.finditer(r"(?<![A-Za-z])of[ \t]+", t):
        r = _take_place_fwd(t, m.end(), False, 3)
        if r is None:
            continue
        ws = t[r[0]:r[1]].split()
        has_part = _PT_PART.search(t, r[0], r[1]) is not None
        if not (has_part or any(_PLACE_SUFFIX.search(w) and len(w) >= 6 for w in ws)):
            continue
        if _ORG_NEXT.match(t, r[1]):
            continue
        cx.add(r[0], r[1], "VILLAGE", "", 5)


def _layer_place_runs(cx: _Ctx) -> None:
    """A comma-separated name right after a detected locality / village is part of the same address
    ("H. No. 7 Vaddem, Curtorim"), unless it is a district / state or ends the line before a PIN."""
    t = cx.text
    kinds = ("VILLAGE", "LOCALITY", "HOUSE", "LANDMARK", "ADDRESS")
    for prio, s, e, kind, value in list(cx.cands):
        if kind not in kinds:
            continue
        m = re.match(r"[ \t]*,[ \t]*", t[e:e + 4])
        if not m:
            continue
        p = e + m.end()
        r = _take_place_fwd(t, p, False, 2)
        if r is None:
            continue
        nxt = t[r[1]:r[1] + 3]
        if not nxt or nxt[0] in "\n" or re.match(r"[ \t]*[0-9]", nxt):
            continue                    # the last name before a PIN / line end is the town: kept
        if not re.match(r"[ \t]*[,.;\-]|[ \t]+(?:so|and|ke|me|se)\b", t[r[1]:r[1] + 6]):
            continue
        if re.match(r"[ \t]*[,;][ \t]*(?:[0-9]|$)", t[r[1]:r[1] + 6]):
            continue
        cx.add(r[0], r[1], "VILLAGE", "", 5)



# ---------------------------------------------------------------- unlabelled names in prose

# Devanagari: "X Y, उम्र ४७", "X Y (वय ६१", "X Y नामक ५८ वर्षीय", "रोगी X Y को"
_DEV_NAME_BEFORE = re.compile(r"((?:" + _DEV + r"[ \t]+){0,2}" + _DEV + r")(?:[ \t]*,[ \t]*(?:उम्र|आयु|उमर)|[ \t]*\([ \t]*(?:वय|उम्र|आयु)"
                              r"|[ \t]+नामक)(?![ऀ-ॿ])")
_DEV_PT_WORD = re.compile(r"(?<![ऀ-ॿ])(?:रोगी|मरीज़|मरीज|रोगिणी|बच्चा|बच्ची)[ \t]+((?:" + _DEV + r"[ \t]+){0,2}" + _DEV + r")"
                          r"[ \t]+(?:को|ने|की|का|के|से)(?![ऀ-ॿ])")
# "<Surname> V. N. S. <Given>" after a title / name label / kinship marker
_INIT_RUN = re.compile(r"(?<![A-Za-z])(?:Mr|Mrs|Ms|Smt|Shri|Sri|Name|Patient|Pt|S/o|D/o|W/o|wife|husband)\.?[ \t]*:?[ \t]*"
                       r"([A-Z][a-z]{2,}(?:[ \t]+[A-Z]\.){2,}[ \t]*[A-Z][a-z]{2,})(?![A-Za-z])")
# history narrative: "assaulted by a neighbour, one Sukh", "accused Mr X", "landlord X"
_ACCUSED = re.compile(r"(?<![A-Za-z])(?:(?:allegedly[ \t]+)?assaulted[ \t]+by(?:[ \t]+(?:a|the|his|her|one))?(?:[ \t]+"
                      r"(?:neighbou?r|landlord|employer|relative|man|person))?|accused|neighbou?r|landlord|employer|"
                      r"informant|identified[ \t]+by|statement[ \t]+of|as[ \t]+told[ \t]+by|pillion(?:[ \t]+rider)?|"
                      r"driver|owner|complainant|eye[ \t]*witness|witness|"
                      r"by[ \t]+one)[ \t]*[,:\-]?[ \t]*(?:one[ \t]+)?(?:(?:Mr|Shri|Sri|Sh|Seth|Smt|Mrs|Ms|Haji|Sardar)\.?[ \t]+)?"
                      r"([A-Z][a-z]{2,}(?:[ \t]+[A-Z][a-z]{2,}){0,2})(?![A-Za-z])")
# lowercase nursing line: "14:00 <given> <surname> ot se shift hui", "bed 9 <name> ko tremors"
_LOW_LINE_NAME = re.compile(r"(?m)^[ \t]*(?:[0-9]{1,2}[:.][0-9]{2}[ \t]*(?:hrs?)?[ \t]*[-:]?[ \t]*)"
                            r"([a-z]{3,}[ \t]+[a-z]{3,})[ \t]+(?=(?:ot|ward|icu|opd|ko|ne|ka|ki|ke|se|[0-9]{1,3}[ \t]*(?:y|yr|yrs|/)"
                            r")(?![a-z]))")
_LOW_BED_NAME = re.compile(r"(?<![A-Za-z])bed[ \t]*(?:no\.?)?[ \t]*[0-9]{1,3}[ \t]*[-:,]?[ \t]+([a-z]{3,})[ \t]+(?=(?:ko|ne|ka|ki|ke)"
                           r"(?![a-z]))")
_SELF_INTRO = re.compile(r"(?<![A-Za-z])(?:main|mai|mein|myself|i[ \t]+am|this[ \t]+is)[ \t]+"
                         r"([A-Z][a-z]{2,}(?:[ \t]+[A-Z][a-z]{2,}){0,2})[ \t]+(?:bol[ \t]+(?:raha|rahi)|here|speaking)(?![A-Za-z])", re.I)
_SEEN_VERB = re.compile(r"(?<![A-Za-z])(?:Seen|Reviewed|Counsel+ed|Examined|Assessed)[ \t]+"
                        r"([A-Z][a-z]{2,}(?:[ \t]+[A-Z][a-z]{2,})?)(?=[ \t'’,.;:]|$)")
_BN_GEN = re.compile(r"(?<![A-Za-z])([A-Z][a-z]{3,})[ \t]+r[ \t]+(?=[a-z])")


def _dev_name_ok(ws: List[str]) -> bool:
    return bool(ws) and not any(_low(w) in _STOP or _low(w) in _DEV_STOP or _low(w) in _DISTRICTS or
                                _low(w) in lexicon.KINSHIP_MARKERS for w in ws)


def _layer_prose_names(cx: _Ctx) -> None:
    t = cx.text
    for m in _DEV_NAME_BEFORE.finditer(t):
        ws = m.group(1).split()
        k = len(ws)
        while k > 0 and _dev_name_ok([ws[k - 1]]):
            k -= 1
        if k == len(ws):
            continue
        st = m.end(1) - len(" ".join(ws[k:]))
        cx.add(st, m.end(1), "PATIENT_NAME", "", 5)
    for m in _DEV_PT_WORD.finditer(t):
        cx.add(m.start(1), m.end(1), "PATIENT_NAME", "", 5)     # an explicit patient word: ordinary words allowed
    for m in _INIT_RUN.finditer(t):
        cx.add(m.start(1), m.end(1), "PATIENT_NAME", "", 3)
    for m in _ACCUSED.finditer(t):
        ws = m.group(1).split()
        if any(_low(w) in _STOP or _low(w) in _DISTRICTS for w in ws[:1]):
            continue
        k = 1
        while k < len(ws) and _low(ws[k]) not in _STOP and _low(ws[k]) not in _DISTRICTS:
            k += 1
        if k < len(ws):
            cx.add(m.start(1), m.start(1) + len(" ".join(ws[:k])), "PERSON", "", 4)
        else:
            cx.add(m.start(1), m.end(1), "PERSON", "", 4)
    for rx in (_LOW_LINE_NAME, _LOW_BED_NAME):
        for m in rx.finditer(t):
            ws = m.group(1).split()
            if all(_plain_word(w) and _low(w) not in _LOW_VERBISH and _low(w) not in lexicon.KINSHIP_MARKERS
                   and _low(w) not in _ROLE_WORDS for w in ws):
                cx.add(m.start(1), m.end(1), "PATIENT_NAME", "", 6)
    for rx, kind in ((_SELF_INTRO, "PATIENT_NAME"), (_SEEN_VERB, "PERSON")):
        for m in rx.finditer(t):
            ws = m.group(1).split()
            k = len(ws)
            while k > 0 and (_low(ws[k - 1]) in _STOP or _low(ws[k - 1]) in _DISTRICTS):
                k -= 1
            if k == 0 or any(_low(w) in _STOP for w in ws[:k]):
                continue
            cx.add(m.start(1), m.start(1) + len(" ".join(ws[:k])), kind, "", 4)
    for m in _BN_GEN.finditer(t):
        w = m.group(1)
        if _low(w) in _STOP or _low(w) in _DISTRICTS or _low(w) in _EN_COMMON:
            continue
        cx.add(m.start(1), m.end(1), "PERSON", "", 6)


_ROLE_WORDS = _ws("anm asha aww mpw chw cho didi sister nurse doctor staff ward bed pt patient attendant")


# a closing line followed by a one-line signature: "Thanks,\nAsha" / "धन्यवाद,\nX"
_SIGNOFF_RE = re.compile(r"(?im)^[ \t]*(?:thanks|thank[ \t]+you|regards|warm[ \t]+regards|best[ \t]+regards|"
                         r"kind[ \t]+regards|yours(?:[ \t]+(?:sincerely|truly|faithfully))?|sincerely|"
                         r"धन्यवाद|भवदीय|भवदीया|आपका|आपकी)[ \t]*[,!.]?[ \t]*\n[ \t]*")


def _layer_signoff(cx: _Ctx) -> None:
    t = cx.text
    for m in _SIGNOFF_RE.finditer(t):
        s = m.end()
        le = t.find("\n", s)
        le = len(t) if le < 0 else le
        line = t[s:le].rstrip(" \t,.")
        if not line or re.match(r"(?:Dr|DR|dr|Doctor|Prof|डॉ|डा)\b", line):
            continue
        toks = _WORD_ANY.findall(line)
        if not 1 <= len(toks) <= 3 or _HEADER_LINE.search(line):
            continue
        if not re.fullmatch(r"[A-Za-zऀ-ॿ .'’\-]+", line):
            continue
        nm = _take_name(t, s, s + len(line), "cap", max_tok=3)
        if nm:
            cx.add(nm[0], nm[1], "PERSON", "", 4)


# lower-case nursing shorthand: "pt <name> ko ...", "attendant (husband <name>)"
_LOW_PT = re.compile(r"(?<![A-Za-z])(?:pt|patient|mareez|mariz|marij)\.?[ \t]+([a-z][a-z'\-]{2,})"
                     r"(?:[ \t]+([a-z][a-z'\-]{2,}))?[ \t]+(?:ko|ka|ki|ke|ne|se)(?![A-Za-z])", re.I)
_KIN_LOW = r"(?:husband|wife|mother|father|son|daughter|brother|sister|bhai|behen|pati|patni|beta|beti|pita|mata)"
_LOW_ATT = re.compile(r"(?<![A-Za-z])(?:attndnt|attendant|attender|relative|nok)[ \t]*\(([^()\n]{1,60})\)", re.I)
_LOW_KIN_IN = re.compile(r"(?<![A-Za-z])" + _KIN_LOW + r"[ \t]*:?[ \t]+([A-Za-z][a-z'\-]{2,})(?:[ \t]+([A-Za-z][a-z'\-]{2,}))?",
                         re.I)


_LOW_NOT_NAME = _ws("""
absent present away informed called available unavailable notified sleeping awake outside inside here there
gone left aware unaware ok okay alone along says said told asked refused agreed consented counselled
explained informed waiting present not also only bedside ward home
""")


def _plain_word(w: str) -> bool:
    lw = _low(w)
    return (len(lw) >= 3 and lw not in _STOP and lw not in _LOW_NOT_NAME and lw not in _NOT_LOWER_NAME and lw not in lexicon.HINDI_COMMON_WORDS
            and lw not in lexicon.CLINICAL_WORDS and lw not in lexicon.COMPLAINT_WORDS
            and lw not in ("ko", "ka", "ki", "ke", "ne", "se", "hai", "tha", "thi", "ji"))


def _layer_lower_names(cx: _Ctx) -> None:
    t = cx.text
    for m in _LOW_PT.finditer(t):
        if not _plain_word(m.group(1)):
            continue
        e = m.end(1)
        if m.group(2) and _plain_word(m.group(2)):
            e = m.end(2)
        elif m.group(2):
            continue
        cx.add(m.start(1), e, "PATIENT_NAME", "", 5)
    for m in _LOW_ATT.finditer(t):
        for k in _LOW_KIN_IN.finditer(t, m.start(1), m.end(1)):
            if not _plain_word(k.group(1)):
                continue
            e = k.end(1)
            if k.group(2) and _plain_word(k.group(2)):
                e = k.end(2)
            cx.add(k.start(1), e, "RELATIVE_NAME", "", 4)


# lowercase Hinglish frames: "pati <x>", "saas <x>", "<x> ke ghar", "<x> ki patni", "<x y>, 9 mahine"
_KIN_HL = (r"(?:pati|patni|sasur|saas|sas|beta|beti|bhai|bhaiya|behen|bahen|devar|nanad|jeth|jethani|bahu|damad|"
           r"chacha|chachi|mama|mami|nana|nani|dada|dadi|bhabhi|jija|saala|saali|w/o|s/o|d/o|h/o)")
_LOW_KIN_NEXT = re.compile(r"(?<![A-Za-z/])" + _KIN_HL + r"[ \t]*[:\-]?[ \t]+([a-z][a-z'\-]{2,})(?![A-Za-z])")
_LOW_GEN = re.compile(r"(?<![A-Za-z])([a-z][a-z'\-]{2,})[ \t]+(?:ke[ \t]+ghar|ka[ \t]+(?:mob|mobile|number|phone|no)|"
                      r"ki[ \t]+(?:patni|beti|maa|saas|bahu|behen)|ke[ \t]+(?:pati|bete|beta|bhai|sasur|papa)|ka[ \t]+(?:beta|pati|bhai))"
                      r"(?![A-Za-z])")
_LOW_AGE = re.compile(r"(?<![A-Za-z])([a-z][a-z'\-]{2,})(?:[ \t]+([a-z][a-z'\-]{2,}))?[ \t]*,[ \t]*[0-9]{1,3}[ \t]*"
                      r"(?:mahine|mahina|saal|sal|varsh|yrs?|years?)(?![A-Za-z])")
_LOW_VERBISH = _ws("""
ne ko ka ki ke se hai hain tha thi the ho hua hui gaya gayi gaye aaya aayi aaye bola boli bole bataya batayi
kaha kahi diya di de raha rahi rahe sath saath bhi aur ya to ji jee sahab didi bhaiya ghar ghr phone mob mobile
number gaadi doctor dr asha anm aww phc chc sdh hospital wala wali log given says said only told was is has
""")


def _low_ok(w: str) -> bool:
    return _plain_word(w) and _low(w) not in _LOW_VERBISH and _low(w) not in _EN_COMMON


def _layer_low_frames(cx: _Ctx) -> None:
    t = cx.text
    for m in _LOW_KIN_NEXT.finditer(t):
        if _low_ok(m.group(1)):
            cx.add(m.start(1), m.end(1), "RELATIVE_NAME", "", 6)
    for m in _LOW_GEN.finditer(t):
        if _low_ok(m.group(1)):
            kind = "RELATIVE_NAME" if re.search(r"(?:ki|ke|ka)[ \t]+(?:patni|beti|maa|saas|bahu|behen|pati|bete|beta|bhai|sasur|papa)",
                                                m.group()) else "PATIENT_NAME"
            cx.add(m.start(1), m.end(1), kind, "", 6)
    for m in _LOW_AGE.finditer(t):
        if not _low_ok(m.group(1)) or (m.group(2) and not _low_ok(m.group(2))):
            continue
        cx.add(m.start(1), m.end(2) if m.group(2) else m.end(1), "PATIENT_NAME", "", 6)


# name immediately before an age / sex shape: "<X>, 34/F", "<X> (F/57)", "<X> 62 Y / M", "<X>, 41 M"
_AGE_SEX_AFTER = re.compile(
    r"[ \t]*(?:,[ \t]*|\([ \t]*)?(?:[0-9]{1,3}[ \t]*(?:y|yr|yrs|years?|Y|Yrs)?[ \t]*[/,]?[ \t]*(?:M|F|Male|Female)(?![A-Za-z])"
    r"|(?:M|F)[ \t]*/[ \t]*[0-9]{1,3}(?![0-9])|[0-9]{1,3}[ \t]*(?:yrs?|years?)(?![A-Za-z])"
    r"|(?:उम्र|आयु|वय)[ \t]*[:\-]?[ \t]*[0-9०-९])")
_AGE_SEX_START = re.compile(r"(?:[0-9]{1,3}[ \t]*(?:y|yr|yrs|years?|Y|Yrs)?[ \t]*/?[ \t]*[MF]|[MF][ \t]*/[ \t]*[0-9]|[0-9]{1,3}[ \t]*(?:yrs?|years?)|उम्र|आयु|वय)")


# declarant and kin lists: "I, <Name>, son of", "मैं <नाम>, उम्र", "sons <A> and <B>", "भतीजा <नाम>"
_DECLARANT = re.compile(r"(?:^|(?<=[.\n]))[ \t]*(?:I|मैं)[ \t]*,?[ \t]+(?=[A-Zऀ-ॿ])")
_KIN_LIST = re.compile(r"(?<![A-Za-z])(?:sons|daughters|brothers|sisters|children|nephews)[ \t]+")
_KIN_HI2 = re.compile(r"(?<![ऀ-ॿ])(?:भतीजा|भतीजी|भांजा|भांजी|सास|ससुर|देवर|ननद|जेठ|बहू|दामाद|मुलगा|मुलगी|नातू|पहचानकर्ता|"
                      r"गवाह|अभिभावक|साक्षी)[ \t]*[:\-]?[ \t]*")


def _layer_declarant(cx: _Ctx) -> None:
    t = cx.text
    for m in _DECLARANT.finditer(t):
        le = t.find("\n", m.end())
        le = len(t) if le < 0 else le
        nm = _take_name(t, m.end(), le, "cap", max_tok=3)
        if nm and re.match(r"[ \t]*,", t[nm[1]:nm[1] + 2]):
            cx.add(nm[0], nm[1], "PERSON", "", 5)
    for m in _KIN_LIST.finditer(t):
        le = t.find("\n", m.end())
        le = len(t) if le < 0 else le
        pos = m.end()
        for _ in range(4):
            nm = _take_name(t, pos, le, "cap", max_tok=3)
            if not nm:
                break
            cx.add(nm[0], nm[1], "RELATIVE_NAME", "", 5)
            j = re.match(r"[ \t]*(?:,|and|&)[ \t]*", t[nm[1]:nm[1] + 8])
            if not j:
                break
            pos = nm[1] + j.end()
    for m in _KIN_HI2.finditer(t):
        le = t.find("\n", m.end())
        le = len(t) if le < 0 else le
        nm = _take_name(t, m.end(), le, "cap", max_tok=3)
        if nm and _is_dev(t[nm[0]]):
            cx.add(nm[0], nm[1], "RELATIVE_NAME", "", 4)


_INTRO_WORD = re.compile(r"(?:(?:Seen|Saw|Reviewed|Examined|Kindly|See|Referring|Referred|Patient|Pt|Rx|One|Baby|Master|"
                         r"Late|Admitted|Received|Today|Mr|Mrs|Ms|Smt|Shri)\.?[ \t]+)+")


def _layer_name_age(cx: _Ctx) -> None:
    t = cx.text
    for m in re.finditer(r"[,(]?[ \t]*(?=" + _AGE_SEX_START.pattern + r")", t):
        s = m.start()
        if s == 0 or not _AGE_SEX_AFTER.match(t, s):
            continue
        if s > 0 and t[s - 1].isdigit():
            continue
        nm = _take_name_back(t, s, "cap", 4, allow_comma=False)
        if not nm:
            continue
        w0 = t[nm[0]:nm[1]]
        if re.match(r"(?:Dr|DR|Doctor|Age|Sex|Ward|Bed|Room|Day)\b", w0):
            continue
        intro = _INTRO_WORD.match(w0)
        if intro:                                 # "Seen <X>, 34/M", "Kindly see <X>", "Patient <X>"
            if intro.end() >= len(w0):
                continue
            nm = (nm[0] + intro.end(), nm[1])
        if _ORG_NEXT.match(t, nm[1]):
            continue
        cx.add(nm[0], nm[1], "PATIENT_NAME", "", 4)


# bare kinship word + capitalised name: "my mother Asha", "brother Ravi Kumar", Hinglish "pati Ramu"
_KIN_BARE = re.compile(r"(?<![A-Za-z/])(?:[Mm]y[ \t]+|[Hh]er[ \t]+|[Hh]is[ \t]+)?((?:[Hh]usband|[Ww]ife|[Bb]rother|[Ss]ister|"
                       r"[Pp]arent|[Mm]other|[Ff]ather|[Ss]on|[Dd]aughter)(?:-in-law)?|pati|patni|pita|mata|beta|beti|"
                       r"bhai|behen|bro\.|sis\.)[ \t]+(?![oO][fF][ \t])")


def _layer_kin_bare(cx: _Ctx) -> None:
    t = cx.text
    for m in _KIN_BARE.finditer(t):
        le = t.find("\n", m.end())
        le = len(t) if le < 0 else le
        if re.match(r"(?:Dr|DR|Doctor|डॉ)\b", t[m.end():m.end() + 8]):
            continue
        nm = _take_name(t, m.end(), le, "cap", max_tok=3)
        if not nm:
            # a one-word name that is also an ordinary word ("Mother <Peace> says ...")
            om = re.match(r"([A-Z][a-z]{3,})(?![A-Za-z])", t[m.end():m.end() + 30])
            if (om and _low(om.group(1)) not in _EN_COMMON and _low(om.group(1)) not in _ORG_STOP
                    and _low(om.group(1)) not in lexicon.CLINICAL_WORDS
                    and _low(om.group(1)) not in lexicon.COMPLAINT_WORDS
                    and not re.match(r"[ \t]*[:(]", t[m.end() + om.end():m.end() + om.end() + 2])):
                nm = (m.end(), m.end() + om.end())
        if nm and t[nm[0]].isupper():
            kind = "PATIENT_NAME" if _clinical_after(t, nm[1]) and m.group().lower().startswith("my") else "RELATIVE_NAME"
            cx.add(nm[0], nm[1], kind, m.group(1).lower(), 5)


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
            if nm and letter in "CH" and re.search(r"(?<![A-Za-z])[a-z]", t[nm[0]:nm[1]]):
                nm = None                    # "H/O NSAID intake": history of, not husband of
        if nm and letter in "CH" and re.match(r"[ \t]+[a-z]", t[nm[1]:nm[1] + 3]):
            nm = None                        # "H/O NSAID intake", "C/O Fever since": clinical
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
            ws = t[nm[0]:nm[1]].split()
            while len(ws) > 1 and (_low(ws[-1]) in _DISTRICTS or _low(ws[-1]) in _HI_FUNC):
                ws.pop()                       # "बेटा <X> <Y> सूरत में": the town is not part of the name
            cx.add(nm[0], nm[0] + len(" ".join(ws)), "RELATIVE_NAME", m.group(1), 3)


def _layer_honorifics(cx: _Ctx) -> None:
    t = cx.text
    chat_spans = []
    for m in _CHAT_RE.finditer(t):
        tm = _CHAT_TILDE.match(t, m.end())
        if tm:
            nm = _take_name(t, tm.start(1), tm.end(1), "cap")
            if nm:
                cx.add(nm[0], nm[1], "PERSON", "", 3)
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


_MAIL_HDR = re.compile(r"(?im)^[ \t>]*(?:from|to|cc|bcc|sender|reply-to)[ \t]*:[ \t]*\"?([^\"<>\n:,]{2,50}?)\"?[ \t]*<[^<>\n@]+@")
_MAIL_WROTE = re.compile(r"(?i)\bon[ \t][^\n<>]{4,60}?,[ \t]*([A-Za-z][^<>\n,:]{1,40}?)[ \t]*<[^<>\n@]+@[^<>\n]+>[ \t]*wrote")
_FWD_FROM = re.compile(r"(?i)\bforwarded[ \t]+from[ \t]+([^\n:]{2,40})")
_INTRO = re.compile(r"(?<![A-Za-z])(?:[Mm]y[ \t]+name[ \t]+is|I[ \t]+am|I'm|[Tt]his[ \t]+is|[Mm]era[ \t]+naam|"
                    r"[Mm]ain)[ \t]+([A-Z][a-z]{2,})(?=[ \t]*,[ \t]*(?:his|her|uski|unki|beti|beta|"
                    r"daughter|son|wife|husband|mother|father)|[ \t]+(?:here|speaking|calling|bol))")
_INTRO_NAME = re.compile(r"(?<![A-Za-z])(?:[Mm]y[ \t]+name[ \t]+is|[Mm]era[ \t]+naam)[ \t]+([A-Z][a-z]{2,})")
_SUFFIX_VOC = re.compile(r"(?:^|(?<=[:.!?]))[ \t]*([A-Z][a-z]{2,}(?:ben|bhai|bai|amma|appa|anna|kutty))(?=[ \t]*[,!?])",
                         re.M)


def _layer_mail_intro(cx: _Ctx) -> None:
    """E-mail display names (From / To / Cc, "On <date>, X <addr> wrote:", "Forwarded from X"), speakers
    introducing themselves, and "-ben / -bhai / -amma" names used as a vocative at a turn start."""
    t = cx.text
    if len(t) < 6:
        return
    for rx in ((_MAIL_HDR, _MAIL_WROTE) if "@" in t else ()) + ((_FWD_FROM,) if ("orward" in t or "ORWARD" in t) else ()):
        for m in rx.finditer(t):
            nm = _take_name(t, m.start(1), m.end(1), "cap")
            if nm and not any(w.lower() in _MAILBOX_WORDS for w in t[nm[0]:nm[1]].split()):
                cx.add(nm[0], nm[1], "PERSON", "", 3)
    for rx in (_INTRO, _INTRO_NAME):
        for m in rx.finditer(t):
            w = _low(m.group(1))
            if w not in _EN_COMMON and w not in lexicon.CLINICAL_WORDS and w not in _ORG_STOP:
                cx.add(m.start(1), m.end(1), "PERSON", "", 4)
    for m in _SUFFIX_VOC.finditer(t):
        cx.add(m.start(1), m.end(1), "PERSON", "", 4)


def _layer_verbs(cx: _Ctx) -> None:
    t = cx.text
    for rx, kind in ((_VERB_RE, "PERSON"), (_OF_RE, "PATIENT_NAME")):
        for m in rx.finditer(t):
            le = t.find("\n", m.end())
            le = len(t) if le < 0 else le
            if re.match(r"(?:Dr|DR|dr|Doctor|डॉ)\b", t[m.end():m.end() + 8]):
                continue
            nm = _take_name(t, m.end(), le, "cap")
            if nm and re.match(r"[ \t]+[0-9]{1,4}(?![0-9])(?![ \t]*[0-9])", t[nm[1]:nm[1] + 12]) and nm[1] - nm[0] > 3 and \
                    " " not in t[nm[0]:nm[1]]:
                continue                         # "Caller: <Drug> 200 two puffs": a dose, not a person
            if nm:
                cx.add(nm[0], nm[1], kind, "", 5)


def _layer_phone_proximity(cx: _Ctx) -> None:
    t = cx.text
    phones = sorted((c[1], c[2]) for c in cx.cands if c[3] == "PHONE")
    for ps, pe in phones:
        ls = t.rfind("\n", max(0, ps - 90), ps) + 1
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
                hm = re.match(r"(?:-[A-Z][a-z]+)+", t[e:ps])
                if hm:
                    e += hm.end()               # "Zadeng-Kawlni": a hyphenated surname is one token
                cx.add(s, e, "PERSON", "", 7)
                break
            k = j


# ---- extra free-text frames (localities, street lines, footers, role words, SMS salutations)
_LOC_SFX = (r"nagar|nagara|pet|peta|pettai|pura|puram|wadi|wada|bagh|ganj|vihar|toli|tola|khali|sahi|palli|palya|"
            r"halli|padu|gudem|kuppam|pada|para|abad|bad|gunj|kheda|khera|garh")
_RE_LOC_WORD = re.compile(r"(?<![A-Za-z])([A-Z][a-z]{2,}(?:" + _LOC_SFX + r"))(?![A-Za-z])")
_INST_NEXT = re.compile(r"[ \t]*(?:Diagnostic|Polyclinic|Clinic|Dental|Medical|Nursing|Hospital|College|Path|Lab|Scan|"
                        r"Imaging|Eye|Heart)")
_RE_PREV_CAP = re.compile(r"(?<![A-Za-z])([A-Z][a-z]{2,})[ \t]+\Z")
_RE_STREET = re.compile(r"(?<![A-Za-z])((?:[A-Z][a-z]+[ \t]+){0,2}[0-9]{1,3}(?:st|nd|rd|th)[ \t]+(?:Cross|Main|Line|Lane|Street|"
                        r"Road|Avenue|Marg|Path|Block|Phase|Sector|Stage)(?:[ \t]+Road)?)(?![A-Za-z])")
_RE_SOCIETY = re.compile(r"(?<![A-Za-z0-9/])(?:([A-Z]?[/\-]?[0-9]{1,4}[A-Z]?(?:/[0-9]{1,4})?)[ \t]*,?[ \t]+)?"
                         r"((?:[A-Z][a-z]+[ \t]+){1,2}(?:Society|Residency|Apartments?|Heights|Towers?|Enclave|Layout|"
                         r"Extension|Extn\.?|Colony|Complex|Park|Gardens?|Villas?|Nagar|Vihar|Bagh|Ganj|Puram|Pura)"
                         r"(?:[ \t]+(?:Phase|Sector|Stage|Block)[ \t]*[0-9IVX]+[A-Z]?)?)(?![A-Za-z])")
_RE_DIR_PLACE = re.compile(r"(?<![A-Za-z])(?:from|of|at|in|ghar|village|vill\.?|gaon)[ \t]*[:,]?[ \t]+"
                           r"([A-Z][a-z]{2,}(?:[ \t]+(?:West|East|North|South|Khurd|Kalan|Buzurg)))(?![A-Za-z])")
_RE_DOOR = re.compile(r"(?:(?<=,[ \t])|(?<=,))[0-9]{1,4}/[0-9]{1,4}[A-Z]?(?=[ \t]*,[ \t]*[A-Z])")
_RE_ADDR_LINE_CUE = re.compile(r"(?i)(?<![a-z])(?:c/o|r/o|address|addr|ghar|house|lives|living|resid|shifted|plot|"
                               r"d\.?\s*no|door|flat|h\.?\s*no|#[0-9]|near|opp|behind|pin|from)(?![a-z])")
_RE_LOC_LINE_CUE = re.compile(r"(?i)(?<![a-z])(?:c/o|r/o|address|addr|ghar|house|home|lives|living|resid\w*|shifted|"
                              r"plot|d\.?\s*no|door|flat|h\.?\s*no|#[0-9]|near|opp|behind|pin|block|zila|jila|district|dist|"
                              r"distt|tehsil|taluk|village|vill|gram|gaon|mohalla|sector|cross|main|post|p\.?\s*o|thana|"
                              r"ward\s*no|stays?|from|kendra|centre|center)(?![a-z])|[0-9]{1,4}(?:st|nd|rd|th)\s|[1-9][0-9]{5}")
_RE_ADDR_LABEL_PLACE = re.compile(r"(?<![A-Za-z])(?:Ghar|Ghar[ \t]+ka[ \t]+pata|Pata|Address|Up-?kendra|Upkendra|"
                                  r"Sub-?cent(?:re|er)|Gaon|Mohalla|Tola)[ \t]*[:\-]?[ \t]+([A-Z][a-z]{3,})(?=[ \t]*[,.]|[ \t]+[a-z])")
_RE_LOW_SAHI = re.compile(r"(?<![A-Za-z])([A-Z][a-z]{2,}[ \t]+(?:sahi|toli|tola|basti|mohalla|para|pada|wadi|nagar|colony))(?![A-Za-z])")
_RE_FOOTER = re.compile(r"(?i)(?<![a-z])(?:printed|prepared|generated|typed|verified|checked|issued)[ \t]+by|"
                        r"(?<![a-z])(?:dealing[ \t]+(?:assistant|clerk|hand)|desk[ \t]+officer|contact[ \t]+person|"
                        r"for[ \t]+(?:queries|query|any[ \t]+query)[ \t]+(?:contact|call)|helpdesk|help[ \t]+desk)[ \t]*[:\-]?")
_RE_FOOT_NAME = re.compile(r"[ \t]*[:\-]?[ \t]*((?:[A-Z][a-z]+|[A-Z]\.?)(?:-[A-Z][a-z]+)*(?:[ \t]+(?:[A-Z][a-z]+|[A-Z]\.)(?:-[A-Z][a-z]+)*){1,2})"
                           r"(?![A-Za-z])")
_RE_DEAR_CAPS = re.compile(r"(?<![A-Za-z])(?:Dear|Hi|Hello|Namaste|Namaskar|Mr|Mrs|Ms|Shri|Smt)\.?[ \t]+"
                           r"([A-Z]{3,}(?:[ \t]+[A-Z]{3,}){0,2}(?:[ \t]+[A-Z]\.?)?)(?=[ \t]*[,:.!]|[ \t]+[a-z])")
_CAPS_NOT = _ws("sir madam maam customer patient user member team all parent guardian beneficiary applicant doctor")
_DEV_ROLE = (r"गवाह|साक्षी|परिजन|अभिभावक|हस्ताक्षरकर्ता|रिश्तेदार|संबंधी|सम्बन्धी|पड़ोसी|पडोसी|मित्र|दोस्त|साला|साली|जीजा|"
             r"देवर|ननद|भाभी|भतीजा|भतीजी|भांजा|भांजी|ससुर|सास|बहू|दामाद|चाचा|चाची|मामा|मामी|ताऊ|ताई|फूफा|बुआ|मौसा|मौसी|"
             r"नाना|नानी|दादा|दादी|सहमति[ \t]+देने[ \t]+वाला|सहमति[ \t]+देने[ \t]+वाली|रक्तदाता")
_RE_DEV_ROLE = re.compile(r"(?<![ऀ-ॿ])(?:" + _DEV_ROLE + r")(?![ऀ-ॿ])[ \t]*(?:\([^()\n]{0,20}\))?[ \t]*[:\-]?[ \t]*"
                          r"((?:" + _DEV + r")(?:[ \t]+" + _DEV + r"){0,2})")

_RE_DEV_ROLE_ONLY = re.compile(r"(?:" + _DEV_ROLE + r")")

def _layer_extra_frames(cx: _Ctx) -> None:
    t = cx.text
    for m in _RE_LOC_WORD.finditer(t):
        ls = t.rfind("\n", 0, m.start()) + 1
        le = t.find("\n", m.end())
        if not _RE_LOC_LINE_CUE.search(t[ls:le if le >= 0 else len(t)]):
            continue                        # "<X>wadi" in prose without an address cue: a public place
        w = _low(m.group(1))
        if w in _DISTRICTS or w in _STOP or w in lexicon.CLINICAL_WORDS or len(w) < 6:
            continue
        s0 = m.start(1)
        pm = _RE_PREV_CAP.search(t[max(ls, s0 - 30):s0])
        p = pm.group(1) if pm else ""
        if p and _low(p) not in _STOP and _low(p) not in _DISTRICTS and _low(p) not in _HEADER_WORDS \
                and _low(p) not in _LABEL_WORDS:
            s0 -= len(pm.group())           # "Vallabh Vidyanagar": the qualifier is part of the name
        if _ORG_NEXT.match(t, m.end(1)) or _INST_NEXT.match(t, m.end(1)):
            continue                        # "<X>nagar Diagnostic & Polyclinic": an institution
        cx.add(s0, m.end(1), "LOCALITY", "", 6)
    for m in _RE_STREET.finditer(t):
        cx.add(m.start(1), m.end(1), "LOCALITY", "", 5)
    for m in _RE_SOCIETY.finditer(t):
        if m.group(1):
            cx.add(m.start(1), m.end(1), "HOUSE", "", 4)
        cx.add(m.start(2), m.end(2), "LOCALITY", "", 4)
    for m in _RE_DIR_PLACE.finditer(t):
        if _low(m.group(1).split()[0]) not in _DISTRICTS:
            cx.add(m.start(1), m.end(1), "VILLAGE", "", 5)
    for m in _RE_DOOR.finditer(t):
        ls = t.rfind("\n", 0, m.start()) + 1
        le = t.find("\n", m.end())
        line = t[ls:le if le >= 0 else len(t)]
        if _RE_ADDR_LINE_CUE.search(line):
            cx.add(m.start(), m.end(), "HOUSE", "", 4)
    for m in _RE_ADDR_LABEL_PLACE.finditer(t):
        w = _low(m.group(1))
        if w not in _DISTRICTS and w not in _STOP and w not in lexicon.CLINICAL_WORDS:
            cx.add(m.start(1), m.end(1), "VILLAGE", "", 6)
    for m in _RE_LOW_SAHI.finditer(t):
        w = _low(m.group(1).split()[0])
        if w not in _DISTRICTS and w not in _STOP and w not in lexicon.CLINICAL_WORDS:
            cx.add(m.start(1), m.end(1), "LOCALITY", "", 6)
    for m in _RE_FOOTER.finditer(t):
        n = _RE_FOOT_NAME.match(t, m.end())
        if not n or re.match(r"(?:Dr|DR|Doctor)\b", n.group(1)):
            continue
        ws = [_low(w) for w in re.findall(r"[A-Za-z]+", n.group(1))]
        if any(w in _STOP or w in _HEADER_WORDS for w in ws if len(w) > 1):
            continue
        cx.add(n.start(1), n.end(1), "PERSON", "", 4)
    for m in _RE_DEAR_CAPS.finditer(t):
        ws = [_low(w) for w in m.group(1).split()]
        if any(w in _CAPS_NOT or w in _STOP or w in _HEADER_WORDS for w in ws if len(w) > 1):
            continue
        cx.add(m.start(1), m.end(1), "PATIENT_NAME", "", 4)
    for m in (_RE_DEV_ROLE.finditer(t) if _IS_DEVA.search(t) else ()):
        toks = list(re.finditer(_DEV, m.group(1)))
        keep = []
        for k in toks:
            w = _nfc(k.group())
            if not keep and _RE_DEV_ROLE_ONLY.fullmatch(w):
                continue                    # "रक्तदाता: साला <name>": a second role word before the name
            if w in _STOP or w in _HI_FUNC or w in _DEV_STOP:
                break
            keep.append(k)
        if keep and _dev_name_ok([k.group() for k in keep]):
            base = m.start(1)
            cx.add(base + keep[0].start(), base + keep[-1].end(), "PERSON", "", 5)


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


# ---- run-wide caches for the known-name layer. Every entry is keyed by the identity of an
# immutable object (frozenset / tuple) and keeps that object alive, so a hit is always for the very
# same content: results cannot leak between inputs. reset_caches() frees them between runs.
_KCACHE = {}  # type: Dict[int, Tuple[Any, Any]]
_WKEY = {}  # type: Dict[str, str]
_SMALL_OWN = 48


def reset_caches() -> None:
    patterns.reset_protected_cache()
    _KCACHE.clear()
    _WKEY.clear()
    _RCACHE.clear()


def _cached(obj: Any, build: Any) -> Any:
    hit = _KCACHE.get(id(obj))
    if hit is not None and hit[0] is obj:
        return hit[1]
    val = build(obj)
    if len(_KCACHE) > 50000:
        _KCACHE.clear()
    _KCACHE[id(obj)] = (obj, val)
    return val


def _word_key(w: str) -> str:
    k = _WKEY.get(w)
    if k is None:
        toks = name_tokens(w)
        k = name_key(toks[0]) if len(toks) == 1 else ""
        if len(_WKEY) > 200000:
            _WKEY.clear()
        _WKEY[w] = k
    return k


def _build_full(names: Any) -> Dict[int, Set[Tuple[str, ...]]]:
    full = {}  # type: Dict[int, Set[Tuple[str, ...]]]
    for fn in names:
        ks = tuple(sorted(k for k in fn if k))
        if len(ks) >= 2:
            full.setdefault(len(ks), set()).add(ks)
    return full


def _dels(k: str, depth: int) -> Set[str]:
    out = {k}
    frontier = {k}
    for _ in range(depth):
        nxt = set()  # type: Set[str]
        for x in frontier:
            for i in range(len(x)):
                nxt.add(x[:i] + x[i + 1:])
        out |= nxt
        frontier = nxt
    return out


def _vnorm(k: str) -> str:
    try:
        from .translit import _vowel_norm
        return _vowel_norm(k)
    except Exception:  # pragma: no cover
        return k


class _OwnIndex:
    """Exact candidate filter for `any(_fuzzy_keys(k, o) for o in own)`.

    _fuzzy_keys needs edit distance <= 1 (<= 2 only when the longer key has 9+ letters), either on
    the raw keys or on their vowel-normalised forms. Two strings within edit distance d share a
    string reachable by <= d deletions from each, so a deletion-neighbourhood index per space
    (1 deletion for every key, 2 deletions for keys of 7+ letters) finds every true match; each
    candidate is then confirmed with _fuzzy_keys itself. Small sets are scanned directly."""

    def __init__(self, keys: Any) -> None:
        own = sorted(k for k in keys if k and k not in _GENERIC_KEYS)
        self.own = own
        self.own_set = frozenset(own)
        aff = set()  # type: Set[str]
        if len(own) <= _SMALL_OWN:
            for o in own:
                for n in range(5, len(o) - 1):
                    aff.add(o[:n])
                    aff.add(o[-n:])
        self.affix = frozenset(aff)
        self.memo = {}  # type: Dict[str, bool]
        self.idx = None  # type: Optional[Tuple[Dict[str, List[str]], Dict[str, List[str]]]]
        if len(own) > _SMALL_OWN:
            raw = {}  # type: Dict[str, List[str]]
            vow = {}  # type: Dict[str, List[str]]
            for o in own:
                for space, key in ((raw, o), (vow, _vnorm(o))):
                    for v in _dels(key, 2 if len(key) >= 7 else 1):
                        space.setdefault(v, []).append(o)
            self.idx = (raw, vow)

    def fuzzy(self, k: str) -> bool:
        hit = self.memo.get(k)
        if hit is not None:
            return hit
        if self.idx is None:
            res = any(_fuzzy_keys(k, o) for o in self.own)
        else:
            raw, vow = self.idx
            cands = set()  # type: Set[str]
            for space, key in ((raw, k), (vow, _vnorm(k))):
                for v in _dels(key, 2 if len(key) >= 7 else 1):
                    cands.update(space.get(v, ()))
            res = any(_fuzzy_keys(k, o) for o in sorted(cands))
        self.memo[k] = res
        return res


def _layer_known(cx: _Ctx, known: Known) -> None:
    t = cx.text
    oi = _cached(known.own_keys, _OwnIndex)
    own_set = oi.own_set
    full = _cached(known.full_names, _build_full)
    words = [(m.start(), m.end(), m.group()) for m in _WORD_ANY.finditer(t)]
    keys = [_word_key(w) for _, _, w in words]
    if oi.own:
        for (s, e, w), k in zip(words, keys):
            if not k or k in _GENERIC_KEYS:
                continue
            if k in own_set or (len(k) >= 4 and oi.fuzzy(k)) or (
                    k in oi.affix and (w[:1].isupper() or _is_dev(w)) and _low(w) not in _STOP
                    and _low(w) not in _DISTRICTS):
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


_PIN_AFTER = re.compile(r"[ \t]*[\-–][ \t]*[1-9][0-9]{5}(?![0-9])")


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
                        and not _PLACE_BEFORE.search(_tail(t, ls, s))
                        and not (nxt and _low(nxt.group(1)) in _ORG_TAIL)
                        and not _PIN_AFTER.match(t, e)
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


def _tail(t: str, ls: int, s: int, keep: int = 40) -> str:
    """The end of t[ls:s] that a `...[ \t]*$` pattern (no look-behind, short head) can match in:
    the trailing blanks plus `keep` characters before them. Bounded, unlike t[ls:s]."""
    j = s
    while j > ls and t[j - 1] in " \t":
        j -= 1
    return t[max(ls, j - keep):s]


def _name_context(t: str, ls: int, s: int) -> bool:
    before = _tail(t, ls, s)
    return bool(re.search(r"(?:name|naam|नाम|patient|[sdwhc]/o)[^:\n]{0,12}[:\-]?[ \t]*$", before, re.I))


_MAILBOX_WORDS = _ws("""
info admin office records record help helpdesk desk support contact dept department hospital clinic lab labs
reports report opd ipd billing accounts care team mail noreply reply enquiry enquiries query queries appointments
appointment radiology pathology medical services service health secretary director registrar casualty
""")


def _layer_self_propagate(cx: _Ctx, spans: List[Span]) -> None:
    """Every other whole-word occurrence of a name token found by an anchor, in any case and (through the
    phonetic key) any script. Tokens of strong anchors (prio <= 8: labels, kinship, titles, chat senders,
    e-mail names ...) also propagate when they are ordinary words, and as clipped / pet forms (a prefix or
    suffix of 4+ letters, or a longer word whose prefix / suffix is the anchored token)."""
    t = cx.text
    prio_of = {}  # type: Dict[Tuple[int, int], int]
    for c in cx.cands:
        k0 = (c[1], c[2])
        if c[0] < prio_of.get(k0, 99):
            prio_of[k0] = c[0]
    keymap = {}  # type: Dict[str, Tuple[str, str]]
    strong_words = {}  # type: Dict[str, Tuple[str, str]]   # lowercased common-word names (strong only)
    pets = {}  # type: Dict[str, Tuple[str, str]]           # lowercased Latin token -> kind (strong only)
    for sp in spans:
        if sp.kind not in NAME_KINDS:
            continue
        strong = prio_of.get((sp.start, sp.end), 99) <= 8
        for w in _WORD_ANY.findall(t[sp.start:sp.end]):
            lw = _low(w)
            if lw in _GENERIC or len(lw) < 3 or lw in _DROP:
                continue
            if lw in _STOP:
                if strong and (w[0].isupper() or _is_dev(w)) and len(lw) >= 4 and lw not in _EN_COMMON:
                    strong_words.setdefault(lw, (sp.kind, sp.value))
                continue
            if strong and not _is_dev(w) and len(lw) >= 4:
                prev = pets.get(lw)
                if prev is None or (prev[0] == "PERSON" and sp.kind != "PERSON"):
                    pets[lw] = (sp.kind, sp.value)
            for tok in name_tokens(w):
                k = name_key(tok)
                if k and k not in _GENERIC_KEYS and len(k) >= 2:
                    prev = keymap.get(k)
                    if prev is None or (prev[0] == "PERSON" and sp.kind != "PERSON"):
                        keymap[k] = (sp.kind, sp.value)
    for sp in spans:
        if sp.kind == "EMAIL" and "@" in t[sp.start:sp.end]:
            local = t[sp.start:sp.end].split("@")[0]
            for w in re.split(r"[._\-+0-9]+", local):
                lw = w.lower()
                if (len(lw) >= 4 and lw.isalpha() and lw not in _STOP and lw not in _GENERIC
                        and lw not in _MAILBOX_WORDS):
                    pets.setdefault(lw, ("PERSON", ""))
                    k = name_key(lw)
                    if k and k not in _GENERIC_KEYS:
                        keymap.setdefault(k, ("PERSON", ""))
    if not keymap and not strong_words:
        return
    pet_parts = {}  # type: Dict[str, Tuple[str, str]]
    for lw, hit in pets.items():
        for n in range(4, len(lw)):
            pet_parts.setdefault(lw[:n], hit)
            pet_parts.setdefault(lw[-n:], hit)
    for m in _WORD_ANY.finditer(t):
        w = m.group()
        lw = _low(w)
        if lw in _GENERIC:
            continue
        if lw in _STOP:
            hit = strong_words.get(lw)
            if hit and (w[0].isupper() or _is_dev(w)):
                cx.add(m.start(), m.end(), hit[0], hit[1], 10)
            continue
        toks = name_tokens(w)
        if len(toks) != 1:
            continue
        hit = keymap.get(name_key(toks[0]))
        if not hit and len(lw) >= 4 and not _is_dev(w) and lw not in _EN_COMMON:
            hit = pet_parts.get(lw)
            if not hit and w[0].isupper():
                for n in range(4, len(lw)):
                    hit = pets.get(lw[:n]) or pets.get(lw[-n:])
                    if hit:
                        break
        if hit:
            cx.add(m.start(), m.end(), hit[0], hit[1], 10)


_WRAP_NAME = re.compile(r"(-?)[ \t]*\n[ \t]*([A-Za-z][A-Za-z'’]*(?:[ \t][A-Z][A-Za-z'’]*){0,2})"
                        r"(?=[ \t]{2,}|[ \t]*\n|[ \t]*$)")
_WRAP_ID = re.compile(r"[ \t]*\n[ \t]*([0-9]{2,8})[ \t]*(?=\n|$)")


def _layer_wraps(cx: _Ctx, spans: List[Span]) -> None:
    """A labelled name or id cut by a line break (OCR, narrow forms): the rest of the value on the next
    line takes the same kind. Only when the value ends its line and the next line starts with name
    tokens that stand alone (2+ blanks or the line end after them)."""
    t = cx.text
    if "\n" not in t:
        return
    for sp in spans:
        ls = t.rfind("\n", 0, sp.start) + 1
        if ":" not in t[ls:sp.start] and "：" not in t[ls:sp.start]:
            continue
        if sp.kind in NAME_KINDS:
            m = _WRAP_NAME.match(t, sp.end)
            if not m:
                continue
            hyph = bool(m.group(1)) or t[sp.end - 1] == "-"
            ws = m.group(2).split()
            if not hyph and not ws[0][0].isupper():
                continue
            if all(_is_name_tok(w, "any") for w in ws) and not re.match(r"[ \t]*[:/]", t[m.end():m.end() + 3]):
                cx.add(m.start(2), m.end(2), sp.kind, sp.value, 2)
        elif sp.kind == "MRN":
            m = _WRAP_ID.match(t, sp.end)
            if m:
                cx.add(sp.start, m.end(1), "MRN", sp.value, 1)


def _lift_covering_names(cx: _Ctx) -> None:
    """A known name token (prio 6) inside a longer, weaker name run ("Baby of <Given> <Surname>") must not
    split it: the covering run is lifted to the token's priority so the whole name is replaced."""
    inner = sorted((c[1], c[2]) for c in cx.cands if c[0] == 6 and c[3] in NAME_KINDS)
    if not inner:
        return
    starts = [a for a, _ in inner]
    for c in list(cx.cands):
        if c[0] <= 6 or c[3] not in NAME_KINDS:
            continue
        i = bisect.bisect_left(starts, c[1])
        while i < len(inner) and inner[i][0] < c[2]:
            a, b = inner[i]
            if b <= c[2] and b - a < c[2] - c[1]:
                cx.cands.append((6, c[1], c[2], c[3], c[4]))
                break
            i += 1


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


_RCACHE = {}  # type: Dict[Tuple[Any, ...], Tuple[Any, ...]]
_RCACHE_MAX_TEXT = 4096


def _run(text: str, known: Optional[Known], order: str) -> Tuple[List[Span], Set[int]]:
    """Memoised _run1: the same cell text under the same known sets (shared, immutable objects,
    kept alive by the entry and checked by identity) is detected once per run."""
    if not text or len(text) > _RCACHE_MAX_TEXT:
        return _run1(text, known, order)
    ks = (known.own_keys, known.full_names, known.id_values) if known is not None else (None, None, None)
    key = (text, order, id(ks[0]), id(ks[1]), id(ks[2]))
    hit = _RCACHE.get(key)
    if hit is not None and hit[0] is ks[0] and hit[1] is ks[1] and hit[2] is ks[2]:
        return [Span(a, b, c, d) for a, b, c, d in hit[3]], set(hit[4])
    spans, enc = _run1(text, known, order)
    if len(_RCACHE) > 20000:
        _RCACHE.clear()
    _RCACHE[key] = (ks[0], ks[1], ks[2], tuple((sp.start, sp.end, sp.kind, sp.value) for sp in spans),
                    frozenset(enc))
    return spans, enc


def _run1(text: str, known: Optional[Known], order: str) -> Tuple[List[Span], Set[int]]:
    if not text:
        return [], set()
    text = scripts.fold(text)  # 11 scripts -> Devanagari/Latin; same length, so spans index the original
    cx = _Ctx(text)
    _layer_slash_header(cx)
    _layer_identifiers(cx)
    _layer_pid_labels(cx)
    _layer_labels(cx)
    keep_cells = _layer_tables(cx)
    _layer_space_labels(cx)
    _layer_dob(cx, order)
    _layer_address_lines(cx)
    _layer_places(cx)
    _layer_path_names(cx)
    _layer_patient_anchor(cx)
    _layer_surname_first(cx)
    _layer_residence(cx)
    _layer_house_markers(cx)
    _layer_landmarks(cx)
    _layer_place_words(cx)
    _layer_place_runs(cx)
    _layer_prose_names(cx)
    _layer_kinship(cx)
    _layer_kin_bare(cx)
    _layer_signoff(cx)
    _layer_lower_names(cx)
    _layer_low_frames(cx)
    _layer_name_age(cx)
    _layer_declarant(cx)
    _layer_honorifics(cx)
    _layer_mail_intro(cx)
    _layer_verbs(cx)
    _layer_dev_case(cx)
    _layer_extra_frames(cx)
    if known is not None:
        _layer_known(cx, known)
    _layer_phone_proximity(cx)
    _layer_unknown_pairs(cx)
    _layer_ages(cx)
    _lift_covering_names(cx)
    first = _resolve(cx.cands)
    _layer_wraps(cx, first)
    _layer_self_propagate(cx, first)
    spans = _extend_generic(cx, _reclassify(_resolve(cx.cands), text))
    if keep_cells:
        spans = [sp for sp in spans if not (sp.kind in ("PHONE", "PIN", "MRN", "AADHAAR") and
                                            any(a <= sp.start and sp.end <= b for a, b in keep_cells))]
    return spans, cx.enc_starts


def detect(text: str, known: Optional[Known] = None, order: str = "dmy") -> List[Span]:
    """Non-overlapping identity spans of `text`, sorted by start."""
    return _run(text, known, order)[0]


# ---------------------------------------------------------------- facts

_ID_PREFIX = {"PHONE": "phone", "AADHAAR": "aadhaar", "AADHAAR_MASKED": "aadhaar", "ABHA_NUMBER": "abha",
              "ABHA_ADDRESS": "abhaaddr", "EMAIL": "email", "PAN": "pan", "INSURANCE_ID": "ins"}


# a name right after one of these is somebody else in the patient's story: redacted, never linked as the patient
_THIRD_PARTY_BEFORE = re.compile(
    r"(?:visitor|visitors|caller|witness|attendant|attender|informant|escort|companion|neighbou?r|bystander|"
    r"driver|staff|ward\s*boy|guard)\b[ \t]*[:\-]?[ \t]*(?:(?:mr|mrs|ms|smt|shri|sri)\.?[ \t]+)?$", re.I)
_KIN_BEFORE = re.compile(
    r"(?<![A-Za-z])(husband|wife|father|mother|son|daughter|brother|sister|beta|beti|bhai|pati|patni|pita|mata)"
    r"(?:'s)?[ \t]*[:\-]?[ \t]*(?:(?:mr|mrs|smt|shri|sri)\.?[ \t]+)?$", re.I)


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
            before = text[max(0, sp.start - 40):sp.start]
            if _THIRD_PARTY_BEFORE.search(before):
                continue                       # "Visitor Zubeida Fernandes": a third party, not this patient
            km = _KIN_BEFORE.search(before)
            if km:                             # "Unke husband Venkatesh ji": the patient's relative
                key2 = (km.group(1).lower(), " ".join(name_tokens(surf)))
                if key2[1] and key2 not in seen_rel:
                    seen_rel.add(key2)
                    f.relatives.append((km.group(1).lower(), surf))
                continue
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
