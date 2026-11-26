"""Hostile inputs, determinism, secrets and format round-trips, run through main.py as a subprocess.

All data is invented. Every run gets private, empty TMPDIR and HOME folders, which must stay empty.
The slow cases (30 MB CSV, 5 MB JSON string, 5,000 columns) run only with RAKSHA_STRESS=1.
"""
from __future__ import annotations

import csv
import hashlib
import io
import json
import os
import re
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from typing import Dict, List, Optional, Tuple

REPO = Path(__file__).resolve().parent.parent
MAIN = REPO / "main.py"
SECRET = "zq9X-wardtest-SECRET-7731-kappa"
STRESS = os.environ.get("RAKSHA_STRESS") == "1"

_STDOUT_OK = re.compile(r"^files \d+ sanitized \d+ quarantined \d+ records \d+ linked \d+$")
_STDERR_OK = re.compile(r"^raksha: [A-Za-z_]+ in [a-z_]+$")

# Invented people (formats only resemble the real ones).
PEOPLE = [
    ("Tarvin Oglekar", "9812307745", "UHX-0048123", "1998-04-17"),
    ("Meenal Wadkarni", "9734002186", "UHX-0048777", "1985-11-02"),
    ("Javesh Pundhir", "8890123476", "UHX-0049310", "1972-06-30"),
]


def sha(b: bytes) -> str:
    return hashlib.sha256(b).hexdigest()


def reg_csv(people=PEOPLE, nl: str = "\n", delim: str = ",") -> str:
    rows = [delim.join(["patient_id", "name", "phone", "dob", "visit_date", "diagnosis", "bp"])]
    for i, (n, ph, uh, dob) in enumerate(people):
        rows.append(delim.join([uh, n, ph, dob, "2026-0%d-1%d" % (i + 3, i + 2), "Type 2 diabetes", "130/8%d" % i]))
    return nl.join(rows) + nl


def note(p=PEOPLE[0]) -> str:
    n, ph, uh, dob = p
    return ("Discharge summary\nPatient: %s\nUHID: %s\nContact: %s\nAdmitted 2026-03-12, discharged 2026-03-19.\n"
            "Tab Metformin 500 mg 1-0-1\nBP 130/80 mmHg\n" % (n, uh, ph))


def opd_json(people=PEOPLE) -> str:
    return json.dumps({"visits": [{"patient": {"name": n, "mobile": ph, "uhid": uh},
                                   "date": "2026-05-0%d" % (i + 1), "complaint": "fever x 3 days",
                                   "rx": "Paracetamol 650 mg SOS"} for i, (n, ph, uh, _) in enumerate(people)]},
                      indent=1)


def regular_files(root: Path) -> List[Path]:
    out = []
    for dp, dn, fn in os.walk(str(root), followlinks=False):
        for f in fn:
            p = Path(dp) / f
            if not p.is_symlink() and p.is_file():
                out.append(p)
    return out


def tree_digest(root: Path) -> str:
    h = hashlib.sha256()
    for p in sorted(regular_files(root)):
        if not os.access(str(p), os.R_OK):
            h.update(p.relative_to(root).as_posix().encode("utf-8", "surrogateescape") + b"\0<unreadable>")
            continue
        h.update(p.relative_to(root).as_posix().encode("utf-8", "surrogateescape") + b"\0" + p.read_bytes())
    return h.hexdigest()


def out_digest(out: Path) -> str:
    h = hashlib.sha256()
    san = out / "sanitized"
    for p in sorted(regular_files(san)) if san.is_dir() else []:
        h.update(p.relative_to(san).as_posix().encode() + b"\0" + p.read_bytes())
    rec = out / "records.jsonl"
    h.update(rec.read_bytes() if rec.is_file() else b"<none>")
    return h.hexdigest()


class Base(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        self.inp = self.root / "in"
        self.inp.mkdir()
        self.out = self.root / "out"
        self.tmpdir = self.root / "tmp"
        self.home = self.root / "home"
        self.tmpdir.mkdir()
        self.home.mkdir()

    def tearDown(self):
        for dp, dn, fn in os.walk(str(self.root)):
            for x in dn + fn:
                try:
                    os.chmod(os.path.join(dp, x), 0o700, follow_symlinks=False)
                except (OSError, NotImplementedError):
                    pass
        self._tmp.cleanup()

    def main(self, secret: Optional[str] = SECRET, out: Optional[Path] = None, hashseed: str = "0",
             timeout: int = 600) -> Tuple[int, str, str]:
        env = {"PATH": os.environ.get("PATH", ""), "TMPDIR": str(self.tmpdir), "HOME": str(self.home),
               "PYTHONHASHSEED": hashseed, "PYTHONDONTWRITEBYTECODE": "1"}
        if secret is not None:
            env["RAKSHA_SECRET"] = secret
        p = subprocess.run([sys.executable, str(MAIN), "--input", str(self.inp), "--output", str(out or self.out)],
                           cwd=str(REPO), env=env, capture_output=True, timeout=timeout)
        return p.returncode, p.stdout.decode("utf-8", "replace"), p.stderr.decode("utf-8", "replace")

    def check_run(self, n_files: Optional[int] = None, forbidden: Tuple[str, ...] = ()) -> Dict:
        before = tree_digest(self.inp)
        shas = sorted(sha(p.read_bytes()) for p in regular_files(self.inp) if os.access(str(p), os.R_OK))
        code, so, se = self.main()
        self.assertEqual(code, 0, se[-500:])
        self.assertNotIn("Traceback", so + se)
        for line in so.splitlines():
            self.assertRegex(line, _STDOUT_OK)
        for line in se.splitlines():
            self.assertRegex(line, _STDERR_OK)
        for v in forbidden + (SECRET,):
            self.assertNotIn(v, so + se)
        self.assertEqual(tree_digest(self.inp), before, "input modified")
        self.assertEqual(sorted(os.listdir(str(self.root))), ["home", "in", "out", "tmp"])
        self.assertEqual(os.listdir(str(self.tmpdir)), [], "TMPDIR not empty")
        self.assertEqual(os.listdir(str(self.home)), [], "HOME not empty")
        rep = json.loads((self.out / "report.json").read_text(encoding="utf-8"))
        files = rep["files"]
        got = [f["input_sha256"] for f in files]
        if n_files is not None:
            self.assertEqual(len(files), n_files)
        for s in shas:  # every readable regular file exactly once (identical bytes: once per path)
            self.assertEqual(got.count(s), shas.count(s))
        self.assertEqual(rep["counts"]["files_total"], len(files))
        self.assertEqual(rep["counts"]["files_sanitized"], sum(f["status"] == "sanitized" for f in files))
        for f in files:
            if f["status"] == "sanitized":
                self.assertTrue((self.out / f["output"]).is_file())
        san = self.out / "sanitized"
        self.assertEqual(sum(1 for _ in regular_files(san)), rep["counts"]["files_sanitized"])
        blob = b"".join(p.read_bytes() for p in regular_files(self.out))
        names = "\n".join(p.relative_to(self.out).as_posix() for p in regular_files(self.out))
        for v in forbidden + (SECRET,):
            self.assertNotIn(v.encode(), blob)
            self.assertNotIn(v, names)
        for line in (self.out / "records.jsonl").read_text(encoding="utf-8").splitlines():
            json.loads(line)
        return rep


IDS = tuple(x for p in PEOPLE for x in (p[0], p[1], p[2]))


class HostileInputs(Base):
    def test_kitchen_sink(self):
        i = self.inp
        (i / "nul.txt").write_bytes(b"Patient: Tarvin Oglekar\x00\x00 9812307745\n")
        (i / "utf16_nobom.txt").write_bytes(note().encode("utf-16-le"))
        (i / "mixed_eol.txt").write_bytes(note().replace("\n", "\r\n", 3).replace("\n", "\r").encode())
        (i / "unbalanced.csv").write_text(reg_csv() + '"UHX-1,"Oddly quoted, 9000000001\nA,B,C\n', encoding="utf-8")
        for k, v in (("null", "null"), ("empty_list", "[]"), ("text", '"just text"'), ("num", "42"),
                     ("float", "-3.5e2"), ("obj", "{}")):
            (i / ("j_%s.json" % k)).write_text(v, encoding="utf-8")
        (i / "top_array.json").write_text(json.dumps([{"patient_id": uh, "name": n, "phone": ph}
                                                      for n, ph, uh, _ in PEOPLE]), encoding="utf-8")
        (i / "top_array_noid.json").write_text(json.dumps([{"name": n, "phone": ph} for n, ph, _, _ in PEOPLE]),
                                               encoding="utf-8")
        (i / "a" / "b" / "c").mkdir(parents=True)
        (i / "empty_dir").mkdir()
        (i / "noext").write_text(note(PEOPLE[1]), encoding="utf-8")
        (i / "with space name.txt").write_text(note(PEOPLE[2]), encoding="utf-8")
        (i / "पर्ची नोट.txt").write_text("रोगी: तर्विन ओगलेकर\nफ़ोन 9812307745\nबुखार\n", encoding="utf-8")
        (i / ".hidden.csv").write_text(reg_csv(), encoding="utf-8")
        (i / ("L" * 240 + ".txt")).write_text(note(), encoding="utf-8")
        (i / "Case.txt").write_text(note(PEOPLE[0]), encoding="utf-8")
        try:
            (i / "case.txt").write_text(note(PEOPLE[1]), encoding="utf-8")
        except OSError:
            pass
        (i / "reg.csv").write_text(reg_csv(), encoding="utf-8")
        (i / "opd.json").write_text(opd_json(), encoding="utf-8")
        (i / "zero.txt").write_bytes(b"")
        (i / "ws.txt").write_text("  \n\t\n", encoding="utf-8")
        (i / "bad.json").write_text('{"name": "Tarvin Oglekar", ', encoding="utf-8")
        (i / "cp.txt").write_bytes("Patient: Javesh Pundhir caf\xe9\n".encode("cp1252"))
        (i / "broken_utf8.txt").write_bytes(b"Patient \xc3\x28 \xff\xfe\xfd Meenal Wadkarni\n")
        rep = self.check_run(n_files=len(regular_files(i)), forbidden=IDS)
        by = {f["input_sha256"]: f for f in rep["files"]}
        self.assertEqual(by[sha((i / "nul.txt").read_bytes())]["status"], "quarantined")
        self.assertEqual(by[sha((i / "zero.txt").read_bytes())]["status"], "quarantined")
        lines = [json.loads(x) for x in (self.out / "records.jsonl").read_text(encoding="utf-8").splitlines()]
        top = [r for r in lines if r["file"].endswith("top_array.json")]
        self.assertEqual(sorted(r["loc"] for r in top), ["/0", "/1", "/2"])
        # A top-level list of name+phone objects (no id key) is still one "doc" record in harvest.py today:
        # accepted (the longest-loc rule still covers it), not asserted either way.

    def test_empty_input_dir(self):
        rep = self.check_run(n_files=0)
        self.assertEqual(rep["counts"]["files_total"], 0)
        self.assertEqual((self.out / "records.jsonl").read_text(encoding="utf-8"), "")

    def test_only_empty_dirs(self):
        (self.inp / "x" / "y").mkdir(parents=True)
        self.check_run(n_files=0)

    def test_output_exists_and_is_empty(self):
        self.out.mkdir()
        (self.inp / "reg.csv").write_text(reg_csv(), encoding="utf-8")
        self.check_run(n_files=1, forbidden=IDS)

    @unittest.skipIf(os.name != "posix" or (hasattr(os, "geteuid") and os.geteuid() == 0), "needs non-root posix")
    def test_unreadable_file(self):
        (self.inp / "reg.csv").write_text(reg_csv(), encoding="utf-8")
        p = self.inp / "locked.txt"
        p.write_text(note(), encoding="utf-8")
        os.chmod(str(p), 0)
        d = self.inp / "lockeddir"
        d.mkdir()
        (d / "inside.txt").write_text(note(), encoding="utf-8")
        os.chmod(str(d), 0)
        rep = self.check_run(forbidden=IDS)
        q = [f for f in rep["files"] if f["status"] == "quarantined"]
        self.assertEqual(len(q), 1)
        self.assertEqual(len(rep["files"]), 2)

    @unittest.skipIf(not hasattr(os, "symlink"), "no symlinks")
    def test_symlinks_not_followed_outside(self):
        outside = self.root / "outside_secret.txt"
        outside.write_text("Patient: Zorawar Quintelle 9988776655\n", encoding="utf-8")
        outside_dir = self.root / "outside_dir"
        outside_dir.mkdir()
        (outside_dir / "x.txt").write_text("Patient: Zorawar Quintelle\n", encoding="utf-8")
        (self.inp / "reg.csv").write_text(reg_csv(), encoding="utf-8")
        os.symlink(str(outside), str(self.inp / "link_out.txt"))
        os.symlink(str(outside_dir), str(self.inp / "link_dir"))
        os.symlink("reg.csv", str(self.inp / "link_in.csv"))
        os.symlink(str(self.root / "missing"), str(self.inp / "dangling.txt"))
        code, so, se = self.main()
        self.assertEqual(code, 0, se)
        blob = b"".join(p.read_bytes() for p in regular_files(self.out))
        self.assertNotIn(b"Zorawar", blob)
        self.assertNotIn(b"9988776655", blob)
        rep = json.loads((self.out / "report.json").read_text(encoding="utf-8"))
        self.assertEqual(sum(f["status"] == "sanitized" for f in rep["files"]),
                         sum(1 for _ in regular_files(self.out / "sanitized")))
        self.assertIn(sha((self.inp / "reg.csv").read_bytes()), [f["input_sha256"] for f in rep["files"]])
        outside_sha = sha(outside.read_bytes())
        self.assertNotIn(outside_sha, [f["input_sha256"] for f in rep["files"]])
        self.assertEqual(os.listdir(str(self.tmpdir)), [])
        self.assertEqual(sorted(os.listdir(str(self.root))),
                         ["home", "in", "out", "outside_dir", "outside_secret.txt", "tmp"])

    @unittest.skipUnless(STRESS, "set RAKSHA_STRESS=1")
    def test_big_csv_30mb(self):
        rows = ["patient_id,name,phone,visit_date,diagnosis,notes"]
        pad = "stable; review in 2 weeks; continue tablets as advised " * 2
        i = 0
        size = 0
        while size < 30 * 1024 * 1024:
            n, ph, uh, _ = PEOPLE[i % 3]
            r = "%s-%d,%s,%s,2026-04-%02d,Hypertension,%s" % (uh, i, n, ph, i % 28 + 1, pad)
            rows.append(r)
            size += len(r) + 1
            i += 1
        (self.inp / "big.csv").write_text("\n".join(rows) + "\n", encoding="utf-8")
        self.check_run(n_files=1, forbidden=IDS)

    @unittest.skipUnless(STRESS, "set RAKSHA_STRESS=1")
    def test_json_5mb_string(self):
        s = ("Patient Tarvin Oglekar seen. BP 130/80. " * 130000)[:5 * 1024 * 1024]
        (self.inp / "big.json").write_text(json.dumps({"note": s, "phone": PEOPLE[0][1]}), encoding="utf-8")
        self.check_run(n_files=1, forbidden=IDS)

    @unittest.skipUnless(STRESS, "set RAKSHA_STRESS=1")
    def test_csv_5000_columns(self):
        head = ["name", "phone"] + ["c%d" % k for k in range(4998)]
        body = [[n, ph] + [str(k % 97) for k in range(4998)] for n, ph, _, _ in PEOPLE * 10]
        buf = io.StringIO()
        w = csv.writer(buf, lineterminator="\n")
        w.writerow(head)
        w.writerows(body)
        (self.inp / "wide.csv").write_text(buf.getvalue(), encoding="utf-8")
        self.check_run(n_files=1, forbidden=IDS)


class DeterminismAndSecrets(Base):
    def make(self):
        (self.inp / "reg").mkdir()
        (self.inp / "reg" / "reg.csv").write_text(reg_csv(), encoding="utf-8")
        (self.inp / "opd.json").write_text(opd_json(), encoding="utf-8")
        for k, p in enumerate(PEOPLE):
            (self.inp / ("note_%d.txt" % k)).write_text(note(p), encoding="utf-8")

    def run_to(self, name: str, secret: str = SECRET, hashseed: str = "0") -> Path:
        out = self.root / name
        code, so, se = self.main(secret=secret, out=out, hashseed=hashseed)
        self.assertEqual(code, 0, se)
        for v in (SECRET, "other-" + SECRET):
            self.assertNotIn(v, so + se)
        return out

    def test_same_secret_identical_across_hash_seeds(self):
        self.make()
        a = out_digest(self.run_to("o0", hashseed="0"))
        self.assertEqual(a, out_digest(self.run_to("o1", hashseed="1")))
        self.assertEqual(a, out_digest(self.run_to("or", hashseed="random")))
        self.assertEqual(a, out_digest(self.run_to("or2", hashseed="random")))

    def test_secret_never_written(self):
        self.make()
        out = self.run_to("o")
        for p in regular_files(out):
            data = p.read_bytes()
            self.assertNotIn(SECRET.encode(), data)
            self.assertNotIn(SECRET.encode("utf-16-le"), data)
            self.assertNotIn(SECRET, p.name)
        self.assertEqual(os.listdir(str(self.tmpdir)), [])
        self.assertEqual(os.listdir(str(self.home)), [])

    def test_other_secret_changes_pseudonyms_and_shifts(self):
        self.make()
        a, b = self.run_to("oa"), self.run_to("ob", secret="other-" + SECRET)

        def psns(out):
            return {json.loads(x)["patient"] for x in (out / "records.jsonl").read_text(encoding="utf-8").splitlines()
                    } - {None}

        pa, pb = psns(a), psns(b)
        self.assertTrue(pa and pb)
        self.assertEqual(pa & pb, set())
        for p in pa:  # no pseudonym of run A appears anywhere in run B
            self.assertNotIn(p.encode(), b"".join(x.read_bytes() for x in regular_files(b)))

        def dates(out):
            txt = b"".join(x.read_bytes() for x in sorted(regular_files(out / "sanitized"))).decode("utf-8")
            return re.findall(r"20\d\d-\d\d-\d\d", txt)

        da, db = dates(a), dates(b)
        self.assertEqual(len(da), len(db))
        self.assertTrue(da)
        self.assertGreater(sum(x != y for x, y in zip(da, db)), len(da) // 2)

    def test_missing_or_empty_secret_exits_nonzero(self):
        self.make()
        for secret in (None, ""):
            out = self.root / ("o_%s" % ("none" if secret is None else "empty"))
            code, so, se = self.main(secret=secret, out=out)
            self.assertNotEqual(code, 0)
            self.assertNotIn("Traceback", se)
            self.assertIn("secret", se)
            for v in IDS:
                self.assertNotIn(v, so + se)
            self.assertFalse((out / "sanitized").exists() and any((out / "sanitized").iterdir()))


class FormatRoundTrip(Base):
    def test_csv_tsv_shape_and_text_lines(self):
        (self.inp / "crlf.csv").write_bytes(reg_csv(nl="\r\n").encode("utf-8"))
        (self.inp / "bom.csv").write_bytes(b"\xef\xbb\xbf" + reg_csv().encode("utf-8"))
        (self.inp / "tabs.tsv").write_text(reg_csv(delim="\t"), encoding="utf-8")
        (self.inp / "quoted.csv").write_text(
            'patient_id,name,remarks\nUHX-0048123,"Oglekar, Tarvin","line one\nline two"\n'
            'UHX-0048777,Meenal Wadkarni,"said ""ok"""\n', encoding="utf-8")
        (self.inp / "n.txt").write_text(note() + "\n\n", encoding="utf-8")
        (self.inp / "mixed.txt").write_bytes(b"line a\r\nline b\rline c\nline d\n")
        self.check_run(n_files=6, forbidden=IDS)
        rep = json.loads((self.out / "report.json").read_text(encoding="utf-8"))
        for src in sorted(self.inp.iterdir()):
            raw = src.read_bytes()
            f = [x for x in rep["files"] if x["input_sha256"] == sha(raw)][0]
            self.assertEqual(f["status"], "sanitized", src.suffix)
            dst = (self.out / f["output"]).read_text(encoding="utf-8-sig")
            text = raw.decode("utf-8-sig")
            if src.suffix in (".csv", ".tsv"):
                d = "\t" if src.suffix == ".tsv" else ","
                a = list(csv.reader(io.StringIO(text, newline=""), delimiter=d))
                b = list(csv.reader(io.StringIO(dst, newline=""), delimiter=d))
                self.assertEqual(len(a), len(b))
                self.assertEqual([len(r) for r in a], [len(r) for r in b])
                self.assertEqual(a[0], b[0])
                if d == "\t":
                    self.assertIn("\t", dst.splitlines()[0])
            else:
                self.assertEqual(len(text.splitlines()), len(dst.splitlines()), src.name)


def _sha_with_digit_run(prefix: str) -> Tuple[str, str]:
    """(content, run): content whose sha256 hex holds an isolated decimal run of 5-6 digits."""
    for k in range(200000):
        c = "%s %d\n" % (prefix, k)
        h = sha(c.encode("utf-8"))
        for m in re.finditer(r"(?<![0-9])[0-9]{5,6}(?![0-9])", h):
            return c, m.group(0)
    raise AssertionError("no candidate")


class ReportHashesUntouched(Base):
    def test_gate_never_alters_hashes_unit(self):
        from raksha import gate, pipeline
        from raksha.types import Facts
        c, run = _sha_with_digit_run("unit")
        h = sha(c.encode())
        fb = gate.forbidden_from_facts([Facts(ids=["UHX-" + run])])
        self.assertTrue(gate.scan(h, fb))  # the hash really contains a forbidden core
        rep = {"files": [{"input_sha256": h, "output": "sanitized/a.txt", "status": "sanitized"}],
               "counts": {"files_total": 1}, "entities": {"PHONE": 1}}
        pipeline._gate_report(rep, fb)
        self.assertEqual(rep["files"][0]["input_sha256"], h)
        self.assertEqual(rep["files"][0]["output"], "sanitized/a.txt")

    def test_gate_never_alters_hashes_end_to_end(self):
        c, run = _sha_with_digit_run("Clinic note. Stable on review.")
        (self.inp / "n.txt").write_text(c, encoding="utf-8")
        (self.inp / "reg.csv").write_text("patient_id,name,phone\nUHX-%s,Tarvin Oglekar,9812307745\n" % run,
                                          encoding="utf-8")
        rep = self.check_run(n_files=2, forbidden=("Tarvin Oglekar", "9812307745"))
        hashes = sorted(f["input_sha256"] for f in rep["files"])
        self.assertEqual(hashes, sorted(sha(p.read_bytes()) for p in self.inp.iterdir()))
        for f in rep["files"]:
            self.assertRegex(f["input_sha256"], r"^[0-9a-f]{64}$")
        for line in (self.out / "records.jsonl").read_text(encoding="utf-8").splitlines():
            r = json.loads(line)
            self.assertTrue(r["patient"] is None or re.match(r"^PSN-[0-9A-Z]+$", r["patient"]), r["patient"])
            if r["file"].endswith(".csv"):
                self.assertRegex(r["loc"], r"^row:\d+$")


if __name__ == "__main__":
    unittest.main()
