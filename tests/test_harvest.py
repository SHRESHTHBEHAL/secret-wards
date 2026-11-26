"""Tests for raksha.harvest (invented data only)."""
from __future__ import annotations

import base64
import datetime as dt
import unittest

from raksha import harvest
from raksha.types import KIND_CSV, KIND_FHIR, KIND_JSON, KIND_QUARANTINE, KIND_TEXT, ParsedFile


def _csv(header, rows, rel="reg/test.csv", delim=","):
    return ParsedFile(rel=rel, sha256="x", kind=KIND_CSV, header=header, rows=rows, delimiter=delim)


def _json(data, rel="opd/test.json", kind=KIND_JSON):
    return ParsedFile(rel=rel, sha256="x", kind=kind, data=data)


class CsvTests(unittest.TestCase):
    def test_split_names_relative_ids_dates(self):
        pf = _csv(
            ["PatientID", "LastName", "FirstName", "Sex", "DOB (MM/DD/YYYY)", "Guardian", "City", "Zip",
             "Phone", "Registered (MM/DD/YYYY)"],
            [["UHID-123456", "Verma", "Tarun", "M", "03/25/1981", "S/O KAMLESH VERMA", "Rampura", "226010",
              "98111-22334", "01/15/2026"],
             [],
             ["UHID-123457", "Saxena", "Rupa", "F", "07/04/1990", "W/O ANIL SAXENA", "Bhawanpur", "226011",
              "", "02/16/2026"]])
        recs = harvest.harvest_file(pf)
        self.assertEqual([r.loc for r in recs], ["row:0", "row:1", "row:2"])
        f = recs[0].facts
        self.assertIn("Tarun Verma", f.names)
        self.assertIn("uhid:UHID123456", f.ids)
        self.assertIn("phone:9811122334", f.ids)
        self.assertIn("UHID-123456", f.raw_ids)
        self.assertEqual(f.dob, dt.date(1981, 3, 25))
        self.assertEqual(f.gender, "M")
        self.assertEqual(f.village, "Rampura")
        self.assertEqual(f.pin, "226010")
        self.assertEqual(f.ref_date, dt.date(2026, 1, 15))
        self.assertEqual([n for _r, n in f.relatives], ["KAMLESH VERMA"])
        self.assertEqual(f.relatives[0][0], "S/o")
        self.assertTrue(f.is_patient)
        self.assertEqual(recs[1].facts.names, [])

    def test_hindi_header_tsv_row(self):
        pf = _csv(["Reg No", "Naam", "Ling", "Umar", "Janm Tithi", "Pita/Pati ka Naam", "Gaon", "Mobile No",
                   "Aadhar", "Registration Date"],
                  [["ABC-0012345", "सीमा यादव", "महिला", "47 वर्ष", "14-08-1978", "D/o रामू यादव", "नयागांव",
                    "07612-345678", "4321 5678 9012", "08-05-2026"]], rel="reg/test.tsv", delim="\t")
        f = harvest.harvest_file(pf)[0].facts
        self.assertIn("सीमा यादव", f.names)
        self.assertEqual(f.gender, "F")
        self.assertEqual(f.age, 47)
        self.assertEqual(f.dob, dt.date(1978, 8, 14))
        self.assertIn(("D/o", "रामू यादव"), f.relatives)
        self.assertIn("aadhaar:432156789012", f.ids)
        self.assertIn("uhid:ABC0012345", f.ids)

    def test_relation_column_masked_aadhaar_address_care_of(self):
        pf = _csv(["UHID", "Patient Name", "Age", "Relation", "Relative Name", "Address", "Aadhaar No"],
                  [["XYZ/26/000111", "Mohan Lal", "60", "S/o", "Hari Lal",
                    "C/O Hari Lal, H.No. 12, Ward 3, near Shiv Mandir", "XXXX XXXX 1234"]])
        f = harvest.harvest_file(pf)[0].facts
        self.assertIn(("S/o", "Hari Lal"), f.relatives)
        self.assertFalse(any(t.startswith("aadhaar:") for t in f.ids))
        self.assertEqual(f.age, 60)
        self.assertNotIn("Hari Lal", f.names)

    def test_age_sex_lab_rows(self):
        pf = _csv(["sample_id", "patient_name", "age_sex", "uhid", "test", "result", "collected_on"],
                  [["S1000001", "Kiran Devi", "65/F", "QQH-0001234", "Haemoglobin", "11.2", "15/10/2026"]])
        f = harvest.harvest_file(pf)[0].facts
        self.assertEqual((f.age, f.gender), (65, "F"))
        self.assertEqual(f.ref_date, dt.date(2026, 10, 15))

    def test_non_patient_log(self):
        pf = _csv(["trip", "from", "to", "remarks"],
                  [["AMB-101", "Townpur", "Cityganj", "called by Meena Joshi 94123-45678"]])
        f = harvest.harvest_file(pf)[0].facts
        self.assertFalse(f.is_patient)
        self.assertIn("phone:9412345678", f.ids)

    def test_ragged_and_empty(self):
        pf = _csv(["a"], [["x", "y", None], [None]])
        self.assertEqual([r.loc for r in harvest.harvest_file(pf)], ["row:0", "row:1"])


class JsonTests(unittest.TestCase):
    def test_nested_patient_array(self):
        data = {"facility": {"name": "Some Hospital"}, "patients": [{
            "uhid": "ZZH2026-000123", "name": {"first": "Lata", "last": "Gupta", "local": "लता गुप्ता"},
            "gender": "female", "dob": "1980-02-03",
            "guardian": {"relation": "W/o", "name": "Suresh Gupta"},
            "contact": {"mobile": "9876501234"}, "address": {"village": "Kherpur", "pin": "241001"},
            "ids": {"aadhar_no": 234567890123}}]}
        recs = harvest.harvest_file(_json(data))
        self.assertEqual([r.loc for r in recs], ["/patients/0"])
        f = recs[0].facts
        self.assertIn("Lata Gupta", f.names)
        self.assertIn("लता गुप्ता", f.names)
        self.assertIn(("W/o", "Suresh Gupta"), f.relatives)
        self.assertIn("aadhaar:234567890123", f.ids)
        self.assertIn("phone:9876501234", f.ids)
        self.assertEqual(f.dob, dt.date(1980, 2, 3))
        self.assertEqual(f.gender, "F")
        self.assertTrue(f.is_patient)

    def test_opd_visit_with_patient_ref_only(self):
        data = {"_export_meta": {"source_path": "D:\\exports\\Some_Name_0001\\v.json"},
                "visits": [{"visit_id": "OPD/26/01/00001", "patient_ref": "QQH-0007777",
                            "visit_date": "18-05-2026", "complaints": "fever x 3 days"},
                           {"visit_id": "OPD/26/01/00002", "patient_ref": "QQH-0007778",
                            "visit_date": "19-05-2026", "patient": {"name": "Ravi Kant", "age_sex": "40/M"}}]}
        recs = harvest.harvest_file(_json(data))
        self.assertEqual([r.loc for r in recs], ["/visits/0", "/visits/1"])
        self.assertIn("uhid:QQH0007777", recs[0].facts.ids)
        self.assertEqual(recs[0].facts.ref_date, dt.date(2026, 5, 18))
        self.assertEqual(recs[1].facts.names, ["Ravi Kant"])
        self.assertEqual((recs[1].facts.age, recs[1].facts.gender), (40, "M"))

    def test_honorific_after_own_name_is_not_a_relative(self):
        data = {"visits": [{"patient_ref": "QQH-0005555", "patient": {"name": "Kamla Devi"},
                            "notes": "Kamla amma ka BP 120/80, review after 2 weeks."}]}
        f = harvest.harvest_file(_json(data))[0].facts
        self.assertNotIn("Kamla", [n for _r, n in f.relatives])

    def test_reference_data_and_non_patient_json(self):
        recs = harvest.harvest_file(_json({"wards": [{"ward": "Ward 1", "beds": 30}]}))
        self.assertEqual([r.loc for r in recs], ["doc"])
        self.assertEqual(recs[0].facts.names, [])
        tickets = {"tickets": [{"id": "HD-0001", "category": "billing query",
                                "meta": {"raised_by": {"name": "Neelam Rao", "callback": "9123456780"}}}]}
        recs = harvest.harvest_file(_json(tickets))
        self.assertEqual([r.loc for r in recs], ["doc"])
        self.assertFalse(recs[0].facts.is_patient)
        self.assertIn("phone:9123456780", recs[0].facts.ids)

    def test_single_report_with_file_name_phone_and_b64(self):
        note = base64.b64encode("Sample of Gopal Das, mobile 9988776655.".encode()).decode()
        data = {"lab": "Some Lab", "patient": {"name": "Gopal Das", "age": 50, "hospital_uhid": "QQH-0001111"},
                "attachment": {"data": note}}
        recs = harvest.harvest_file(_json(data, rel="lab/9012345678_report_0001.json"))
        self.assertEqual([r.loc for r in recs], ["doc"])
        f = recs[0].facts
        self.assertIn("phone:9012345678", f.ids)
        self.assertIn("phone:9988776655", f.ids)
        self.assertIn("uhid:QQH0001111", f.ids)
        self.assertEqual(f.age, 50)

    def test_deep_and_odd_values(self):
        deep = cur = {}
        for _ in range(200):
            cur["x"] = {}
            cur = cur["x"]
        for data in (deep, [1, None, "a"], {"a": None, "b": float("nan")}, "text", None):
            recs = harvest.harvest_file(_json(data))
            self.assertTrue(recs)


class FhirTests(unittest.TestCase):
    def test_bundle(self):
        att = base64.b64encode("Referral: Pooja Sen, mobile 9090909090".encode()).decode()
        data = {"resourceType": "Bundle", "entry": [
            {"resource": {"resourceType": "Patient",
                          "text": {"div": "<div>Pooja Sen, 30 yrs</div>"},
                          "identifier": [{"type": {"coding": [{"code": "MR"}]}, "value": "ABC/26/000999"},
                                         {"system": "https://healthid.abdm.gov.in", "value": "91-1111-2222-3333"}],
                          "name": [{"text": "Pooja Sen", "given": ["Pooja"], "family": "Sen"}],
                          "telecom": [{"system": "phone", "value": "+91-9090909090"}],
                          "gender": "female", "birthDate": "1996-01-02",
                          "address": [{"line": ["H.No. 5, near Bus Stand"], "city": "Lalpur", "postalCode": "226001"}]}},
            {"resource": {"resourceType": "Encounter", "identifier": [{"value": "IPD-2026-00999"}],
                          "period": {"start": "2026-02-04T18:15:00+05:30"}}},
            {"resource": {"resourceType": "RelatedPerson", "relationship": [{"text": "husband"}],
                          "name": [{"text": "Amit Sen"}]}},
            {"resource": {"resourceType": "DocumentReference", "content": [{"attachment": {"data": att}}]}}]}
        recs = harvest.harvest_file(_json(data, rel="fhir/b1.json", kind=KIND_FHIR))
        self.assertEqual([r.loc for r in recs], ["doc"])
        f = recs[0].facts
        self.assertIn("Pooja Sen", f.names)
        for tok in ("uhid:ABC26000999", "abha:91111122223333", "enc:IPD202600999", "phone:9090909090"):
            self.assertIn(tok, f.ids)
        self.assertEqual(f.dob, dt.date(1996, 1, 2))
        self.assertEqual(f.ref_date, dt.date(2026, 2, 4))
        self.assertEqual((f.gender, f.village, f.pin), ("F", "Lalpur", "226001"))
        self.assertIn("Amit Sen", [n for _r, n in f.relatives])


class TextTests(unittest.TestCase):
    def test_text_note_and_file_name(self):
        text = "DISCHARGE SUMMARY\nPatient Name: Nirmala Joshi   Age: 52 Yrs   Sex: F\nDOA: 03/02/2026\n"
        pf = ParsedFile(rel="discharge/Discharge_Summary_Nirmala_Joshi_ABC-26-000123.txt", sha256="x",
                        kind=KIND_TEXT, text=text)
        recs = harvest.harvest_file(pf)
        self.assertEqual([r.loc for r in recs], ["doc"])
        f = recs[0].facts
        self.assertIn("Nirmala Joshi", f.names)
        self.assertIn("uhid:ABC26000123", f.ids)
        self.assertTrue(f.is_patient)

    def test_file_name_admission_number(self):
        pf = ParsedFile(rel="notes/nursing_adm000999.txt", sha256="x", kind=KIND_TEXT,
                        text="Night: patient slept well. BP 120/80.")
        self.assertIn("enc:ADM000999", harvest.harvest_file(pf)[0].facts.ids)

    def test_lowercase_file_name_gives_no_name_or_bogus_id(self):
        pf = ParsedFile(rel="prescriptions/rx_somehospital_00012.txt", sha256="x", kind=KIND_TEXT,
                        text="Rx\nTab Paracetamol 650 mg")
        f = harvest.harvest_file(pf)[0].facts
        self.assertEqual(f.names, [])
        self.assertFalse(any(t.startswith("uhid:") for t in f.ids))

    def test_visitor_log_not_patient(self):
        pf = ParsedFile(rel="notes/log.txt", sha256="x", kind=KIND_TEXT,
                        text="VISITOR LOG\n18:40 - Om Prakash (attendant, bed 4), mob 9345678901\n")
        f = harvest.harvest_file(pf)[0].facts
        self.assertFalse(f.is_patient)
        self.assertIn("phone:9345678901", f.ids)

    def test_quarantine_has_no_records(self):
        pf = ParsedFile(rel="x.bin", sha256="x", kind=KIND_QUARANTINE, reason="unsupported_format")
        self.assertEqual(harvest.harvest_file(pf), [])
        self.assertEqual(harvest.record_locs(pf), [])


class HelperTests(unittest.TestCase):
    def test_split_relative_and_gender(self):
        self.assertEqual(harvest.split_relative("S/O SHYAM LAL"), ("S/o", "SHYAM LAL"))
        self.assertEqual(harvest.split_relative("d/o  किशन"), ("D/o", "किशन"))
        self.assertEqual(harvest.split_relative("Ram Lal"), ("", "Ram Lal"))
        for w, g in (("Male", "M"), ("f", "F"), ("पुरुष", "M"), ("महिला", "F"), ("Purush", "M"),
                     ("Mahila", "F"), ("other", "")):
            self.assertEqual(harvest.gender_of(w), g)


if __name__ == "__main__":
    unittest.main()
