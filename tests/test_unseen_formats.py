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
        self.rt("Mon, 24 Jan 2026", "2026-01-24")
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
