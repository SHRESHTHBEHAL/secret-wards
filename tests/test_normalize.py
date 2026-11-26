from __future__ import annotations

import base64
import unittest

from raksha.normalize import (decode_layers, digits_only, norm_text, to_ascii_digits,
                              try_b64_text)


class TestDigits(unittest.TestCase):
    def test_devanagari_digits(self):
        self.assertEqual(to_ascii_digits("९८७६५४३२१०"), "9876543210")
        self.assertEqual(to_ascii_digits("मो. ९४१५०१२३४५"), "मो. 9415012345")

    def test_other_indic_digits(self):
        self.assertEqual(to_ascii_digits("১২৩"), "123")   # Bengali
        self.assertEqual(to_ascii_digits("૪૫૬"), "456")   # Gujarati

    def test_digits_only(self):
        self.assertEqual(digits_only("+91 ९४१५-०१२ 345"), "919415012345")
        self.assertEqual(digits_only("abc"), "")


class TestNormText(unittest.TestCase):
    def test_casefold_and_diacritics(self):
        self.assertEqual(norm_text("JOSÉ Ñandú"), "jose nandu")

    def test_zero_width_and_bom(self):
        self.assertEqual(norm_text("﻿Ra​vi‍"), "ravi")

    def test_keeps_devanagari_marks(self):
        self.assertEqual(norm_text("सुनीता"), "सुनीता")

    def test_fullwidth_and_digits(self):
        self.assertEqual(norm_text("ＡＢ१२"), "ab12")


class TestDecoding(unittest.TestCase):
    SENT = "Patient Vikram Chaturvedi phone 9876501234"

    def test_b64_sentence(self):
        enc = base64.b64encode(self.SENT.encode()).decode()
        self.assertEqual(try_b64_text(enc), self.SENT)
        self.assertIn(self.SENT, decode_layers("note: " + enc + " end"))

    def test_b64_rejects(self):
        self.assertIsNone(try_b64_text("short"))
        self.assertIsNone(try_b64_text("HospitalRegistrationNumber"))
        self.assertIsNone(try_b64_text("1234567890123456"))

    def test_b64_unicode(self):
        enc = base64.b64encode("नाम सुनीता वर्मा".encode()).decode()
        self.assertEqual(try_b64_text(enc), "नाम सुनीता वर्मा")

    def test_unicode_escape(self):
        out = decode_layers("name=\\u0938\\u0941\\u0928\\u0940\\u0924\\u093e")
        self.assertIn("name=सुनीता", out)

    def test_percent(self):
        out = decode_layers("q=Ravi%20Kumar%40mail.test")
        self.assertIn("q=Ravi Kumar@mail.test", out)

    def test_hex(self):
        h = self.SENT.encode().hex()
        self.assertIn(self.SENT, decode_layers("blob " + h))

    def test_html_entities(self):
        self.assertIn("Anil & Sons <b>", decode_layers("Anil &amp; Sons &lt;b&gt;"))
        self.assertIn("राम", decode_layers("&#2352;&#2366;&#2350;"))

    def test_nested(self):
        inner = base64.b64encode(self.SENT.encode()).decode()
        outer = base64.b64encode(inner.encode()).decode()
        self.assertIn(self.SENT, decode_layers(outer))

    def test_plain_text_nothing(self):
        self.assertEqual(decode_layers("BP 120/80 pulse 72"), [])
        self.assertEqual(decode_layers(""), [])


if __name__ == "__main__":
    unittest.main()
