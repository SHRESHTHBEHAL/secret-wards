from __future__ import annotations

import unittest

from raksha import fields as F


class LabelTests(unittest.TestCase):
    CASES = [
        # names
        ("Patient Name", F.NAME), ("Patient's Name", F.NAME), ("Rogi Naam", F.NAME), ("Naam", F.NAME),
        ("patinet_name", F.NAME), ("PATIENT NAME", F.NAME), ("Pt. Name", F.NAME), ("Mareez ka Naam", F.NAME),
        ("मरीज़ का नाम", F.NAME), ("रोगी का नाम", F.NAME), ("patientname", F.NAME), ("Name", F.NAME),
        ("First Name", F.FIRST_NAME), ("FirstName", F.FIRST_NAME), ("Surname", F.LAST_NAME),
        ("LastName", F.LAST_NAME), ("Name (Hindi)", F.LOCAL_NAME),
        # relatives
        ("Pita/Pati ka Naam", F.RELATIVE), ("Father's Name", F.RELATIVE), ("Husband Name", F.RELATIVE),
        ("Guardian", F.RELATIVE), ("Gaurdian Name", F.RELATIVE), ("Relative Name", F.RELATIVE),
        ("पिता का नाम", F.RELATIVE), ("S/O", F.RELATIVE), ("Attendant", F.RELATIVE),
        ("Emergency Contact Name", F.RELATIVE), ("Relation", F.RELATION), ("Rishta", F.RELATION),
        # ids
        ("UHID", F.PATIENT_ID), ("PatientID", F.PATIENT_ID), ("Reg No", F.PATIENT_ID),
        ("Regn. #", F.PATIENT_ID), ("MRN", F.PATIENT_ID), ("patient_ref", F.PATIENT_ID),
        ("पंजीकरण सं.", F.PATIENT_ID), ("Hospital UHID", F.PATIENT_ID), ("CR No.", F.PATIENT_ID),
        ("IPD No", F.ENC_ID), ("Admission No", F.ENC_ID), ("ADM", F.ENC_ID),
        ("bill_no", F.OTHER_ID), ("sample_id", F.OTHER_ID), ("visit_id", F.OTHER_ID),
        ("package_code", F.OTHER_ID), ("trip", F.OTHER_ID), ("Invoice #", F.OTHER_ID),
        ("pmjay_id", F.INSURANCE), ("policy_no", F.INSURANCE), ("Ayushman Card", F.INSURANCE),
        ("payer_pan", F.PAN), ("PAN No", F.PAN),
        ("Aadhaar No", F.AADHAAR), ("aadhar_no", F.AADHAAR), ("Adhaar", F.AADHAAR), ("आधार", F.AADHAAR),
        ("UID", F.AADHAAR), ("ABHA No", F.ABHA), ("Health ID", F.ABHA), ("ABHA Address", F.ABHA_ADDR),
        ("E-mail", F.EMAIL), ("Email ID", F.EMAIL),
        # phones
        ("Mobile", F.PHONE), ("Mobile No", F.PHONE), ("Contact No.", F.PHONE), ("mobil", F.PHONE),
        ("Phone", F.PHONE), ("WhatsApp", F.PHONE), ("मोबाइल नंबर", F.PHONE), ("Callback", F.PHONE),
        ("Tel.", F.PHONE),
        # address
        ("Address", F.ADDRESS), ("Pata", F.ADDRESS), ("पता", F.ADDRESS), ("Street", F.ADDRESS),
        ("Addr Line 1", F.ADDRESS), ("Residential Adress", F.ADDRESS), ("House No", F.HOUSE),
        ("Makan No.", F.HOUSE), ("Village/Mohalla", F.VILLAGE), ("Gram/Mohalla", F.VILLAGE),
        ("Gaon", F.VILLAGE), ("गाँव", F.VILLAGE), ("City", F.VILLAGE), ("Mohalla", F.LOCALITY),
        ("Locality", F.LOCALITY), ("Tehsil", F.TEHSIL), ("तहसील", F.TEHSIL), ("Taluka", F.TEHSIL),
        ("District", F.DISTRICT), ("Jila", F.DISTRICT), ("Zila", F.DISTRICT), ("जिला", F.DISTRICT),
        ("Distt.", F.DISTRICT), ("State", F.STATE), ("PIN", F.PIN), ("Pin Code", F.PIN),
        ("Zip", F.PIN), ("Postal Code", F.PIN), ("पिन कोड", F.PIN),
        # demographics and dates
        ("Age", F.AGE), ("Umar", F.AGE), ("उम्र", F.AGE), ("आयु", F.AGE), ("Age (Yrs)", F.AGE),
        ("age_sex", F.AGE_SEX), ("Age/Sex", F.AGE_SEX), ("Sex", F.GENDER), ("Gender", F.GENDER),
        ("Ling", F.GENDER), ("लिंग", F.GENDER),
        ("DOB", F.DOB), ("DOB (MM/DD/YYYY)", F.DOB), ("Janm Tithi", F.DOB), ("Date of Birth", F.DOB),
        ("D.O.B.", F.DOB), ("जन्म तिथि", F.DOB), ("dateofbirth", F.DOB),
        ("Reg Date", F.DATE), ("Registration Date", F.DATE), ("collected_on", F.DATE),
        ("visit_date", F.DATE), ("admission_date", F.DATE), ("Registered (MM/DD/YYYY)", F.DATE),
        ("तारीख", F.DATE), ("Dinank", F.DATE), ("generated_at", F.DATE),
        # doctors, hospitals
        ("ref_doctor", F.DOCTOR), ("Doctor", F.DOCTOR), ("Consultant", F.DOCTOR), ("Ref. Dr.", F.DOCTOR),
        ("referred_by", F.DOCTOR), ("reviewed_by", F.DOCTOR), ("डॉक्टर", F.DOCTOR), ("Chikitsak", F.DOCTOR),
        ("Hospital", F.HOSPITAL), ("Facility Name", F.HOSPITAL), ("lab", F.HOSPITAL),
        # clinical
        ("test", F.CLINICAL), ("result", F.CLINICAL), ("unit", F.CLINICAL), ("ref_range", F.CLINICAL),
        ("procedure", F.CLINICAL), ("diagnosis", F.CLINICAL), ("complaints", F.CLINICAL),
        ("history", F.CLINICAL), ("drug", F.CLINICAL), ("strength", F.CLINICAL), ("frequency", F.CLINICAL),
        ("duration", F.CLINICAL), ("department", F.CLINICAL), ("status", F.CLINICAL),
        ("amount_inr", F.CLINICAL), ("Diagnosis Code", F.CLINICAL), ("निदान", F.CLINICAL),
        ("Daignosis", F.CLINICAL), ("reference_range", F.CLINICAL), ("Ward", F.CLINICAL),
        # free text
        ("Notes", F.FREE_TEXT), ("remarks", F.FREE_TEXT), ("Comments", F.FREE_TEXT),
        ("टिप्पणी", F.FREE_TEXT), ("exported_by", F.FREE_TEXT),
        # unsure
        ("", F.OTHER), ("time", F.OTHER), ("schema", F.OTHER), ("AB-1234 Kiran", F.OTHER),
    ]

    def test_labels(self):
        bad = [(l, F.classify_label(l), want) for l, want in self.CASES if F.classify_label(l) != want]
        self.assertEqual(bad, [])


class ValueTests(unittest.TestCase):
    def test_shapes(self):
        self.assertEqual(F.classify_values(["9876543210", "+91 91234 56789", "07890123456"]), F.PHONE)
        self.assertEqual(F.classify_values(["2345 6789 0123", "345678901234", "XXXX XXXX 4321"]), F.AADHAAR)
        self.assertEqual(F.classify_values(["12-3456-7890-1234", "98-7654-3210-9876"]), F.ABHA)
        self.assertEqual(F.classify_values(["ABCDE1234F", "PQRSX9876Z"]), F.PAN)
        self.assertEqual(F.classify_values(["a.b@example.com", "x_y@mail.in"]), F.EMAIL)
        self.assertEqual(F.classify_values(["kiran.r@abdm", "dev12@sbx"]), F.ABHA_ADDR)
        self.assertEqual(F.classify_values(["226010", "110001", "560034"]), F.PIN)
        self.assertEqual(F.classify_values(["12/03/1980", "2001-07-15", "5 Jan 1999"]), F.DATE)
        self.assertEqual(F.classify_values(["Dr. Anil Verma", "Dr Kavya Rao"]), F.DOCTOR)
        self.assertEqual(F.classify_values(["M", "F", "Female", "महिला"]), F.GENDER)
        self.assertEqual(F.classify_values(["47 वर्ष", "65 Yrs", "3 yrs"]), F.AGE)
        self.assertEqual(F.classify_values(["65/F", "32/M", "8 Y/F"]), F.AGE_SEX)
        self.assertEqual(F.classify_values(["S/o", "W/o", "D/o"]), F.RELATION)
        self.assertEqual(F.classify_values(["Kiran Devi", "RAMU PRASAD", "सुमन लता", "Om P. Gupta"]), F.NAME)
        self.assertEqual(F.classify_values(["Paracetamol 500", "Dengue fever", "120/80"]), F.OTHER)
        self.assertEqual(F.classify_values([]), F.OTHER)
        self.assertEqual(F.classify_values([None, "", "  "]), F.OTHER)

    def test_threshold(self):
        self.assertEqual(F.classify_values(["9876543210", "abc", "def"]), F.OTHER)


class ColumnTests(unittest.TestCase):
    def test_combine(self):
        names = ["Kiran Devi", "Ramu Prasad", "Asha Kumari"]
        self.assertEqual(F.classify_column("Col 7", names), F.NAME)
        self.assertEqual(F.classify_column("Ref Doctor", ["Ravi Shankar", "Mina Joshi"]), F.DOCTOR)
        self.assertEqual(F.classify_column("Name", ["Dr. Ravi Shankar", "Dr Mina Joshi"]), F.DOCTOR)
        self.assertEqual(F.classify_column("Phone", ["2345 6789 0123", "3456 7890 1234"]), F.AADHAAR)
        self.assertEqual(F.classify_column("Field X", ["9876543210", "8765432109"]), F.PHONE)
        self.assertEqual(F.classify_column("Janm Tithi", ["01-02-1970", "15-08-1985"]), F.DOB)
        self.assertEqual(F.classify_column("Misc", ["01-02-2026", "15-08-2026"]), F.DATE)
        self.assertEqual(F.classify_column("Test", ["Blood Sugar Fasting", "Serum Uric Acid"]), F.CLINICAL)
        self.assertEqual(F.classify_column("amount_inr", ["250000", "120000"]), F.CLINICAL)
        self.assertEqual(F.classify_column("sample_id", ["123456", "234567"]), F.OTHER_ID)
        self.assertEqual(F.classify_column("Umar", ["47 वर्ष", "65"]), F.AGE)
        self.assertEqual(F.classify_column("Age", ["65/F", "40/M"]), F.AGE_SEX)
        self.assertEqual(F.classify_column("Notes", ["Ramu Prasad", "Kiran Devi"]), F.FREE_TEXT)
        self.assertEqual(F.classify_column("Guardian", ["S/O Ramu Prasad", "W/O Mohan Lal"]), F.RELATIVE)

    def test_clean_columns_not_pii(self):
        for label, vals in [("drug", ["Paracetamol", "Amoxicillin"]), ("strength", ["500 mg", "250 mg"]),
                            ("form", ["Tab", "Cap"]), ("category", ["Analgesic", "Antibiotic"]),
                            ("schedule", ["H", "G"]), ("test", ["Haemoglobin", "Platelet Count"]),
                            ("loinc", ["718-7", "777-3"]), ("unit", ["g/dL", "%"]),
                            ("reference_range", ["13.0-17.0", "150-450"])]:
            self.assertFalse(F.is_pii_type(F.classify_column(label, vals)), label)

    def test_is_pii(self):
        for t in (F.NAME, F.RELATIVE, F.PHONE, F.AADHAAR, F.ADDRESS, F.VILLAGE, F.PIN, F.DOB, F.AGE,
                  F.PATIENT_ID, F.EMAIL):
            self.assertTrue(F.is_pii_type(t))
        for t in (F.CLINICAL, F.DOCTOR, F.HOSPITAL, F.DISTRICT, F.GENDER, F.OTHER, F.OTHER_ID):
            self.assertFalse(F.is_pii_type(t))


class JsonTests(unittest.TestCase):
    CASES = [
        (["patients", "guardian", "name"], "Mohan Lal", F.RELATIVE),
        (["patients", "guardian", "relation"], "S/o", F.RELATION),
        (["patients", "name", "first"], "Kiran", F.FIRST_NAME),
        (["patients", "name", "last"], "Devi", F.LAST_NAME),
        (["patients", "name", "local"], "किरण देवी", F.LOCAL_NAME),
        (["patients", "ids", "aadhar_no"], 234567890123, F.AADHAAR),
        (["patients", "ids", "adhaar"], "2345 6789 0123", F.AADHAAR),
        (["patients", "ids", "abha"], None, F.ABHA),
        (["patients", "ids", "abha_address"], None, F.ABHA_ADDR),
        (["patients", "contact", "mobil"], "9876543210", F.PHONE),
        (["patients", "contact", "email"], None, F.EMAIL),
        (["patients", "address", "line"], "H.No. 12, Ward 3", F.ADDRESS),
        (["patients", "address", "pin"], "226010", F.PIN),
        (["patients", "address", "gaon"], "Rampur", F.VILLAGE),
        (["patients", "uhid"], "ABC-1234567", F.PATIENT_ID),
        (["patients", "dob"], "1970-01-02", F.DOB),
        (["patients", "age"], 47, F.AGE),
        (["patients", "gender"], "female", F.GENDER),
        (["visits", "patient_ref"], "ABCD-123456", F.PATIENT_ID),
        (["visits", "doctor"], "Dr. Anil Verma", F.DOCTOR),
        (["visits", "reviewed_by"], "Dr. Anil Verma", F.DOCTOR),
        (["visits", "patient", "name"], "Kiran Devi", F.NAME),
        (["visits", "patient", "age_sex"], "65/F", F.AGE_SEX),
        (["visits", "rx", "drug"], "Paracetamol", F.CLINICAL),
        (["visits", "rx", "name"], "Paracetamol", F.CLINICAL),
        (["visits", "diagnosis", "code"], "A90", F.CLINICAL),
        (["visits", "diagnosis", "display"], "Dengue fever", F.CLINICAL),
        (["visits", "vitals", "pulse"], 88, F.CLINICAL),
        (["visits", "visit_id"], "XY/26/05/00012", F.OTHER_ID),
        (["visits", "notes"], "Seen with wife", F.FREE_TEXT),
        (["_export_meta", "exported_by"], "user.one.admin", F.FREE_TEXT),
        (["_export_meta", "hospital"], "Some General Hospital", F.HOSPITAL),
        (["tickets", "meta", "raised_by", "name"], "Asha Kumari", F.NAME),
        (["tickets", "meta", "raised_by", "callback"], "9876543210", F.PHONE),
        (["tickets", "id"], "HD-0012", F.OTHER_ID),
        (["facility", "name"], "District Hospital", F.HOSPITAL),
        (["doctor", "name"], "Anil Verma", F.DOCTOR),
        (["practitioner", "name", "given"], "Anil", F.DOCTOR),
        (["hospital", "name"], "City Care", F.HOSPITAL),
        (["panels", "name"], "Haemogram", F.CLINICAL),
        (["panels", "results", "value"], 13.2, F.CLINICAL),
        (["results", "patient_name"], "Kiran Devi", F.NAME),
        (["test", "name"], "Haemoglobin", F.CLINICAL),
        (["package", "name"], "Knee replacement", F.CLINICAL),
        (["name"], "Kiran Devi", F.NAME),
        (["patient"], "Kiran Devi", F.NAME),
        (["patinet_name"], "Kiran Devi", F.NAME),
        (["attendant", "naam"], "Mohan Lal", F.RELATIVE),
        (["records", "ids", "misc"], 234567890123, F.AADHAAR),
        (["records", "id"], 9876543210, F.PHONE),
        (["records", "id"], 42, F.OTHER_ID),
        (["records", "extra"], "9876543210", F.PHONE),
        (["admission", "no"], "IP-26-00001", F.ENC_ID),
        (["wards", "beds"], 20, F.CLINICAL),
        ([], "x", F.OTHER),
    ]

    def test_paths(self):
        bad = [(p, F.json_key_type(p, v), want) for p, v, want in self.CASES if F.json_key_type(p, v) != want]
        self.assertEqual(bad, [])

    def test_deterministic(self):
        a = [F.json_key_type(p, v) for p, v, _ in self.CASES]
        b = [F.json_key_type(p, v) for p, v, _ in self.CASES]
        self.assertEqual(a, b)


if __name__ == "__main__":
    unittest.main()


class GenericKeyTests(unittest.TestCase):
    def test_generic_keys_not_clinical_at_top(self):
        for k, v in (("category", "billing query"), ("status", "closed"), ("form", "surgical consent"),
                     ("type", "complaint")):
            self.assertEqual(F.json_key_type([k], v), F.OTHER, k)
        self.assertEqual(F.json_key_type(["ticket", "status"], "closed"), F.OTHER)

    def test_generic_keys_clinical_under_clinical_ancestor(self):
        for p in (["visits", 0, "form"], ["rx", 0, "form"], ["diagnosis", "status"], ["tests", "category"],
                  ["results", 0, "status"], ["vitals", "status"], ["panels", 0, "category"]):
            self.assertEqual(F.json_key_type(p, "x"), F.CLINICAL, p)
