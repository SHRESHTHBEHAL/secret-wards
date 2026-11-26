"""DEV TOOL. Adversarial free-text generator: hard name / ID / label variants plus meaning traps (check_dev-compatible truth).

python3 scripts/synth_gen3.py <out_dir> <seed>
"""
import hashlib, json, random, shutil, sys
from pathlib import Path

ROOT = Path(sys.argv[1]); SEED = int(sys.argv[2]) if len(sys.argv) > 2 else 1
R = random.Random(SEED * 104729 + 7)
IN, TR = ROOT / "input", ROOT / "truth"
GF = ["Kavitha", "Shalini", "Farzana", "Rupinder", "Bhagyashree", "Nandini", "Tanvi", "Rukhsana", "Yamini", "Chitra"]
GM = ["Murali", "Harish", "Zubair", "Sukhwinder", "Omkar", "Prasanth", "Dinesh", "Arvind", "Kamran", "Yogesh"]
SN = ["Murugan", "Kulkarni", "Siddiqui", "Gill", "Iyer", "Banerjee", "Rathod", "Choudhary", "Kapoor", "Hegde"]
VILL = ["Kothrud", "Nanded", "Sangli", "Jalna", "Wardha", "Latur"]
DOCF = ["Dr. Kavitha Rao", "Dr. Harish Menon", "Dr. Farzana Ali"]   # doctors share first names with patients
MEDS = ["Dolo 650 1-0-1 x 3 days", "Crocin 500 mg SOS", "Tab Thyronorm 50 mcg OD", "Inj Monocef 1 g IV BD",
        "Tab Telma-H 1-0-0", "Syp Grilinctus 5 ml TDS", "Tab Pan-D 40 mg OD before food"]
DXS = ["Parkinson's disease", "Down syndrome", "Bell's palsy", "Hashimoto's thyroiditis", "Cushing's syndrome",
       "Graves disease", "Wilson disease", "Addison's disease"]
VIT = ["BP 136/88 mmHg", "SpO2 97% on RA", "Temp 99.4 F", "RR 18/min", "Pulse 92 bpm", "GRBS 182 mg/dL"]


def dg(n): return "".join(R.choice("0123456789") for _ in range(n))


files, content = {}, {}
def nf(rel): files[rel] = {"path": rel, "format": "text", "expect": "sanitize", "units": {}}
def u_(rel): return files[rel]["units"].setdefault("doc", {"loc": "doc", "patient": None, "link": "none", "entities": [], "preserve": []})
def ent(u, t, s, sc="latin", ch="content", role="patient"): u["entities"].append({"type": t, "surface": s, "script": sc, "channel": ch, "role": role})
def keep(u, s): u["preserve"].append({"text": s})

for k in range(40):
    g = R.choice("FM"); f = R.choice(GF if g == "F" else GM); s = R.choice(SN); rf = R.choice(GM); age = R.randint(19, 84)
    phone = R.choice("6789") + dg(9); uh = f"{R.choice(['NMC', 'SVH', 'KGH'])}/{R.randint(20, 26)}/{dg(6)}"
    aad = R.choice("23456789") + dg(11); vill = R.choice(VILL); med = R.choice(MEDS); dx = R.choice(DXS); vit = R.choice(VIT)
    doc = next((d for d in DOCF if d.split()[1] == f), R.choice(DOCF)); email = f"{f.lower()}.{s.lower()}{R.randint(1, 99)}@gmail.com"
    style = k % 10
    rel = f"notes/note_{k:03d}.txt"; nf(rel); u = u_(rel)
    if style == 0:
        name = f"{f.upper()} {s.upper()}"; line = f"PATIENT: {name}   AGE/SEX: {age}/{g}\nMOB: {phone[:2]} {phone[2:5]} {phone[5:]}\n"
        ent(u, "PATIENT_NAME", name); ent(u, "PHONE", f"{phone[:2]} {phone[2:5]} {phone[5:]}")
    elif style == 1:
        name = f"{s.upper()}, {f.upper()}"; line = f"Patinet Nmae: {name}\nContact no:- {phone[:4]}-{phone[4:7]}-{phone[7:]}\n"
        ent(u, "PATIENT_NAME", f"{s.upper()}, {f.upper()}"); ent(u, "PHONE", f"{phone[:4]}-{phone[4:7]}-{phone[7:]}")
    elif style == 2:
        name = f"{f[0]}. {s}"; line = f"Pt {name} ({age} y/o {'female' if g == 'F' else 'male'}) seen in OPD. UHID {uh}.\n"
        ent(u, "PATIENT_NAME", name); ent(u, "MRN", uh)
    elif style == 3:
        name = f"{f.lower()} {s.lower()}"; line = f"night note: {name} ji ko neend nahi aayi. {'husband' if g == 'F' else 'father'} {rf.lower()} ji saath hain.\n"
        ent(u, "PATIENT_NAME", name, "hinglish"); ent(u, "RELATIVE_NAME", rf.lower(), "hinglish", role="relative")
    elif style == 4:
        name = f"{f} {s}"; line = f"Referred {name} (D.O.B 12th May {2026 - age}), email {email}, Aadhaar {aad[:4]}  {aad[4:8]}  {aad[8:]}.\n"
        ent(u, "PATIENT_NAME", name); ent(u, "DOB", f"12th May {2026 - age}"); ent(u, "EMAIL", email); ent(u, "AADHAAR", f"{aad[:4]}  {aad[4:8]}  {aad[8:]}")
    elif style == 5:
        name = f"Smt. {f} {s}" if g == "F" else f"Shri {f} {s}"; line = f"{name}, r/o {vill}, ph {phone}. (husband: {rf} {s})\n"
        ent(u, "PATIENT_NAME", f"{f} {s}"); ent(u, "VILLAGE", vill); ent(u, "PHONE", phone); ent(u, "RELATIVE_NAME", f"{rf} {s}", role="relative")
    elif style == 6:
        name = f"{f} {s}"; line = f"{f} ki maa {R.choice(GF)} {s} ne bataya ki {f} ko 3 din se bukhar hai. ref no {uh}\n"
        ent(u, "PATIENT_NAME", f), ent(u, "MRN", uh)
        mom = line.split(" ki maa ")[1].split(" ne ")[0]; ent(u, "RELATIVE_NAME", mom, "hinglish", role="relative")
    elif style == 7:
        name = f"{f} {s}"; line = f"Pat1ent Narne: {name}\nPh0ne: {phone}\nAge: {age} Yrs\n"
        ent(u, "PATIENT_NAME", name); ent(u, "PHONE", phone)
    elif style == 8:
        name = f"{f} {s}"; line = f"To,\nThe Medical Officer\nSub: certificate for {name}, {uh}\nThis is to certify that {f} {s} was under treatment.\n"
        ent(u, "PATIENT_NAME", name); ent(u, "MRN", uh)
    else:
        name = f"{f} {s}"; line = f"Caller {R.choice(GM)} {R.choice(SN)} enquired about {name} (bed 12). Told to call {phone[:5]} {phone[5:]}.\n"
        ent(u, "PATIENT_NAME", name); ent(u, "PHONE", f"{phone[:5]} {phone[5:]}")
    txt = line + f"Dx: {dx}. {vit}. Rx: {med}. Seen by {doc}.\n"
    content[rel] = txt.encode()
    for x in (dx, vit, med, doc): keep(u, x)

shutil.rmtree(IN, ignore_errors=True); shutil.rmtree(TR, ignore_errors=True)
for rel, b in content.items():
    p = IN / rel; p.parent.mkdir(parents=True, exist_ok=True); p.write_bytes(b); files[rel]["sha256"] = hashlib.sha256(b).hexdigest()
TR.mkdir(parents=True, exist_ok=True)
(TR / "truth.json").write_text(json.dumps({"schema": "raksha-truth/1", "files": files, "patients": {}, "canaries": [],
                                           "traps": {"homonym_pairs": []}}, indent=1), encoding="utf-8")
bad = sum(1 for rel, f in files.items() for u in f["units"].values() for e in u["entities"] + [{"surface": x["text"]} for x in u["preserve"]]
          if e["surface"] not in content[rel].decode())
print(f"seed {SEED}: notes {len(files)} entities {sum(len(u['entities']) for f in files.values() for u in f['units'].values())} missing {bad}")
