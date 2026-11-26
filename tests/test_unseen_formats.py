"""Label / identifier / date variants that neither the practice set nor scripts/chaos.py produce."""
import datetime as dt
import unittest

from raksha import dates as D, fields as F, patterns as P
from raksha.translit import same_name


class LabelVariants(unittest.TestCase):
    def test_labels(self):
        cases = {
            "Hospital ID": F.PATIENT_ID, "MR No": F.PATIENT_ID, "Card No": F.PATIENT_ID,
            "File No": F.PATIENT_ID, "Case ID": F.PATIENT_ID, "Enrolment No": F.PATIENT_ID,
            "MRD No.": F.PATIENT_ID, "Patient File No": F.PATIENT_ID,
            "Pitaji ka Naam": F.RELATIVE, "Janm Tithi": F.DOB, "Vayas": F.AGE, "Jendar": F.GENDER,
            "Thikana": F.ADDRESS, "Mouza": F.VILLAGE, "Jilha": F.DISTRICT, "Durbhash": F.PHONE,
            "Tahasil": F.TEHSIL, "submitted_by": F.NAME, "Consultant": F.DOCTOR,
            "Sample ID": F.OTHER_ID, "Bill No": F.OTHER_ID, "Forename": F.FIRST_NAME,
            "filename": F.FREE_TEXT, "Patient Name": F.NAME,
        }
        bad = [(k, F.classify_label(k), v) for k, v in cases.items() if F.classify_label(k) != v]
        self.assertEqual(bad, [])

    def test_value_shape_ids(self):
        self.assertEqual(F.classify_column("Pehchaan", ["MH-2026/004512", "MH-2026/004513", "KA-2025/000017"]),
                         F.PATIENT_ID)
        self.assertEqual(F.classify_column("Kram", ["IPD/26/0012", "IPD/26/0013", "IPD/26/0099"]), F.ENC_ID)
        self.assertNotIn(F.classify_column("Amount", ["14000", "500", "78500"]), (F.PATIENT_ID, F.ENC_ID))
        self.assertNotIn(F.classify_column("Sample Barcode", ["S26000225", "S26000226"]), (F.PATIENT_ID,))
        self.assertNotIn(F.classify_column("week", ["2026-W44", "2026-W45"]), (F.PATIENT_ID,))

    def test_phone_vs_aadhaar_shape(self):
        self.assertEqual(F.classify_values(["(+91) 98765 43210", "(+91) 70123 45678"]), F.PHONE)
        self.assertEqual(F.classify_values(["3972.0583.9628", "5185.9480.8328"]), F.AADHAAR)


class DateVariants(unittest.TestCase):
    def rt(self, text, iso):
        hits = D.find_dates(text)
        self.assertEqual([h.date.isoformat() for h in hits], [iso], text)
        shifted = D.shift_text(text, 41)
        self.assertNotEqual(shifted, text)
        self.assertEqual(D.shift_text(shifted, -41), text)

    def test_formats(self):
        self.rt("Sat, 24 Jan 2026", "2026-01-24")  # weekday is recomputed on shift
        self.rt("seen 2026-01-24 14:30:00 IST", "2026-01-24")
        self.rt("24.01.26", "2026-01-24")
        self.rt("DOB 12-Apr-45", "1945-04-12")
        self.rt("Jan-24-2026", "2026-01-24")
        self.rt("24 01 2026", "2026-01-24")
        self.rt("2026/1/5", "2026-01-05")
        self.rt("1977.04.12", "1977-04-12")
        self.rt("DOB: 29 Apr 72.", "1972-04-29")

    def test_not_dates(self):
        for t in ("v1.2.3", "192.168.1.1", "12.5.1", "2026.1.5", "BP 120/80", "1-0-1", "12 May 26 mg"):
            self.assertEqual(D.find_dates(t), [], t)

    def test_pivot(self):
        self.assertLessEqual(D.parse_one("01-Jan-30").year, 2030)
        self.assertEqual(D.parse_one("01-Jan-31"), dt.date(1931, 1, 1))


class IdentifierVariants(unittest.TestCase):
    def kinds(self, t):
        return [(s.kind, s.value) for s in P.find_identifiers(t)]

    def test_phone_aadhaar(self):
        self.assertEqual(self.kinds("ph 0091-98765-43210"), [("PHONE", "9876543210")])
        self.assertEqual(self.kinds("Aadhaar: 3972.0583.9628"), [("AADHAAR", "397205839628")])
        self.assertEqual(self.kinds("(0) 98765 43210"), [("PHONE", "9876543210")])

    def test_hospital_ids(self):
        self.assertEqual([s.value for s in P.find_patient_ids("Patient ID: P-00432")], ["P00432"])
        self.assertEqual([s.value for s in P.find_patient_ids("nursing_P.00454.txt")], ["P00454"])
        txt = [s.value for s in P.find_patient_ids("UHID#010607 reviewed")]
        self.assertEqual(txt, [P.norm_id("UHID#010607")])
        self.assertEqual(P.norm_id("mh-2026/004512"), P.norm_id("MH 2026 004512"))


class NameVariants(unittest.TestCase):
    def test_vowel_slips(self):
        self.assertTrue(same_name("Pandoorang Pereeera", "Pandurang Pereira"))
        self.assertTrue(same_name("Hareesh", "Harish"))
        self.assertFalse(same_name("Rajesh", "Rajiv"))


if __name__ == "__main__":
    unittest.main()


class CrossFileIds(unittest.TestCase):
    def test_harvest_all_upgrades_unlabelled_id_column(self):
        from raksha import harvest as H
        from raksha.types import KIND_CSV, ParsedFile
        a = ParsedFile(rel="a.csv", sha256="a", kind=KIND_CSV, header=["UHID", "Name"],
                       rows=[["QX-110", "Asha Verma"], ["QX-120", "Ravi Rao"]])
        b = ParsedFile(rel="b.csv", sha256="b", kind=KIND_CSV, header=["Zzq", "Result"],
                       rows=[["qx 110", "7.6"], ["QX/120", "8.1"]])
        self.assertFalse(any(r.facts.ids for r in H.harvest_file(b)))
        out = H.harvest_all([a, b])
        self.assertEqual([r.facts.ids for r in out["b.csv"]], [["uhid:QX110"], ["uhid:QX120"]])
        H.prepare([])


class FreshDataFixesTest(unittest.TestCase):
    def test_native_script_pin_after_village_label(self):
        from raksha import detect
        for s in ("கிராமம்: மேலூர், மதுரை - 625106", "ਪਿੰਡ: ਰਾਏਕੋਟ, ਲੁਧਿਆਣਾ - ੧੪੧੧੦੯", "ગામ: બોરસદ, આણંદ - ૩૮૮૫૪૦"):
            self.assertIn("PIN", [x.kind for x in detect.detect(s)], s)

    def test_country_code_mobile_without_separator(self):
        from raksha import detect
        s = "Contact: 919656922594"
        self.assertEqual([x.kind for x in detect.detect(s)], ["PHONE"])

    def test_doctor_value_under_person_key_is_kept(self):
        from raksha import fields
        self.assertEqual(fields.json_key_type(["encounters", "attending"], "Dr. Ketan Vyas"), fields.DOCTOR)
        self.assertEqual(fields.json_key_type(["guardian", "name"], "Dr. Ajay"), fields.RELATIVE)

    def test_hl7_is_quarantined(self):
        import tempfile
        from pathlib import Path
        from raksha import ingest
        d = Path(tempfile.mkdtemp())
        (d / "a.hl7").write_text("MSH|^~\\&|HIS|X\rPID|1||KMT/2026/1||Rao^Lavanya\r")
        self.assertEqual(ingest.load(d / "a.hl7", d).kind, "quarantine")


class AdversarialVariantsTest(unittest.TestCase):
    def _kinds(self, s):
        from raksha import detect
        return [(x.kind, s[x.start:x.end]) for x in detect.detect(s)]

    def test_misspelt_and_ocr_labels(self):
        for s in ("Patinet Nmae: Kavitha Hegde", "Pat1ent Narne: Kavitha Hegde"):
            self.assertIn(("PATIENT_NAME", "Kavitha Hegde"), self._kinds(s))

    def test_surname_first_with_comma(self):
        self.assertIn(("PATIENT_NAME", "HEGDE, KAVITHA"), self._kinds("Patient Name: HEGDE, KAVITHA"))
        self.assertIn(("RELATIVE_NAME", "SHARMA, RAJESH"), self._kinds("Father: SHARMA, RAJESH"))

    def test_initials_after_patient_word(self):
        self.assertIn(("PATIENT_NAME", "C. Rathod"), self._kinds("Pt C. Rathod (71 y/o female) seen"))
        self.assertIn(("PATIENT_NAME", "K. Choudhary"), self._kinds("Pt K. Choudhary seen"))

    def test_one_letter_drug_forms_still_protected(self):
        from raksha import patterns
        for s in ("C. Pan-D 40 mg OD", "T. Dolo 650 1-0-1", "T. Crocin SOS"):
            self.assertEqual(self._kinds(s), [], s)
            self.assertIn("DOSE", [x.kind for x in patterns.protected_spans(s)], s)

    def test_double_spaced_aadhaar(self):
        self.assertEqual(self._kinds("Aadhaar 9553  0422  8134"), [("AADHAAR", "9553  0422  8134")])

    def test_reference_numbers_redacted_not_linked(self):
        from raksha import detect
        self.assertEqual(self._kinds("ref no NMC/25/137211"), [("REF_ID", "NMC/25/137211")])
        self.assertEqual(detect.text_facts("ref no NMC/25/137211").ids, [])

    def test_initial_is_not_a_name_key(self):
        from raksha import sanitize
        self.assertEqual(sanitize._name_keys("R. Hegde"), [sanitize._name_keys("Hegde")[0]])


class RobustnessSweepTest(unittest.TestCase):
    """Odd but plausible inputs end in a full release with none of the planted (invented) values."""

    PLANTED = ("Ravindra Pokharkar", "9811122334", "Suvarna Tidke", "9722233445", "3041 7712 905",
               "Kunnathu Veedu", "Dhanraj Ukey")

    def _run(self, files):
        import contextlib
        import io
        import json
        import tempfile
        from pathlib import Path
        from raksha import pipeline
        from raksha.policy import DEFAULTS
        with tempfile.TemporaryDirectory() as td:
            inp, out = Path(td) / "in", Path(td) / "out"
            for rel, body in files.items():
                p = inp / rel
                p.parent.mkdir(parents=True, exist_ok=True)
                p.write_bytes(body.encode("utf-8"))
            with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
                pipeline.run(inp, out, b"unit-secret", dict(DEFAULTS))
            blob = b""
            for p in sorted(out.rglob("*")):
                if p.is_file():
                    blob += p.read_bytes() + str(p.relative_to(out)).encode("utf-8")
            recs = [json.loads(x) for x in (out / "records.jsonl").read_text(encoding="utf-8").splitlines() if x]
            return blob.decode("utf-8", "replace"), recs

    def test_sweep(self):
        fhir = ('{"resourceType": "Bundle", "type": "collection", "entry": [{"resource": {"resourceType": '
                '"Patient", "name": [{"text": "Dhanraj Ukey"}], "telecom": [{"value": "9811122334"}]}}]}')
        files = {
            "a/header_line3.csv": "OPD register\nexported 2026\nname,mobile,diagnosis\n"
                                  "Ravindra Pokharkar,9811122334,Lobar pneumonia\n",
            "a/totals.tsv": "name\tmobile\tamount\nSuvarna Tidke\t9722233445\t1200\nTOTAL\t\t1200\n",
            "a/single.json": '"Ravindra Pokharkar 9811122334"',
            "a/scalars.json": '["Lobar pneumonia", 3, "9811122334"]',
            "a/broken.ndjson": '{"name": "Suvarna Tidke", "mobile": "9722233445"}\n{"name": "x", \n'
                               '{"name": "Ravindra Pokharkar", "mobile": "9811122334"}\n',
            "a/empty_bundle.json": '{"resourceType": "Bundle", "type": "collection", "entry": []}',
            "a/headers_only.csv": "name,mobile,diagnosis\n",
            "b/Ravindra Pokharkar रवि 9811122334 notes.txt": "Seen in OPD. Stable.\n",
            "Ravindra Pokharkar/l2/l3/l4/visit.txt": "Patient Ravindra Pokharkar, mob 9811122334. BP 120/80.\n",
            "c/one/same.csv": "name,mobile\nSuvarna Tidke,9722233445\n",
            "c/two/same.csv": "name,mobile\nDhanraj Ukey,9811122334\n",
            "d/bundle.csv": fhir,
            "e/preauth.txt": "# pre-auth\ninsured.name = Ravindra Pokharkar\ninsured.house = Kunnathu Veedu\n"
                             "insured.landline = 9811122334\nproposer.bank_ac = 3041 7712 905\n"
                             "diagnosis.1 = Lobar pneumonia\n",
            "e/claims.csv": 'claim_batch,name,bank_ac,address\n9988776655,Suvarna Tidke,3041 7712 905,'
                            '"Kunnathu Veedu,\nMele Para,\nKottayam 686001"\n',
        }
        blob, recs = self._run(files)
        for v in self.PLANTED:
            self.assertNotIn(v, blob)
        self.assertNotIn("686001", blob)
        self.assertIn("Lobar pneumonia", blob)
        self.assertIn("9988776655", blob)                 # a claim batch number stays
        st = {r["file"]: r["status"] for r in recs}
        self.assertFalse(any("broken.ndjson" in f for f in st), st)    # quarantined, never passed through
        self.assertEqual(sum(1 for f in st if f.endswith("same.csv")), 2)
