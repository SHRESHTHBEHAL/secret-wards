"""Free-text rule families (invented names and places only)."""
import unittest

from raksha import detect, patterns


def kinds(text, kind=None):
    return [(sp.kind, text[sp.start:sp.end]) for sp in detect.detect(text) if kind is None or sp.kind == kind]


def ids(text):
    return [(sp.kind, text[sp.start:sp.end]) for sp in patterns.find_identifiers(text)]


class PhoneShapes(unittest.TestCase):
    def test_landline_and_wrap(self):
        self.assertIn(("PHONE", "020 2553 0000"), ids("sister (Ph. 020 2553 0000)"))
        self.assertIn(("PHONE", "0389-2340000"), ids("call 0389-2340000 today"))
        self.assertIn(("PHONE", "90031\n77400"), ids("mob 90031\n77400"))

    def test_reference_veto(self):
        for t in ("Trip ID 8794000066", "package 9848000045", "Lab ref LRN-9845000067", "Ref no ABC/26/9830000045"):
            self.assertEqual([k for k, _ in ids(t) if k == "PHONE"], [], t)

    def test_partial_aadhaar(self):
        self.assertIn(("AADHAAR_MASKED", "4321"), ids("Aadhaar last four 4321 only"))
        self.assertEqual(ids("Hb last four days 9.1"), [])


class KeepValues(unittest.TestCase):
    def test_reference_numbers_not_patient_ids(self):
        for t in ("Lab No. Q-1234/26", "Cyto No Q-1187/26", "MLR No QX/26/77100"):
            self.assertEqual([sp for sp in patterns.find_patient_ids(t)], [], t)
        self.assertTrue(patterns.find_patient_ids("UHID No. QQ26-0091-5540"))

    def test_eponyms_and_schemes(self):
        t = "Forrest IIa ulcer; Orphan Annie nuclei; enrolled in Pradhan Sahayata Yojana and Mission Swasthya."
        self.assertEqual(kinds(t, "PERSON") + kinds(t, "PATIENT_NAME"), [])

    def test_institution_after_name(self):
        self.assertEqual(kinds("Referred to Ratanpur SDH for USG."), [])
        self.assertEqual(kinds("Accompanied by ASHA and nurse."), [])

    def test_history_of(self):
        self.assertEqual(kinds("H/O NSAID intake for two months.", "RELATIVE_NAME"), [])
        self.assertTrue(kinds("H/O Bikram Tandel, attendant.", "RELATIVE_NAME"))

    def test_police_station_kept(self):
        t = "निवासी ग्राम सोनपुरा, थाना रतनगढ़, जिला कोटा"
        self.assertFalse(any("रतनगढ़" in v for _, v in kinds(t)))


class NameFrames(unittest.TestCase):
    def test_name_before_age_sex(self):
        self.assertIn(("PATIENT_NAME", "Bhavik Tamrakar"), kinds("Seen Bhavik Tamrakar, 34/M today."))
        self.assertIn(("PATIENT_NAME", "Ojasvi Rane"), kinds("Patient Ojasvi Rane (F/57) reviewed"))
        self.assertEqual(kinds("Dr. Ojasvi Rane, 45/F", "PATIENT_NAME"), [])

    def test_lowercase_hinglish(self):
        t = "aaj tulsiya ke ghar gayi. pati bhimraj ne gaadi bulayi"
        got = [v for _, v in kinds(t)]
        self.assertIn("tulsiya", got)
        self.assertIn("bhimraj", got)
        self.assertEqual(kinds("pati ne bataya ki bukhar hai"), [])

    def test_slash_header(self):
        t = "Ketaki Pandit/41F/QMC2600999/OT-2/Dr. Vimal Joshi"
        got = kinds(t)
        self.assertIn(("PATIENT_NAME", "Ketaki Pandit"), got)
        self.assertIn(("MRN", "QMC2600999"), got)
        self.assertFalse(any("Vimal" in v for _, v in got))

    def test_declarant_and_third_party(self):
        self.assertIn(("PERSON", "Tarakesh"), kinds("I, Tarakesh, son of the patient"))
        self.assertTrue(kinds("documents couriered by Jharna Mookerjee, ABHA pending"))
        got = [v for _, v in kinds("sons Pravin and Ujjwal were informed")]
        self.assertEqual(got, ["Pravin", "Ujjwal"])

    def test_devanagari_pid_label(self):
        t = "भर्ती संख्या - कखग/२६/०१२३४"
        self.assertTrue(kinds(t, "MRN"))


class Addresses(unittest.TestCase):
    def test_house_and_lane(self):
        got = kinds("Correspondence address: # 4471, Sector 19-C, near Ratanpur water tank.")
        self.assertIn(("HOUSE", "# 4471"), got)
        self.assertIn(("LOCALITY", "Sector 19-C"), got)
        self.assertTrue(any(k == "LANDMARK" for k, _ in got))
        self.assertEqual(kinds("Block 2 nerve conduction normal"), [])

    def test_landmark_postposition(self):
        self.assertTrue(any(k in ("LANDMARK", "VILLAGE", "LOCALITY") for k, _ in kinds("ghar purani chakki ke paas hai")))
        self.assertTrue(kinds("हनुमान मंदिर के सामने रहते हैं", "LANDMARK"))
        self.assertEqual(kinds("near normal limits; behind the eye"), [])


if __name__ == "__main__":
    unittest.main()
