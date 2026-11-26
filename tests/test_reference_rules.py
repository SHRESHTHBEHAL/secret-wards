"""Rules distilled from the reference annotator's cues (invented names and places only)."""
import unittest

from raksha import detect as D
from raksha import fields as F
from raksha import harvest as H


def kinds(text):
    return [(sp.kind, text[sp.start:sp.end]) for sp in D.detect(text)]


def surfaces(text, kind=None):
    return [s for k, s in kinds(text) if kind is None or k == kind]


class LabelStems(unittest.TestCase):
    def test_name_of_pt_with_initials(self):
        t = "Name of Pt.: P. V. Ramadurai    Sex/Age: M/60"
        self.assertIn("P. V. Ramadurai", surfaces(t, "PATIENT_NAME"))

    def test_double_colon_label(self):
        self.assertIn("Jaiveer Tondak", surfaces("Patient :: Jaiveer Tondak\n", "PATIENT_NAME"))

    def test_doctor_after_label_kept(self):
        self.assertEqual(surfaces("Name of Pt.: Dr. K. Mehtani\n", "PATIENT_NAME"), [])

    def test_fo_relation_marker(self):
        self.assertIn("S. Gopalarathnam", surfaces("F/O: S. Gopalarathnam\n", "RELATIVE_NAME"))

    def test_witness_hindi(self):
        self.assertIn("रमाकांत धुर्वे", surfaces("गवाह: रमाकांत धुर्वे\n"))


class Residence(unittest.TestCase):
    def test_prose_resident_of(self):
        t = "Mrs. Velmathi Arasu, resident of 9/3 Temple Street, Kottur, Salem dist. Her BP is 130/80."
        k = kinds(t)
        self.assertIn(("ADDRESS", "Kottur"), k)
        self.assertIn(("DISTRICT", "Salem dist"), k)
        self.assertFalse(any("BP" in s for _, s in k))

    def test_hindi_nivasi(self):
        t = "निवासी मकान सं. 12, गांधी नगर, पटना, अपने ऑपरेशन की सहमति देती हूँ।"
        k = kinds(t)
        self.assertIn(("LOCALITY", "गांधी नगर"), k)
        self.assertIn(("DISTRICT", "पटना"), k)
        self.assertFalse(any("ऑपरेशन" in s for _, s in k))

    def test_district_before_pin_is_a_place(self):
        t = "R/O: Plot 4, Nehru Colony, P.O. Kandi, Bara Banki - 225001"
        k = kinds(t)
        self.assertIn(("DISTRICT", "Bara Banki"), k)
        self.assertFalse(any(kd in D.NAME_KINDS for kd, _ in k))


class Persons(unittest.TestCase):
    def test_signoff(self):
        self.assertIn("Rohini", surfaces("Please confirm.\nThanks,\nRohini\n", "PERSON"))

    def test_signoff_doctor_kept(self):
        self.assertEqual(surfaces("Regards,\nDr. Rohini Pathak\n", "PERSON"), [])

    def test_my_mother(self):
        self.assertIn("Kamala Venkatesh", surfaces("Appointment for my mother Kamala Venkatesh\n"))

    def test_kin_word_without_name(self):
        self.assertEqual([k for k, _ in kinds("mother Diabetic since 2019.") if k in D.NAME_KINDS], [])

    def test_lower_case_nursing_names(self):
        t = "pt meenakshiya ko raat se bukhar hai. attndnt (husband ramprakash) ko bataya."
        k = kinds(t)
        self.assertIn(("PATIENT_NAME", "meenakshiya"), k)
        self.assertIn(("RELATIVE_NAME", "ramprakash"), k)

    def test_lower_case_clinical_words_not_names(self):
        t = "pt bukhar ko dawa di. attendant (husband absent) informed."
        self.assertEqual([k for k, _ in kinds(t) if k in D.NAME_KINDS], [])


class Ids(unittest.TestCase):
    def test_lab_ref_is_not_patient_id(self):
        self.assertEqual(F.classify_column("Lab Ref", ["L-2001", "L-2002"]), F.OTHER_ID)
        self.assertEqual(F.classify_column("Hosp ID", ["QX-551204", "QX-551299"]), F.PATIENT_ID)

    def test_id_shaped_keys(self):
        self.assertTrue(H.id_shaped_key("QX-551204"))
        self.assertTrue(H.id_shaped_key("MRD/2025/0042"))
        self.assertFalse(H.id_shaped_key("L-1001"))
        self.assertFalse(H.id_shaped_key("2026-01-05"))
        self.assertFalse(H.id_shaped_key("name"))

    def test_keyed_collection(self):
        d = {"patients": {"QX-551204": {"naam": "Harsimran Gill", "sampark": "9812345670"},
                          "QX-551299": {"naam": "Tsering Dolma", "sampark": "9812345671"}}}
        out = []
        H._record_arrays(d, "", [], out)
        self.assertEqual([u[0] for u in out], ["/patients/QX-551204", "/patients/QX-551299"])
        self.assertEqual(H.keyed_record_id("/patients/QX-551204"), "QX-551204")

    def test_dated_object_not_a_collection(self):
        d = {"vitals": {"2026-01-05": {"bp": "120/80"}, "2026-01-06": {"bp": "118/76"}}}
        out = []
        H._record_arrays(d, "", [], out)
        self.assertEqual(out, [])


if __name__ == "__main__":
    unittest.main()
