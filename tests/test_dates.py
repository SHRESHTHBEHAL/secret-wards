from __future__ import annotations

import datetime as dt
import unittest

from raksha.dates import (
    age_band, band_age_text, find_ages, find_dates, format_like, infer_order,
    parse_one, shift_date, shift_text,
)


class FindDatesTest(unittest.TestCase):
    def test_formats_recognised(self):
        cases = [
            ("on 24/01/2026 ok", dt.date(2026, 1, 24)),
            ("on 24-01-2026 ok", dt.date(2026, 1, 24)),
            ("on 26.10.2026 ok", dt.date(2026, 10, 26)),
            ("on 2026-05-20 ok", dt.date(2026, 5, 20)),
            ("[30/05/26, 9:32 pm] Ravi:", dt.date(2026, 5, 30)),
            ("seen 24 Jan 2026.", dt.date(2026, 1, 24)),
            ("seen Sep 5, 2026.", dt.date(2026, 9, 5)),
            ("तारीख: २६.१०.२०२६", dt.date(2026, 10, 26)),
            ("5 सितम्बर 2026 को", dt.date(2026, 9, 5)),
            ("Date:3/7/2026", dt.date(2026, 7, 3)),
        ]
        for text, want in cases:
            hits = find_dates(text)
            self.assertEqual([h.date for h in hits], [want], text)

    def test_month_first(self):
        self.assertEqual(find_dates("01/13/2026", order="mdy")[0].date, dt.date(2026, 1, 13))
        self.assertEqual(find_dates("01/13/2026"), [])

    def test_iso_datetime(self):
        h = find_dates("x 2026-02-04T18:15:00+05:30 y")
        self.assertEqual(len(h), 1)
        self.assertTrue(h[0].has_time)
        self.assertEqual(shift_text("2026-02-04T18:15:00+05:30", 3), "2026-02-07T18:15:00+05:30")

    def test_non_dates(self):
        for text in ["BP 117/82", "1-0-1", "70-140", "12.0-16.0", "x 5 days",
                     "SNJ/26/064371", "IPD-2026-00450", "OPD/26/01/00099",
                     "+91 98765 43210", "98-765-43210", "31/02/2026", "13/13/2026",
                     "12/05/1850", "3.14.15", "1234/12/12345"]:
            self.assertEqual(find_dates(text), [], text)

    def test_partial(self):
        self.assertEqual(find_dates("Visit: 5 September"), [])
        h = find_dates("Visit: 5 September", default_year=2026)
        self.assertEqual(h[0].date, dt.date(2026, 9, 5))
        self.assertFalse(h[0].has_year)
        self.assertEqual(shift_text("Visit: 5 September", 3), "Visit: 5 September")


class ShiftTest(unittest.TestCase):
    def test_round_trip_formats(self):
        samples = [
            "24/01/2026", "24-01-2026", "26.10.2026", "2026-05-20",
            "[30/05/26, 9:32 pm]", "24 Jan 2026", "24-JAN-2026", "1st March 2026",
            "Sep 5, 2026", "२६.१०.२०२६", "5 दिसंबर 2026", "2026-02-04T18:15:00+05:30",
            "a 01/02/2026 b 3.4.2026 c",
        ]
        for s in samples:
            for days in (37, -37, 400, 1):
                self.assertEqual(shift_text(shift_text(s, days), -days), s, (s, days))

    def test_exact_format(self):
        self.assertEqual(shift_text("24/01/2026", 10), "03/02/2026")
        self.assertEqual(shift_text("4/1/2026", 1), "5/1/2026")
        self.assertEqual(shift_text(shift_text("4/1/2026", 3), -3), "4/1/2026")
        self.assertEqual(shift_text("30/05/26", 3), "02/06/26")
        self.assertEqual(shift_text("24 Jan 2026", 10), "3 Feb 2026")
        self.assertEqual(shift_text("24-JAN-2026", 10), "3-FEB-2026")
        self.assertEqual(shift_text("28 february 2026", 2), "2 march 2026")
        self.assertEqual(shift_text("२६.१०.२०२६", 7), "०२.११.२०२६")
        self.assertEqual(shift_text("30 अक्टूबर 2026", 2), "1 नवंबर 2026")
        self.assertEqual(shift_text("1st March 2026", 1), "2nd March 2026")
        self.assertEqual(shift_text("01/13/2026", 1, order="mdy"), "01/14/2026")

    def test_stay_length_kept(self):
        text = "Admitted: 25/12/2025\nDischarged: 03/01/2026"
        out = shift_text(text, 45)
        a, b = [h.date for h in find_dates(out)]
        self.assertEqual((b - a).days, 9)

    def test_partial_crosses_year(self):
        out = shift_text("seen on 28 December", 10, default_year=2026)
        self.assertEqual(out, "seen on 7 January")
        self.assertEqual(shift_text(out, -10, default_year=2026), "seen on 28 December")

    def test_helpers(self):
        self.assertEqual(shift_date(dt.date(2026, 2, 27), 2), dt.date(2026, 3, 1))
        self.assertEqual(format_like("4/1/2026", dt.date(2026, 12, 25)), "25/12/2026")
        self.assertEqual(format_like("Jan 3, 2026", dt.date(2026, 2, 9)), "Feb 9, 2026")
        self.assertEqual(format_like("01/13/2026", dt.date(2026, 2, 5), "mdy"), "02/05/2026")
        self.assertEqual(parse_one(" 24/01/2026 "), dt.date(2026, 1, 24))
        self.assertIsNone(parse_one("24/01/2026 and more"))
        self.assertIsNone(parse_one("hello"))


class InferOrderTest(unittest.TestCase):
    def test_rules(self):
        self.assertEqual(infer_order(["01/02/2026"], "Visit (MM/DD/YYYY)"), "mdy")
        self.assertEqual(infer_order(["01/13/2026"], "date DD/MM"), "dmy")
        self.assertEqual(infer_order(["01/02/2026", "13/02/2026"]), "dmy")
        self.assertEqual(infer_order(["01/02/2026", "02/13/2026"]), "mdy")
        self.assertEqual(infer_order(["01/02/2026", "2026-12-31"]), "dmy")
        self.assertEqual(infer_order([]), "dmy")


class AgeTest(unittest.TestCase):
    def test_age_band(self):
        self.assertEqual(age_band(48), "45-49")
        self.assertEqual(age_band(0), "0-4")
        self.assertEqual(age_band(85), "85+")
        self.assertEqual(age_band(97), "85+")

    def test_age_forms(self):
        cases = {
            "48 Yrs/F": "45-49 Yrs/F",
            "65/F": "65-69/F",
            "47 वर्ष": "45-49 वर्ष",
            "Age: 52": "Age: 50-54",
            "48 Y / F": "45-49 Y / F",
            "आयु: 53 वर्ष": "आयु: 50-54 वर्ष",
            "Age/Sex: 39 Yrs/M": "Age/Sex: 35-39 Yrs/M",
            "Age: 48/F": "Age: 45-49/F",
            "Age: 91/M": "Age: 85+/M",
            "52 Yrs": "50-54 Yrs",
            "४७ वर्ष": "४५-४९ वर्ष",
            "a 62 year old man": "a 60-64 year old man",
        }
        for src, want in cases.items():
            out = band_age_text(src)
            self.assertEqual(out, want, src)
            self.assertEqual(band_age_text(out), out, src)

    def test_non_ages(self):
        for text in ["DM2 x 12 yrs", "6 yrs", "since 7 yrs", "7 yrs back", "8 दिन से",
                     "3 days", "Hb 12.0-16.0", "range 70-140", "BP 117/82", "x 9 Yrs",
                     "5 वर्ष से", "Age: 6 months"]:
            self.assertEqual(band_age_text(text), text, text)

    def test_find_ages(self):
        self.assertEqual(find_ages("Name X  Age: 48/F"), [(13, 15, 48)])


if __name__ == "__main__":
    unittest.main()


class LowerAgeSexTest(unittest.TestCase):
    def test_lower_case_age_gender(self):
        from raksha.dates import band_age_text, find_ages
        self.assertEqual([a for _, _, a in find_ages("Tarla Mhatre, 27 yrs, female, QRH1")], [27])
        self.assertEqual(band_age_text("97 yrs, male", 5, 85), "85+ yrs, male")
        self.assertEqual(band_age_text("45 years, M", 5, 85), "45-49 years, M")
        for t in ("x 12 yrs, female", "since 7 yrs", "7 yrs back", "for 3 yrs, male"):
            self.assertEqual(find_ages(t), [], t)
