from __future__ import annotations

import unittest

from raksha import lexicon, patterns as P


def kinds(spans):
    return [s.kind for s in spans]


def vals(spans, kind):
    return [s.value for s in spans if s.kind == kind]


def _verhoeff_append(base: str) -> str:
    for d in "0123456789":
        if P.verhoeff_ok(base + d):
            return base + d
    raise AssertionError


class TestPhones(unittest.TestCase):
    def test_formats(self):
        cases = {
            "Mobile: +91 73521 40986": "7352140986",
            "ph 68412-55307": "6841255307",
            "Mob 060073-81264": "6007381264",
            "call 8172630945 now": "8172630945",
            "+91-6928374615": "6928374615",
            "+919812345670": "9812345670",
            "मोबाइल: ९८७६५४३२१०": "9876543210",
            "0 98123 45678": "9812345678",
        }
        for text, want in cases.items():
            with self.subTest(text=text):
                self.assertEqual(vals(P.find_identifiers(text), "PHONE"), [want])

    def test_offsets_on_devanagari_digits(self):
        t = "फोन ८५९९२५३५२१ है"
        sp = P.find_identifiers(t)
        self.assertEqual(len(sp), 1)
        self.assertEqual(t[sp[0].start:sp[0].end], "८५९९२५३५२१")

    def test_norm_phone(self):
        self.assertEqual(P.norm_phone("+91 98765 43210"), "9876543210")
        self.assertEqual(P.norm_phone("09876543210"), "9876543210")
        self.assertEqual(P.norm_phone("919876543210"), "9876543210")
        self.assertEqual(P.norm_phone("1234567890"), "")
        self.assertEqual(P.norm_phone("49500"), "")


class TestGovIds(unittest.TestCase):
    def test_aadhaar(self):
        self.assertEqual(vals(P.find_identifiers("Aadhaar 482913570264"), "AADHAAR"), ["482913570264"])
        self.assertEqual(vals(P.find_identifiers("Aadhar: 4829 1357 0264"), "AADHAAR"), ["482913570264"])
        self.assertEqual(vals(P.find_identifiers("UID 4829-1357-0264"), "AADHAAR"), ["482913570264"])
        self.assertEqual(vals(P.find_identifiers("आधार ४८२९ १३५७ ०२६४"), "AADHAAR"), ["482913570264"])

    def test_aadhaar_masked(self):
        for t in ("XXXX XXXX 7731", "xxxx-xxxx-7731", "********7731", "XXXXXXXX7731"):
            with self.subTest(t=t):
                self.assertEqual(kinds(P.find_identifiers("Aadhaar " + t)), ["AADHAAR_MASKED"])

    def test_abha(self):
        self.assertEqual(vals(P.find_identifiers("ABHA No: 91-5521-8830-4417"), "ABHA_NUMBER"),
                         ["91552188304417"])
        self.assertEqual(vals(P.find_identifiers("ABHA 91552188304417"), "ABHA_NUMBER"), ["91552188304417"])
        self.assertEqual(kinds(P.find_identifiers("abha addr kamla.devi88@abdm")), ["ABHA_ADDRESS"])
        self.assertEqual(kinds(P.find_identifiers("raju_k@sbx")), ["ABHA_ADDRESS"])

    def test_email_pan(self):
        self.assertEqual(vals(P.find_identifiers("mail ravi.k1987@example.org."), "EMAIL"),
                         ["ravi.k1987@example.org"])
        self.assertEqual(vals(P.find_identifiers("PAN: ABQPK1234L"), "PAN"), ["ABQPK1234L"])
        self.assertEqual(vals(P.find_identifiers("pan abqpk1234l"), "PAN"), ["ABQPK1234L"])

    def test_insurance(self):
        self.assertEqual(vals(P.find_identifiers("PMJAY-UP-6614290837"), "INSURANCE_ID"), ["PMJAYUP6614290837"])
        self.assertEqual(vals(P.find_identifiers("x,POL/71/50938217,y"), "INSURANCE_ID"), ["POL7150938217"])
        self.assertEqual(kinds(P.find_identifiers("Policy No: HX-88-1209934")), ["INSURANCE_ID"])
        self.assertEqual(kinds(P.find_identifiers("Ayushman card: 7700112233445")), ["INSURANCE_ID"])

    def test_verhoeff(self):
        good = _verhoeff_append("23456789012")
        self.assertTrue(P.verhoeff_ok(good))
        bad = good[:-1] + str((int(good[-1]) + 1) % 10)
        self.assertFalse(P.verhoeff_ok(bad))

    def test_no_identifier_in_clinical_text(self):
        for t in ("Dolo 650 BD x 5 days", "1-0-1", "Ramipril 5 mg", "BP 117/82", "range 70-140",
                  "WBC 9339 /uL", "amount 49500", "Date: 12/03/2026", "on 2026-03-12T09:30:00+05:30",
                  "Ward 8 (Medicine)", "Haemoglobin 7.6 g/dL", "4000-11000", "Temp 101.2 F",
                  "SpO2 92%", "Pulse 106/min", "LOINC 2345-7", "N39.0", "Tab Paracetamol 650mg 1-1-1 x 5 days",
                  "Platelets 1.5 lakh/cumm", "26.10.2026"):
            with self.subTest(t=t):
                self.assertEqual(P.find_identifiers(t), [])
                self.assertEqual(P.find_patient_ids(t), [])


class TestPatientIds(unittest.TestCase):
    def test_shapes(self):
        for t, v in (("UHID: KMH/26/093318", "KMH26093318"), ("UHID-020731", "UHID020731"),
                     ("Reg No: RGH2026-051177", "RGH2026051177"), ("IP/26/00917", "IP2600917"),
                     ("ADM000845", "ADM000845"), ("IPD No: XYZ-IPD-00812", "XYZIPD00812"),
                     ("ref ABC-0091234", "ABC0091234"), ("पंजीकरण सं.: KMH२०२६-०८४१२२", "KMH2026084122")):
            with self.subTest(t=t):
                self.assertEqual(vals(P.find_patient_ids(t), "MRN"), [v])

    def test_excluded(self):
        for t in ("BL/26/000731", "Bill No: XQ/26/000731", "S26004415", "sample_id: QW26004415",
                  "OPD/26/03/00412", '"visit_id": "VX/26/03/00412"', "MG019B", "Invoice INV-2026-88211",
                  "PMJAY-UP-6614290837", "Receipt: RC2026-00123"):
            with self.subTest(t=t):
                self.assertEqual(P.find_patient_ids(t), [])

    def test_bare_digits_after_label(self):
        self.assertEqual(vals(P.find_patient_ids("Hospital No: 2026045519"), "MRN"), ["2026045519"])
        self.assertEqual(P.find_patient_ids("Reg Date: 30/06/2025"), [])

    def test_after_label_only(self):
        self.assertEqual(P.find_patient_ids("seen KMH-0071234", after_label_only=True), [])
        self.assertEqual(len(P.find_patient_ids("UHID KMH-0071234", after_label_only=True)), 1)
        self.assertEqual(len(P.find_patient_ids("UHID-0071234", after_label_only=True)), 1)

    def test_core_and_norm(self):
        self.assertEqual(P.id_core("KMH/26/093318"), "093318")
        self.assertEqual(P.id_core("ADM000845"), "000845")
        self.assertEqual(P.norm_id("kmh/26/०९३३१८"), "KMH26093318")


class TestPins(unittest.TestCase):
    def test_pins(self):
        self.assertEqual(vals(P.find_pins("H.No. 12, Vill. Rampur, Distt. Unnao - 209801"), "PIN"), ["209801"])
        self.assertEqual(vals(P.find_pins("ग्राम भीमपुर, जिला हरदोई - २४१६०२"), "PIN"), ["241602"])
        self.assertEqual(vals(P.find_pins("PIN: 226010"), "PIN"), ["226010"])
        self.assertEqual(P.find_pins("WBC 150000 /uL"), [])
        self.assertEqual(P.find_pins("amount 125000 settled"), [])


class TestProtected(unittest.TestCase):
    def covered(self, text, needle, kind=None):
        i = text.index(needle)
        for s in P.protected_spans(text):
            if s.start <= i and i + len(needle) <= s.end and (kind is None or s.kind == kind):
                return True
        return False

    def test_doctor(self):
        t = "Consultant: Dr. Kiran Valecha (MD Medicine)"
        self.assertTrue(self.covered(t, "Dr. Kiran Valecha (MD Medicine)", "DOCTOR"))
        t = "डॉ. अजय सिन्हा ने देखा"
        self.assertTrue(self.covered(t, "डॉ. अजय सिन्हा", "DOCTOR"))

    def test_clinical(self):
        t = "Tab Ramipril 5 mg 0-0-1 x 15 days. BP 117/82 mmHg, Temp 101.2 F, SpO2 92%. Haemoglobin 7.6 g/dL."
        self.assertTrue(self.covered(t, "Ramipril 5 mg", "DOSE"))
        self.assertTrue(self.covered(t, "0-0-1 x 15 days", "FREQ"))
        self.assertTrue(self.covered(t, "BP 117/82", "VITAL"))
        self.assertTrue(self.covered(t, "Temp 101.2 F", "VITAL"))
        self.assertTrue(self.covered(t, "SpO2 92%", "VITAL"))
        self.assertTrue(self.covered(t, "Haemoglobin 7.6 g/dL", "LAB"))
        self.assertTrue(self.covered("Dolo 650 BD x 5 days", "BD x 5 days", "FREQ"))
        self.assertTrue(self.covered("Dolo 650 BD x 5 days", "Dolo 650"))
        self.assertTrue(self.covered('"range": "70-140"', "70-140", "LAB"))
        self.assertFalse(self.covered("ph 68412-55307", "68412-55307"))

    def test_ward(self):
        self.assertTrue(self.covered("Ward/Bed: Ward 8 (Medicine) / Bed 23", "Ward 8 (Medicine) / Bed 23", "WARD"))
        self.assertTrue(self.covered("Ward: 4 (Medicine)", "Ward: 4 (Medicine)", "WARD"))
        self.assertFalse(self.covered("H.No. 22, Ward 20, Mohalla Purana", "Ward 20"))
        self.assertFalse(self.covered("Address: C/O Mohan Lal, Ward 3", "Ward 3"))

    def test_eponym_asha(self):
        self.assertTrue(self.covered("K/C/O Parkinson's disease", "Parkinson's disease"))
        self.assertTrue(self.covered("had bell's palsy last year", "bell's palsy", "EPONYM"))
        self.assertTrue(self.covered("Referred by ASHA worker", "ASHA worker", "ASHA"))
        self.assertFalse(self.covered("Asha Kumari aayi", "Asha"))

    def test_history(self):
        self.assertTrue(self.covered("History: K/C/O DM2 x 6 yrs. Stable", "K/C/O DM2 x 6 yrs", "HISTORY"))
        self.assertTrue(self.covered("H/O TB in 2019", "H/O TB", "HISTORY"))
        self.assertTrue(self.covered("C/O fever for 3 days, weakness", "C/O fever for 3 days", "HISTORY"))
        self.assertTrue(self.covered("C/O pet mein dard", "C/O pet mein dard", "HISTORY"))
        self.assertFalse(self.covered("C/O Ramesh Patel, Ward 1", "Ramesh"))
        self.assertFalse(self.covered("H/o Suresh Yadav", "Suresh"))

    def test_is_complaint_of(self):
        self.assertTrue(P.is_complaint_of("C/O fever", 0))
        self.assertTrue(P.is_complaint_of("pt c/o bukhar", 3))
        self.assertTrue(P.is_complaint_of("C/O बुखार", 0))
        self.assertFalse(P.is_complaint_of("C/O Ramesh Patel", 0))
        self.assertFalse(P.is_complaint_of("C/O RAMESH PATEL", 0))
        self.assertFalse(P.is_complaint_of("C/O रमेश पटेल", 0))


class TestLexicon(unittest.TestCase):
    def test_sets(self):
        self.assertGreater(len(lexicon.CLINICAL_WORDS), 300)
        for w in ("paracetamol", "tab", "bukhar", "बुखार", "haemoglobin", "dengue"):
            self.assertIn(w, lexicon.CLINICAL_WORDS)
        for w in ("ka", "ki", "mein", "theek", "को", "में", "दिन"):
            self.assertIn(w, lexicon.HINDI_COMMON_WORDS)
        for w in ("s/o", "w/o", "पिता"):
            self.assertIn(w, lexicon.KINSHIP_MARKERS)
        self.assertIn("called by", lexicon.PERSON_VERBS)
        for w in ("h.no", "mohalla", "मोहल्ला", "tehsil", "जिला", "ward"):
            self.assertIn(w, lexicon.ADDRESS_CUES)
        for s in (lexicon.CLINICAL_WORDS, lexicon.COMPLAINT_WORDS, lexicon.HINDI_COMMON_WORDS):
            self.assertTrue(all(w == w.lower() for w in s))


if __name__ == "__main__":
    unittest.main()


class TestUnderscoreIds(unittest.TestCase):
    def test_file_names_not_mrn(self):
        for t in ("report_00005", "arogya_opd_2026_05", "visits_2026_02.json", "export_123456",
                  "summary_page_00012", "claims_forward_2026_03"):
            self.assertEqual(P.find_patient_ids(t), [], t)

    def test_underscore_id_kept(self):
        sp = P.find_patient_ids("UHID_010610")
        self.assertEqual([(s.start, s.end) for s in sp], [(0, 11)])

    def test_id_inside_file_name(self):
        t = "report_QRH2077123_final"
        self.assertEqual([t[s.start:s.end] for s in P.find_patient_ids(t)], ["QRH2077123"])
