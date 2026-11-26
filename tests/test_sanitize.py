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
        self.assertEqual(row[3], "[DOB]")
        self.assertEqual(row[6], "[DISTRICT]")   # a release of one patient: cell smaller than geo_min_cell
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
        self.assertEqual(v["age"], "50-59")
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
        self.assertIn("40-49", res.content)
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
        self.assertEqual(p["address"][0]["district"], "[DISTRICT]")
        self.assertEqual(p["address"][0]["postalCode"], "[PIN]")
        self.assertNotIn("birthDate", p)
        self.assertNotIn("1979", res.content)
        self.assertEqual(e["identifier"][0]["value"], "[ENC-ID]")
        self.assertEqual(e["subject"], {"reference": "urn:uuid:p1", "display": "[NAME]"})
        self.assertRegex(e["period"]["start"], r"^\d{4}-\d\d-\d\dT10:00:00\+05:30$")
        s = dt.date.fromisoformat(e["period"]["start"][:10])
        t = dt.date.fromisoformat(e["period"]["end"])
        self.assertEqual((t - s).days, 7)
        self.assertEqual([x["fullUrl"] for x in out["entry"]], ["urn:uuid:p1", "urn:uuid:e1"])
        self.assertNotIn("Pendse", res.content)


def _facts(age, district="Sitapur", gender="M", name="Ilavar Pendse", ref=None):
    return Facts(names=[name], ids=[], raw_ids=[], age=age, gender=gender, district=district, ref_date=ref)


def multi_env(rel, patients, policy=None):
    """patients: list of (key, psn, loc, [Facts of the patient]); the record facts are the first fact."""
    assign, book, psns, recs = {}, {}, {}, []
    for key, psn, loc, facts in patients:
        assign[(rel, loc)] = key
        book[key] = Patient(key=key, records=[(rel, loc)], facts=list(facts))
        psns[key] = psn
        recs.append(Record(rel=rel, loc=loc, facts=facts[0]))
    pol = dict(DEFAULTS)
    pol.update(policy or {})
    return Env(keys=Keys(b"unit-secret"), assign=assign, book=book, policy=pol, pseudonyms=psns,
               records={rel: recs})


class PrivacyPolicyTest(unittest.TestCase):
    HEADER = ["uhid", "name", "age", "dob", "district", "pin", "address", "diagnosis"]

    def _pf(self, rows):
        return ParsedFile(rel="reg/p.csv", sha256="9" * 64, kind=KIND_CSV, delimiter=",",
                          header=list(self.HEADER), rows=rows)

    def _row(self, uhid, name, age, district="Sitapur"):
        return [uhid, name, str(age), "14/03/1979", district, "261001",
                "H.No. 4, Kotharpur, Distt. %s" % district, "Fever"]

    def test_dob_removed_in_fields_and_text(self):
        text = "Name: Ilavar Pendse\nDOB: 14/03/1979\nAge: 47 Yrs/M\n"
        pf = ParsedFile(rel="t/a.txt", sha256="1" * 64, kind=KIND_TEXT, text=text)
        res = sanitize_file(pf, env_for(pf.rel, ["doc"]))
        self.assertIn("[DOB]", res.content)
        self.assertNotIn("1979", res.content)
        self.assertEqual(res.records[0][2], "generalized")

    def test_dob_modes(self):
        pf = self._pf([self._row("QRH-2077123", "Ilavar Pendse", 47)])
        for mode, want in (("year", "1979"), ("remove", "[DOB]")):
            env = env_for(pf.rel, ["row:0"])
            env.policy["dob_mode"] = mode
            row = list(csv.reader(io.StringIO(sanitize_file(pf, env).content)))[1]
            self.assertEqual(row[3], want)
        env = env_for(pf.rel, ["row:0"])
        env.policy["dob_mode"] = "shift"
        row = list(csv.reader(io.StringIO(sanitize_file(pf, env).content)))[1]
        self.assertRegex(row[3], r"^\d\d/\d\d/\d{4}$")
        self.assertNotEqual(row[3], "14/03/1979")

    def test_band_consistent_per_patient(self):
        # visits years apart: stated ages 48 and 51 straddle two 10-year bands
        facts = [_facts(48), _facts(51)]
        text = "Name: Ilavar Pendse  Age/Sex: 48 Yrs/M\nPatient is a 48 year old man.\n"
        pf = ParsedFile(rel="t/b.txt", sha256="2" * 64, kind=KIND_TEXT, text=text)
        res = sanitize_file(pf, multi_env(pf.rel, [("k1", PSN, "doc", facts)]))
        self.assertEqual(res.content.count("40-59"), 2)
        self.assertNotIn("48", res.content)
        # same patient, single band: every form gets that band
        pf2 = ParsedFile(rel="t/c.txt", sha256="3" * 64, kind=KIND_TEXT, text=text)
        res2 = sanitize_file(pf2, multi_env(pf2.rel, [("k1", PSN, "doc", [_facts(48), _facts(46)])]))
        self.assertEqual(res2.content.count("40-49"), 2)

    def test_band_never_excludes_stated_age(self):
        # the record says 62 although the rest of the patient book says 48: the band must hold 62
        pf = self._pf([self._row("QRH-2077123", "Ilavar Pendse", 62)])
        env = multi_env(pf.rel, [("k1", PSN, "row:0", [_facts(48), _facts(49)])])
        row = list(csv.reader(io.StringIO(sanitize_file(pf, env).content)))[1]
        self.assertEqual(row[2], "60-69")

    def test_district_suppressed_in_small_cell(self):
        pf = self._pf([self._row("QRH-2077123", "Ilavar Pendse", 47)])
        res = sanitize_file(pf, env_for(pf.rel, ["row:0"]))
        row = list(csv.reader(io.StringIO(res.content)))[1]
        self.assertEqual(row[4], "[DISTRICT]")
        self.assertEqual(row[5], "[PIN]")
        self.assertNotIn("Sitapur", res.content)
        self.assertNotIn("261", res.content)
        self.assertEqual(row[7], "Fever")

    def test_district_kept_in_large_cell(self):
        names = ["Ilavar Pendse", "Mitul Rangra", "Oshan Telvi"]
        rows = [self._row("QRH-207712%d" % i, n, 41 + i) for i, n in enumerate(names)]
        pats = [("k%d" % i, "PSN-TESTAAAAA%d" % i, "row:%d" % i, [_facts(41 + i, name=n)])
                for i, n in enumerate(names)]
        pf = self._pf(rows)
        res = sanitize_file(pf, multi_env(pf.rel, pats))
        out = list(csv.reader(io.StringIO(res.content)))[1:]
        for row in out:
            self.assertEqual(row[2], "40-49")
            self.assertEqual(row[4], "Sitapur")
            self.assertEqual(row[5], "261XXX")
        # a fourth patient of another district stays alone in its cell -> suppressed
        rows.append(self._row("QRH-2077129", "Revan Kotiya", 44, "Hardoi"))
        pats.append(("k9", "PSN-TESTAAAAA9", "row:3", [_facts(44, district="Hardoi", name="Revan Kotiya")]))
        pf = self._pf(rows)
        out = list(csv.reader(io.StringIO(sanitize_file(pf, multi_env(pf.rel, pats)).content)))[1:]
        self.assertEqual(out[0][4], "Sitapur")
        self.assertEqual(out[3][4], "[DISTRICT]")
        self.assertNotIn("Hardoi", out[3][6])
        # geo_min_cell 0 disables suppression
        out = list(csv.reader(io.StringIO(sanitize_file(
            pf, multi_env(pf.rel, pats, {"geo_min_cell": 0})).content)))[1:]
        self.assertEqual(out[3][4], "Hardoi")
        self.assertEqual(out[3][5], "261XXX")

    def test_fhir_birthdate_removed_references_intact(self):
        data = {"resourceType": "Bundle", "id": "b2", "type": "collection", "entry": [
            {"fullUrl": "urn:uuid:p9", "resource": {
                "resourceType": "Patient", "id": "p9", "gender": "male", "birthDate": "1979-03-14",
                "name": [{"text": "Ilavar Pendse"}],
                "text": {"status": "generated", "div": "<div>Ilavar Pendse, 47 yrs, male, DOB 14/03/1979</div>"}}},
            {"fullUrl": "urn:uuid:o9", "resource": {
                "resourceType": "Observation", "id": "o9", "status": "final",
                "subject": {"reference": "urn:uuid:p9"}, "effectiveDateTime": "2026-05-02",
                "valueQuantity": {"value": 7.1, "unit": "%"}}}]}
        pf = ParsedFile(rel="fhir/c.json", sha256="4" * 64, kind=KIND_FHIR, data=data)
        out = json.loads(sanitize_file(pf, env_for(pf.rel, ["doc"])).content)
        p = out["entry"][0]["resource"]
        o = out["entry"][1]["resource"]
        self.assertNotIn("birthDate", p)
        self.assertEqual(p["resourceType"], "Patient")
        self.assertEqual(p["id"], "p9")
        self.assertEqual(o["subject"], {"reference": "urn:uuid:p9"})
        self.assertEqual(o["valueQuantity"], {"value": 7.1, "unit": "%"})
        self.assertIn("40-49", p["text"]["div"])
        self.assertNotIn("1979", json.dumps(out))


if __name__ == "__main__":
    unittest.main()


class NameReplacementGateTest(unittest.TestCase):
    """The shared gate every sanitize name-replacement path applies (invented values)."""

    def test_single_letters_and_units_never_replaced(self):
        from raksha.sanitize import name_replaceable
        self.assertFalse(name_replaceable("D"))
        self.assertFalse(name_replaceable("min"))
        self.assertFalse(name_replaceable("mg"))
        self.assertTrue(name_replaceable("Velunor"))

    def test_short_common_word_needs_four_letters(self):
        from raksha.sanitize import name_key_ok
        self.assertFalse(name_key_ok("min"))
        self.assertTrue(name_key_ok("Zorvi"))

    def test_name_keys_drop_units_keep_devanagari(self):
        from raksha.sanitize import _name_keys
        self.assertEqual(_name_keys("min"), [])
        self.assertTrue(_name_keys("Velunor Tashkiri"))
        self.assertTrue(_name_keys("वेलुनोर"))
