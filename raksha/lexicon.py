"""Word lists used by the detectors. All entries lowercase. Standard library only."""
from __future__ import annotations


def _words(s: str) -> frozenset:
    return frozenset(w.strip().lower() for w in s.split() if w.strip())


_DRUGS = """
paracetamol pcm dolo crocin calpol ibuprofen diclofenac aceclofenac aspirin ecosprin clopidogrel atorvastatin
rosuvastatin metformin glimepiride gliclazide sitagliptin vildagliptin insulin glargine actrapid mixtard
amlodipine telmisartan losartan ramipril enalapril atenolol metoprolol propranolol carvedilol furosemide lasix
torsemide spironolactone hydrochlorothiazide digoxin nitroglycerin isosorbide heparin enoxaparin warfarin
amoxicillin augmentin amoxyclav ampicillin cloxacillin azithromycin clarithromycin erythromycin doxycycline
ciprofloxacin levofloxacin ofloxacin norfloxacin moxifloxacin ceftriaxone cefixime cefuroxime cefotaxime
cefpodoxime ceftazidime cefoperazone piperacillin tazobactam meropenem imipenem vancomycin linezolid
gentamicin amikacin metronidazole tinidazole ornidazole nitrofurantoin cotrimoxazole septran fluconazole
itraconazole clotrimazole albendazole ivermectin artesunate artemether lumefantrine chloroquine primaquine
quinine isoniazid rifampicin pyrazinamide ethambutol akt pantoprazole pan omeprazole rabeprazole esomeprazole
ranitidine famotidine domperidone ondansetron emset metoclopramide ors loperamide lactulose bisacodyl
sucralfate antacid digene cetirizine levocetirizine montelukast salbutamol asthalin budesonide ipratropium
deriphyllin theophylline prednisolone methylprednisolone dexamethasone hydrocortisone betamethasone
thyroxine levothyroxine thyronorm carbimazole iron ferrous folic calcium vitamin b12 methylcobalamin
multivitamin zinc phenytoin levetiracetam valproate carbamazepine diazepam lorazepam alprazolam clonazepam
haloperidol olanzapine risperidone sertraline escitalopram fluoxetine amitriptyline gabapentin pregabalin
tramadol morphine pentazocine ketorolac tranexamic oxytocin misoprostol mifepristone methyldopa labetalol
nifedipine magnesium sulphate mgso4 dextrose saline ns rl ringer kcl sodium bicarbonate mannitol
albumin hydroxychloroquine methotrexate allopurinol febuxostat colchicine tamsulosin finasteride
sildenafil oseltamivir acyclovir valacyclovir tenofovir zidovudine dolutegravir nevirapine
"""

_FORMS = """
tab tabs tablet tablets cap caps capsule capsules inj injection syp syrup susp suspension drops drop oint
ointment cream gel lotion neb nebulisation nebulization inhaler puff sachet iv im sc po sl pr od bd tds tid
qid hs sos stat qhs prn ac pc mg mcg g gm gram ml l iu units unit mmol meq kg cm mm mmhg bpm f c
days day wks wk week weeks month months yrs yr year years hrs hr hour hours min mins
"""

_LABS = """
haemoglobin hemoglobin hb hgb wbc tlc dlc rbc platelet platelets plt pcv hct esr crp mcv mch mchc rdw
neutrophils lymphocytes eosinophils monocytes basophils blood sugar rbs fbs ppbs hba1c glucose urea bun
creatinine serum sodium potassium chloride bilirubin sgot sgpt ast alt alp ggt albumin globulin protein
lipid cholesterol triglycerides hdl ldl vldl tsh t3 t4 urine routine microscopy culture sensitivity
widal dengue ns1 igm igg malaria mp rdt hiv hbsag hcv vdrl ecg ekg echo xray x-ray usg ultrasound ct mri
abg inr pt aptt d-dimer troponin cpk ldh amylase lipase uric acid stool sputum afb cbnaat genexpert
mantoux biopsy fnac pap smear count total differential random fasting report reference range value
"""

_DIAG = """
fever pyrexia cough cold coryza headache pain abdomen abdominal chest breathlessness dyspnoea dyspnea
vomiting nausea diarrhoea diarrhea loose motions constipation weakness fatigue malaise giddiness dizziness
syncope seizure seizures convulsions fits swelling oedema edema rash itching burning micturition dysuria
haematuria hematuria jaundice bleeding palpitations anorexia weight loss insomnia anxiety depression
diabetes dm dm2 t2dm hypertension htn hypothyroidism hyperthyroidism asthma copd tb tuberculosis
pneumonia bronchitis typhoid enteric malaria dengue chikungunya covid influenza uti infection sepsis
septicaemia anaemia anemia ckd aki renal failure heart failure chf cad ihd mi stroke cva tia epilepsy
cirrhosis hepatitis gastritis gerd ulcer appendicitis cholecystitis cholelithiasis pancreatitis hernia
fracture injury trauma burn wound abscess cellulitis arthritis gout osteoarthritis rheumatoid
pregnancy anc pih eclampsia preeclampsia gdm delivery caesarean lscs abortion pph leprosy filariasis
cataract glaucoma otitis tonsillitis pharyngitis sinusitis migraine vertigo neuropathy disease syndrome
disorder unspecified acute chronic severe mild moderate known case history complaints complaint
diagnosis provisional final impression admitted discharged treated conservatively stable improved
referred review follow up advised advice diet low salt diabetic normal abnormal positive negative
reactive nonreactive elevated raised high low patient attendant hospital clinic ward bed icu ot opd ipd
emergency casualty medicine surgery orthopaedics orthopedics paediatrics pediatrics gynaecology
obstetrics obg ent ophthalmology dermatology psychiatry cardiology nephrology neurology gastroenterology
pulmonology oncology urology general consultant resident nurse sister staff duty doctor round
dressing catheter cannula oxygen ventilator monitoring vitals bp pulse temp temperature spo2 rr
respiratory rate heart weight height bmi gcs pallor icterus cyanosis clubbing lymphadenopathy
"""

_HINGLISH = """
bukhar bukhaar dard pet sir sar ulti ultee kamzori kamjori khansi khaansi zukam jukam dast chakkar
saans sans dhadkan jalan khujli sujan soojan neend bhook pyaas peshab pishab latrine kabz thakan
ghabrahat pasina kaanpna thand kamar ghutna jodon chhati seene gala galey naak kaan aankh daant
dawai dawa dawaai goli tikka injection pani khoon bp sugar
"""

_HINDI = """
बुखार दर्द खांसी खाँसी उल्टी कमजोरी कमज़ोरी पेट सिर सर दस्त चक्कर सांस साँस जुकाम जलन खुजली सूजन
नींद भूख पेशाब कब्ज थकान घबराहट पसीना छाती सीना गला दवा दवाई गोली इंजेक्शन खून शुगर मधुमेह
रक्तचाप निमोनिया मलेरिया टाइफाइड डेंगू टीबी क्षय पीलिया दमा निदान इलाज उपचार मरीज़ मरीज रोगी
अस्पताल वार्ड बिस्तर डॉक्टर नर्स जांच जाँच रिपोर्ट भर्ती छुट्टी सलाह आहार परहेज
"""

CLINICAL_WORDS = frozenset(
    _words(_DRUGS) | _words(_FORMS) | _words(_LABS) | _words(_DIAG) | _words(_HINGLISH) | _words(_HINDI)
)

COMPLAINT_WORDS = frozenset(_words("""
fever pain cough cold headache vomiting nausea diarrhoea diarrhea loose breathlessness dyspnoea dyspnea
weakness fatigue giddiness dizziness swelling rash itching burning bleeding chest abdomen abdominal
palpitations seizure seizures fits convulsions jaundice constipation sore throat body ache aches
backache weight loss decreased reduced increased difficulty yellowish yellow high low generalised
generalized painful burning blood shortness
bukhar bukhaar dard pet sir sar ulti kamzori kamjori khansi zukam jukam dast chakkar saans jalan khujli
sujan soojan ghabrahat thakan kabz
बुखार दर्द खांसी खाँसी उल्टी कमजोरी कमज़ोरी पेट सिर दस्त चक्कर सांस साँस जुकाम जलन खुजली सूजन
""") | _words(_DIAG) - _words("patient attendant hospital clinic ward bed doctor nurse sister staff general consultant resident"))

HINDI_COMMON_WORDS = frozenset(_words("""
ka ki ke ko se hai hain tha thi the mein me main par pe ne aur ya bhi nahi nahin na ab abhi kal aaj din
raat subah shaam theek thik se sahi band ho gaya gayi gaye hua hui hue diya diye liya li kiya kiye karna
kar kare karen raha rahi rahe wala wali wale yeh ye woh wo is us iska uska unka inka apna apni hum aap
tum mera meri tera kuch bahut zyada jyada kam thoda sab koi kya kyun kab kaise kahan jab tab to toh hi
bas fir phir baad pehle saath liye wajah se tak dobara roz rozana ek do teen char paanch hafte haftey
mahine saal ghanta ghante neend li lena dena khana peena chalna jana aana
को की का के से है हैं था थी थे में पर ने और या भी नहीं ना अब अभी कल आज दिन रात सुबह शाम ठीक सही बंद हो
गया गयी गई गए हुआ हुई हुए दिया दिए लिया ली किया किए करना कर करें रहा रही रहे वाला वाली वाले यह ये वह वो
इस उस इसका उसका उनका अपना अपनी हम आप तुम मेरा मेरी कुछ बहुत ज्यादा कम थोड़ा सब कोई क्या क्यों कब कैसे
कहाँ जब तब तो ही बस फिर बाद पहले साथ लिए तक रोज़ एक दो तीन चार पांच हफ्ते महीने साल घंटे से नाम आयु उम्र
वर्ष पुरुष महिला पता तारीख की
"""))

KINSHIP_MARKERS = (
    "s/o", "d/o", "w/o", "h/o", "c/o", "f/o", "m/o", "b/o", "so", "do", "wo",
    "son of", "daughter of", "wife of", "husband of", "care of", "father", "mother", "husband", "wife",
    "पिता", "पति", "पत्नी", "माता", "पुत्र", "पुत्री", "पिता का नाम", "पति का नाम", "पिता/पति",
    "pita", "pati", "patni", "mata", "beta", "beti",
)

PERSON_VERBS = (
    "called by", "raised by", "witnessed by", "brought by", "accompanied by", "referred by",
    "informed by", "signed by", "consent by", "reported by", "visited by", "received by",
    "attended by", "escorted by", "collected by", "verified by", "registered by", "requested by",
)

ADDRESS_CUES = (
    "h.no", "h no", "h.no.", "house", "house no", "makan", "makan no", "मकान", "मकान नं", "mohalla",
    "मोहल्ला", "near", "opp", "opp.", "opposite", "behind", "gram", "ग्राम", "gaon", "गांव", "vill",
    "vill.", "village", "tehsil", "तहसील", "distt", "distt.", "district", "dist", "जिला", "ज़िला",
    "ward", "वार्ड", "post", "po", "p.o", "block", "pin", "pincode", "pin code", "पिन", "address", "पता",
    "street", "road", "nagar", "colony", "sector", "lane", "gali", "गली", "basti", "bazar", "chowk",
)
