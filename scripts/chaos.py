#!/usr/bin/env python3
"""Chaos generator: mutate the practice dataset into an "unseen-format" dataset.

    python3 scripts/chaos.py --dev "<toolkit>/dev" --out <dir> [--seed N] [--level 0|1|2|3]

Writes <dir>/input/... and <dir>/truth/truth.json (same schema as dev/truth/truth.json), so
    check_dev.py --output <out> --truth <dir>/truth/truth.json
works unchanged.  Levels are cumulative:
    0  no mutation (byte-identical copy; sanity check of the harness)
    1  person names -> a new pool (Tamil, Bengali, Marathi, Malayali, Punjabi, NE, Parsi, Goan,
       Odia, Kannada, Gujarati) with consistent Latin/Devanagari pairs; spelling variants of one
       name map to spelling variants of one new name
    2  + field labels: CSV/TSV headers, JSON keys (not FHIR), "Label:" text labels
    3  + hospital-id shapes, phone styles, Aadhaar grouping, date formats (per file)
Every mutation is applied by ONE function to the input files and to every truth string that
mirrors them (surfaces, tokens, text keys, preserve, exclude, paths, locs, file names), so the
truth stays consistent.  Standard library only, deterministic given --seed.
"""
from __future__ import annotations

import argparse
import base64
import binascii
import collections
import difflib
import hashlib
import json
import os
import random
import re
import shutil
import sys
import unicodedata
from pathlib import Path

# --------------------------------------------------------------------------------------------
# New name pool (Latin | Devanagari).  Deliberately outside the practice data's communities.
# --------------------------------------------------------------------------------------------
GIVEN = """
Senthil|सेंथिल Murugan|मुरुगन Tamilselvi|तमिलसेल्वी Kannan|कन्नन Valli|वल्ली Selvam|सेल्वम
Arivazhagan|अरिवलगन Thenmozhi|तेनमोझी Ponni|पोन्नी Karthikeyan|कार्तिकेयन Anbu|अन्बु Elango|एलंगो
Sourav|सौरव Debashis|देबाशीष Mousumi|मौसुमी Tanushree|तनुश्री Anirban|अनिर्बान Sudipta|सुदीप्ता
Rituparna|रितुपर्णा Subhankar|शुभंकर Arpita|अर्पिता Joydeep|जॉयदीप Paramita|परमिता
Dnyaneshwar|ज्ञानेश्वर Sayali|सायली Tejaswini|तेजस्विनी Mrunal|मृणाल Pandurang|पांडुरंग Vithoba|विठोबा
Shubhangi|शुभांगी Madhura|मधुरा Omkar|ओंकार Biju|बिजु Sreeja|श्रीजा Anoop|अनूप Jishnu|जिष्णु
Lijo|लिजो Shyni|शाइनी Sajeev|सजीव Remya|रम्या Vineetha|विनीता Unnikrishnan|उन्नीकृष्णन
Harjot|हरजोत Simranjeet|सिमरनजीत Balwinder|बलविंदर Jasleen|जसलीन Amritpal|अमृतपाल Gurdeep|गुरदीप
Rupinder|रुपिंदर Kulwant|कुलवंत Lalremruati|ललरेमरुआती Tomba|तोम्बा Lalthanpuia|ललथनपुइया
Bidyarani|बिद्यारानी Chaoba|चाओबा Pema|पेमा Akum|अकुम Imkong|इमकोंग Jehangir|जहांगीर Rustom|रुस्तम
Perizad|परीज़ाद Zarine|ज़रीन Cyrus|साइरस Farokh|फ़ारोख Dinshaw|दिनशॉ Hormazd|होर्मज़्द
Joaquim|जोआकिम Filomena|फिलोमेना Agnelo|एग्नेलो Rosario|रोज़ारियो Savio|सावियो Inacio|इनासियो
Sasmita|सस्मिता Bishnupriya|बिष्णुप्रिया Pradyumna|प्रद्युम्न Subhasmita|सुभस्मिता Manjunath|मंजुनाथ
Nagaveni|नागवेणी Basavaraj|बसवराज Sravani|स्रावणी Nagarjuna|नागार्जुन Padmaja|पद्मजा Hiral|हिरल
Jignesh|जिग्नेश Bhavik|भाविक Foram|फोरम Kinjal|किंजल Thamarai|तामरै Ezhil|एझिल Sangeetha|संगीता
Indrani|इंद्राणी Tapas|तापस Shyamal|श्यामल Ketaki|केतकी Revathi|रेवती Girija|गिरिजा Nirmal|निर्मल
Ujjwala|उज्ज्वला Bhaskar|भास्कर Lakshmikant|लक्ष्मीकांत Sunanda|सुनंदा Dorothy|डोरोथी
""".split()
SURNAMES = """
Ramasamy|रामासामी Palaniswamy|पलानीस्वामी Subramaniam|सुब्रमण्यम Arumugam|अरुमुगम Thangavel|तंगावेल
Muthusamy|मुथुसामी Kandasamy|कंदसामी Annamalai|अन्नामलाई Chattopadhyay|चट्टोपाध्याय
Mukhopadhyay|मुखोपाध्याय Bandyopadhyay|बंद्योपाध्याय Sengupta|सेनगुप्ता Majumdar|मजूमदार
Dasgupta|दासगुप्ता Ghoshal|घोषाल Bhowmik|भौमिक Haldar|हलदर Kulkarni|कुलकर्णी Deshpande|देशपांडे
Gaikwad|गायकवाड़ Jadhav|जाधव Pawar|पवार Shinde|शिंदे Bhosale|भोसले Patwardhan|पटवर्धन Mhatre|म्हात्रे
Sawant|सावंत Menon|मेनन Pillai|पिल्लई Kurup|कुरुप Panicker|पणिक्कर Varghese|वर्गीज़ Kuriakose|कुरियाकोस
Namboodiri|नंबूदिरी Sandhu|संधू Dhillon|ढिल्लों Grewal|ग्रेवाल Sidhu|सिद्धू Randhawa|रंधावा Bajwa|बाजवा
Cheema|चीमा Thangjam|थांगजम Laishram|लैशराम Ngangom|नगांगोम Longkumer|लोंगकुमेर Jamir|जमीर
Sangma|संगमा Marak|मारक Lyngdoh|लिंगदोह Kharkongor|खारकोंगोर Wadia|वाडिया Mistry|मिस्त्री
Daruwalla|दारूवाला Batliwala|बाटलीवाला Irani|ईरानी Bharucha|भरूचा Fernandes|फर्नांडिस
Rodrigues|रोड्रिग्स Pereira|परेरा Furtado|फुर्ताडो Gomes|गोम्स Colaco|कोलाको Menezes|मेनेज़िस
Mohapatra|महापात्र Panigrahi|पाणिग्रही Behera|बेहेरा Samal|सामल Satpathy|सत्पथी Gowda|गौड़ा
Hegde|हेगड़े Naidu|नायडू Desai|देसाई Vaghela|वाघेला Solanki|सोलंकी Kamath|कामत Shenoy|शेनॉय
""".split()

STOP = {"bhaiya", "mama", "papa", "chachu", "chacha", "didi", "bhai", "ji", "devi", "kumar", "kumari",
        "md", "mohd", "begum", "bibi", "bai", "भैया", "जी", "देवी", "कुमार", "कुमारी"}
NAME_TYPES = {"PATIENT_NAME", "RELATIVE_NAME", "CANARY"}
DEVA = "ऀ-ॿ"
WORDCH = "A-Za-z0-9À-ɏ" + DEVA
SKIP_FORMATS = {"pdf", "binary"}          # never rewrite binary payloads

# --------------------------------------------------------------------------------------------
# Labels (level 2).  Each original maps to a list of synonyms; one is chosen per file.
# --------------------------------------------------------------------------------------------
COL_LABELS = {
    "UHID": ["Regn. #", "Hosp. No", "CR No."], "Patient Name": ["Pt. Naam", "Patient's Name", "Rogi ka Naam"],
    "Gender": ["Sex", "M/F"], "Age": ["Age (Yrs)", "Umr"], "DOB": ["Date of Birth", "D.O.B."],
    "Relation": ["Rishta", "Relationship"], "Relative Name": ["Attendant Name", "Kin Name", "S/o-W/o-D/o"],
    "Address": ["Residence", "Pata"], "Village/Mohalla": ["Gram/Mohalla", "Gaon/Ward"],
    "Tehsil": ["Taluka", "Block"], "District": ["Zila", "Distt."], "PIN": ["Pincode", "Postal"],
    "Mobile": ["Contact No.", "Whatsapp", "Mob. No."], "Aadhaar No": ["UID", "Aadhar Card"],
    "ABHA No": ["ABHA ID", "Health ID"], "Reg Date": ["Date of Regn.", "Regd. On"],
    "PatientID": ["CR No.", "Regn. #"], "LastName": ["Surname", "Family Name"],
    "FirstName": ["Given Name", "Forename"], "Sex": ["Gender", "M/F"],
    "DOB (MM/DD/YYYY)": ["Birth Date (MM/DD/YYYY)", "D.O.B. (MM/DD/YYYY)"],
    "Guardian": ["Next of Kin", "Escort"], "Street": ["Addr Line", "Residence"], "City": ["Town", "Place"],
    "Zip": ["Postal Code", "Pincode"], "Phone": ["Whatsapp", "Contact No."], "Email": ["E-mail ID", "Mail"],
    "Registered (MM/DD/YYYY)": ["Regd On (MM/DD/YYYY)", "Enrolled (MM/DD/YYYY)"],
    "Reg No": ["Hosp. No", "Panjikaran Sankhya"], "Naam": ["Rogi ka Naam", "Mareez ka Naam"],
    "Ling": ["Linga", "Jender"], "Umar": ["Aayu", "Umr"], "Janm Tithi": ["Janam Tarikh", "Janm Din"],
    "Pita/Pati ka Naam": ["Abhibhavak ka Naam", "Pita/Pati"], "Pata": ["Niwas", "Pata/Address"],
    "Gaon": ["Gram", "Mauza"], "Jila": ["Zila", "Janpad"], "Pin Code": ["Pincode", "Dak Pin"],
    "Mobile No": ["Phone No.", "Sampark"], "Aadhar": ["Aadhar Card", "UID No"],
    "Registration Date": ["Panjikaran Tithi", "Regn Dt"],
    "patient_name": ["pt_name", "rogi_naam"], "uhid": ["hosp_no", "cr_no"], "pmjay_id": ["ab_pmjay_no"],
    "payer_pan": ["pan_no"], "policy_no": ["policy_number"],
}
JSON_KEYS = {
    "patient_ref": ["pt_id", "patient_code"], "mobile": ["contact_no", "whatsapp"], "name": ["full_name", "naam"],
    "guardian": ["next_of_kin", "attendant"], "patient_name": ["pt_name", "rogi_naam"],
    "uhid": ["hosp_no", "cr_no"], "phone": ["contact_no", "tel"], "hospital_uhid": ["hosp_regn_no"],
    "age_sex": ["age_gender", "agesex"], "dob": ["birth_dt", "date_of_birth"], "village": ["gram", "gaon"],
    "pin": ["pincode"], "aadhar_no": ["uid_no", "aadhaar"], "address": ["residence", "pata"],
    "exported_by": ["created_by", "operator"], "relation": ["rishta"], "first": ["given_name"],
    "last": ["surname"], "email": ["email_id"], "abha": ["abha_id"], "district": ["zila"],
    "tehsil": ["taluka"], "patient": ["pt_details", "rogi"], "by_name": ["name_index"],
    "by_uhid": ["id_index"], "raised_by": ["reported_by"], "callback": ["callback_no"],
    "contact": ["attendant_contact"], "abha_address": ["phr_address"],
}
TEXT_LABELS = {
    "Patient Name": ["Patient's Name", "Pt. Name", "Name of Patient"], "Name": ["Naam", "Full Name"],
    "UHID": ["CR No.", "Regn. #", "Hosp. No"], "Address": ["Residence", "Pata"],
    "Mobile": ["Contact No.", "Whatsapp"], "Mob": ["Ph", "Cell"], "Attendant": ["Escort", "Accompanied by"],
    "DOB": ["Date of Birth", "D.O.B."], "ABHA No": ["ABHA ID", "Health ID"],
    "Address (attendant)": ["Escort address", "Attendant residence"],
    "मरीज़ का नाम": ["रोगी का नाम", "मरीज का नाम"], "नाम": ["पूरा नाम", "नाम/Name"],
    "मोबाइल": ["फोन नं.", "मोबाइल नं."], "पता": ["निवास", "पता/Address"], "ग्राम": ["गांव", "ग्राम/मोहल्ला"],
    "पंजीकरण सं.": ["रजि. नं.", "पंजीयन क्रमांक"], "पिता का नाम": ["पिताजी का नाम", "पिता/अभिभावक"],
    "पति का नाम": ["पति/पत्नी का नाम", "पति श्री"],
}

MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]
DATE_STYLES = ["d Mon yyyy", "yyyy.mm.dd", "dd-Mon-yy", "Mon d, yyyy"]
PHONE_STYLES = ["(+91) {a} {b}", "{a}.{b}", "0-{a}-{b}", "+91-{a}{b}"]
AADHAAR_STYLES = ["{0}-{1}-{2}", "{0}.{1}.{2}"]


def h(*parts) -> int:
    return int(hashlib.sha256("\x1f".join(map(str, parts)).encode()).hexdigest()[:12], 16)


def norm(s: str) -> str:
    return " ".join(unicodedata.normalize("NFKC", s).casefold().split())


_B64 = re.compile(r"[A-Za-z0-9+/]{24,}={0,2}")


def with_b64(text: str) -> str:   # identical to check_dev.py
    extra = []
    for m in _B64.finditer(text):
        tok = m.group(0)
        try:
            extra.append(base64.b64decode(tok + "=" * (-len(tok) % 4)).decode("utf-8", errors="ignore"))
        except (binascii.Error, ValueError):
            pass
    return text + "\n" + "\n".join(extra) if extra else text


def is_deva(s: str) -> bool:
    return any("ऀ" <= c <= "ॿ" for c in s)


def case_like(src: str, new: str) -> str:
    if is_deva(src):
        return new
    if src.isupper() and len(src) > 1:
        return new.upper()
    if src.islower():
        return new.lower()
    return new[:1].upper() + new[1:].lower()


VARIANT_RULES = [("ee", "i"), ("i", "ee"), ("th", "t"), ("t", "th"), ("u", "oo"), ("oo", "u"), ("sh", "s"),
                 ("v", "w"), ("w", "v"), ("a", "aa"), ("y", "i"), ("k", "kh"), ("d", "dh")]


def variant(name: str, k: int) -> str:
    """k-th spelling variant of a (lowercase) name; k=0 is the name itself."""
    out, n = name, 0
    for a, b in VARIANT_RULES:
        if n >= k:
            break
        i = out.find(a, 1)
        if i > 0:
            out = out[:i] + b + out[i + len(a):]
            n += 1
    return out if n >= k else name + "h" * (k - n)


# --------------------------------------------------------------------------------------------
class Mutator:
    def __init__(self, truth: dict, level: int, seed: str, avoid_text: str):
        self.level, self.seed = level, seed
        self.count = collections.Counter()
        self.name_map: dict[str, str] = {}     # lower latin / deva token -> new token (lower latin)
        self.mrn_map: dict[str, str] = {}      # surface -> new surface
        self.mrn_fname: dict[str, str] = {}
        self.phone: dict[str, str] = {}        # surface -> 10 digits
        self.aadhaar: dict[str, str] = {}      # surface -> 12 digits
        if level >= 1:
            self._build_names(truth, avoid_text)
        if level >= 3:
            self._build_ids(truth)
        self._compile()

    # ---------------- names
    def _build_names(self, truth, avoid_text):
        avoid = set(re.findall(r"[a-zऀ-ॿ]+", avoid_text.lower()))
        orig = set()
        ents = []
        for f in truth["files"].values():
            for u in f["units"].values():
                for e in u["entities"]:
                    if e["type"] in NAME_TYPES:
                        toks = [t for t in e.get("tokens") or [] if t not in STOP and len(t) > 2]
                        orig.update(toks)
                        ents.append((e["person"], e["role"], toks))
        okp = lambda pair: pair.split("|")[0].lower() not in avoid and pair.split("|")[0].lower() not in orig \
            and pair.split("|")[1] not in avoid
        given = [p.split("|") for p in GIVEN if okp(p)]
        surn = [p.split("|") for p in SURNAMES if okp(p)]
        self.pool_dropped = len(GIVEN) + len(SURNAMES) - len(given) - len(surn)
        rng = random.Random(f"chaos-names-{self.seed}")
        rng.shuffle(given)
        rng.shuffle(surn)
        # union-find over tokens: same (person, role), same position, similar spelling
        parent = {t: t for t in orig}

        def find(x):
            while parent[x] != x:
                parent[x] = parent[parent[x]]
                x = parent[x]
            return x
        freq = collections.Counter()
        pos_role = collections.defaultdict(collections.Counter)
        groups = collections.defaultdict(list)
        for person, role, toks in ents:
            freq.update(toks)
            for i, t in enumerate(toks):
                pos_role[t]["sur" if (i == len(toks) - 1 and len(toks) > 1) else "given"] += 1
            if len(toks) >= 2:
                groups[(person, role, len(toks))].append(toks)
        deva_link = collections.defaultdict(collections.Counter)
        for toks_list in groups.values():
            lat = [t for t in toks_list if not any(is_deva(x) for x in t)]
            dev = [t for t in toks_list if all(is_deva(x) for x in t)]
            for a in lat:
                for b in lat:
                    for x, y in zip(a, b):
                        if x != y and difflib.SequenceMatcher(None, x, y).ratio() >= 0.7:
                            parent[find(x)] = find(y)
            for d in dev:
                for a in lat:
                    for x, y in zip(d, a):
                        deva_link[x][y] += 1
        clusters = collections.defaultdict(list)
        for t in sorted(t for t in orig if not is_deva(t)):
            clusters[find(t)].append(t)
        gi = si = 0
        deva_of = {}
        for root in sorted(clusters, key=lambda r: (-sum(freq[t] for t in clusters[r]), r)):
            members = sorted(clusters[root], key=lambda t: (-freq[t], t))
            role = "sur" if sum(pos_role[t]["sur"] for t in members) > sum(pos_role[t]["given"] for t in members) else "given"
            if role == "sur" and si < len(surn):
                lat, dev = surn[si]; si += 1
            elif gi < len(given):
                lat, dev = given[gi]; gi += 1
            else:
                lat, dev = surn[si]; si += 1
            for k, t in enumerate(members):
                self.name_map[t] = variant(lat.lower(), k)
                deva_of[t] = dev
        for d in sorted(t for t in orig if is_deva(t)):
            if deva_link[d]:
                self.name_map[d] = deva_of[deva_link[d].most_common(1)[0][0]]
            else:
                if gi < len(given):
                    self.name_map[d] = given[gi][1]; gi += 1
                else:
                    self.name_map[d] = surn[si][1]; si += 1
        self.pool_used = (gi, si)

    # ---------------- identifiers
    def _build_ids(self, truth):
        for f in truth["files"].values():
            for u in f["units"].values():
                for e in u["entities"]:
                    s, key = e["surface"], e.get("key") or ""
                    if e["type"] == "MRN" and not s.isdigit() and key and s.endswith(key) and len(s) > len(key):
                        self.mrn_map[s] = None
                    elif e["type"] == "PHONE" and re.sub(r"\D", "", s).endswith(key) and len(key) == 10:
                        self.phone[s] = key
                    elif e["type"] == "AADHAAR" and len(key) == 12 and re.sub(r"\D", "", s) == key:
                        self.aadhaar[s] = key
        for s in list(self.mrn_map):
            # key = trailing digits of the truth entity; prefix decides the new scheme
            m = re.match(r"^(.*?)(\d+)$", s)
            prefix, core = m.group(1), m.group(2)
            letters = re.sub(r"[^A-Z]", "", prefix.upper()) or "H"
            st = h(self.seed, "mrn", prefix) % 5
            yy = "2026"
            new = [f"{letters[:2]}-{yy}/{core}", f"P.{core}", f"HN{core}A", f"{letters}#{core}",
                   f"{letters[:1]}{letters[-1:]}/{core}/R"][st]
            self.mrn_map[s] = new
            self.mrn_fname[s] = re.sub(r"[^A-Za-z0-9._-]+", "-", new).strip("-")

    def _compile(self):
        names = sorted(self.name_map, key=len, reverse=True)
        self.name_re = re.compile(
            r"(?<![%s])(%s)(?![%s])" % (WORDCH, "|".join(map(re.escape, names)), WORDCH), re.IGNORECASE) if names else None
        ids = sorted(list(self.mrn_map) + list(self.phone) + list(self.aadhaar), key=len, reverse=True)
        self.id_re = re.compile(r"(?<![A-Za-z0-9])(%s)(?![0-9])" % "|".join(map(re.escape, ids))) if ids else None

    # ---------------- per-file context
    def ctx(self, rel: str, f: dict) -> dict:
        fmt = f.get("format")
        styles = list(DATE_STYLES)
        if fmt in ("csv", "tsv"):
            styles = [s for s in styles if "," not in s]
        c = {
            "rel": rel, "fmt": fmt, "hint": f.get("date_hint") or "dmy",
            "date_style": styles[h(self.seed, "date", rel) % len(styles)],
            "phone_style": PHONE_STYLES[h(self.seed, "phone", rel) % len(PHONE_STYLES)],
            "aad_style": AADHAAR_STYLES[h(self.seed, "aad", rel) % len(AADHAAR_STYLES)],
            "pick": lambda kind, orig: h(self.seed, kind, rel, orig),
        }
        return c

    # ---------------- the single mutation function (text level)
    def text(self, s: str, c: dict, fname: bool = False, labels: bool = True, count: bool = False) -> str:
        if self.level == 0 or not s:
            return s
        parts = []
        last = 0
        if not fname:
            for m in _B64.finditer(s):
                tok = m.group(0)
                try:
                    raw = base64.b64decode(tok + "=" * (-len(tok) % 4), validate=True)
                    dec = raw.decode("utf-8")
                except (binascii.Error, ValueError, UnicodeDecodeError):
                    continue
                if sum(ch.isprintable() or ch in "\r\n\t" for ch in dec) < 0.95 * len(dec):
                    continue
                new_dec = self.text(dec, c, labels=labels, count=count)
                parts.append(self._plain(s[last:m.start()], c, fname, labels, count))
                if new_dec != dec:
                    enc = base64.b64encode(new_dec.encode("utf-8")).decode("ascii")
                    if not tok.endswith("="):
                        enc = enc.rstrip("=")
                    if count:
                        self.count["base64 payloads rewritten"] += 1
                    parts.append(enc)
                else:
                    parts.append(tok)
                last = m.end()
        parts.append(self._plain(s[last:], c, fname, labels, count))
        return "".join(parts)

    def _plain(self, s, c, fname, labels, count):
        if not s:
            return s
        # 1. names
        if self.name_re is not None:
            def nrep(m):
                w = m.group(0)
                if w == "ASHA" or (w == "आशा" and re.match(r"\s*(कार्यकर्ता|वर्कर|दीदी)", s[m.end():])):
                    return w   # ASHA (community health worker) is not a name
                key = w if is_deva(w) else w.lower()
                new = self.name_map.get(key)
                if new is None:
                    return w
                if count:
                    self.count["name tokens"] += 1
                return case_like(w, new)
            s = self.name_re.sub(nrep, s)
        if self.level >= 3:
            # 2. dates (before ids so new id shapes are never re-read as dates)
            if c["fmt"] != "fhir":
                s = self._dates(s, c, count)
            # 3. ids
            if self.id_re is not None:
                def irep(m):
                    w = m.group(0)
                    if w in self.mrn_map:
                        if count:
                            self.count["hospital ids"] += 1
                        return self.mrn_fname[w] if fname else self.mrn_map[w]
                    if w in self.phone:
                        k = self.phone[w]
                        if count:
                            self.count["phones"] += 1
                        if fname:
                            return f"{k[:5]}-{k[5:]}"
                        return c["phone_style"].format(a=k[:5], b=k[5:])
                    if w in self.aadhaar:
                        k = self.aadhaar[w]
                        if count:
                            self.count["aadhaar"] += 1
                        return c["aad_style"].format(k[:4], k[4:8], k[8:])
                    return w
                s = self.id_re.sub(irep, s)
        if self.level >= 2 and labels and not fname:
            s = self._text_labels(s, c, count)
        return s

    _DATE = re.compile(r"(?<![\d/.\-])(\d{1,2})([/.\-])(\d{1,2})\2(\d{4}|\d{2})(?![\d/.\-]|:\d)")

    def _dates(self, s, c, count):
        def rep(m):
            a, b, y = int(m.group(1)), int(m.group(3)), m.group(4)
            d, mo = (b, a) if c["hint"] == "mdy" else (a, b)
            if not (1 <= d <= 31 and 1 <= mo <= 12):
                return m.group(0)
            yr = int(y) if len(y) == 4 else 2000 + int(y)
            if len(y) == 4 and not (1900 <= yr <= 2035):
                return m.group(0)
            if count:
                self.count["dates"] += 1
            st = c["date_style"]
            if st == "d Mon yyyy":
                return f"{d} {MONTHS[mo-1]} {yr}"
            if st == "yyyy.mm.dd":
                return f"{yr}.{mo:02d}.{d:02d}"
            if st == "dd-Mon-yy":
                return f"{d:02d}-{MONTHS[mo-1]}-{yr % 100:02d}"
            return f"{MONTHS[mo-1]} {d}, {yr}"
        return self._DATE.sub(rep, s)

    def _text_labels(self, s, c, count):
        labs = sorted(TEXT_LABELS, key=len, reverse=True)
        rx = re.compile(r"(?m)(^|(?<=[\s|(\[]))(%s)(?=\s*[:：])" % "|".join(map(re.escape, labs)))

        def rep(m):
            opts = TEXT_LABELS[m.group(2)]
            if count:
                self.count["text labels"] += 1
            return m.group(1) + opts[c["pick"]("tl", m.group(2)) % len(opts)]
        return rx.sub(rep, s)

    def col(self, name: str, c: dict, count=False) -> str:
        new = self.text(name, c, labels=False, count=count)
        if self.level >= 2:
            st = new.strip()
            if st in COL_LABELS:
                opts = COL_LABELS[st]
                if count:
                    self.count["column headers"] += 1
                new = new.replace(st, opts[c["pick"]("col", st) % len(opts)])
        return new

    def key(self, name: str, c: dict, count=False) -> str:
        new = self.text(name, c, labels=False, count=count)
        if self.level >= 2 and c["fmt"] != "fhir" and new in JSON_KEYS:
            opts = JSON_KEYS[new]
            if count:
                self.count["json keys"] += 1
            new = opts[c["pick"]("key", new) % len(opts)]
        return new

    # ---------------- file-level
    _LIT = re.compile(r'"(?:[^"\\\n]|\\.)*"(\s*:)?|(?<![\w."])(\d{10,14})(?![\w."])')

    def json_text(self, s: str, c: dict) -> str:
        def rep(m):
            lit = m.group(0)
            if m.group(2):                       # bare JSON number (phone / aadhaar stored as int)
                new = self.text(lit, c, count=True)
                return lit if new == lit else json.dumps(new, ensure_ascii=False)
            colon = m.group(1) or ""
            body = lit[: len(lit) - len(colon)]
            try:
                val = json.loads(body)
            except ValueError:
                return lit
            new = self.key(val, c, count=True) if colon else self.text(val, c, count=True)
            if new == val:
                return lit
            return json.dumps(new, ensure_ascii="\\u" in body) + colon
        return self._LIT.sub(rep, s)

    def table_text(self, s: str, c: dict, delim: str) -> str:
        nl = s.find("\n")
        head, rest = (s, "") if nl < 0 else (s[:nl], s[nl:])
        if head.lstrip().startswith("{"):        # not really a table (mislabeled export)
            return self.text(s, c, count=True)
        cells = head.split(delim)
        out = []
        for cell in cells:
            q = cell.strip().startswith('"') and cell.strip().endswith('"') and len(cell.strip()) >= 2
            inner = cell.strip()[1:-1] if q else cell
            new = self.col(inner.rstrip("\r"), c, count=True) + ("\r" if inner.endswith("\r") else "")
            out.append('"%s"' % new if q else new)
        return delim.join(out) + self.text(rest, c, count=True)

    def file_text(self, s: str, c: dict, f: dict) -> str:
        fmt = c["fmt"]
        if fmt in ("json", "fhir"):
            return self.json_text(s, c)
        if fmt in ("csv", "tsv"):
            return self.table_text(s, c, f.get("delimiter") or ("\t" if fmt == "tsv" else ","))
        return self.text(s, c, count=True)

    # ---------------- truth paths
    def path(self, p: str, c: dict) -> str:
        if self.level < 1 or not isinstance(p, str):
            return p
        if p.startswith("col:"):
            return "col:" + self.col(p[4:], c)
        if p.startswith("/"):
            segs = p.split("/")
            return "/".join(seg if (seg == "" or seg.isdigit() or seg == "[]")
                            else self.key(seg.replace("~1", "/").replace("~0", "~"), c).replace("~", "~0").replace("/", "~1")
                            for seg in segs)
        return p


# --------------------------------------------------------------------------------------------
def decode(raw: bytes, enc: str):
    try:
        return raw.decode(enc)
    except (UnicodeDecodeError, LookupError):
        return None


def hay_for(text: str) -> str:
    return norm(with_b64(text))


def main() -> int:
    ap = argparse.ArgumentParser(description="Generate a chaos (unseen-format) copy of the practice dataset.")
    ap.add_argument("--dev", required=True, help="toolkit dev folder (has input/ and truth/truth.json)")
    ap.add_argument("--out", required=True)
    ap.add_argument("--seed", default="1")
    ap.add_argument("--level", type=int, default=3, choices=[0, 1, 2, 3])
    ap.add_argument("--avoid-dir", default=str(Path(__file__).resolve().parents[1] / "raksha"),
                    help="code folder whose words must not appear in the new name pool (default: repo raksha/)")
    a = ap.parse_args()
    dev, out = Path(a.dev), Path(a.out)
    truth = json.loads((dev / "truth" / "truth.json").read_text(encoding="utf-8"))
    avoid = ""
    if os.path.isdir(a.avoid_dir):
        for dp, _, fns in os.walk(a.avoid_dir):
            for n in fns:
                if n.endswith((".py", ".txt", ".json", ".toml", ".csv", ".tsv")):
                    avoid += Path(dp, n).read_text(encoding="utf-8", errors="ignore") + "\n"
    cfg = Path(__file__).resolve().parents[1] / "config"
    if cfg.is_dir():
        for dp, _, fns in os.walk(cfg):
            for n in fns:
                avoid += Path(dp, n).read_text(encoding="utf-8", errors="ignore") + "\n"
    M = Mutator(truth, a.level, a.seed, avoid)
    if out.exists():
        shutil.rmtree(out)
    (out / "input").mkdir(parents=True)
    (out / "truth").mkdir(parents=True)

    new_files = {}
    problems, pres_problems = [], []
    renamed = 0
    src_root = dev / "input"
    seen_rel = set()
    for rel, f in truth["files"].items():
        seen_rel.add(rel)
        c = M.ctx(rel, f)
        src = src_root / rel
        raw = src.read_bytes() if src.is_file() else None
        d, base = os.path.split(rel)
        new_rel = os.path.join(d, M.text(base, c, fname=True, count=True)) if a.level else rel
        if new_rel != rel:
            renamed += 1
        mutate_content = a.level > 0 and f.get("format") not in SKIP_FORMATS and raw is not None
        text = decode(raw, f.get("encoding") or "utf-8") if mutate_content else None
        if text is None:
            mutate_content = False
        if mutate_content:
            new_text = M.file_text(text, c, f)
            new_raw = raw if new_text == text else new_text.encode(f.get("encoding") or "utf-8")
        else:
            new_text, new_raw = text, raw
        dst = out / "input" / new_rel
        dst.parent.mkdir(parents=True, exist_ok=True)
        if raw is not None:
            dst.write_bytes(new_raw)
        # ---- truth for this file
        tc = c if mutate_content else dict(c, fmt="__none__")
        nf = dict(f)
        nf["path"] = new_rel
        if raw is not None:
            nf["sha256"] = hashlib.sha256(new_raw).hexdigest()
            nf["size"] = len(new_raw)
        if mutate_content and a.level >= 3 and c["date_style"] == "yyyy.mm.dd" and c["fmt"] != "fhir":
            nf["date_hint"] = "ymd"
        nf["generalizable"] = [M.path(g, c) if mutate_content else g for g in f.get("generalizable") or []]
        units = {}
        old_hay = hay_for(text) if text is not None else ""
        new_hay = hay_for(new_text) if new_text is not None else ""
        old_fn, new_fn = norm(rel), norm(new_rel)
        for loc, u in f["units"].items():
            nu = json.loads(json.dumps(u))
            nloc = M.path(loc, c) if (mutate_content and loc.startswith("/")) else loc
            nu["loc"] = nloc
            for e in nu["entities"]:
                fn = e["channel"] == "filename"
                if not (mutate_content or fn):
                    continue
                old_s = e["surface"]
                e["surface"] = M.text(old_s, c, fname=fn, labels=False)
                if e.get("tokens"):
                    e["tokens"] = [M.text(t, c, labels=False).lower() for t in e["tokens"]]
                if e.get("match") == "text" and e.get("key"):
                    e["key"] = norm(M.text(e["key"], c, labels=False))
                if e["type"] != "CANARY":
                    was = norm(old_s) in (old_fn if fn else old_hay)
                    now = norm(e["surface"]) in (new_fn if fn else new_hay)
                    if was and not now:
                        problems.append((rel, loc, e["type"], old_s, e["surface"]))
            if mutate_content:
                for p in nu.get("preserve") or []:
                    old_p = p["text"]
                    p["text"] = M.text(old_p, c)
                    if "path" in p:
                        p["path"] = M.path(p["path"], c)
                    if norm(old_p) in old_hay and norm(p["text"]) not in new_hay:
                        pres_problems.append((rel, loc, old_p, p["text"]))
                for dt in nu.get("dates") or []:
                    if "path" in dt:
                        dt["path"] = M.path(dt["path"], c)
                    if nf["date_hint"] == "ymd" and dt.get("hint"):
                        dt["hint"] = "ymd"
                for fl in nu.get("fields") or []:
                    if "path" in fl:
                        fl["path"] = M.path(fl["path"], c)
                nu["exclude"] = [M.text(x, c, labels=False) for x in nu.get("exclude") or []]
            units[nloc] = nu
        nf["units"] = units
        new_files[new_rel] = nf
    # files present in input but not in truth: copy as-is
    for dp, _, fns in os.walk(src_root):
        for n in fns:
            rel = os.path.relpath(os.path.join(dp, n), src_root)
            if rel not in seen_rel:
                (out / "input" / rel).parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(os.path.join(dp, n), out / "input" / rel)
    nt = dict(truth)
    nt["files"] = new_files
    nt["chaos"] = {"level": a.level, "seed": a.seed, "generator": "secret-wards/scripts/chaos.py"}
    if a.level >= 3:
        for pt in nt.get("patients", {}).values():
            for hosp, ids in (pt.get("uhids") or {}).items():
                pt["uhids"][hosp] = [M.mrn_map.get(i) or i for i in ids]
    (out / "truth" / "truth.json").write_text(json.dumps(nt, ensure_ascii=False, indent=1), encoding="utf-8")

    # ---------------- summary + self-check
    print(f"chaos level {a.level}, seed {a.seed} -> {out}")
    if a.level >= 1:
        print(f"  name pool: {len(GIVEN)} given + {len(SURNAMES)} surnames, {M.pool_dropped} dropped (found in repo code/config "
              f"or practice data), used {M.pool_used[0]} given / {M.pool_used[1]} surnames for {len(M.name_map)} tokens")
    for k, v in sorted(M.count.items()):
        print(f"  {k:<26} {v}")
    print(f"  {'files renamed':<26} {renamed}")
    if a.level >= 3:
        print(f"  id schemes: {len(M.mrn_map)} hospital-id surfaces, {len(M.phone)} phone surfaces, {len(M.aadhaar)} aadhaar surfaces")
    if a.level == 0:
        same = all((out / "input" / r).read_bytes() == (src_root / r).read_bytes()
                   for r in truth["files"] if (src_root / r).is_file())
        print(f"  level-0 identity check: {'OK, byte-identical' if same else 'FAILED'}")
        if not same:
            return 1
    print(f"SELF-CHECK: {len(problems)} entity surfaces findable before but not after mutation; "
          f"{len(pres_problems)} preserve probes lost")
    # Counts by type and by opaque file handle only: file names and locations can hold personal data,
    # so nothing read from a record (or its path) is ever printed.
    by_type = {}
    for p in problems:
        by_type[str(p[2])] = by_type.get(str(p[2]), 0) + 1
    for t, n in sorted(by_type.items()):
        print(f"   ENTITY type {t:<18} {n}")
    lost_files = {hashlib.sha256(str(p[0]).encode("utf-8", "replace")).hexdigest()[:8] for p in pres_problems}
    if pres_problems:
        print(f"   PRESERVE probes lost in {len(lost_files)} files (handles: {' '.join(sorted(lost_files)[:15])})")
    return 1 if problems else 0


if __name__ == "__main__":
    raise SystemExit(main())
