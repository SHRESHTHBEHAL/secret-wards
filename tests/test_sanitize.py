from __future__ import annotations

import base64
import csv
import datetime as dt
import io
import json
import unittest

from raksha.policy import DEFAULTS
from raksha.pseudo import Keys
from raksha.sanitize import Env, sanitize_file
from raksha.types import KIND_CSV, KIND_FHIR, KIND_JSON, KIND_TEXT, Facts, ParsedFile, Patient, Record

PSN = "PSN-TESTAAAAAA"
FACTS = Facts(names=["Ilavar Pendse"], relatives=[("S/o", "Mitul Pendse")],
              ids=["uhid:QRH2077123", "phone:9123456780"], raw_ids=["QRH-2077123", "9123456780"],
              dob=dt.date(1979, 3, 14), age=47, village="Kotharpur")


def env_for(rel: str, locs, linked: bool = True) -> Env:
    recs = [Record(rel=rel, loc=loc, facts=FACTS) for loc in locs]
    assign = {(rel, loc): ("k1" if linked else None) for loc in locs}
    book = {"k1": Patient(key="k1", records=[(rel, loc) for loc in locs], facts=[FACTS])} if linked else {}
    return Env(keys=Keys(b"unit-secret"), assign=assign, book=book, policy=dict(DEFAULTS),
               pseudonyms={"k1": PSN} if linked else {}, records={rel: recs})


class CsvTest(unittest.TestCase):
    def setUp(self):
        self.pf = ParsedFile(
            rel="reg/patients.csv", sha256="a" * 64, kind=KIND_CSV, delimiter=",",
            header=["uhid", "name", "mobile", "dob", "admission_date", "discharge_date", "district", "diagnosis"],
            rows=[["QRH-2077123", "Ilavar Pendse", "9123456780", "14/03/1979", "02/05/2026", "09/05/2026",
                   "Sitapur", "Type 2 diabetes mellitus"]])
        self.env = env_for(self.pf.rel, ["row:0"])

    def test_cells(self):
        res = sanitize_file(self.pf, self.env)
        rows = list(csv.reader(io.StringIO(res.content)))
        self.assertEqual(rows[0], self.pf.header)
        row = rows[1]
        self.assertEqual(row[0], PSN)
        self.assertEqual(row[1], "[NAME]")
        self.assertEqual(row[2], "[PHONE]")
        self.assertNotEqual(row[3], "14/03/1979")
        self.assertRegex(row[3], r"^\d\d/\d\d/\d{4}$")
        self.assertEqual(row[6], "Sitapur")
        self.assertEqual(row[7], "Type 2 diabetes mellitus")
        a = dt.datetime.strptime(row[4], "%d/%m/%Y")
        b = dt.datetime.strptime(row[5], "%d/%m/%Y")
        self.assertEqual((b - a).days, 7)
        self.assertEqual(res.records, [("row:0", PSN, "generalized")])
        self.assertGreater(res.counts["identifiers"], 0)
        self.assertNotIn("Pendse", res.content)

    def test_deterministic(self):
        a = sanitize_file(self.pf, self.env).content
        b = sanitize_file(self.pf, env_for(self.pf.rel, ["row:0"])).content
        self.assertEqual(a, b)

    def test_name_slot_gets_pseudonym_without_id_slot(self):
        pf = ParsedFile(rel="r.csv", sha256="b" * 64, kind=KIND_CSV, delimiter=",",
                        header=["name", "remarks"], rows=[["Ilavar Pendse", "stable"]])
        res = sanitize_file(pf, env_for("r.csv", ["row:0"]))
        self.assertIn(PSN, res.content)


class JsonTest(unittest.TestCase):
    def test_record(self):
        data = {"export": {"source_path": "D:\\exports\\Ilavar_Pendse_2077123\\v.json"},
                "visits": [{"patient_ref": "QRH-2077123", "age": 52, "guardian": "S/O Mitul Pendse",
                            "notes": "Ilavar ji ko bukhar hai, call 9123456780", "doctor": "Dr. Ravi Menon",
                            "aadhar_no": 234567891234}]}
        pf = ParsedFile(rel="opd/v.json", sha256="c" * 64, kind=KIND_JSON, data=data)
        res = sanitize_file(pf, env_for(pf.rel, ["/visits/0"]))
        out = json.loads(res.content)
        v = out["visits"][0]
        self.assertEqual(list(v), list(data["visits"][0]))
        self.assertEqual(v["patient_ref"], PSN)
        self.assertEqual(v["age"], "50-54")
        self.assertEqual(v["guardian"], "S/O [RELATIVE]")
        self.assertNotIn("Ilavar", v["notes"])
        self.assertNotIn("9123456780", v["notes"])
        self.assertEqual(v["doctor"], "Dr. Ravi Menon")
        self.assertEqual(v["aadhar_no"], 0)
        self.assertNotIn("2077123", res.content)
        self.assertNotIn("Pendse", res.content)

    def test_clean_file_unchanged(self):
        data = {"wards": [{"ward": "Ward 4 (Medicine)", "beds": 20, "date": "2026-05-01"}]}
        pf = ParsedFile(rel="clean/census.json", sha256="d" * 64, kind=KIND_JSON, data=data)
        env = Env(keys=Keys(b"s"), assign={}, book={}, policy=dict(DEFAULTS),
                  records={pf.rel: [Record(rel=pf.rel, loc="/wards/0")]})
        res = sanitize_file(pf, env)
        self.assertEqual(json.loads(res.content), data)
        self.assertEqual(res.out_rel, pf.rel)


class TextTest(unittest.TestCase):
    def test_document(self):
        text = ("Patient Name: Ilavar Pendse   Age/Sex: 47 Yrs/M\n"
                "S/o Mitul Pendse\nMobile: 9123456780\n"
                "Date of Admission: 02/05/2026\nDate of Discharge: 09/05/2026\n"
                "Medicine: Ramipril 5 mg 1-0-1\n")
        pf = ParsedFile(rel="ds/Discharge_Summary_Ilavar_Pendse_QRH-2077123.txt", sha256="e" * 64,
                        kind=KIND_TEXT, text=text)
        res = sanitize_file(pf, env_for(pf.rel, ["doc"]))
        self.assertEqual(res.content.count("\n"), text.count("\n"))
        self.assertIn(PSN, res.content)
        for bad in ("Ilavar", "Pendse", "9123456780", "Mitul"):
            self.assertNotIn(bad, res.content)
        self.assertIn("Ramipril 5 mg 1-0-1", res.content)
        self.assertIn("45-49", res.content)
        self.assertTrue(res.out_rel.startswith("ds/Discharge_Summary_"))
        self.assertTrue(res.out_rel.endswith(".txt"))
        self.assertNotIn("Pendse", res.out_rel)
        self.assertNotIn("2077123", res.out_rel)

    def test_base64_value(self):
        payload = base64.b64encode("Consent witnessed by Mitul Pendse, phone 9123456780.".encode()).decode()
        pf = ParsedFile(rel="misc/c.json", sha256="f" * 64, kind=KIND_JSON, data={"attachment": payload})
        res = sanitize_file(pf, env_for(pf.rel, ["doc"]))
        out = json.loads(res.content)["attachment"]
        dec = base64.b64decode(out).decode()
        self.assertNotIn("9123456780", dec)
        self.assertNotIn("Pendse", dec)


class FhirTest(unittest.TestCase):
    def test_bundle(self):
        data = {"resourceType": "Bundle", "id": "b1", "type": "document", "entry": [
            {"fullUrl": "urn:uuid:p1", "resource": {
                "resourceType": "Patient", "id": "p1",
                "identifier": [{"type": {"coding": [{"code": "MR"}]}, "system": "https://h.example/uhid",
                                "value": "QRH-2077123"}],
                "name": [{"text": "Ilavar Pendse", "given": ["Ilavar"], "family": "Pendse"}],
                "telecom": [{"system": "phone", "value": "9123456780"}],
                "birthDate": "1979-03-14",
                "address": [{"line": ["H.No. 12, Kotharpur"], "district": "Sitapur", "postalCode": "261001"}]}},
            {"fullUrl": "urn:uuid:e1", "resource": {
                "resourceType": "Encounter", "id": "e1", "status": "finished",
                "identifier": [{"value": "IPD-2026-00777"}],
                "subject": {"reference": "urn:uuid:p1", "display": "Ilavar Pendse"},
                "period": {"start": "2026-05-02T10:00:00+05:30", "end": "2026-05-09"}}}]}
        pf = ParsedFile(rel="fhir/b.json", sha256="0" * 64, kind=KIND_FHIR, data=data)
        res = sanitize_file(pf, env_for(pf.rel, ["doc"]))
        out = json.loads(res.content)
        p = out["entry"][0]["resource"]
        e = out["entry"][1]["resource"]
        self.assertEqual(p["identifier"][0]["value"], PSN)
        self.assertEqual(p["name"][0]["given"], ["[NAME]"])
        self.assertEqual(p["telecom"][0]["value"], "[PHONE]")
        self.assertEqual(p["address"][0]["district"], "Sitapur")
        self.assertEqual(p["address"][0]["postalCode"], "261XXX")
        self.assertRegex(p["birthDate"], r"^\d{4}-\d\d-\d\d$")
        self.assertNotEqual(p["birthDate"], "1979-03-14")
        self.assertEqual(e["identifier"][0]["value"], "[ENC-ID]")
        self.assertEqual(e["subject"], {"reference": "urn:uuid:p1", "display": "[NAME]"})
        self.assertRegex(e["period"]["start"], r"^\d{4}-\d\d-\d\dT10:00:00\+05:30$")
        s = dt.date.fromisoformat(e["period"]["start"][:10])
        t = dt.date.fromisoformat(e["period"]["end"])
        self.assertEqual((t - s).days, 7)
        self.assertEqual([x["fullUrl"] for x in out["entry"]], ["urn:uuid:p1", "urn:uuid:e1"])
        self.assertNotIn("Pendse", res.content)


if __name__ == "__main__":
    unittest.main()
