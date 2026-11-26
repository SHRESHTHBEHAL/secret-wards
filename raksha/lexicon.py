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
ghutna ghutne ghutnon kamar pairon haath haathon peeth pith kandha kandhe gardan aankhon kaanon daant pindli edi
ediyon talwe ungli ungliyon jod jodo kalai kohni koolha kulha jangh jaangh pet pesab peshaab baar taraf dono
sujan soojan sunnapan jhunjhuni akdan akadan kamjori bechaini hichki
"""

_HINDI = """
बुखार दर्द खांसी खाँसी उल्टी कमजोरी कमज़ोरी पेट सिर सर दस्त चक्कर सांस साँस जुकाम जलन खुजली सूजन
नींद भूख पेशाब कब्ज थकान घबराहट पसीना छाती सीना गला दवा दवाई गोली इंजेक्शन खून शुगर मधुमेह
रक्तचाप निमोनिया मलेरिया टाइफाइड डेंगू टीबी क्षय पीलिया दमा निदान इलाज उपचार मरीज़ मरीज रोगी
अस्पताल वार्ड बिस्तर डॉक्टर नर्स जांच जाँच रिपोर्ट भर्ती छुट्टी सलाह आहार परहेज
बच्चेदानी गर्भाशय ऑपरेशन आपरेशन शल्य हीमोग्लोबिन रक्त खून ब्लड ग्रुप पॉजिटिव नेगेटिव ग्राम एल डी
"""

# anatomy and examination findings: capitalised in notes ("Optic Disc normal"), never a person
_ANATOMY = """
optic disc disk retina retinal cornea corneal lens pupil pupils fundus fundi macula conjunctiva sclera eyelid
tonsil tonsils pharynx larynx trachea bronchus bronchi lung lungs lobe pleura pleural atrium ventricle valve aorta
artery arteries vein veins liver spleen kidney kidneys ureter bladder urethra prostate uterus ovary ovaries cervix
stomach duodenum jejunum ileum colon rectum pancreas gallbladder thyroid adrenal pituitary brain cerebrum
cerebellum spinal cord nerve nerves muscle muscles tendon ligament femur tibia fibula humerus ulna pelvis spine
vertebra vertebrae skull rib ribs sternum knee hip shoulder elbow wrist ankle abdomen chest thorax scalp neck
lymph node nodes axilla groin umbilicus sinus sinuses mitral tricuspid aortic pulmonary carotid femoral radial
left right bilateral mca aca pca ica lad lcx rca svc ivc lv rv la ra infarct infarction hemiparesis hemiplegia
paraparesis quadriparesis aphasia dysarthria ataxia spasticity
"""

# acronyms, mechanisms, devices, departments and staff words written capitalised in notes
_CLIN_EXTRA = """
rta rti mlc avf af afib paroxysmal persistent alleged implant implants lot batch serial neurosurgery neurosurgical
nephrology haematology hematology neonatology anaesthesia anesthesia radiology pathology microbiology dialysis
haemodialysis hemodialysis technician technologist deworming immunisation immunization vaccination national
shaft skid ptb pcos pcod att rt lt bl murmur fistula shunt mortuary hearse helpline tollfree pillion
sdh edh sah ich dvt pe ards mods hie rds nec ivh pda vsd asd tof copd ild ckd esrd aki dka hhs uti cauti vap
lscs nvd ftnd svd ppiucd iucd pphn iugr sga lga prom pprom gdm pih apgar nicu sncu hdu ccu iccu micu sicu picu
"""

CLINICAL_WORDS = frozenset(
    _words(_CLIN_EXTRA) | _words(_DRUGS) | _words(_FORMS) | _words(_LABS) | _words(_DIAG) | _words(_HINGLISH) | _words(_HINDI) | _words(_ANATOMY)
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
बजे बजकर सुबह शाम दोपहर रात्रि आज कल परसों लगभग करीब केवल सिर्फ हालत स्थिति समय दिनांक घंटे मिनट
मैं मुझे मुझको मेरे हमें हमारा हमारी हमारे उन्होंने उसने इसने वह वे यह ये जो जिसे जिसको जिनको किसी कोई
सभी स्वयं खुद यहाँ यहां वहाँ वहां अंदर बाहर ऊपर नीचे पास दूर साथ बिना लिए द्वारा हेतु तथा एवं अथवा परंतु लेकिन
किया गया दिया लिया लाया लाए लेकर देकर आकर जाकर करके होकर रहे रहा रही था थे थी है हैं हो होगा होगी होंगे
करें करे करना करने कराया कराई करवाया बताया बताए बताई बताया कहा कहे सुना देखा मिला मिली मिले पाया पाई
पीने पीकर खाने खाकर लेने देने आने जाने चलने सोने उठने बैठने गिरने गिरकर काटने काटा लगा लगी लगे हुआ हुई
सिर माथा आंख आँख कान नाक मुंह मुँह दांत गला गर्दन कंधा हाथ उंगली छाती पेट कमर पीठ पैर घुटना एड़ी त्वचा
हृदय दिल फेफड़ा फेफड़े गुर्दा लिवर यकृत खून रक्त पेशाब मल हड्डी नस नसें मांसपेशी पुतली नाड़ी सांस
बुखार दर्द सूजन जलन खुजली चक्कर बेहोशी कमजोरी थकान उल्टी दस्त खांसी कंपकंपी ठंड पसीना घाव चोट जख्म
सूचना पत्र कार्ड पर्ची पर्चा सारांश रेफरल प्रमाण सहमति घोषणा महोदय महोदया सेवा प्रभारी अधीक्षक चिकित्सा
विषाक्तता कीटनाशक जहर सांप साँप बिच्छू कुत्ता काटने वर्षीय वर्षीया पुत्र पुत्री भतीजा भतीजी भांजा भांजी
"""))

# oblique infinitives and light verbs that open a procedure phrase ("<organ> निकालने का ऑपरेशन")
HINDI_COMMON_WORDS = HINDI_COMMON_WORDS | _words("""
निकालने निकालना करवाने करवाना कराने कराना लगवाने लगाने चढ़ाने चढाने चढ़वाने देने लेने करने होने जाने आने रखने
बदलने बंद खोलने सिलने जोड़ने काटने
""")

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

# Public geography: districts / major towns of India (Latin, lowercase) and their common Devanagari
# spellings. Districts and states are kept in the release; this list stops the place-phrase rules from
# taking them as villages. Not exhaustive.
DISTRICTS = _words("""
agra ahmedabad ahmednagar aizawl ajmer akola alappuzha aligarh allahabad prayagraj almora alwar ambala
amravati amritsar anand anantapur anantnag angul araria ariyalur arwal ashoknagar auraiya aurangabad azamgarh
badaun bagalkot bageshwar baghpat bahraich balaghat balangir baleshwar ballia balrampur banaskantha banda
bankura banswara barabanki baramulla baran bardhaman bareilly bargarh barmer barnala barpeta barwani bastar
basti bathinda beed begusarai belgaum belagavi bellary ballari betul bhadrak bhagalpur bhandara bharatpur
bharuch bhavnagar bhilwara bhind bhiwani bhojpur bhopal bidar bijapur vijayapura bijnor bikaner bilaspur
birbhum bokaro bongaigaon budaun bulandshahr buldhana bundi burhanpur buxar cachar chamba chamoli champawat
chandauli chandigarh chandrapur changlang chatra chennai chhatarpur chhindwara chikkamagaluru chitradurga
chitrakoot chittoor chittorgarh churu coimbatore cuddalore cuttack dahod dakshina damoh dantewada darbhanga
darjeeling darrang datia dausa davanagere dehradun deoghar deoria dewas dhanbad dhar dharmapuri dharwad
dhemaji dhenkanal dholpur dhubri dhule dibrugarh dimapur dindigul dindori dumka dungarpur durg east west
north south ernakulam erode etah etawah faizabad ayodhya faridabad faridkot farrukhabad fatehabad fatehpur
firozabad ferozepur gadag gadchiroli gajapati ganderbal gandhinagar ganjam garhwa gaya ghaziabad ghazipur
giridih goalpara godda golaghat gonda gondia gopalganj gorakhpur gulbarga kalaburagi gumla guna guntur
gurdaspur gurgaon gurugram guwahati gwalior hailakandi hamirpur hanumangarh hapur harda hardoi haridwar
hassan hathras haveri hazaribagh hingoli hisar hooghly hoshangabad hoshiarpur howrah hyderabad idukki
imphal indore jabalpur jagatsinghpur jaipur jaisalmer jajpur jalandhar jalaun jalgaon jalna jalore
jalpaiguri jammu jamnagar jamshedpur jamtara jamui janjgir jashpur jaunpur jehanabad jhabua jhajjar
jhalawar jhansi jharsuguda jhunjhunu jind jodhpur jorhat junagadh kadapa kaithal kakinada kalahandi
kamrup kanchipuram kandhamal kangra kanker kannauj kannur kanpur kanyakumari kapurthala karaikal karauli
karbi karimganj karimnagar karnal karur kasaragod kathua katihar katni kaushambi kendrapara kendujhar
keonjhar khagaria khammam khandwa khargone kheda khordha khunti kinnaur kishanganj kishtwar kodagu koderma
kohima kokrajhar kolar kolasib kolhapur kolkata kollam koppal koraput korba koriya kota kottayam kozhikode
subansiri siang kameng garo khasi jaintia
krishna kullu kupwara kurnool kurukshetra kutch lakhimpur lakhisarai lalitpur latur lawngtlai leh lohardaga
lucknow ludhiana lunglei madhepura madhubani madurai mahabubnagar mahasamund mahendragarh mahoba mainpuri
malappuram malda mamit mandi mandla mandsaur mandya mangalore mathura mau mayurbhanj medak meerut mehsana
mirzapur moga mokokchung moradabad morena morigaon mumbai munger murshidabad muzaffarnagar muzaffarpur
mysore mysuru nabarangpur nadia nagaon nagapattinam nagaur nagpur nainital nalanda nalbari nalgonda namakkal
nanded nandurbar narmada narsinghpur nashik navsari nawada nayagarh neemuch nellore nicobar nilgiris nizamabad
noida nuapada osmanabad palakkad palamu palghar pali palwal panchkula panchmahal panipat panna papum
parbhani pashchim patan pathanamthitta pathankot patiala patna pauri perambalur pilibhit pithoragarh
porbandar pratapgarh pudukkottai pulwama pune puri purnia purulia raebareli raichur raigad raigarh raipur
raisen rajgarh rajkot rajnandgaon rajouri rajsamand ramanathapuram ramgarh rampur ranchi ratlam ratnagiri
rayagada reasi rewa rewari rohtak rohtas rudraprayag rupnagar sabarkantha sagar saharanpur saharsa sahibganj
saiha salem samastipur sambalpur sangli sangrur sant saran satara satna sawai sehore senapati seoni serchhip
shahdol shahjahanpur shajapur sheikhpura sheohar shimla shimoga shivamogga shivpuri shopian shravasti
siddharthnagar sidhi sikar simdega sindhudurg singrauli sirmaur sirohi sirsa sitamarhi sitapur sivaganga
sivasagar siwan solan solapur sonbhadra sonipat sonitpur srikakulam srinagar sultanpur sundargarh supaul
surat surendranagar surguja tapi tarn thane thanjavur theni thiruvananthapuram thoothukudi thrissur tikamgarh
tinsukia tirap tiruchirappalli tirunelveli tiruppur tiruvallur tiruvannamalai tonk tumkur tumakuru tuensang
udaipur udalguri udham udhampur udupi ujjain ukhrul umaria una unnao uttara vadodara vaishali valsad
varanasi vellore vidisha villupuram virudhunagar visakhapatnam vizianagaram warangal wardha washim wayanad
yadgir yamunanagar yavatmal zunheboto bardez salcete tiswadi pernem bicholim sattari ponda sanguem quepem
canacona mormugao dharashiv shillong
आगरा अहमदाबाद अजमेर अलीगढ़ अल्मोड़ा अलवर अमृतसर आजमगढ़ बहराइच बलिया बांकुड़ा बाँकुड़ा बांदा बाराबंकी बरेली
बरगढ़ बाड़मेर बस्ती बेगूसराय भागलपुर भरतपुर भीलवाड़ा भोपाल बीकानेर बिलासपुर बोकारो बुलंदशहर चतरा छिंदवाड़ा
दरभंगा देहरादून देवघर देवरिया धनबाद धार डिब्रूगढ़ दुमका दुर्ग इटावा फैजाबाद अयोध्या फर्रुखाबाद फतेहपुर
गया गाजियाबाद गाज़ीपुर गिरिडीह गोंडा गोरखपुर गुमला ग्वालियर हमीरपुर हरदोई हरिद्वार हजारीबाग इंदौर जबलपुर
जयपुर जालौन जौनपुर झांसी झाँसी जोधपुर कानपुर कटिहार खूंटी कोडरमा कोटा लखनऊ ललितपुर लोहरदगा मधुबनी
महोबा मैनपुरी मथुरा मऊ मेरठ मिर्जापुर मुरादाबाद मुंगेर मुजफ्फरपुर नागपुर नालंदा नवादा पलामू पटना
पूर्णिया पुरुलिया प्रयागराज रायबरेली रायपुर राजगढ़ रामगढ़ रांची राँची रीवा रोहतास सागर सहारनपुर समस्तीपुर
संबलपुर सारण सतना सीहोर शाहजहांपुर सीतापुर सीवान सोनभद्र सुल्तानपुर उदयपुर उज्जैन उन्नाव वाराणसी
विदिशा साहिबगंज सिमडेगा पाकुड़ गोड्डा जामताड़ा गढ़वा लातेहार पश्चिमी पूर्वी सिंहभूम जुन्नर पुणे नाशिक
""")
# more districts (J&K, Ladakh, the North-East, Jharkhand, Odisha, Tamil Nadu, Bengal, Punjab) and the
# multi-word names, matched as whole phrases
DISTRICTS = DISTRICTS | _words("""
bandipora kulgam ramban poonch budgam kargil wokha phek kiphire longleng peren noklak chumoukedima niuland
shamator tseminyu latehar sahebganj pakur seraikela boudh malkangiri sonepur deogarh mayiladuthurai tiruvarur
tenkasi krishnagiri kallakurichi ranipet tirupattur chengalpattu jhargram alipurduar coochbehar kalimpong
fazilka mansa muktsar mohali nawanshahr malerkotla berhampur brahmapur rourkela bhubaneswar majuli biswanath
charaideo hojai sribhumi champhai saitual khawzawl hnahthial siaha churachandpur chandel tamenglong thoubal
bishnupur kakching jiribam kangpokpi noney pherzawl tengnoupal kamjong
""") | frozenset({"tarn taran", "dima hasao", "karbi anglong", "west karbi anglong", "cooch behar",
                 "sri muktsar sahib", "fatehgarh sahib", "purba medinipur", "paschim medinipur", "purba bardhaman",
                 "paschim bardhaman", "uttar dinajpur", "dakshin dinajpur", "east khasi hills", "west khasi hills",
                 "west garo hills", "east garo hills", "south garo hills", "lower subansiri", "upper subansiri"})

