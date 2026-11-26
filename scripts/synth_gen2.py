"""DEV TOOL. Second-generation synthetic dataset: layouts and scripts the pipeline was never tuned on.

python3 scripts/synth_gen2.py <out_dir> <seed>   ->   <out>/input/..., <out>/truth/truth.json (check_dev-compatible)
Fully synthetic; deterministic per seed.
"""
import base64, datetime as dt, hashlib, json, random, shutil, sys
from pathlib import Path

ROOT = Path(sys.argv[1]); SEED = int(sys.argv[2]) if len(sys.argv) > 2 else 1
R = random.Random(SEED * 7919 + 13)
IN, TR = ROOT / "input", ROOT / "truth"

DIG = {"beng": "০১২৩৪৫৬৭৮৯", "gujr": "૦૧૨૩૪૫૬૭૮૯", "guru": "੦੧੨੩੪੫੬੭੮੯", "arab": "۰۱۲۳۴۵۶۷۸۹", "deva": "०१२३४५६७८९"}
POOL = {   # script: (female given, male given, surnames, place: (village latin, village native, district latin, district native, pin))
 "beng": ([("Moumita", "মৌমিতা"), ("Sharmistha", "শর্মিষ্ঠা"), ("Riya", "রিয়া")],
          [("Sourav", "সৌরভ"), ("Arnab", "অর্ণব"), ("Debashish", "দেবাশিস")],
          [("Chatterjee", "চ্যাটার্জি"), ("Bose", "বসু"), ("Ghosh", "ঘোষ")],
          [("Kalna", "কালনা", "Bardhaman", "বর্ধমান", "713409"), ("Memari", "মেমারি", "Bardhaman", "বর্ধমান", "713146")]),
 "taml": ([("Kavitha", "கவிதா"), ("Meena", "மீனா"), ("Revathi", "ரேவதி")],
          [("Senthil", "செந்தில்"), ("Karthik", "கார்த்திக்"), ("Murugan", "முருகன்")],
          [("Rajan", "ராஜன்"), ("Pandian", "பாண்டியன்"), ("Velu", "வேலு")],
          [("Melur", "மேலூர்", "Madurai", "மதுரை", "625106"), ("Usilampatti", "உசிலம்பட்டி", "Madurai", "மதுரை", "625532")]),
 "telu": ([("Lavanya", "లావణ్య"), ("Swathi", "స్వాతి")], [("Srinivas", "శ్రీనివాస్"), ("Ravi", "రవి")],
          [("Naidu", "నాయుడు"), ("Rao", "రావు")],
          [("Tenali", "తెనాలి", "Guntur", "గుంటూరు", "522201"), ("Ponnur", "పొన్నూరు", "Guntur", "గుంటూరు", "522124")]),
 "gujr": ([("Hetal", "હેતલ"), ("Komal", "કોમલ")], [("Jignesh", "જીગ્નેશ"), ("Bhavesh", "ભાવેશ")],
          [("Patel", "પટેલ"), ("Desai", "દેસાઈ")],
          [("Borsad", "બોરસદ", "Anand", "આણંદ", "388540"), ("Petlad", "પેટલાદ", "Anand", "આણંદ", "388450")]),
 "guru": ([("Manpreet", "ਮਨਪ੍ਰੀਤ"), ("Simran", "ਸਿਮਰਨ")], [("Jasbir", "ਜਸਬੀਰ"), ("Gurdeep", "ਗੁਰਦੀਪ")],
          [("Sandhu", "ਸੰਧੂ"), ("Grewal", "ਗਰੇਵਾਲ")],
          [("Raikot", "ਰਾਏਕੋਟ", "Ludhiana", "ਲੁਧਿਆਣਾ", "141109"), ("Jagraon", "ਜਗਰਾਓਂ", "Ludhiana", "ਲੁਧਿਆਣਾ", "142026")]),
 "arab": ([("Nasreen", "نسرین"), ("Ayesha", "عائشہ")], [("Tariq", "طارق"), ("Imran", "عمران")],
          [("Farooqui", "فاروقی"), ("Hashmi", "ہاشمی")],
          [("Aminabad", "امین آباد", "Lucknow", "لکھنؤ", "226018"), ("Chowk", "چوک", "Lucknow", "لکھنؤ", "226003")]),
 "mlym": ([("Divya", "ദിവ്യ"), ("Anjali", "അഞ്ജലി")], [("Anoop", "അനൂപ്"), ("Rajesh", "രാജേഷ്")],
          [("Menon", "മേനോൻ"), ("Pillai", "പിള്ള")],
          [("Chalakudy", "ചാലക്കുടി", "Thrissur", "തൃശ്ശൂർ", "680307"), ("Kodakara", "കൊടകര", "Thrissur", "തൃശ്ശൂർ", "680684")]),
 "deva": ([("Sunaina", "सुनैना"), ("Pallavi", "पल्लवी")], [("Vikas", "विकास"), ("Rohit", "रोहित")],
          [("Tripathi", "त्रिपाठी"), ("Bhardwaj", "भारद्वाज")],
          [("Pipraich", "पिपराइच", "Gorakhpur", "गोरखपुर", "273152"), ("Chauri", "चौरी", "Gorakhpur", "गोरखपुर", "273201")]),
}
LABELS = {  # name, age, relative(father/husband), phone, village, years-word, female, male
 "beng": ("রোগীর নাম", "বয়স", ("পিতা", "স্বামী"), "মোবাইল", "গ্রাম", "বছর", "মহিলা", "পুরুষ"),
 "taml": ("நோயாளி பெயர்", "வயது", ("தந்தை", "கணவர்"), "கைபேசி", "கிராமம்", "வயது", "பெண்", "ஆண்"),
 "telu": ("రోగి పేరు", "వయస్సు", ("తండ్రి", "భర్త"), "ఫోన్", "గ్రామం", "సంవత్సరాలు", "స్త్రీ", "పురుషుడు"),
 "gujr": ("દર્દીનું નામ", "ઉંમર", ("પિતા", "પતિ"), "મોબાઇલ", "ગામ", "વર્ષ", "સ્ત્રી", "પુરુષ"),
 "guru": ("ਮਰੀਜ਼ ਦਾ ਨਾਮ", "ਉਮਰ", ("ਪਿਤਾ", "ਪਤੀ"), "ਫ਼ੋਨ", "ਪਿੰਡ", "ਸਾਲ", "ਔਰਤ", "ਮਰਦ"),
 "arab": ("مریض کا نام", "عمر", ("والد", "شوہر"), "فون", "پتہ", "سال", "خاتون", "مرد"),
 "mlym": ("രോഗിയുടെ പേര്", "വയസ്സ്", ("അച്ഛൻ", "ഭർത്താവ്"), "ഫോൺ", "ഗ്രാമം", "വയസ്സ്", "സ്ത്രീ", "പുരുഷൻ"),
 "deva": ("मरीज़ का नाम", "आयु", ("पिता", "पति"), "मोबाइल", "ग्राम", "वर्ष", "महिला", "पुरुष"),
}
HOSP = [("Brahmaputra Civil Hospital", "bch"), ("Kaveri Medical Trust", "kmt"), ("Sabarmati Seva Hospital", "ssh")]
DOCS = ["Dr. Anirban Sen", "Dr. Lalitha Krishnan", "Dr. Harjeet Bawa", "Dr. Zeenat Qadri", "Dr. Ketan Vyas"]
DX = [("Acute febrile illness", "R50.9", ["Tab Paracetamol 650 mg TDS", "Tab Cetirizine 10 mg HS"]),
      ("Type 2 diabetes mellitus", "E11.9", ["Tab Glimepiride 1 mg OD", "Tab Metformin 1000 mg BD"]),
      ("Hypertensive heart disease", "I11.9", ["Tab Losartan 50 mg OD", "Tab Metoprolol 25 mg BD"]),
      ("Urinary tract infection", "N39.0", ["Tab Nitrofurantoin 100 mg BD x 5 days", "Syp Alkasol 10 ml TDS"]),
      ("Bronchial asthma", "J45.9", ["Inh Budesonide 200 mcg BD", "Inh Salbutamol 2 puffs SOS"]),
      ("Malaria, P. vivax", "B51.9", ["Tab Chloroquine 600 mg stat", "Tab Primaquine 15 mg OD x 14 days"]),
      ("Cholelithiasis", "K80.2", ["Inj Pantoprazole 40 mg IV OD", "Tab Ursodeoxycholic acid 300 mg BD"])]
REF = dt.date(2026, 11, 20)


def dig(s, script):
    t = DIG.get(script)
    return "".join(t[int(c)] if (t and c.isdigit()) else c for c in s)


def rnd_digits(n): return "".join(R.choice("0123456789") for _ in range(n))


patients, used = [], set()
for i in range(30):
    sc = R.choice(list(POOL)); fg, mg, sn, places = POOL[sc]
    g = R.choice("FM")
    for _ in range(50):
        f = R.choice(fg if g == "F" else mg); s = R.choice(sn)
        if (f, s) not in used: break
    used.add((f, s))
    rel_is_husband = g == "F" and R.random() < 0.6
    rf = R.choice(mg); place = R.choice(places)
    h = R.choice(HOSP)
    uh = {"bch": lambda: f"BCH-{R.randint(10, 99)}-{R.randint(10000, 99999)}",
          "kmt": lambda: f"KMT/2026/{R.randint(1000000, 9999999)}",
          "ssh": lambda: f"SSH#{R.randint(100000, 999999)}"}[h[1]]()
    dx = R.choice(DX); age = R.randint(18, 82); adm = REF - dt.timedelta(days=R.randint(10, 280)); los = R.randint(1, 12)
    patients.append(dict(pid=f"G{SEED:02d}P{i:03d}", sc=sc, f=f, s=s, g=g, rel="W/o" if rel_is_husband else ("D/o" if g == "F" else "S/o"),
                         rk=1 if rel_is_husband else 0, rf=rf, rs=s, place=place, hosp=h, uhid=uh, dx=dx, age=age,
                         dob=dt.date(REF.year - age, R.randint(1, 12), R.randint(1, 28)), adm=adm, dis=adm + dt.timedelta(days=los),
                         los=los, phone=R.choice("6789") + rnd_digits(9), aad=R.choice("23456789") + rnd_digits(11),
                         abha_addr=f"{f[0].lower()}.{s[0].lower()}{R.randint(1, 99)}@abdm", house=f"{R.randint(1, 300)}/{R.randint(1, 40)}",
                         doc=R.choice(DOCS)))
P = patients
if len(P) > 2:   # a homonym pair
    P[-1]["f"], P[-1]["s"], P[-1]["sc"], P[-1]["g"] = P[0]["f"], P[0]["s"], P[0]["sc"], P[0]["g"]
latin = lambda p: f"{p['f'][0]} {p['s'][0]}"
native = lambda p: f"{p['f'][1]} {p['s'][1]}"
rel_latin = lambda p: f"{p['rf'][0]} {p['rs'][0]}"
rel_native = lambda p: f"{p['rf'][1]} {p['rs'][1]}"

files, content = {}, {}
def newfile(rel, fmt, expect="sanitize"): files[rel] = {"path": rel, "format": fmt, "expect": expect, "units": {}}
def unit(rel, loc, pid=None, link="required"):
    return files[rel]["units"].setdefault(loc, {"loc": loc, "patient": pid, "link": link if pid else "none", "entities": [], "preserve": []})
def ent(u, t, s, script="latin", ch="content", role="patient"): u["entities"].append({"type": t, "surface": s, "script": script, "channel": ch, "role": role})
def keep(u, s): u["preserve"].append({"text": s})
def fmt_phone(p, k):
    return [f"+91 {p[:5]} {p[5:]}", f"0091-{p}", f"{p[:5]}-{p[5:]}", f"(+91){p}", f"91{p}"][k % 5]
def fmt_date(d, k):
    return [d.strftime("%d %b %Y"), f"{d.day}{'th' if 10 <= d.day % 100 <= 20 else {1:'st',2:'nd',3:'rd'}.get(d.day % 10, 'th')} {d.strftime('%B %Y')}",
            d.strftime("%Y/%m/%d"), d.strftime("%d.%m.%y"), d.strftime("%d-%m-%Y")][k % 5]

# 1. registration: semicolon CSV, Hinglish headers, cp1252
rel = "registration/regn_export_semicolon.csv"; newfile(rel, "csv")
rows = ["Mareez Naam;Ling;Umar;Pita/Pati Naam;Gaon/Mohalla;Zila;Pincode;Mob No;Aadhar;Panjikaran No"]
n = 0
for p in P[:18]:
    ph = fmt_phone(p["phone"], n); aad = f"{p['aad'][:4]}-{p['aad'][4:8]}-{p['aad'][8:]}"
    rows.append(";".join([latin(p), p["g"], str(p["age"]), f"{p['rel']} {rel_latin(p)}", p["place"][0], p["place"][2], p["place"][4], ph, aad, p["uhid"]]))
    u = unit(rel, f"row:{n}", p["pid"])
    for t, s_ in [("PATIENT_NAME", latin(p)), ("RELATIVE_NAME", rel_latin(p)), ("VILLAGE", p["place"][0]), ("PIN", p["place"][4]),
                  ("PHONE", ph), ("AADHAAR", aad), ("MRN", p["uhid"])]:
        ent(u, t, s_, role="relative" if t == "RELATIVE_NAME" else "patient")
    n += 1
content[rel] = ("\r\n".join(rows) + "\r\n").encode("cp1252")

# 2. native-script discharge notes (one per patient P[:18] in its own script)
for k, p in enumerate(P[:18]):
    sc = p["sc"]; L = LABELS[sc]; rel = f"discharge/{sc}_note_{k:02d}.txt"; newfile(rel, "text")
    dx, icd, meds = p["dx"]; ph = dig(p["phone"], sc)
    txt = (f"{p['hosp'][0]}\n{L[0]}: {native(p)}    {L[1]}: {dig(str(p['age']), sc)} {L[5]}  {L[6] if p['g'] == 'F' else L[7]}\n"
           f"{L[2][p['rk']]}: {rel_native(p)}\n{L[3]}: {ph}\n{L[4]}: {p['place'][1]}, {p['place'][3]} - {dig(p['place'][4], sc)}\n"
           f"UHID: {p['uhid']}\nDiagnosis: {dx} ({icd})\nRx: {meds[0]}; {meds[1]}\nBP 128/84 mmHg, Pulse 86/min\n{p['doc']}\n")
    content[rel] = txt.encode("utf-8")
    u = unit(rel, "doc", p["pid"])
    for t, s_ in [("PATIENT_NAME", native(p)), ("RELATIVE_NAME", rel_native(p)), ("PHONE", ph), ("VILLAGE", p["place"][1]),
                  ("PIN", dig(p["place"][4], sc)), ("MRN", p["uhid"])]:
        ent(u, t, s_, "latin" if t == "MRN" else ("deva" if sc == "deva" else "deva"), role="relative" if t == "RELATIVE_NAME" else "patient")
    for x in [dx, icd, meds[0], meds[1], "BP 128/84 mmHg", "Pulse 86/min", p["doc"]]: keep(u, x)

# 3. WhatsApp chat export (multi-patient: no linking)
rel = "misc/WhatsApp Chat with Ward 6 Nurses.txt"; newfile(rel, "text")
lines, u = [], unit("misc/WhatsApp Chat with Ward 6 Nurses.txt", "doc")
for k, p in enumerate(P[18:24]):
    d = p["adm"]; ph = fmt_phone(p["phone"], k + 1)
    lines.append(f"[{d.strftime('%d/%m/%y')}, {R.randint(7, 11)}:{R.randint(10, 59)} pm] Sister Rekha: {latin(p)} ka sugar 310 aaya, {p['doc']} ko bataya")
    lines.append(f"[{d.strftime('%d/%m/%y')}, {R.randint(7, 11)}:{R.randint(10, 59)} pm] {p['doc']}: Inj Insulin Regular 8 units SC stat. Attendant ka no. {ph}")
    ent(u, "PATIENT_NAME", latin(p), "hinglish"); ent(u, "PHONE", ph, "hinglish")
    keep(u, "Inj Insulin Regular 8 units SC stat")
lines.append(f"[{P[20]['adm'].strftime('%d/%m/%y')}, 11:58 pm] Sister Rekha: Visitor Ilavarasi Thamizhselvan bed 4 ke paas baithi hai")
ent(u, "CANARY", "Ilavarasi Thamizhselvan")
content[rel] = ("\n".join(lines) + "\n").encode("utf-8")

# 4. email thread referral
for k, p in enumerate(P[24:27]):
    rel = f"referrals/email_{k}.txt"; newfile(rel, "text")
    dx, icd, meds = p["dx"]
    txt = (f"From: ward.clerk@{p['hosp'][1]}.example.org\nTo: referrals@district-hospital.example.org\n"
           f"Subject: Referral - {latin(p)} ({p['uhid']})\nDate: {fmt_date(p['adm'], k)}\n\n"
           f"Dear Sir/Madam,\nWe are referring {latin(p)}, {p['age']}/{p['g']}, {p['rel']} {rel_latin(p)}, resident of {p['place'][0]}, "
           f"{p['place'][2]}, for further management of {dx}. ABHA address: {p['abha_addr']}. Contact: {fmt_phone(p['phone'], k + 2)}.\n"
           f"Current medication: {meds[0]}.\nRegards,\n{p['doc']}\n")
    content[rel] = txt.encode("utf-8"); u = unit(rel, "doc", p["pid"])
    for t, s_ in [("PATIENT_NAME", latin(p)), ("MRN", p["uhid"]), ("RELATIVE_NAME", rel_latin(p)), ("VILLAGE", p["place"][0]),
                  ("ABHA_ADDRESS" if False else "EMAIL", p["abha_addr"]), ("PHONE", fmt_phone(p["phone"], k + 2))]:
        ent(u, t, s_, role="relative" if t == "RELATIVE_NAME" else "patient")
    for x in [dx, meds[0], p["doc"]]: keep(u, x)

# 5. HL7 v2 pipe messages
rel = "interfaces/adt_feed.hl7"; newfile(rel, "text", expect="either")
msgs = []; u = unit(rel, "doc")
for p in P[27:30]:
    msgs.append(f"MSH|^~\\&|HIS|{p['hosp'][1].upper()}|LIS|LAB|{p['adm'].strftime('%Y%m%d')}0930||ADT^A01|{R.randint(10000, 99999)}|P|2.5")
    msgs.append(f"PID|1||{p['uhid']}||{p['s'][0]}^{p['f'][0]}||{p['dob'].strftime('%Y%m%d')}|{p['g']}|||{p['house']}^^{p['place'][0]}^^{p['place'][4]}||{p['phone']}")
    msgs.append(f"PV1|1|I|WARD6^BED{R.randint(1, 30)}||||{p['doc'].replace('Dr. ', '').replace(' ', '^')}")
    for t, s_ in [("MRN", p["uhid"]), ("PATIENT_NAME", p["s"][0] + "^" + p["f"][0]), ("DOB", p["dob"].strftime('%Y%m%d')),
                  ("VILLAGE", p["place"][0]), ("PHONE", p["phone"])]:
        ent(u, t, s_)
content[rel] = ("\r".join(msgs) + "\r").encode("utf-8")

# 6. nested JSON export (records under /patients/i)
rel = "exports/emr_nested.json"; newfile(rel, "json")
arr = []
for i, p in enumerate(P[:10]):
    dx, icd, meds = p["dx"]
    arr.append({"demographics": {"fullName": latin(p), "sex": p["g"], "ageYears": p["age"],
                                 "contact": {"mobile": fmt_phone(p["phone"], i), "email": p["abha_addr"]},
                                 "residence": {"line1": f"H No {p['house']}", "village": p["place"][0], "district": p["place"][2], "pin": p["place"][4]},
                                 "guardian": {"relation": p["rel"], "name": rel_latin(p)}},
                "ids": {"hospitalNo": p["uhid"], "aadhaarMasked": f"XXXX-XXXX-{p['aad'][-4:]}"},
                "encounters": [{"admitted": p["adm"].isoformat(), "discharged": p["dis"].isoformat(),
                                "diagnosis": {"code": icd, "text": dx}, "orders": meds, "attending": p["doc"]}]})
    u = unit(rel, f"/patients/{i}", p["pid"])
    for t, s_ in [("PATIENT_NAME", latin(p)), ("PHONE", fmt_phone(p["phone"], i)), ("EMAIL", p["abha_addr"]), ("HOUSE", f"H No {p['house']}"),
                  ("VILLAGE", p["place"][0]), ("PIN", p["place"][4]), ("RELATIVE_NAME", rel_latin(p)), ("MRN", p["uhid"]),
                  ("AADHAAR_MASKED", f"XXXX-XXXX-{p['aad'][-4:]}")]:
        ent(u, t, s_, role="relative" if t == "RELATIVE_NAME" else "patient")
    for x in [dx, icd, meds[0], meds[1], p["doc"]]: keep(u, x)
content[rel] = (json.dumps({"export": {"system": "EMR-9", "generated": REF.isoformat()}, "patients": arr}, indent=2, ensure_ascii=False) + "\n").encode()

# 7. headerless lab CSV (no header row: the first line is data, row:0)
rel = "lab/lab_dump_noheader.csv"; newfile(rel, "csv")
rows = []
for i, p in enumerate(P[10:20]):
    hb = f"{R.randint(85, 140) / 10}"; rows.append(f"{p['uhid']},{latin(p)},{p['g']},{p['age']},Haemoglobin,{hb},g/dL,{p['adm'].strftime('%d/%m/%Y')}")
    u = unit(rel, f"row:{i}", p["pid"]); ent(u, "MRN", p["uhid"]); ent(u, "PATIENT_NAME", latin(p)); keep(u, hb)
content[rel] = ("\n".join(rows) + "\n").encode()

# 8. folder named after the patient, note inside with Hinglish
for k, p in enumerate(P[20:24]):
    rel = f"scans/{latin(p)}/{p['uhid'].replace('/', '-').replace('#', '')}_notes.txt"; newfile(rel, "text")
    txt = (f"{latin(p)} ji ka follow-up. {p['rel']} {rel_latin(p)} saath aaye. Ghar {p['place'][0]} mein hai, landmark: near Shiv Mandir.\n"
           f"Tab Pantoprazole 40 mg OD continue. Next visit {fmt_date(p['dis'] + dt.timedelta(days=14), k + 1)}.\n")
    content[rel] = txt.encode(); u = unit(rel, "doc", p["pid"])
    ent(u, "PATIENT_NAME", latin(p), "hinglish"); ent(u, "RELATIVE_NAME", rel_latin(p), "hinglish", role="relative")
    ent(u, "VILLAGE", p["place"][0], "hinglish"); ent(u, "LANDMARK", "near Shiv Mandir", "hinglish")
    ent(u, "PATIENT_NAME", latin(p), ch="filename"); ent(u, "MRN", p["uhid"].replace('/', '-').replace('#', ''), ch="filename")
    keep(u, "Tab Pantoprazole 40 mg OD")

# 9. FHIR with RelatedPerson + extension
for k, p in enumerate(P[:6]):
    rel = f"fhir/bundle_{SEED}_{k}.json"; newfile(rel, "fhir")
    pat = {"resourceType": "Patient", "id": "p1", "identifier": [{"system": f"urn:{p['hosp'][1]}:uhid", "value": p["uhid"]}],
           "name": [{"use": "official", "family": p["s"][0], "given": [p["f"][0]]}, {"use": "usual", "text": native(p)}],
           "gender": "female" if p["g"] == "F" else "male", "telecom": [{"system": "phone", "value": fmt_phone(p["phone"], k)}],
           "address": [{"text": f"{p['house']}, {p['place'][0]}, {p['place'][2]} {p['place'][4]}", "postalCode": p["place"][4]}],
           "extension": [{"url": "http://example.org/fhir/StructureDefinition/mothers-maiden-name", "valueString": f"{R.choice(POOL[p['sc']][0])[0]} {R.choice(POOL[p['sc']][2])[0]}"}]}
    rp = {"resourceType": "RelatedPerson", "id": "r1", "patient": {"reference": "Patient/p1"},
          "relationship": [{"text": p["rel"]}], "name": [{"text": rel_latin(p)}], "telecom": [{"system": "phone", "value": p["phone"]}]}
    dx, icd, meds = p["dx"]
    cond = {"resourceType": "Condition", "id": "c1", "subject": {"reference": "Patient/p1"},
            "code": {"coding": [{"system": "http://hl7.org/fhir/sid/icd-10", "code": icd, "display": dx}]}}
    enc = {"resourceType": "Encounter", "id": "e1", "status": "finished", "class": {"code": "IMP"}, "subject": {"reference": "Patient/p1"},
           "period": {"start": p["adm"].isoformat(), "end": p["dis"].isoformat()}}
    b = {"resourceType": "Bundle", "type": "collection", "entry": [{"resource": x} for x in (pat, rp, cond, enc)]}
    content[rel] = (json.dumps(b, ensure_ascii=False, indent=2) + "\n").encode(); u = unit(rel, "doc", p["pid"])
    mm = pat["extension"][0]["valueString"]
    for t, s_ in [("MRN", p["uhid"]), ("PATIENT_NAME", p["f"][0]), ("PATIENT_NAME", native(p)), ("PHONE", fmt_phone(p["phone"], k)),
                  ("VILLAGE", p["place"][0]), ("PIN", p["place"][4]), ("RELATIVE_NAME", rel_latin(p)), ("RELATIVE_NAME", mm)]:
        ent(u, t, s_, "deva" if s_ == native(p) else "latin", role="relative" if t == "RELATIVE_NAME" else "patient")
    for x in [dx, icd]: keep(u, x)
    files[rel]["los"] = {"adm": p["adm"].isoformat(), "dis": p["dis"].isoformat(), "days": p["los"]}

# 10. referral letter with a data-URI attachment
p = P[5]; rel = "referrals/letter_with_attachment.txt"; newfile(rel, "text")
att = base64.b64encode(f"Consent signed by {latin(p)}, mobile {p['phone']}, witness Okonjo Ramaswamy".encode()).decode()
content[rel] = (f"Referral for further care.\nDiagnosis: {p['dx'][0]}\nAttachment: data:text/plain;base64,{att}\n").encode()
u = unit(rel, "doc", None); ent(u, "PATIENT_NAME", latin(p), ch="base64"); ent(u, "PHONE", p["phone"], ch="base64")
ent(u, "CANARY", "Okonjo Ramaswamy"); keep(u, p["dx"][0])

# 11. roster table (several patients, no linking)
rel = "misc/ward_census.txt"; newfile(rel, "text"); u = unit(rel, "doc")
lines = ["Bed | Patient | Age/Sex | Contact | Diagnosis", "----|---------|---------|---------|----------"]
for b_, p in enumerate(P[:8], 1):
    lines.append(f"{b_} | {latin(p)} | {p['age']}/{p['g']} | {p['phone'][:5]} {p['phone'][5:]} | {p['dx'][0]}")
    ent(u, "PATIENT_NAME", latin(p)); ent(u, "PHONE", f"{p['phone'][:5]} {p['phone'][5:]}"); keep(u, p["dx"][0])
lines.append("Caller on night duty line: Prabhleen Kaur-Odhiambo")
ent(u, "CANARY", "Prabhleen Kaur-Odhiambo")
content[rel] = ("\n".join(lines) + "\n").encode()

# 12. broken / unsupported
rel = "misc/broken_quote.csv"; newfile(rel, "csv", expect="either")
content[rel] = f'name,phone\n"{latin(P[1])},{P[1]["phone"]}\n'.encode(); u = unit(rel, "doc"); ent(u, "PATIENT_NAME", latin(P[1]))
rel = "misc/report.xlsx"; newfile(rel, "binary", expect="either"); content[rel] = b"PK\x03\x04" + latin(P[2]).encode() + b"\x00" * 40
u = unit(rel, "doc"); ent(u, "PATIENT_NAME", latin(P[2]))

# ---------------------------------------------------------------- write + self-check
shutil.rmtree(IN, ignore_errors=True); shutil.rmtree(TR, ignore_errors=True)
for rel, b in content.items():
    pth = IN / rel; pth.parent.mkdir(parents=True, exist_ok=True); pth.write_bytes(b)
    files[rel]["sha256"] = hashlib.sha256(b).hexdigest()
TR.mkdir(parents=True, exist_ok=True)
truth = {"schema": "raksha-truth/1", "generator_version": "gen2", "seed": SEED, "ref_date": REF.isoformat(), "files": files,
         "patients": {p["pid"]: {"name": latin(p), "script": p["sc"]} for p in P}, "canaries": ["C1", "C2", "C3"],
         "traps": {"homonym_pairs": [[P[0]["pid"], P[-1]["pid"]]], "fragmented": [], "rare_dx": []}}
(TR / "truth.json").write_text(json.dumps(truth, ensure_ascii=False, indent=1), encoding="utf-8")
bad = 0
for rel, f in files.items():
    raw = content[rel].decode("cp1252" if rel.endswith("semicolon.csv") else "utf-8", "replace")
    raw += "\n" + base64.b64decode(att).decode() if rel.endswith("attachment.txt") else ""
    for u in f["units"].values():
        for e in u["entities"]:
            hay = rel if e["channel"] == "filename" else raw
            if e["surface"] not in hay: bad += 1; print("MISSING", e["type"])      # type only: never echo a value or a file name
        for pv in u["preserve"]:
            if pv["text"] not in raw: bad += 1; print("MISSING PRESERVE")
print(f"seed {SEED}: files {len(files)} entities {sum(len(u['entities']) for f in files.values() for u in f['units'].values())} missing {bad}")
