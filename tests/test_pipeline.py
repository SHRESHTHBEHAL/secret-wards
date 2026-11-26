from __future__ import annotations

import contextlib
import io
import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from raksha import pipeline, report
from raksha.policy import DEFAULTS, load_policy
from raksha.sanitize import Sanitized
from raksha.types import Facts, Record

CSV = "pid,name,phone\nA1,Ilavar Pendse,9123456780\nA2,Mitul Gorai,9000012345\n"
JSON = '{"visits": [{"n": "x"}, {"n": "y"}, {"n": "z"}], "meta": {"v": 1}}'


def make_input(root: Path) -> None:
    (root / "reg").mkdir(parents=True)
    (root / "reg" / "a.csv").write_text(CSV, encoding="utf-8")
    (root / "reg" / "copy_of_a.csv").write_text(CSV, encoding="utf-8")
    (root / "opd").mkdir()
    (root / "opd" / "v.json").write_text(JSON, encoding="utf-8")
    (root / "opd" / "broken.json").write_text('{"a": [1, 2', encoding="utf-8")
    (root / "note.txt").write_text("Patient seen.\n\nStable.\n", encoding="utf-8")


def run(inp: Path, out: Path, secret: bytes = b"unit-secret"):
    so, se = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(so), contextlib.redirect_stderr(se):
        code = pipeline.run(inp, out, secret, dict(DEFAULTS))
    return code, so.getvalue(), se.getvalue()


class PipelineTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.inp = self.root / "in"
        make_input(self.inp)

    def tearDown(self):
        self.tmp.cleanup()

    def load(self, out: Path):
        rep = json.loads((out / "report.json").read_text(encoding="utf-8"))
        lines = [json.loads(x) for x in (out / "records.jsonl").read_text(encoding="utf-8").splitlines()]
        return rep, lines

    def test_end_to_end_contract(self):
        out = self.root / "out"
        code, so, se = run(self.inp, out)
        self.assertEqual(code, 0)
        self.assertEqual(se, "")
        self.assertEqual(len(so.strip().splitlines()), 1)
        rep, lines = self.load(out)
        self.assertEqual(rep["schema"], "raksha-report/1")
        self.assertEqual(rep["counts"]["files_total"], 5)
        self.assertEqual(rep["counts"]["files_quarantined"], 1)
        q = [f for f in rep["files"] if f["status"] == "quarantined"]
        self.assertEqual(len(q), 1)
        self.assertIsNone(q[0]["output"])
        self.assertTrue(q[0]["reason"])
        self.assertFalse((out / "sanitized" / "opd" / "broken.json").exists())
        for f in rep["files"]:
            if f["output"]:
                self.assertTrue((out / f["output"]).is_file())
        self.assertEqual(rep["counts"]["records_processed"], len(lines))
        # nothing from the input passes the stub sanitizer
        a = (out / "sanitized" / "reg" / "a.csv").read_text(encoding="utf-8")
        self.assertNotIn("Pendse", a)
        self.assertNotIn("9123456780", a)
        self.assertTrue(a.startswith("pid,name,phone\n"))

    def test_duplicates_exported_twice(self):
        out = self.root / "out"
        calls = []
        real = pipeline.load

        def spy(p, root):
            calls.append(p.name)
            return real(p, root)

        with mock.patch.object(pipeline, "load", spy):
            run(self.inp, out)
        self.assertEqual(sorted(calls).count("copy_of_a.csv") + sorted(calls).count("a.csv"), 1)
        rep, lines = self.load(out)
        outs = sorted(f["output"] for f in rep["files"] if f["output"])
        self.assertIn("sanitized/reg/a.csv", outs)
        self.assertIn("sanitized/reg/copy_of_a.csv", outs)
        shas = [f["input_sha256"] for f in rep["files"]]
        self.assertEqual(len(shas), 5)
        self.assertEqual(len(set(shas)), 4)
        self.assertEqual(sum(1 for r in lines if r["file"] == "sanitized/reg/copy_of_a.csv"), 2)

    def test_records_ordering(self):
        out = self.root / "out"
        (self.inp / "big.csv").write_text("h\n" + "".join("r%d\n" % i for i in range(12)), encoding="utf-8")
        run(self.inp, out)
        _, lines = self.load(out)
        keys = [(r["file"], r["loc"]) for r in lines]
        big = [loc for f, loc in keys if f == "sanitized/big.csv"]
        self.assertEqual(big, ["row:%d" % i for i in range(12)])
        files = [f for f, _ in keys]
        self.assertEqual(files, sorted(files))
        self.assertEqual([loc for f, loc in keys if f == "sanitized/opd/v.json"], ["/visits/0", "/visits/1", "/visits/2"])
        self.assertEqual(report.loc_key("/v/10") > report.loc_key("/v/9"), True)
        self.assertLess(report.loc_key("row:2"), report.loc_key("row:10"))

    def test_deterministic(self):
        a, b = self.root / "o1", self.root / "o2"
        run(self.inp, a)
        run(self.inp, b)
        for rel in ("records.jsonl", "sanitized/reg/a.csv", "sanitized/opd/v.json", "sanitized/note.txt"):
            self.assertEqual((a / rel).read_bytes(), (b / rel).read_bytes())

    def test_empty_secret(self):
        out = self.root / "out"
        code, so, se = run(self.inp, out, secret=b"")
        self.assertEqual(code, 2)
        self.assertFalse((out / "report.json").exists())
        self.assertNotIn("a.csv", se)

    def test_harvest_crash_quarantines_only_that_file(self):
        out = self.root / "out"
        real = pipeline.harvest_file

        def boom(pf):
            if pf.rel.endswith(".txt"):
                raise KeyError("secret data")
            return real(pf)

        with mock.patch.object(pipeline, "harvest_file", boom):
            code, so, se = run(self.inp, out)
        self.assertEqual(code, 0)
        self.assertEqual(se.strip(), "raksha: KeyError in harvest")
        rep, _ = self.load(out)
        reasons = sorted(f.get("reason", "") for f in rep["files"] if f["status"] == "quarantined")
        self.assertIn("internal_error", reasons)
        self.assertFalse((out / "sanitized" / "note.txt").exists())

    def test_sanitize_crash(self):
        out = self.root / "out"
        with mock.patch.object(pipeline, "sanitize_file", side_effect=ValueError("x")):
            code, _, se = run(self.inp, out)
        self.assertEqual(code, 0)
        self.assertEqual(se.strip(), "raksha: ValueError in sanitize")
        rep, lines = self.load(out)
        self.assertEqual(rep["counts"]["files_sanitized"], 0)
        self.assertEqual(lines, [])

    def test_leak_gate_cleans_and_quarantines(self):
        out = self.root / "out"
        facts = Facts(names=["Ilavar Pendse"], ids=["phone:9123456780"])

        def harvest(pf):
            return [Record(rel=pf.rel, loc="doc", facts=facts)]

        def leaky(pf, env):
            if pf.rel == "note.txt":
                content = "call 91234 56780 or Ilavar Pendse\n"
            elif pf.rel.endswith(".json"):
                content = '{"p": 9123456780, "n": "Pendse Ilavar"}\n'
            else:
                content = "pid,name\nA1,Ilavar Pendse\n"
            return Sanitized(out_rel=pf.rel, content=content, records=[("doc", None, "sanitized")], counts={"identifiers": 1, "PHONE": 1})

        with mock.patch.object(pipeline, "harvest_file", harvest), mock.patch.object(pipeline, "sanitize_file", leaky):
            code, so, se = run(self.inp, out)
        self.assertEqual(code, 0)
        note = (out / "sanitized" / "note.txt").read_text(encoding="utf-8")
        self.assertEqual(note, "call [REDACTED] or [REDACTED]\n")
        v = json.loads((out / "sanitized" / "opd" / "v.json").read_text(encoding="utf-8"))
        self.assertEqual(v, {"p": 0, "n": "[REDACTED]"})
        a = (out / "sanitized" / "reg" / "a.csv").read_text(encoding="utf-8")
        self.assertEqual(a, "pid,name\nA1,[REDACTED]\n")
        rep, _ = self.load(out)
        self.assertGreater(rep["counts"]["leak_gate_hits"], 0)
        self.assertEqual(rep["entities"].get("PHONE"), 4)
        for text in (so, se, (out / "report.json").read_text(), (out / "records.jsonl").read_text()):
            self.assertNotIn("Pendse", text)
            self.assertNotIn("9123456780", text)

    def test_leak_gate_unfixable_quarantines(self):
        out = self.root / "out"
        facts = Facts(names=["Ilavar Pendse"])

        def harvest(pf):
            return [Record(rel=pf.rel, loc="doc", facts=facts)]

        def leaky(pf, env):
            return Sanitized(out_rel=pf.rel, content="a\nIlavar Pendse\n", records=[("doc", None, "sanitized")], counts={})

        with mock.patch.object(pipeline, "harvest_file", harvest), \
                mock.patch.object(pipeline, "sanitize_file", leaky), \
                mock.patch.object(pipeline.gate, "clean", lambda t, fb, *a, **k: (t, 1)):
            code, _, _ = run(self.inp, out)
        self.assertEqual(code, 0)
        rep, lines = self.load(out)
        self.assertEqual(rep["counts"]["files_sanitized"], 0)
        self.assertEqual({f["reason"] for f in rep["files"]}, {"leak_gate", "malformed_json"})
        self.assertEqual(lines, [])
        self.assertEqual(list((out / "sanitized").rglob("*")), [])

    def test_base64_payload_redacted(self):
        import base64
        out = self.root / "out"
        facts = Facts(names=["Ilavar Pendse"])
        blob = base64.b64encode(b"Ilavar Pendse").decode()

        def harvest(pf):
            return [Record(rel=pf.rel, loc="doc", facts=facts)]

        def leaky(pf, env):
            return Sanitized(out_rel=pf.rel, content="note %s end\n" % blob, records=[], counts={})

        with mock.patch.object(pipeline, "harvest_file", harvest), mock.patch.object(pipeline, "sanitize_file", leaky):
            run(self.inp, out)
        self.assertEqual((out / "sanitized" / "note.txt").read_text(encoding="utf-8"), "note [REDACTED] end\n")

    def test_out_rel_collision_and_pii_name(self):
        out = self.root / "out"
        facts = Facts(names=["Ilavar Pendse"])

        def harvest(pf):
            return [Record(rel=pf.rel, loc="doc", facts=facts)]

        def renamer(pf, env):
            rel = "same.txt" if pf.rel.endswith(".csv") else pf.rel
            if pf.rel == "note.txt":
                rel = "Ilavar_Pendse.txt"
            return Sanitized(out_rel=rel, content="ok\n", records=[("doc", None, "sanitized")], counts={})

        with mock.patch.object(pipeline, "harvest_file", harvest), mock.patch.object(pipeline, "sanitize_file", renamer):
            code, _, _ = run(self.inp, out)
        self.assertEqual(code, 0)
        rep, _ = self.load(out)
        outs = sorted(f["output"] for f in rep["files"] if f["output"])
        self.assertEqual(len(outs), len(set(outs)))
        self.assertIn("sanitized/same.txt", outs)
        self.assertFalse(any("Pendse" in o for o in outs))
        for o in outs:
            self.assertTrue((out / o).is_file())

    def test_policy_defaults(self):
        p = self.root / "p.yaml"
        p.write_text("rare_k: 4   # c\nrare_rule: off\n", encoding="utf-8")
        pol = load_policy(p)
        self.assertEqual(pol["rare_k"], 4)
        self.assertEqual(pol["rare_rule"], "off")
        self.assertEqual(pol["age_top"], 85)
        self.assertEqual(load_policy(self.root / "missing.yaml"), DEFAULTS)


if __name__ == "__main__":
    unittest.main()
