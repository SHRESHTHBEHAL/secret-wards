"""Multi-script support: Bengali, Gurmukhi, Gujarati, Odia, Tamil, Telugu, Kannada, Malayalam, Urdu, Marathi."""
import unittest

from raksha import detect, gate, scripts, translit
from raksha.types import Facts

NOTES = {
    "bengali": ("রোগীর নাম: রহিম শেখ   বয়স: ৪৫\nপিতার নাম: করিম শেখ\nমোবাইল: ৯৮৭৬৫৪৩২১০\nগ্রাম: চাঁদপুর\n"
                "Tab Metformin 500 mg BD. ডাঃ সুব্রত বসু", ["রহিম শেখ", "করিম শেখ", "৯৮৭৬৫৪৩২১০", "চাঁদপুর", "৪৫"],
                ["Tab Metformin 500 mg BD", "ডাঃ সুব্রত বসু"]),
    "punjabi": ("ਮਰੀਜ਼ ਦਾ ਨਾਮ: ਗੁਰਪ੍ਰੀਤ ਕੌਰ  ਉਮਰ: 52\nਪਤੀ ਦਾ ਨਾਮ: ਜਸਵਿੰਦਰ ਸਿੰਘ\nਫ਼ੋਨ: 98140 22113\n"
                "Tab Amlodipine 5 mg OD. ਡਾ. ਹਰਜੀਤ ਗਿੱਲ", ["ਗੁਰਪ੍ਰੀਤ ਕੌਰ", "ਜਸਵਿੰਦਰ ਸਿੰਘ", "98140 22113"],
                ["Tab Amlodipine 5 mg OD", "ਡਾ. ਹਰਜੀਤ ਗਿੱਲ", "ਪਤੀ ਦਾ ਨਾਮ"]),
    "gujarati": ("દર્દીનું નામ: કિંજલ પટેલ  ઉંમર: 33\nપતિ: હાર્દિક પટેલ\nમોબાઇલ: ૯૯૨૫૦ ૧૨૩૪૫\n"
                 "Inj Ceftriaxone 1 g IV BD. ડૉ. મેહુલ શાહ", ["કિંજલ પટેલ", "હાર્દિક પટેલ", "૯૯૨૫૦ ૧૨૩૪૫"],
                 ["Inj Ceftriaxone 1 g IV BD", "ડૉ. મેહુલ શાહ"]),
    "odia": ("ରୋଗୀର ନାମ: ସୁଭଶ୍ରୀ ମହାନ୍ତି  ବୟସ: 28\nପିତା: ପ୍ରଦୀପ ମହାନ୍ତି\nଫୋନ: 9437012345\nTab Paracetamol 650 mg TDS",
             ["ସୁଭଶ୍ରୀ ମହାନ୍ତି", "ପ୍ରଦୀପ ମହାନ୍ତି", "9437012345"], ["Tab Paracetamol 650 mg TDS"]),
    "tamil": ("நோயாளி பெயர்: கார்த்திக் சுப்ரமணியன்  வயது: 61\nதந்தை: சுப்ரமணியன்\nகைபேசி: 94440 55667\n"
              "Tab Atorvastatin 20 mg 0-0-1. டாக்டர் மீனாட்சி", ["கார்த்திக்", "94440 55667"],
              ["Tab Atorvastatin 20 mg 0-0-1", "டாக்டர் மீனாட்சி"]),
    "telugu": ("రోగి పేరు: వెంకటేశ్వర్లు రెడ్డి  వయస్సు: 70\nతండ్రి: రామయ్య రెడ్డి\nఫోన్: 9848012345\nTab Telmisartan 40 mg 1-0-0",
               ["వెంకటేశ్వర్లు రెడ్డి", "రామయ్య రెడ్డి", "9848012345"], ["Tab Telmisartan 40 mg 1-0-0"]),
    "kannada": ("ರೋಗಿಯ ಹೆಸರು: ಮಂಜುನಾಥ ಗೌಡ  ವಯಸ್ಸು: 44\nತಂದೆ: ಬಸವರಾಜ ಗೌಡ\nಮೊಬೈಲ್: 9845098450\nTab Doxycycline 100 mg 1-0-1",
                ["ಮಂಜುನಾಥ ಗೌಡ", "ಬಸವರಾಜ ಗೌಡ", "9845098450"], ["Tab Doxycycline 100 mg 1-0-1"]),
    "malayalam": ("രോഗിയുടെ പേര്: ഫാത്തിമ ബീവി  വയസ്സ്: 38\nഭർത്താവ്: അബ്ദുൾ റഹ്മാൻ\nഫോൺ: 9447012345\n"
                  "Hb 9.8 g/dL. ഡോ. ജോസഫ് മാത്യു", ["ഫാത്തിമ ബീവി", "അബ്ദുൾ റഹ്മാൻ", "9447012345"],
                  ["Hb 9.8 g/dL", "ഡോ. ജോസഫ് മാത്യു"]),
    "urdu": ("مریض کا نام: رشید احمد  عمر: 55\nوالد کا نام: محمود احمد\nفون: ۹۸۷۶۵۴۳۲۱۰\nTab Metformin 500 mg BD",
             ["رشید احمد", "محمود احمد", "۹۸۷۶۵۴۳۲۱۰"], ["Tab Metformin 500 mg BD"]),
    "marathi": ("रुग्णाचे नाव: सुनील पाटील  वय: 49\nवडील: बाळासाहेब पाटील\nमोबाइल: ९८२२०१२३४५\nगाव: शिरूर\nTab Ecosprin 75 mg OD",
                ["सुनील पाटील", "बाळासाहेब पाटील", "९८२२०१२३४५", "शिरूर"], ["Tab Ecosprin 75 mg OD"]),
}


def redact(text):
    spans = sorted(detect.detect(text), key=lambda s: s.start)
    out, pos = [], 0
    for s in spans:
        if s.start < pos:
            continue
        out += [text[pos:s.start], "[X]"]
        pos = s.end
    return "".join(out) + text[pos:]


class FoldTest(unittest.TestCase):
    def test_length_preserving_all_blocks(self):
        for lo, hi in scripts.BLOCKS.values():
            s = "".join(chr(c) for c in range(lo, hi + 1))
            self.assertEqual(len(scripts.fold(s)), len(s))

    def test_latin_and_devanagari_unchanged(self):
        s = "Patient: Ram Kumar, आयु 45, BP 140/90"
        self.assertEqual(scripts.fold(s), s.replace("४", "4"))

    def test_native_digits(self):
        self.assertEqual(scripts.fold("৯৮৭ ੯੮੭ ૯૮૭ ୯୮୭ ௯௮௭ ౯౮౭ ೯೮೭ ൯൮൭ ۹۸۷ ٩٨٧"), "987 987 987 987 987 987 987 987 987 987")

    def test_labels_fold_to_hindi(self):
        for w in ("নাম", "ਨਾਮ", "નામ", "ନାମ", "نام"):
            self.assertEqual(scripts.alias_label_word(scripts.fold(w)), "नाम")
        for w in ("பெயர்", "పేరు", "ಹೆಸರು", "പേര്", "नाव"):
            self.assertEqual(scripts.alias_label_word(scripts.fold(w)), "नाम")

    def test_script_mix(self):
        mix = scripts.script_mix("রোগী Rahim رشید")
        self.assertEqual(set(mix), {"beng", "latin", "arab"})


class DetectTest(unittest.TestCase):
    def test_every_language(self):
        for lang, (note, gone, kept) in NOTES.items():
            out = redact(note)
            for g in gone:
                self.assertNotIn(g, out, "%s leaked %r" % (lang, g))
            for k in kept:
                self.assertIn(k, out, "%s lost %r" % (lang, k))


class LinkKeyTest(unittest.TestCase):
    def test_cross_script_same_person(self):
        for a, b in [("রহিম শেখ", "Rahim Shekh"), ("ਗੁਰਪ੍ਰੀਤ ਕੌਰ", "Gurpreet Kaur"), ("કિંજલ પટેલ", "Kinjal Patel"),
                     ("కార్తిక్", "Karthik"), ("கார்த்திக்", "Karthik"), ("ಮಂಜುನಾಥ ಗೌಡ", "Manjunath Gowda"),
                     ("ഫാത്തിമ ബീവി", "Fathima Beevi"), ("رشید احمد", "Rashid Ahmed"), ("محمود", "Mahmood"),
                     ("ସୁଭଶ୍ରୀ ମହାନ୍ତି", "Subhashree Mohanty"), ("ਗੁਰਪ੍ਰੀਤ ਕੌਰ", "गुरप्रीत कौर")]:
            self.assertTrue(translit.same_name(a, b), (a, b))

    def test_different_people_stay_apart(self):
        for a, b in [("রহিম শেখ", "Karim Shekh"), ("கார்த்திக்", "Kartikeya"), ("رشید احمد", "Rashida Begum")]:
            self.assertFalse(translit.same_name(a, b), (a, b))


class GateTest(unittest.TestCase):
    def test_known_identity_removed_from_other_script(self):
        fb = gate.forbidden_from_facts([Facts(names=["Rahim Shekh"], ids=["phone:9876543210"])])
        out = gate.clean("রোগী রহিম শেখ ফোন ৯৮৭৬৫ ৪৩২১০ ভর্তি", fb)[0]
        self.assertNotIn("রহিম", out)
        self.assertNotIn("৯৮৭৬৫", out)
        self.assertIn("ভর্তি", out)


if __name__ == "__main__":
    unittest.main()
