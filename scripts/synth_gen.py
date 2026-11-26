"""DEV TOOL. Synthetic Secret-Wards-style dataset with a check_dev.py-compatible truth file.

Deliberately uses NEW hospitals, name pools, villages and ID formats (none from the practice set),
so it also tests generalisation. Fully synthetic; deterministic for a given seed.

    python3 scripts/synth_gen.py <out_dir> [seed]      # writes <out_dir>/input and <out_dir>/truth/truth.json
"""
import base64, datetime as dt, hashlib, json, os, random, shutil, sys
from pathlib import Path

ROOT = Path(sys.argv[1] if len(sys.argv) > 1 else Path(__file__).parent)
IN, TR = ROOT / "input", ROOT / "truth"
R = random.Random(int(sys.argv[2]) if len(sys.argv) > 2 else 20261126)

F = [("Kavya", "काव्या"), ("Lakshmi", "लक्ष्मी"), ("Farhana", "फरहाना"), ("Gurleen", "गुरलीन"),
     ("Ananya", "अनन्या"), ("Shabnam", "शबनम"), ("Pooja", "पूजा"), ("Revathi", "रेवती"),
     ("Mamta", "ममता"), ("Nirmala", "निर्मला"), ("Tanuja", "तनुजा"), ("Bilkis", "बिलकिस")]
M = [("Arjun", "अर्जुन"), ("Imran", "इमरान"), ("Harpreet", "हरप्रीत"), ("Sandeep", "संदीप"),
     ("Venkatesh", "वेंकटेश"), ("Abhishek", "अभिषेक"), ("Tarun", "तरुण"), ("Naveen", "नवीन"),
     ("Salim", "सलीम"), ("Devendra", "देवेंद्र"), ("Manoj", "मनोज"), ("Prakash", "प्रकाश"),
     ("Kishore", "किशोर"), ("Rafiq", "रफ़ीक")]
S = [("Reddy", "रेड्डी"), ("Ansari", "अंसारी"), ("Gill", "गिल"), ("Banerjee", "बनर्जी"), ("Nair", "नायर"),
     ("Rajput", "राजपूत"), ("Kurmi", "कुर्मी"), ("Saxena", "सक्सेना"), ("Qureshi", "क़ुरैशी"),
     ("Pillai", "पिल्लई"), ("Thakur", "ठाकुर"), ("Meena", "मीणा"), ("Sahu", "साहू")]
PLACES = [("Khajuri Kalan", "खजूरी कलां", "Sehore", "Sehore", "466001"),
          ("Barkhera", "बरखेड़ा", "Ashta", "Sehore", "466116"),
          ("Pipariya", "पिपरिया", "Sonkatch", "Dewas", "455118"),
          ("Kanwas", "कनवास", "Bagli", "Dewas", "455227"),
          ("Raipura", "रायपुरा", "Gyaraspur", "Vidisha", "464111"),
          ("Bichhiya", "बिछिया", "Begumganj", "Raisen", "464881")]
LANDMARKS = ["near Hanuman Mandir", "opp. Gram Panchayat", "behind Govt School", "near Pani ki Tanki"]
DOCTORS = ["Dr. Prakash Bhatt", "Dr. Meenakshi Iyer", "Dr. S. K. Chaturvedi", "Dr. Farooq Hussain"]
DX = [("Dengue fever", "A90"), ("Type 2 diabetes mellitus", "E11.9"), ("Essential hypertension", "I10"),
      ("Acute gastroenteritis", "A09"), ("Community-acquired pneumonia", "J18.9"), ("Enteric fever", "A01.0"),
      ("Scrub typhus", "A75.3"), ("Iron deficiency anaemia", "D50.9"), ("Pulmonary tuberculosis", "A15.0")]
RARE_DX = [("Guillain-Barré syndrome", "G61.0"), ("Snake bite envenomation", "T63.0")]
MEDS = {"A90": ["Tab Paracetamol 650 mg TDS x 5 days", "IV NS 1 L over 8 hrs"],
        "E11.9": ["Tab Metformin 500 mg BD", "Inj Insulin Glargine 10 units HS"],
        "I10": ["Tab Amlodipine 5 mg OD", "Tab Telmisartan 40 mg 1-0-0"],
        "A09": ["ORS 1 sachet after each loose stool", "Tab Ondansetron 4 mg SOS"],
        "J18.9": ["Inj Ceftriaxone 1 g IV BD", "Tab Azithromycin 500 mg OD x 3 days"],
        "A01.0": ["Inj Ceftriaxone 2 g IV OD", "Tab Paracetamol 500 mg SOS"],
        "A75.3": ["Tab Doxycycline 100 mg 1-0-1", "Tab Paracetamol 650 mg SOS"],
        "D50.9": ["Tab Ferrous sulphate 200 mg 0-1-0", "Inj Iron sucrose 200 mg IV"],
        "A15.0": ["Tab Isoniazid 300 mg OD", "Tab Rifampicin 450 mg OD"],
        "G61.0": ["IVIG 0.4 g/kg/day x 5 days", "Tab Pregabalin 75 mg 0-0-1"],
        "T63.0": ["Inj Anti-snake venom 10 vials IV", "Inj Neostigmine 0.5 mg IV"]}
HOSP = {"njk": "Narmada Jan Swasthya Kendra", "sch": "Shivalik Care Hospital",
        "mmh": "Malwa Mission Hospital", "ssc": "Seva Sadan Trust Clinic"}
REF = dt.date(2026, 11, 20)


def digits(n): return "".join(R.choice("0123456789") for _ in range(n))


def phone_fmt(p, k):
    return [f"{p[:5]} {p[5:]}", f"+91-{p}", f"0{p}", f"(+91) {p[:5]}-{p[5:]}", p][k % 5]


# ------------------------------------------------------------------ patients
patients = []
used = set()
def mkname(g):
    while True:
        f = R.choice(F if g == "F" else M); s = R.choice(S)
        if (f[0], s[0]) not in used:
            used.add((f[0], s[0])); return f, s

for i in range(24):
    g = "F" if i % 2 == 0 else "M"
    f, s = mkname(g)
    if i == 23:  # homonym of patient 0: same name, different person
        f, s = patients[0]["f"], patients[0]["s"]; g = "F"
    age = R.randint(19, 78)
    dob = dt.date(REF.year - age, R.randint(1, 12), R.randint(1, 28))
    if g == "F" and R.random() < 0.6:
        rel = "W/o"; rf = R.choice(M); rs = s
    else:
        rel = "S/o" if g == "M" else "D/o"; rf = R.choice(M); rs = s
    v = R.choice(PLACES)
    dx = RARE_DX[i % 2] if i in (5, 11) else R.choice(DX)
    adm = REF - dt.timedelta(days=R.randint(15, 300))
    los = R.randint(2, 11)
    patients.append(dict(pid=f"SY{i:03d}", f=f, s=s, g=g, age=age, dob=dob, rel=rel, rf=rf, rs=rs, v=v,
                         house=f"H.No. {R.randint(10, 480)}", ward=f"Ward {R.randint(1, 18)}",
                         landmark=R.choice(LANDMARKS),
                         phone=R.choice("6789") + digits(9),
                         aadhaar=R.choice("23456789") + digits(11),
                         abha="91" + digits(12), pan="".join(R.choice("ABCDEFGHJKLMNPQRSTUVWXYZ") for _ in range(5)) + digits(4) + R.choice("ABCDEFGHJKLMNPQRSTUVWXYZ"),
                         ins=f"PMJAY-{digits(8)}", dx=dx, adm=adm, dis=adm + dt.timedelta(days=los), los=los,
                         ids={}, doctor=R.choice(DOCTORS)))
# hospitals: every patient registered at njk or sch; some also at mmh / ssc
for i, p in enumerate(patients):
    h = "njk" if i % 3 != 2 else "sch"
    p["ids"][h] = f"NJK-2026-{R.randint(1000, 9999):06d}" if h == "njk" else f"SCH/{R.randint(40000, 59999)}"
    if i % 4 == 0: p["ids"]["mmh"] = f"MMH{R.randint(1000000, 9999999)}"
    if i % 5 == 1: p["ids"]["ssc"] = f"OPD-{R.randint(70000, 79999)}"
P = patients
full = lambda p: f"{p['f'][0]} {p['s'][0]}"
deva = lambda p: f"{p['f'][1]} {p['s'][1]}"
relname = lambda p: f"{p['rf'][0]} {p['rs'][0]}"
relname_d = lambda p: f"{p['rf'][1]} {p['rs'][1]}"

files = {}          # rel -> truth entry
def unit(rel, loc, patient=None, link="required"):
    u = files[rel]["units"].setdefault(loc, {"loc": loc, "patient": patient, "link": link if patient else "none",
                                            "entities": [], "preserve": []})
    return u
def ent(u, typ, surface, script="latin", channel="content", role="patient"):
    u["entities"].append({"type": typ, "surface": surface, "script": script, "channel": channel, "role": role})
def keep(u, text, kind="clinical"):
    u["preserve"].append({"text": text, "kind": kind})
def newfile(rel, fmt, expect="sanitize", delimiter=None, encoding="utf-8"):
    files[rel] = {"path": rel, "format": fmt, "encoding": encoding, "delimiter": delimiter, "expect": expect,
                  "units": {}}
content = {}        # rel -> bytes

# ------------------------------------------------------------------ registration CSV (njk, dd-mm-yyyy)
rel = "registration/narmada_reg_2026.csv"; newfile(rel, "csv", delimiter=",")
rows = ["Reg No,Patient Name,Sex,Age,Date of Birth,Relation,Relative,House,Village,Tehsil,District,PIN,Mobile No,Aadhaar,ABHA ID,Registered On"]
n = 0
for p in P:
    if "njk" not in p["ids"]: continue
    ph = phone_fmt(p["phone"], n); aad = f"{p['aadhaar'][:4]} {p['aadhaar'][4:8]} {p['aadhaar'][8:]}"
    abha = f"{p['abha'][:2]}-{p['abha'][2:6]}-{p['abha'][6:10]}-{p['abha'][10:]}"
    dob = p["dob"].strftime("%d-%m-%Y")
    rows.append(",".join([p["ids"]["njk"], full(p), p["g"], str(p["age"]), dob, p["rel"], relname(p),
                          f"\"{p['house']}, {p['landmark']}\"", p["v"][0], p["v"][2], p["v"][3], p["v"][4], ph, aad, abha,
                          p["adm"].strftime("%d-%m-%Y")]))
    u = unit(rel, f"row:{n}", p["pid"])
    for t, s_ in [("MRN", p["ids"]["njk"]), ("PATIENT_NAME", full(p)), ("DOB", dob), ("RELATIVE_NAME", relname(p)),
                  ("HOUSE", p["house"]), ("LANDMARK", p["landmark"]), ("VILLAGE", p["v"][0]), ("PIN", p["v"][4]),
                  ("PHONE", ph), ("AADHAAR", aad), ("ABHA_NUMBER", abha)]:
        ent(u, t, s_, role="relative" if t == "RELATIVE_NAME" else "patient")
    p["njk_row"] = n; n += 1
content[rel] = ("\n".join(rows) + "\n").encode("utf-8")

# ------------------------------------------------------------------ registration TSV (sch, MM/DD/YYYY, surname first)
rel = "registration/shivalik_patients.tsv"; newfile(rel, "tsv", delimiter="\t")
rows = ["MRN\tSurname\tGiven Name\tGender\tDOB (MM/DD/YYYY)\tGuardian\tLocality\tCity/Village\tPincode\tContact\tPAN"]
n = 0
for p in P:
    if "sch" not in p["ids"]: continue
    ph = phone_fmt(p["phone"], n + 2); dob = p["dob"].strftime("%m/%d/%Y")
    rows.append("\t".join([p["ids"]["sch"], p["s"][0], p["f"][0], p["g"], dob, f"{p['rel']} {relname(p)}",
                           p["ward"], p["v"][0], p["v"][4], ph, p["pan"]]))
    u = unit(rel, f"row:{n}", p["pid"])
    for t, s_ in [("MRN", p["ids"]["sch"]), ("PATIENT_NAME", p["f"][0]), ("DOB", dob), ("RELATIVE_NAME", relname(p)),
                  ("LOCALITY", p["ward"]), ("VILLAGE", p["v"][0]), ("PIN", p["v"][4]), ("PHONE", ph), ("PAN", p["pan"])]:
        ent(u, t, s_, role="relative" if t == "RELATIVE_NAME" else "patient")
    n += 1
content[rel] = ("\n".join(rows) + "\n").encode("utf-8")

# ------------------------------------------------------------------ discharge summaries (English)
def anyid(p): return next(iter(p["ids"].values()))
for k, p in enumerate(P[:10]):
    pid = anyid(p)
    named_file = k in (1, 4)
    rel = (f"discharge/DS_{p['f'][0]}_{p['s'][0]}_{pid.replace('/', '-')}.txt" if named_file
           else f"discharge/ds_{k:03d}.txt")
    newfile(rel, "text")
    dx, icd = p["dx"]; med = MEDS[icd]
    vit = f"BP {R.randint(110, 160)}/{R.randint(70, 98)} mmHg"; pulse = f"Pulse {R.randint(70, 118)}/min"
    lab = f"Hb {R.randint(80, 135) / 10} g/dL"; spo2 = f"SpO2 {R.randint(90, 99)}%"
    complaint = "C/O fever with chills x 4 days" if k % 2 == 0 else "C/O loose motions x 2 days"
    ph = phone_fmt(p["phone"], k)
    txt = f"""{HOSP['njk'] if 'njk' in p['ids'] else HOSP['sch']}
DISCHARGE SUMMARY
Patient: {full(p)}    Age/Sex: {p['age']}/{p['g']}    UHID: {pid}
{p['rel']} {relname(p)}, {p['house']}, {p['v'][0]}, Distt. {p['v'][3]} - {p['v'][4]}
Contact: {ph}
Date of Admission: {p['adm'].strftime('%d/%m/%Y')}    Date of Discharge: {p['dis'].strftime('%d/%m/%Y')}
Consultant: {p['doctor']}

Presenting complaints: {complaint}. Known case of hypertension.
Diagnosis: {dx} ({icd})
On examination: {vit}, {pulse}, {spo2}. {lab}.
Treatment given: {med[0]}; {med[1]}.
Patient improved and is being discharged in stable condition. Attendant {relname(p)} counselled.
Advice: continue {med[0]}. Review in OPD with {p['doctor']} after 7 days.
"""
    content[rel] = txt.encode("utf-8")
    u = unit(rel, "doc", p["pid"])
    for t, s_ in [("PATIENT_NAME", full(p)), ("MRN", pid), ("RELATIVE_NAME", relname(p)), ("HOUSE", p["house"]),
                  ("VILLAGE", p["v"][0]), ("PIN", p["v"][4]), ("PHONE", ph)]:
        ent(u, t, s_, role="relative" if t == "RELATIVE_NAME" else "patient")
    if named_file:
        ent(u, "PATIENT_NAME", f"{p['f'][0]}_{p['s'][0]}", channel="filename")
        ent(u, "MRN", pid.replace("/", "-"), channel="filename")
    for x in [dx, icd, med[0], med[1], vit, pulse, spo2, lab, complaint, p["doctor"]]:
        keep(u, x)
    files[rel]["los"] = {"adm": p["adm"].isoformat(), "dis": p["dis"].isoformat(), "days": p["los"]}

# ------------------------------------------------------------------ Hindi prescriptions (Devanagari)
for k, p in enumerate(P[10:16]):
    rel = f"prescriptions/parchi_{k:02d}.txt"; newfile(rel, "text")
    dx, icd = p["dx"]; med = MEDS[icd]
    phd = "".join("०१२३४५६७८९"[int(c)] for c in p["phone"])
    txt = f"""{HOSP['ssc']} - पर्चा
मरीज़ का नाम: {deva(p)}   उम्र: {p['age']} वर्ष   लिंग: {'महिला' if p['g'] == 'F' else 'पुरुष'}
{'पति' if p['rel'] == 'W/o' else 'पिता'} का नाम: {relname_d(p)}
पता: ग्राम {p['v'][1]}, तहसील {p['v'][2]}, पिन {p['v'][4]}
मोबाइल: {phd}
निदान: {dx}
दवाइयाँ:
1. {med[0]}
2. {med[1]}
बुखार होने पर तुरंत दिखाएँ। {p['doctor']}
"""
    content[rel] = txt.encode("utf-8")
    u = unit(rel, "doc", p["pid"])
    ent(u, "PATIENT_NAME", deva(p), "deva"); ent(u, "RELATIVE_NAME", relname_d(p), "deva", role="relative")
    ent(u, "VILLAGE", p["v"][1], "deva"); ent(u, "PIN", p["v"][4], "deva"); ent(u, "PHONE", phd, "deva")
    for x in [dx, med[0], med[1], p["doctor"]]: keep(u, x)

# ------------------------------------------------------------------ Hinglish nursing notes (incl. fragment + canary)
CANARIES = ["Zubeida Fernandes", "Okonkwo Rathore"]
for k, p in enumerate(P[16:22]):
    rel = f"notes/nursing_{k:02d}.txt"; newfile(rel, "text")
    hon = "ji" if p["age"] > 50 else ("didi" if p["g"] == "F" else "bhaiya")
    bp = f"BP {R.randint(110, 160)}/{R.randint(70, 96)}"; rbs = f"RBS {R.randint(90, 320)} mg/dL"
    if k == 0:   # fragmented identity: first names only
        who = f"{p['f'][0]}, {p['rel']} {p['rf'][0]}"
        ents = [("PATIENT_NAME", p["f"][0]), ("RELATIVE_NAME", p["rf"][0])]
    else:
        who = f"{p['f'][0]} {p['s'][0]} {hon}"
        ents = [("PATIENT_NAME", f"{p['f'][0]} {p['s'][0]}")]
    txt = f"""Night shift note - {p['ward']} bed {R.randint(1, 30)}
{who} ka {bp} tha raat 2 baje, {rbs}. Patient ko ghabrahat ho rahi thi.
Unke {'husband' if p['rel'] == 'W/o' else 'father'} {p['rf'][0]} ji ne bataya ki ghar {p['v'][0]} mein hai, {p['landmark']}.
Phone pe baat hui: {phone_fmt(p['phone'], k + 1)}. {p['doctor']} ko inform kiya, Tab Paracetamol 650 mg diya.
"""
    if k == 2: txt += f"Visitor {CANARIES[0]} ne bed side pe file chhodi.\n"
    content[rel] = txt.encode("utf-8")
    u = unit(rel, "doc", p["pid"])
    for t, s_ in ents: ent(u, t, s_, "hinglish", role="relative" if t == "RELATIVE_NAME" else "patient")
    ent(u, "VILLAGE", p["v"][0], "hinglish"); ent(u, "LANDMARK", p["landmark"], "hinglish")
    ent(u, "PHONE", phone_fmt(p["phone"], k + 1), "hinglish")
    if k == 2: ent(u, "CANARY", CANARIES[0], "latin")
    for x in [bp, rbs, "Tab Paracetamol 650 mg", p["doctor"]]: keep(u, x)

# ------------------------------------------------------------------ OPD visits JSON (ssc)
rel = "opd/seva_sadan_visits.json"; newfile(rel, "json")
visits = []
for p in [q for q in P if "ssc" in q["ids"]] + P[2:6]:
    dx, icd = p["dx"]; med = MEDS[icd]
    v = {"opd_no": p["ids"].get("ssc", f"OPD-{R.randint(70000, 79999)}"), "patient": {"name": full(p), "mobile": p["phone"],
         "age": p["age"], "gender": p["g"]}, "visit_date": p["adm"].isoformat(), "doctor": p["doctor"],
         "diagnosis": dx, "rx": med[0],
         "notes": f"{p['f'][0]} sahab ki tabiyat theek hai, {med[0]} continue. C/O {relname(p)} ne dawai le li."}
    i = len(visits); visits.append(v)
    u = unit(rel, f"/visits/{i}", p["pid"])
    ent(u, "MRN", v["opd_no"]); ent(u, "PATIENT_NAME", full(p)); ent(u, "PHONE", p["phone"])
    ent(u, "RELATIVE_NAME", relname(p), "hinglish", role="relative")
    for x in [dx, med[0], p["doctor"]]: keep(u, x)
content[rel] = (json.dumps({"clinic": HOSP["ssc"], "visits": visits}, ensure_ascii=False, indent=1) + "\n").encode()

# ------------------------------------------------------------------ FHIR bundles (mmh)
for k, p in enumerate([q for q in P if "mmh" in q["ids"]]):
    rel = f"fhir/mmh_bundle_{k:02d}.json"; newfile(rel, "fhir")
    dx, icd = p["dx"]; hb = round(R.uniform(8, 14), 1)
    pat = {"resourceType": "Patient", "id": "pat1",
           "identifier": [{"system": "urn:mmh:mrn", "value": p["ids"]["mmh"]},
                          {"system": "https://healthid.abdm.gov.in", "value": p["abha"]}],
           "name": [{"text": full(p), "family": p["s"][0], "given": [p["f"][0]]}],
           "gender": "female" if p["g"] == "F" else "male", "birthDate": p["dob"].isoformat(),
           "telecom": [{"system": "phone", "value": "+91" + p["phone"]}],
           "address": [{"line": [p["house"]], "city": p["v"][0], "district": p["v"][3], "postalCode": p["v"][4]}],
           "contact": [{"relationship": [{"text": p["rel"]}], "name": {"text": relname(p)}}],
           "text": {"status": "generated", "div": f"<div xmlns=\"http://www.w3.org/1999/xhtml\">{full(p)}, {p['ids']['mmh']}</div>"}}
    enc = {"resourceType": "Encounter", "id": "enc1", "status": "finished",
           "class": {"system": "http://terminology.hl7.org/CodeSystem/v3-ActCode", "code": "IMP"},
           "subject": {"reference": "Patient/pat1"},
           "period": {"start": p["adm"].isoformat(), "end": p["dis"].isoformat()}}
    cond = {"resourceType": "Condition", "id": "c1", "subject": {"reference": "Patient/pat1"},
            "code": {"coding": [{"system": "http://hl7.org/fhir/sid/icd-10", "code": icd, "display": dx}], "text": dx}}
    obs = {"resourceType": "Observation", "id": "o1", "status": "final", "subject": {"reference": "Patient/pat1"},
           "code": {"text": "Haemoglobin"}, "valueQuantity": {"value": hb, "unit": "g/dL"}}
    b = {"resourceType": "Bundle", "type": "collection", "entry": [{"resource": r} for r in (pat, enc, cond, obs)]}
    content[rel] = (json.dumps(b, ensure_ascii=False, indent=2) + "\n").encode()
    u = unit(rel, "doc", p["pid"])
    for t, s_ in [("MRN", p["ids"]["mmh"]), ("ABHA_NUMBER", p["abha"]), ("PATIENT_NAME", full(p)), ("DOB", p["dob"].isoformat()),
                  ("PHONE", p["phone"]), ("HOUSE", p["house"]), ("VILLAGE", p["v"][0]), ("PIN", p["v"][4]),
                  ("RELATIVE_NAME", relname(p))]:
        ent(u, t, s_, role="relative" if t == "RELATIVE_NAME" else "patient")
    for x in [dx, icd, "Haemoglobin"]: keep(u, x)
    files[rel]["los"] = {"adm": p["adm"].isoformat(), "dis": p["dis"].isoformat(), "days": p["los"]}

# ------------------------------------------------------------------ lab reports named by phone number
for k, p in enumerate(P[6:9]):
    rel = f"lab/{p['phone']}_cbc_{k}.json"; newfile(rel, "json")
    plt = f"{R.randint(40, 300)},000"; tlc = f"{R.randint(4, 15)},{R.randint(100, 900)}"
    d = {"report": "CBC", "patient_name": full(p), "uhid": anyid(p), "results": [
        {"test": "Platelet count", "value": plt, "unit": "/cumm"}, {"test": "TLC", "value": tlc, "unit": "/cumm"}],
        "referred_by": p["doctor"]}
    content[rel] = (json.dumps(d, ensure_ascii=False, indent=2) + "\n").encode()
    u = unit(rel, "doc", p["pid"])
    ent(u, "PATIENT_NAME", full(p)); ent(u, "MRN", anyid(p)); ent(u, "PHONE", p["phone"], channel="filename")
    for x in [plt, tlc, "Platelet count", p["doctor"]]: keep(u, x)

# ------------------------------------------------------------------ billing CSV (PAN, insurance, canary in remarks)
rel = "billing/claims_q3.csv"; newfile(rel, "csv", delimiter=",")
rows = ["claim_id,beneficiary,pan,policy_no,amount_inr,package,remarks"]
for n, p in enumerate(P[::3]):
    rem = f"Pre-auth by {CANARIES[1]}" if n == 2 else "Approved"
    pkg = p["dx"][0]
    rows.append(",".join([f"CLM{R.randint(100000, 999999)}", full(p), p["pan"], p["ins"], str(R.randint(4000, 60000)), pkg, rem]))
    u = unit(rel, f"row:{n}", p["pid"])
    # DATASET.md linkability: a name alone (PAN / policy numbers appear nowhere else) is not enough
    u["link"] = "required" if "sch" in p["ids"] else "ambiguous"
    ent(u, "PATIENT_NAME", full(p)); ent(u, "PAN", p["pan"]); ent(u, "INSURANCE_ID", p["ins"])
    if n == 2: ent(u, "CANARY", CANARIES[1])
    keep(u, pkg)
content[rel] = ("\n".join(rows) + "\n").encode()

# ------------------------------------------------------------------ hidden places
rel = "misc/ward_index.json"; newfile(rel, "json")   # names + MRNs as JSON keys, metadata path
idx = {full(p): {"uhid": anyid(p), "ward": p["ward"]} for p in P[:4]}
d = {"_export_meta": {"source_path": f"/exports/{P[0]['f'][0]}_{P[0]['s'][0]}/ward.xlsx"}, "index": idx}
content[rel] = (json.dumps(d, ensure_ascii=False, indent=2) + "\n").encode()
u = unit(rel, "@file")
for p in P[:4]:
    ent(u, "PATIENT_NAME", full(p), channel="key"); ent(u, "MRN", anyid(p))
ent(u, "PATIENT_NAME", f"{P[0]['f'][0]}_{P[0]['s'][0]}", channel="metadata")

rel = "misc/vitals_wide.csv"; newfile(rel, "csv", delimiter=",")   # patient names in CSV headers
hdr = ["time"] + [p["f"][0] + " " + p["s"][0] for p in P[4:7]]
rows = [",".join(hdr)] + [",".join([f"{h:02d}:00"] + [str(R.randint(90, 160)) for _ in range(3)]) for h in (6, 12, 18)]
content[rel] = ("\n".join(rows) + "\n").encode()
u = unit(rel, "@header")
for p in P[4:7]: ent(u, "PATIENT_NAME", full(p), channel="header")

rel = "misc/referral_with_attachment.json"; newfile(rel, "json")   # PII inside base64 attachment
p = P[9]
att = base64.b64encode(f"Referral letter for {full(p)}, mobile {p['phone']}, Aadhaar {p['aadhaar']}".encode()).decode()
d = {"type": "referral", "to": HOSP["mmh"], "reason": p["dx"][0], "attachment": {"contentType": "text/plain", "data": att}}
content[rel] = (json.dumps(d, indent=2) + "\n").encode()
u = unit(rel, "doc", p["pid"])
ent(u, "PATIENT_NAME", full(p), channel="base64"); ent(u, "PHONE", p["phone"], channel="base64")
ent(u, "AADHAAR", p["aadhaar"], channel="base64"); keep(u, p["dx"][0])

# ------------------------------------------------------------------ broken / unsupported (expect either)
p = P[12]
rel = "misc/export_truncated.json"; newfile(rel, "json", expect="either")
content[rel] = ('{"patient": "%s", "mobile": "%s", "visits": [{"date": "2026-0' % (full(p), p["phone"])).encode()
u = unit(rel, "doc"); ent(u, "PATIENT_NAME", full(p)); ent(u, "PHONE", p["phone"])
rel = "misc/scan_0042.pdf"; newfile(rel, "pdf", expect="either")
content[rel] = b"%PDF-1.4\n1 0 obj << /Title (" + full(P[13]).encode() + b") >>\nendobj\n%%EOF\n"
u = unit(rel, "doc"); ent(u, "PATIENT_NAME", full(P[13]))
rel = "misc/empty_upload.txt"; newfile(rel, "text", expect="either"); content[rel] = b""; files[rel]["units"] = {}

# ------------------------------------------------------------------ write
if ROOT.exists():
    shutil.rmtree(IN, ignore_errors=True); shutil.rmtree(TR, ignore_errors=True)
for rel, b in content.items():
    path = IN / rel; path.parent.mkdir(parents=True, exist_ok=True); path.write_bytes(b)
    files[rel]["sha256"] = hashlib.sha256(b).hexdigest(); files[rel]["size"] = len(b)
TR.mkdir(parents=True, exist_ok=True)
truth = {"schema": "raksha-truth/1", "generator_version": "synth-1", "seed": "20261126", "ref_date": REF.isoformat(),
         "files": files, "canaries": ["CANARY-A", "CANARY-B"],
         "patients": {p["pid"]: {"hospitals": sorted(p["ids"]), "uhids": p["ids"], "name": full(p)} for p in P},
         "traps": {"homonym_pairs": [["SY000", "SY023"]], "fragmented": ["SY016"], "rare_dx": ["SY005", "SY011"]}}
(TR / "truth.json").write_text(json.dumps(truth, ensure_ascii=False, indent=1, default=str), encoding="utf-8")
ne = sum(len(u["entities"]) for f in files.values() for u in f["units"].values())
npv = sum(len(u["preserve"]) for f in files.values() for u in f["units"].values())
print(f"files {len(files)}  entities {ne}  preserve-probes {npv}  patients {len(P)}")
