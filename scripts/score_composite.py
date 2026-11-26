"""DEV TOOL. Approximate the official Secret Wards score (docs/SCORING.md + scoring.toml) on the synthetic set.

Computable parts follow the published formulas; the hidden attacker (A2-A5) is approximated by
direct/quasi-identifier exposure. Usage:
  score.py <output_dir> <truth.json> <input_dir> --wall S --rss MB --deterministic 0|1 --exit 0
"""
import argparse, collections, sys, csv, datetime as dt, io, itertools, json, math, re, unicodedata
from pathlib import Path

ap = argparse.ArgumentParser()
ap.add_argument("out"); ap.add_argument("truth"); ap.add_argument("inp")
ap.add_argument("--wall", type=float, required=True); ap.add_argument("--rss", type=float, required=True)
ap.add_argument("--deterministic", type=float, required=True); ap.add_argument("--exit", type=int, default=0)
a = ap.parse_args()
OUT, IN = Path(a.out), Path(a.inp)
T = json.loads(Path(a.truth).read_text(encoding="utf-8"))
DEVA = str.maketrans("०१२३४५६७८९", "0123456789")
B64 = re.compile(r"[A-Za-z0-9+/]{24,}={0,2}")


def norm(s):
    s = unicodedata.normalize("NFKC", s).translate(DEVA)
    s = "".join(c for c in unicodedata.normalize("NFKD", s) if not unicodedata.combining(c) or "ऀ" <= c <= "ॿ")
    return " ".join(s.casefold().split())


def read(p):
    try:
        t = p.read_bytes().decode("utf-8", "replace")
    except OSError:
        return ""
    import base64
    extra = []
    for m in B64.finditer(t):
        try:
            extra.append(base64.b64decode(m.group() + "=" * (-len(m.group()) % 4)).decode("utf-8", "ignore"))
        except Exception:
            pass
    return t + "\n" + "\n".join(extra)


rep = json.loads((OUT / "report.json").read_text(encoding="utf-8")) if (OUT / "report.json").is_file() else {"files": []}
by_sha = {f.get("input_sha256"): f for f in rep.get("files") or []}
recs = collections.defaultdict(dict); claims = []
if (OUT / "records.jsonl").is_file():
    for ln in (OUT / "records.jsonl").read_text(encoding="utf-8").splitlines():
        if ln.strip():
            r = json.loads(ln); f = str(r["file"]).replace("sanitized/", "", 1)
            recs[f][r["loc"]] = r.get("patient"); claims.append((f, r["loc"], r.get("patient")))


def out_rel(rel, f):
    e = by_sha.get(f["sha256"])
    return str(e["output"]).replace("sanitized/", "", 1) if e and e.get("output") else (rel if not e else None)


def rec_for(loc, m):
    if loc in m: return m[loc]
    if loc.startswith("/"):
        parts = loc.split("/")
        for i in range(len(parts) - 1, 1, -1):
            if "/".join(parts[:i]) in m: return m["/".join(parts[:i])]
    return m.get("doc")


# ---------------------------------------------------------------- leaks / probes
TW = {"AADHAAR": 1, "ABHA_NUMBER": 1, "PHONE": 1, "EMAIL": 1, "MRN": 1, "PAN": 1, "INSURANCE_ID": .8, "PATIENT_NAME": 1,
      "RELATIVE_NAME": .8, "DOB": .7, "HOUSE": .6, "LOCALITY": .6, "LANDMARK": .5, "VILLAGE": .5, "PIN": .5, "AADHAAR_MASKED": .5}
DIRECT = {"AADHAAR", "ABHA_NUMBER", "PHONE", "EMAIL", "MRN", "PAN", "INSURANCE_ID"}
tl, tk, sl, sk = collections.Counter(), collections.Counter(), collections.Counter(), collections.Counter()
p_ok = p_all = 0; canary_hit = set(); canaries = set()
exposed = collections.defaultdict(set)   # patient -> exposed surfaces (direct ids / full names)
quasi = collections.defaultdict(bool); patients_seen = set()
unit_pat = {}; los_ok = los_all = 0; tok_in = tok_kept = 0; file_texts = {}
all_out = norm("\n".join([p.name for p in OUT.rglob("*")] + [read(p) for p in OUT.rglob("*") if p.is_file()]))
for rel, f in T["files"].items():
    o = out_rel(rel, f); path = OUT / "sanitized" / o if o else None
    exists = bool(path and path.is_file()); text = norm(read(path)) if exists else ""; file_texts[rel] = text
    fname = norm(o or "")
    for loc, u in f["units"].items():
        pat = u.get("patient")
        if pat: patients_seen.add(pat)
        for e in u["entities"]:
            s = norm(e["surface"])
            if e["type"] == "CANARY":
                canaries.add(s); continue
            hay = fname if e["channel"] == "filename" else text
            hit = bool(s) and (exists or e["channel"] == "filename") and s in hay
            tl[e["type"]] += hit; tk[e["type"]] += 1; sl[e["script"]] += hit; sk[e["script"]] += 1
            if hit and pat and (e["type"] in DIRECT or (e["type"] == "PATIENT_NAME" and " " in e["surface"].strip())):
                exposed[pat].add(s)
            if hit and pat and e["type"] in ("DOB", "VILLAGE"):
                quasi[pat] = True
        if exists:
            for pv in u.get("preserve") or []:
                p_all += 1; p_ok += norm(pv["text"]) in text
        if u.get("link") == "required" and pat:
            unit_pat[(rel, loc)] = (pat, rec_for(loc, recs.get(o or rel, {})) if o else None)
    if "los" in f:
        los_all += 1
        if exists:
            ds = set()
            raw = read(path)
            for m in re.finditer(r"(\d{4})-(\d{2})-(\d{2})", raw):
                try: ds.add(dt.date(int(m[1]), int(m[2]), int(m[3])))
                except ValueError: pass
            for m in re.finditer(r"(\d{1,2})/(\d{1,2})/(\d{4})", raw):
                try: ds.add(dt.date(int(m[3]), int(m[2]), int(m[1])))
                except ValueError: pass
            los_ok += any((y - x).days == f["los"]["days"] for x in ds for y in ds)
            adm = dt.date.fromisoformat(f["los"]["adm"])
            for u in f["units"].values():   # unshifted admission date surviving = targeted-attack exposure
                if u.get("patient") and adm in ds: quasi[u["patient"]] = True
    if f.get("expect") == "sanitize" and f["units"]:
        src = norm(read(IN / rel)); pii_tok = {w for u in f["units"].values() for e in u["entities"] for w in norm(e["surface"]).split()}
        cin = collections.Counter(w for w in re.findall(r"[a-zऀ-ॿ]{3,}", src) if w not in pii_tok)
        cout = collections.Counter(re.findall(r"[a-zऀ-ॿ]{3,}", text))
        tok_in += sum(cin.values()); tok_kept += sum(min(c, cout[w]) for w, c in cin.items())
canary_hit = {c for c in canaries if c in all_out}

recall = 0.5 * sum(TW.get(t, .5) * (1 - tl[t] / tk[t]) for t in tk) / sum(TW.get(t, .5) for t in tk) \
         + 0.5 * sum(1 - sl[s] / sk[s] for s in sk) / len(sk)
cprec = p_ok / p_all if p_all else 0
detection = 5 * cprec * recall / (4 * cprec + recall) if cprec + recall else 0

# ---------------------------------------------------------------- identity
units = list(unit_pat.values()); has_psn = any(y for _, y in units)
def pairs(idx):
    return [(i, j) for i, j in itertools.combinations(idx, 2)]
by_true = collections.defaultdict(list); by_mine = collections.defaultdict(list)
for i, (t, y) in enumerate(units):
    by_true[t].append(i)
    if y: by_mine[y].append(i)
tp = sum(units[i][0] == units[j][0] for m in by_mine.values() for i, j in pairs(m))
fp = sum(units[i][0] != units[j][0] for m in by_mine.values() for i, j in pairs(m))
tpairs = sum(len(v) * (len(v) - 1) // 2 for v in by_true.values())
P_ = tp / (tp + fp) if tp + fp else 0; R_ = tp / tpairs if tpairs else 0
f05 = 1.25 * P_ * R_ / (0.25 * P_ + R_) if P_ + R_ else 0
b3p = b3r = 0
for i, (t, y) in enumerate(units):
    mine = set(by_mine[y]) if y else {i}; true = set(by_true[t])
    b3p += len(mine & true) / len(mine); b3r += len(mine & true) / len(true)
b3p /= max(1, len(units)); b3r /= max(1, len(units)); b3 = 2 * b3p * b3r / (b3p + b3r) if b3p + b3r else 0
def trap_recall(pids, files_pred):
    idx = [i for i, k in enumerate(unit_pat) if units[i][0] in pids and files_pred(k[0])]
    ok = tot = 0
    for i in idx:
        for j in by_true[units[i][0]]:
            if j == i: continue
            tot += 1; ok += bool(units[i][1]) and units[i][1] == units[j][1]
    return ok / tot if tot else 0
lang = trap_recall({u[0] for k, u in unit_pat.items() if k[0].startswith("prescriptions/")}, lambda r: r.startswith("prescriptions/"))
frag = trap_recall(set(T["traps"]["fragmented"]), lambda r: True)
homo = 1.0
for x, y in T["traps"]["homonym_pairs"]:
    px = {u[1] for u in units if u[0] == x and u[1]}; py = {u[1] for u in units if u[0] == y and u[1]}
    homo = 0.0 if px & py else homo
identity = (0.4 * f05 + 0.3 * b3 + 0.1 * lang + 0.1 * frag + 0.1 * homo) if has_psn else 0.0

# ---------------------------------------------------------------- utility
gen_s = gen_n = 0
reg = T["files"].get("registration/narmada_reg_2026.csv")
if reg:
    o = out_rel("registration/narmada_reg_2026.csv", reg); src = list(csv.DictReader(io.StringIO((IN / "registration/narmada_reg_2026.csv").read_text())))
    outp = OUT / "sanitized" / o if o else None
    dst = list(csv.DictReader(io.StringIO(outp.read_text(encoding="utf-8")))) if outp and outp.is_file() else []
    for i, s in enumerate(src):
        d = dst[i] if i < len(dst) else {}
        age = int(s["Age"]); v = (d.get("Age") or "").strip(); m = re.match(r"^(\d+)\s*[-–]\s*(\d+)", v)
        sc = 1.0 if v == s["Age"] else (0 if not m else (0 if not int(m[1]) <= age <= int(m[2]) else
             (.9 if int(m[2]) - int(m[1]) < 5 + 1 else .8 if int(m[2]) - int(m[1]) <= 10 else .6 if int(m[2]) - int(m[1]) <= 20 else .3)))
        gen_s += sc; gen_n += 1
        vv = (d.get("Village") or "").strip()
        gen_s += 1.0 if vv == s["Village"] else .8 if vv == s["Tehsil"] else .7 if vv == s["District"] or (d.get("District") or "").strip() == s["District"] else 0; gen_n += 1
        pv = (d.get("PIN") or "").strip()
        gen_s += 1.0 if pv == s["PIN"] else .7 if pv[:3] == s["PIN"][:3] and len(re.sub(r"\D", "", pv)) >= 3 else 0; gen_n += 1
generalization = gen_s / gen_n if gen_n else 0
dx_files = [r for r, f in T["files"].items() if any(re.match(r"^[A-Z]\d{2}(\.\d)?$", pv["text"]) for u in f["units"].values() for pv in u["preserve"])]
stats = (sum(any(norm(pv["text"]) in file_texts[r] for u in T["files"][r]["units"].values() for pv in u["preserve"]
                 if re.match(r"^[A-Z]\d{2}(\.\d)?$", pv["text"])) for r in dx_files) / len(dx_files) if dx_files else 0) * .5 \
        + (los_ok / los_all if los_all else 0) * .5
san_expected = [r for r, f in T["files"].items() if f.get("expect") == "sanitize"]
rec_ret = sum(bool(file_texts[r]) for r in san_expected) / len(san_expected)
probes = p_ok / p_all if p_all else 0
temporal = los_ok / los_all if los_all else 0
token_ret = tok_kept / tok_in if tok_in else 0
utility = .35 * probes + .20 * temporal + .10 * generalization + .15 * stats + .10 * token_ret + .10 * rec_ret

# ---------------------------------------------------------------- privacy (attacker approximated)
pts = sorted(patients_seen)
a1 = sum(bool(exposed[p]) for p in pts) / len(pts)
aq = sum(quasi[p] or bool(exposed[p]) for p in pts) / len(pts)   # stand-in for A2-A5 (DOB/village/unshifted date/direct)
a6 = 0.0
risk = (0.2 * a1 + 0.6 * aq + 0.1 * a6) / (0.9 if has_psn else 0.8) if has_psn else (0.2 * a1 + 0.6 * aq) / 0.8
privacy = (1 - risk) * min(1, utility / 0.40)

# ---------------------------------------------------------------- integrity
import subprocess
import os
_KIT = os.environ.get("KIT", str(Path(__file__).resolve().parents[1].parent / "Secret-Wards-ToolKit"))
v = subprocess.run([sys.executable, os.path.join(_KIT, "validate_output.py"), "--input", str(IN), "--output", str(OUT)],
                   capture_output=True, text=True).stdout
fmt_ok = 1.0 if "CONTRACT OK" in v else 0.0
fh = [r for r, f in T["files"].items() if f["format"] == "fhir"]
def fhir_ok(r):
    o = out_rel(r, T["files"][r]); p = OUT / "sanitized" / o if o else None
    try:
        b = json.loads(p.read_text(encoding="utf-8")); return b.get("resourceType") == "Bundle" and all("resourceType" in e["resource"] for e in b["entry"])
    except Exception: return False
fhir = sum(fhir_ok(r) for r in fh) / len(fh) if fh else 1
def schema_ok(r):
    f = T["files"][r]; o = out_rel(r, f); p = OUT / "sanitized" / o if o else None
    if not (p and p.is_file()): return 0
    if f["format"] in ("csv", "tsv"):
        d = "\t" if f["format"] == "tsv" else ","
        a_ = list(csv.reader(io.StringIO((IN / r).read_text(encoding="utf-8")), delimiter=d)); b_ = list(csv.reader(io.StringIO(p.read_text(encoding="utf-8")), delimiter=d))
        return float(len(a_) == len(b_) and all(len(x) == len(y) for x, y in zip(a_, b_)))
    if f["format"] in ("json", "fhir"):
        def paths(o_, pre=""):
            if isinstance(o_, dict): return set().union(*[paths(v_, pre + "/" + k) for k, v_ in o_.items()]) | {pre}
            if isinstance(o_, list): return set().union(*[paths(v_, pre + "/*") for v_ in o_]) | {pre} if o_ else {pre}
            return {pre}
        try: x, y = paths(json.loads((IN / r).read_text())), paths(json.loads(p.read_text(encoding="utf-8")))
        except Exception: return 0
        return len(x & y) / len(x | y)
    a_, b_ = (IN / r).read_text(encoding="utf-8").count("\n"), p.read_text(encoding="utf-8").count("\n")
    return min(a_, b_) / max(a_, b_) if max(a_, b_) else 1
schema = sum(schema_ok(r) for r in san_expected) / len(san_expected)
ps_claims = [(f, l, y) for f, l, y in claims if y]
ps_cons = sum(y in read(OUT / "sanitized" / f) for f, l, y in ps_claims) / len(ps_claims) if ps_claims else 0
surf = {norm(e["surface"]) for f in T["files"].values() for u in f["units"].values() for e in u["entities"] if len(e["surface"]) > 4}
chan = []
for nm in ("report.json", "records.jsonl"):
    t_ = norm(read(OUT / nm)); chan.append(0 if any(s in t_ for s in surf) else 1)
names = norm(" ".join(str(p.relative_to(OUT)) for p in OUT.rglob("*")))
chan.append(0 if any(s.replace(" ", "_") in names or s in names for s in surf) else 1)
extra = [p for p in OUT.iterdir() if p.name not in ("sanitized", "report.json", "records.jsonl")]
chan.append(0.5 if extra else 1)
hygiene = sum(chan) / len(chan)
either = [r for r, f in T["files"].items() if f.get("expect") == "either"]
raw_copies = sum(1 for r in either if (lambda o: o and (OUT / "sanitized" / o).is_file() and (OUT / "sanitized" / o).read_bytes() == (IN / r).read_bytes())(out_rel(r, T["files"][r])) and T["files"][r]["units"])
listed = sum(f["sha256"] in by_sha for f in T["files"].values()) / len(T["files"])
quar = 0.5 * (1 - raw_copies / max(1, len(either))) + 0.3 * listed + 0.2 * (1 - raw_copies / max(1, len(either)))
c = rep.get("counts", {}); real_s = sum(1 for e in rep.get("files", []) if e.get("output") and (OUT / e["output"]).is_file())
honest = float(c.get("files_total") == len(T["files"]) and c.get("files_sanitized") == real_s and c.get("files_quarantined") == len(T["files"]) - real_s)
complete = float(all(k in rep for k in ("files", "counts", "timing", "resources")) and listed == 1)
report_q = 0.5 * complete + 0.5 * honest
integrity = .15 * fmt_ok + .20 * schema + .15 * fhir + .10 * ps_cons + .15 * hygiene + .15 * quar + .10 * report_q

# ---------------------------------------------------------------- performance
loglin = lambda x, good, lim: 1.0 if x <= good else 0.0 if x >= lim else 1 - math.log(x / good) / math.log(lim / good)
perf = .3 * (1.0 if a.exit == 0 else .3) + .3 * loglin(a.wall, 60, 900) + .2 * loglin(max(a.rss, 1), 512, 4096) + .2 * a.deterministic

# ---------------------------------------------------------------- penalties
uniq_direct = set().union(*exposed.values()) if exposed else set()
pen = min(25, len(uniq_direct)) + min(15, 3 * len(canary_hit)) + min(20, 5 * raw_copies)
cats = {"detection": (detection, 20), "identity": (identity, 15), "privacy": (privacy, 25), "utility": (utility, 20),
        "integrity": (integrity, 10), "performance": (perf, 10)}
total = sum(s * w for s, w in cats.values()) - pen
print(json.dumps({"total": round(total, 2), "penalty": pen,
                  "categories": {k: {"score": round(s, 3), "points": round(s * w, 2), "of": w} for k, (s, w) in cats.items()},
                  "detail": {"recall": round(recall, 3), "context_precision(probes kept)": round(cprec, 3),
                             "leak_pct": round(100 * sum(tl.values()) / sum(tk.values()), 2),
                             "leak_by_script": {s: round(100 * sl[s] / sk[s], 1) for s in sk},
                             "pairwise_P": round(P_, 3), "pairwise_R": round(R_, 3), "F0.5": round(f05, 3), "B3_F1": round(b3, 3),
                             "lang_trap": round(lang, 3), "frag_trap": round(frag, 3), "homonym_sep": homo,
                             "LOS_kept": f"{los_ok}/{los_all}", "generalization": round(generalization, 3), "token_retention": round(token_ret, 3),
                             "A1_direct_exposure": round(a1, 3), "quasi_exposure": round(aq, 3), "canaries": len(canary_hit),
                             "unique_direct_ids_or_full_names_leaked": len(uniq_direct), "raw_copies": raw_copies,
                             "schema": round(schema, 3), "fhir": round(fhir, 3), "pseudonym_consistency": round(ps_cons, 3),
                             "hygiene": round(hygiene, 3), "report_honest": honest, "contract": bool(fmt_ok)}}, indent=1))
