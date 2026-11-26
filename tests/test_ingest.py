from __future__ import annotations

import hashlib
import json
import tempfile
import unittest
from pathlib import Path

from raksha.ingest import dump_csv, dump_json, load, walk
from raksha.types import KIND_CSV, KIND_FHIR, KIND_JSON, KIND_QUARANTINE, KIND_TEXT


class IngestTest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)

    def tearDown(self):
        self._tmp.cleanup()

    def put(self, rel: str, raw: bytes) -> Path:
        p = self.root / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(raw)
        return p

    def ld(self, rel: str, raw: bytes):
        return load(self.put(rel, raw), self.root)

    def assertQ(self, pf, reason):
        self.assertEqual(pf.kind, KIND_QUARANTINE)
        self.assertEqual(pf.reason, reason)
        self.assertEqual(pf.text, "")

    # --- CSV family -----------------------------------------------------
    def test_utf8_bom_csv(self):
        pf = self.ld("a/bom.csv", b"\xef\xbb\xbfreg_no,full_name\nQX-1001,Tarun Veer\n")
        self.assertEqual(pf.kind, KIND_CSV)
        self.assertEqual(pf.header, ["reg_no", "full_name"])
        self.assertEqual(pf.rows, [["QX-1001", "Tarun Veer"]])
        self.assertEqual(pf.rel, "a/bom.csv")

    def test_utf16_tsv_devanagari(self):
        text = "id\tनाम\tगाँव\nZ-77\tओजस्वी पलाश\tकमलपुर\n"
        pf = self.ld("reg.tsv", text.encode("utf-16"))
        self.assertEqual(pf.kind, KIND_CSV)
        self.assertEqual(pf.delimiter, "\t")
        self.assertEqual(pf.header, ["id", "नाम", "गाँव"])
        self.assertEqual(pf.rows[0][1], "ओजस्वी पलाश")

    def test_utf16_without_bom(self):
        pf = self.ld("x.tsv", "a\tb\n1\tदो\n".encode("utf-16-le"))
        self.assertEqual(pf.kind, KIND_CSV)
        self.assertEqual(pf.rows, [["1", "दो"]])

    def test_cp1252_csv(self):
        raw = "patient,temp,note\nRavi Lal,101.2°F,fever 2–3 days\n".encode("cp1252")
        pf = self.ld("legacy.csv", raw)
        self.assertEqual(pf.kind, KIND_CSV)
        self.assertEqual(pf.rows[0], ["Ravi Lal", "101.2°F", "fever 2–3 days"])

    def test_multiline_quoted_cell_and_ragged_row(self):
        raw = b'name;remarks;ward\n"Meena Kaur";"line one\nline two";W3\nOnly;two\n'
        pf = self.ld("m.csv", raw)
        self.assertEqual(pf.delimiter, ";")
        self.assertEqual(pf.rows[0], ["Meena Kaur", "line one\nline two", "W3"])
        self.assertEqual(pf.rows[1], ["Only", "two"])

    def test_pipe_delimiter_and_roundtrip(self):
        raw = b'a|b|c\n1|"x|y"|3\n4|5\n'
        pf = self.ld("p.csv", raw)
        self.assertEqual(pf.delimiter, "|")
        again = load(self.put("p2.csv", dump_csv(pf).encode("utf-8")), self.root)
        self.assertEqual(again.header, pf.header)
        self.assertEqual(again.rows, pf.rows)

    # --- JSON family ----------------------------------------------------
    def test_nested_json(self):
        obj = {"visits": [{"p": {"name": "Anil Rao", "vitals": {"bp": "120/80"}}}]}
        pf = self.ld("v.json", json.dumps(obj).encode())
        self.assertEqual(pf.kind, KIND_JSON)
        self.assertEqual(pf.data, obj)

    def test_fhir_bundle(self):
        obj = {"resourceType": "Bundle", "type": "collection", "entry": []}
        pf = self.ld("f/b.json", json.dumps(obj).encode())
        self.assertEqual(pf.kind, KIND_FHIR)

    def test_truncated_json(self):
        self.assertQ(self.ld("t.json", b'{"visits": [{"name": "Ornaya'), "malformed_json")

    def test_json_extension_not_json(self):
        self.assertQ(self.ld("n.json", b"just a note\n"), "malformed_json")

    def test_json_inside_csv(self):
        pf = self.ld("odd.csv", b'{"patient": "Hari Om", "age": 40}')
        self.assertEqual(pf.kind, KIND_JSON)
        self.assertEqual(pf.data["age"], 40)

    def test_bracket_text_not_json_stays_text(self):
        pf = self.ld("chat.txt", b"[01/02/26, 9:00 am] Someone: hello\n")
        self.assertEqual(pf.kind, KIND_TEXT)

    def test_too_deep(self):
        raw = ("[" * 1500 + "]" * 1500).encode()
        self.assertQ(self.ld("deep.json", raw), "too_deep")

    def test_depth_ignores_brackets_in_strings(self):
        obj = {"s": "[" * 500 + '"{'}
        pf = self.ld("s.json", json.dumps(obj).encode())
        self.assertEqual(pf.kind, KIND_JSON)

    # --- Quarantine -----------------------------------------------------
    def test_binary_and_xml(self):
        self.assertQ(self.ld("a.pdf", b"%PDF-1.4\n1 0 obj"), "unsupported_format")
        self.assertQ(self.ld("b.jpg", b"\xff\xd8\xff\xe0\x00\x10JFIF"), "unsupported_format")
        self.assertQ(self.ld("c.png", b"\x89PNG\r\n\x1a\n\x00\x00"), "unsupported_format")
        self.assertQ(self.ld("d.xml", b'<?xml version="1.0"?><doc/>'), "unsupported_format")
        self.assertQ(self.ld("e.txt", b"  <ClinicalDocument>x</ClinicalDocument>"), "unsupported_format")

    def test_empty(self):
        self.assertQ(self.ld("z.csv", b""), "empty_file")
        self.assertQ(self.ld("w.txt", b"  \n\t\n"), "empty_file")
        self.assertQ(self.ld("bom.csv", b"\xef\xbb\xbf\n"), "empty_file")

    def test_invalid_utf8_text(self):
        raw = b"Visit note for a patient. \xff\xfe\xc3( Mobile 9000000000. cough.\n"
        self.assertQ(self.ld("bad.txt", raw), "invalid_encoding")

    def test_broken_utf8_sequence(self):
        raw = "Note नाम ok".encode("utf-8")[:-4] + b"\xa4 tail\x81\n"
        self.assertQ(self.ld("bad2.txt", raw), "invalid_encoding")

    # --- Misc -----------------------------------------------------------
    def test_text_and_sha(self):
        raw = "Discharge note: stable.\n".encode()
        pf = self.ld("n/x.note", raw)
        self.assertEqual(pf.kind, KIND_TEXT)
        self.assertEqual(pf.sha256, hashlib.sha256(raw).hexdigest())

    def test_never_raises(self):
        pf = load(self.root / "missing.txt", self.root)
        self.assertEqual(pf.kind, KIND_QUARANTINE)
        self.assertEqual(pf.reason, "internal_error")
        pf = load(self.root, self.root)  # a directory
        self.assertEqual(pf.reason, "internal_error")

    def test_walk_sorted_and_hidden(self):
        for rel in ("b/2.txt", "a/1.txt", ".hidden", "a/b/0.txt"):
            self.put(rel, b"x")
        rels = [p.relative_to(self.root).as_posix() for p in walk(self.root)]
        self.assertEqual(rels, sorted(rels))
        self.assertIn(".hidden", rels)
        self.assertEqual(len(rels), 4)

    def test_dump_json(self):
        self.assertEqual(dump_json({"n": "राम"}), '{\n  "n": "राम"\n}\n')


if __name__ == "__main__":
    unittest.main()
