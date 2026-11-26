from __future__ import annotations

import unittest

from raksha.translit import (GENERIC_NAME_PARTS, HONORIFICS, TITLES, deva_to_latin,
                             full_name_key, is_deva, name_key, name_tokens, same_name,
                             same_token)

MATCH = [
    ("Sunita Verma", "सुनीता वर्मा"),
    ("Rajesh Kumar Yadav", "राजेश कुमार यादव"),
    ("Kamla Devi", "कमला देवी"),
    ("Mohan Lal Gupta", "मोहन लाल गुप्ता"),
    ("Narendra Pal", "नरेन्द्र पाल"),
    ("Krishna Mishra", "कृष्ण मिश्रा"),
    ("Lakshmi Shukla", "लक्ष्मी शुक्ला"),
    ("Pankaj Chauhan", "पंकज चौहान"),
    ("Zakir Hussain", "ज़ाकिर हुसैन"),
    ("Pooja Chaurasia", "पूजा चौरसिया"),
    ("Shambhu Nath Tiwari", "शंभु नाथ तिवारी"),
    ("Geeta Rani Saxena", "गीता रानी सक्सेना"),
    ("Farhan Qureshi", "फ़रहान कुरैशी"),
    ("Kishan Singh", "किशन सिंह"),
    ("Anil Kushwaha", "अनिल कुशवाहा"),
]
NO_MATCH = [
    ("Ramesh Yadav", "Rakesh Yadav"),
    ("Sunita Verma", "Sunil Verma"),
    ("Anita Gupta", "Amita Gupta"),
    ("Kumar Singh", "Kumar Singh Devi Lal"),   # only generic parts
    ("Sunita Verma", "सरिता वर्मा"),
    ("Mohan Lal", "सोहन लाल"),
    ("Pooja Mishra", "Puja Shukla"),
]


class TestScript(unittest.TestCase):
    def test_is_deva(self):
        self.assertTrue(is_deva("राम"))
        self.assertTrue(is_deva("Mr राम"))
        self.assertFalse(is_deva("Ram ९"))   # digits only, not letters

    def test_schwa(self):
        self.assertEqual(deva_to_latin("कमल"), "kamal")
        self.assertEqual(deva_to_latin("कमला"), "kamlaa")
        self.assertEqual(deva_to_latin("राजेश"), "raajesh")
        self.assertEqual(deva_to_latin("ज़ाकिर"), "zaakir")
        self.assertEqual(deva_to_latin("पेड़"), "per")
        self.assertEqual(deva_to_latin("सिंह"), "singh")
        self.assertEqual(deva_to_latin("Ward 3 राम"), "Ward 3 raam")

    def test_sets(self):
        self.assertIn("smt", HONORIFICS)
        self.assertIn("श्रीमती", HONORIFICS)
        self.assertIn("dr", TITLES)
        self.assertIn("devi", GENERIC_NAME_PARTS)


class TestTokens(unittest.TestCase):
    def test_strip_titles(self):
        self.assertEqual(name_tokens("Smt. Kamla Devi"), ["kamla", "devi"])
        self.assertEqual(name_tokens("Dr. Arvind Saxena"), ["arvind", "saxena"])
        self.assertEqual(name_tokens("श्रीमती कमला देवी"), ["kamlaa", "devee"])
        self.assertEqual(name_tokens("S/o Ravi Pal"), ["ravi", "pal"])

    def test_mohammad_family(self):
        for v in ("Md. Arif", "MD Arif", "Mohd Arif", "Mohd. Arif", "Mohammed Arif",
                  "Muhammad Arif", "मोहम्मद आरिफ़", "मो. आरिफ़"):
            self.assertEqual(name_tokens(v)[0], "mohammad", v)
        self.assertTrue(same_name("Md. Arif Ansari", "मोहम्मद आरिफ़ अंसारी"))
        self.assertTrue(same_name("Mohd Arif", "Muhammad Arif"))
        self.assertFalse(same_name("Mohd Arif", "Mohd Salim"))

    def test_keys(self):
        self.assertEqual(name_key("Shyam"), name_key("श्याम"))
        self.assertEqual(name_key("Laxmi"), name_key("Lakshmi"))
        self.assertEqual(name_key("Pooja"), name_key("Puja"))
        self.assertEqual(name_key("Chhaya"), name_key("छाया"))
        self.assertEqual(name_key(""), "")

    def test_full_name_key_order(self):
        self.assertEqual(full_name_key("Verma Sunita"), full_name_key("Sunita Verma"))
        self.assertEqual(full_name_key("SUNITA VERMA"), full_name_key("Sunita Verma"))
        self.assertEqual(full_name_key("Smt. Geeta Rani"), "git rani")


class TestSame(unittest.TestCase):
    def test_pairs_match(self):
        for a, b in MATCH:
            self.assertTrue(same_name(a, b), (a, b))

    def test_pairs_differ(self):
        for a, b in NO_MATCH:
            self.assertFalse(same_name(a, b), (a, b))

    def test_short_tokens_strict(self):
        self.assertFalse(same_token("ramesh", "rakesh"))
        self.assertFalse(same_token("sunita", "sunil"))
        self.assertFalse(same_token("anita", "amita"))
        self.assertFalse(same_token("rani", "renu"))
        self.assertTrue(same_token("kamla", "kamala"))
        self.assertTrue(same_token("Raju", "राजू"))

    def test_long_tokens_fuzzy(self):
        self.assertTrue(same_token("Chaturvedi", "Chaturvedee"))
        self.assertTrue(same_token("Vishwakarma", "Vishvakarma"))

    def test_surname_first_and_caps(self):
        self.assertTrue(same_name("YADAV RAJESH", "Rajesh Kumar Yadav"))
        self.assertTrue(same_name("Verma, Sunita", "सुनीता वर्मा"))
        self.assertTrue(same_name("SUNITA", "Sunita Verma"))

    def test_generic_only_fails(self):
        self.assertFalse(same_name("Devi", "Kamla Devi"))
        self.assertFalse(same_name("", "Kamla"))


if __name__ == "__main__":
    unittest.main()
