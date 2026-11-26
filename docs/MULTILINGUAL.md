# Multi-script support (11 scripts)

Raksha reads patient records in **Latin, Devanagari (Hindi, Marathi), Bengali/Assamese, Gurmukhi (Punjabi),
Gujarati, Odia, Tamil, Telugu, Kannada, Malayalam and Perso-Arabic (Urdu)**, and in Hinglish and other
code-mixed text, without a model.

## How

`raksha/scripts.py` folds every script onto Devanagari **one code point for one**:

* The Brahmic Unicode blocks share Devanagari's ISCII-derived layout at a fixed offset, so a consonant, vowel
  sign or virama in any of them maps to the Devanagari code point with the same role (with a small table for
  script-specific letters: Malayalam chillus, Gurmukhi tippi/addak, Bengali khanda-ta, Tamil "ca" read as "s").
* Urdu is folded with a phonetic table plus position rules for alif / vav / ye (Urdu leaves short vowels implicit).
* Every native digit set becomes ASCII.

Because folding keeps the length, a span found on folded text indexes the original exactly. The detectors, header
classifier, phonetic name keys and leak gate written for Devanagari and Latin therefore work on all 11 scripts, and
the sanitised output keeps its original script.

Native label, kinship, honorific, title and doctor words (নাম, ਨਾਮ, નામ, ନାମ, பெயர், పేరు, ಹೆಸರು, പേര്, نام, नाव ...)
are written natively in `scripts.py` and folded at import onto the Hindi label word the detectors already know.

## Measured

| Check | Without | With |
|---|---|---|
| PII in 10 native-script clinical notes (bench in `tests/test_scripts.py`) | 22 / 32 leaked (69%) | 0 / 32 (0%) |
| Medical values and doctor names in those notes | kept | kept |
| Practice dataset output | — | byte-identical, same runtime |

Cross-script linking: রহিম শেখ ~ Rahim Shekh, ਗੁਰਪ੍ਰੀਤ ਕੌਰ ~ Gurpreet Kaur ~ गुरप्रीत कौर, கார்த்திக் ~ Karthik,
ಮಂಜುನಾಥ ಗೌಡ ~ Manjunath Gowda, رشید احمد ~ Rashid Ahmed, محمود ~ Mahmood.

## Limits

* Tamil script has no separate voiced consonants, so Tamil spellings of names with g/d/b can key differently from
  their Latin spellings; linking then abstains rather than guesses.
* Urdu short vowels are implicit; keys rely on the consonant skeleton plus the fuzzy token match.
