# G-ASET Multilingual PDF Assessment — deterministic field-name mapping (#3 complete)
# Runs fully in-browser (Pyodide / shinylive / GitHub Pages). Pure-Python deps only.
#
# shinylive requirements: pypdf   (langdetect optional)

import re
import io
import csv

from shiny.express import input, render, ui
from shiny import reactive, ui as core_ui
from shiny.session import get_current_session

try:
    from pypdf import PdfReader
except ImportError:
    from PyPDF2 import PdfReader

try:
    from langdetect import detect, DetectorFactory
    DetectorFactory.seed = 0
    HAS_LANGDETECT = True
except ImportError:
    HAS_LANGDETECT = False


ui.page_opts(title="G-ASET Multilingual PDF Assessment", fillable=False)

# ---------- JS helpers ----------
core_ui.tags.script("""
Shiny.addCustomMessageHandler('update_badges', function(msg) {
    function apply() {
        let missing = false;
        for (const id in msg.items) {
            const el = document.getElementById(id);
            if (el) { el.innerHTML = msg.items[id].html; el.style.background = msg.items[id].bg; }
            else { missing = true; }
        }
        return missing;
    }
    if (apply()) { setTimeout(apply, 150); setTimeout(apply, 500); }
});
""")
core_ui.tags.script("""
Shiny.addCustomMessageHandler('set_form_lock', function(msg) {
    function apply() {
        const c = document.getElementById('dynamic_form_container');
        if (!c) return;
        c.querySelectorAll('input').forEach(el => el.disabled = msg.locked);
        c.style.opacity = msg.locked ? '0.75' : '1';
        c.style.pointerEvents = msg.locked ? 'none' : 'auto';
    }
    apply(); setTimeout(apply, 150); setTimeout(apply, 500);
});
""")

# ---------- Localization (stems + Yes/Partial/No only) ----------
LANGS = {
    "en": {"name": "English", "yes": r"Yes", "partial": "Partially implemented", "no": "No",
           "domain_kw": r"Domain", "select_all": r"select all that apply",
           "answer_questions": r"Answer questions",
           "footer_re": r"Global Antibiotic Stewardship Evaluation Tool.*?Healthcare Facilities\s*\d+",
           "ui_upload": "Upload G-ASET PDF",
           "ui_desc": "Values are read **deterministically** from the PDF's form fields.",
           "ui_no_pdf": "No PDF uploaded yet.",
           "ui_upload_prompt": "Upload a G-ASET PDF to generate the assessment form.",
           "ui_status": "📄 PDF Status", "ui_scores": "📊 Assessment Scores",
           "ui_domain": "Domain", "ui_score": "Score", "ui_pct": "Percentage", "ui_overall": "OVERALL",
           "ui_scores_later": "Scores will appear after uploading the PDF.",
           "ui_parsed": "✅ Recognized G-ASET form — {nq} scored items (language: {lang}).",
           "ui_unlock_btn": "🔒 Unlock form", "ui_lock_btn": "🔓 Lock form",
           "ui_locked_msg": "🔒 Form is locked (read-only).",
           "ui_unlocked_msg": "🔓 Form is unlocked (editable)."},
    "es": {"name": "Español", "yes": r"S[íi]", "partial": "Parcialmente implementado", "no": "No",
           "domain_kw": r"Secci[oó]n", "select_all": r"[Ss]eleccione todo lo que corresponda",
           "answer_questions": r"Responda las preguntas",
           "footer_re": r"Herramienta global de evaluaci[oó]n.*?internaci[oó]n\s*\d+",
           "ui_upload": "Cargar PDF de G-ASET",
           "ui_desc": "Los valores se leen **directamente** de los campos del PDF.",
           "ui_no_pdf": "No se ha cargado ningún PDF.",
           "ui_upload_prompt": "Cargue un PDF de G-ASET para generar el formulario.",
           "ui_status": "📄 Estado del PDF", "ui_scores": "📊 Puntuaciones",
           "ui_domain": "Sección", "ui_score": "Puntuación", "ui_pct": "Porcentaje", "ui_overall": "TOTAL",
           "ui_scores_later": "Las puntuaciones aparecerán tras cargar el PDF.",
           "ui_parsed": "✅ Formulario G-ASET reconocido — {nq} ítems (idioma: {lang}).",
           "ui_unlock_btn": "🔒 Desbloquear", "ui_lock_btn": "🔓 Bloquear",
           "ui_locked_msg": "🔒 Formulario bloqueado (solo lectura).",
           "ui_unlocked_msg": "🔓 Formulario desbloqueado (editable)."},
    "fr": {"name": "Français", "yes": r"Oui", "partial": "Partiellement mis en œuvre", "no": "Non",
           "domain_kw": r"Domaine",
           "select_all": r"s[ée]lectionnez tout ce qui s'applique|cochez toutes les cases applicables",
           "answer_questions": r"R[ée]pond(?:re|ez) aux questions",
           "footer_re": r"Outil mondial d.?[ée]valuation.*?\s*\d+",
           "ui_upload": "Télécharger le PDF G-ASET",
           "ui_desc": "Les valeurs sont lues **directement** des champs du PDF.",
           "ui_no_pdf": "Aucun PDF téléchargé.",
           "ui_upload_prompt": "Téléchargez un PDF G-ASET pour générer le formulaire.",
           "ui_status": "📄 État du PDF", "ui_scores": "📊 Scores",
           "ui_domain": "Domaine", "ui_score": "Score", "ui_pct": "Pourcentage", "ui_overall": "TOTAL",
           "ui_scores_later": "Les scores apparaîtront après le téléchargement.",
           "ui_parsed": "✅ Formulaire G-ASET reconnu — {nq} items (langue : {lang}).",
           "ui_unlock_btn": "🔒 Déverrouiller", "ui_lock_btn": "🔓 Verrouiller",
           "ui_locked_msg": "🔒 Formulaire verrouillé (lecture seule).",
           "ui_unlocked_msg": "🔓 Formulaire déverrouillé (modifiable)."},
    "pt": {"name": "Português", "yes": r"Sim", "partial": "Parcialmente implementado", "no": r"N[ãa]o",
           "domain_kw": r"Dom[íi]nio",
           "select_all": r"selecione todas as op[cç][õo]es aplic[áa]veis|marque todas que se aplicam",
           "answer_questions": r"Responda [àa]s perguntas",
           "footer_re": r"Ferramenta global de avalia[cç][ãa]o.*?\s*\d+",
           "ui_upload": "Carregar PDF do G-ASET",
           "ui_desc": "Os valores são lidos **diretamente** dos campos do PDF.",
           "ui_no_pdf": "Nenhum PDF carregado ainda.",
           "ui_upload_prompt": "Carregue um PDF do G-ASET para gerar o formulário.",
           "ui_status": "📄 Status do PDF", "ui_scores": "📊 Pontuações",
           "ui_domain": "Domínio", "ui_score": "Pontuação", "ui_pct": "Porcentagem", "ui_overall": "TOTAL",
           "ui_scores_later": "As pontuações aparecerão após carregar o PDF.",
           "ui_parsed": "✅ Formulário G-ASET reconhecido — {nq} itens (idioma: {lang}).",
           "ui_unlock_btn": "🔒 Desbloquear", "ui_lock_btn": "🔓 Bloquear",
           "ui_locked_msg": "🔒 Formulário bloqueado (somente leitura).",
           "ui_unlocked_msg": "🔓 Formulário desbloqueado (editável)."},
}

# ---------- Canonical schema ----------
_YPN = [1, 2, 3, 5, 7, 8, 10, 12, 13, 15, 16, 17, 20, 21, 22, 23, 24, 25, 26, 27,
        28, 29, 30, 33, 34, 36, 39, 40, 41, 42, 44, 45, 46, 47, 48, 49, 50, 51,
        52, 53, 55, 56, 57, 60, 61, 62, 63, 64, 65, 66]
_CHECKBOX = [4, 9, 11, 14, 18, 19, 31, 32, 37, 38, 43, 54, 58, 59]

CANONICAL = {n: {"type": "ypn"} for n in _YPN}
CANONICAL.update({n: {"type": "checkbox"} for n in _CHECKBOX})
CANONICAL[6] = {"type": "table6"}
CANONICAL[35] = {"type": "table35"}

# ---- Field-name map (from the AcroForm dump) ----
RADIO_FIELDS = {n: f"Assess {n}" for n in _YPN}

CHECKBOX_FIELDS = {
    4:  ["D1_4 Check"] + [f"D1_4 Check{i}" for i in range(2, 17)],
    9:  [f"D1_9 {i}" for i in range(1, 12)],
    11: [f"D1_11 {i}" for i in range(1, 9)],
    14: [f"D2_14 {i}" for i in range(1, 8)],
    18: [f"D2_18 {i}" for i in range(1, 8)],
    19: ["D2_19 1", "D2_19 2", "D2_19 2b", "D2_19 3", "D2_19 4", "D2_19 5", "D2_19 6"],
    31: [f"D4_31 {i}" for i in range(1, 17)],
    32: [f"D4_32 {i}" for i in range(1, 8)],
    37: [f"Assess 37 {i}" for i in range(1, 10)],
    38: [f"Assess 38 {i}" for i in range(1, 6)],
    43: [f"Assess 43 {i}" for i in range(1, 7)],
    54: [f"Assess 54 {i}" for i in range(1, 5)],
    58: [f"Assess 58 {i}" for i in range(1, 14)],
    59: [f"Assess 59 {i}" for i in range(1, 8)],
}
SIX_A_FIELDS = [f"6A {i}" for i in range(1, 14)]
THIRTYFIVE_A_FIELDS = [f"Assess 35A {i}" for i in range(1, 19)]

# ---- Canonical English option labels (display + scoring by index) ----
CHECKBOX_LABELS = {
    4: ["Infection prevention and control (IPC) physician(s)", "IPC nurse(s)", "Non-IPC nurse(s)",
        "Infectious diseases trained physician(s) or clinician(s) with experience practicing infectious diseases",
        "Intensive care unit physician(s)", "Surgeon(s)", "General medicine physician(s)",
        "Other physician(s)",
        "Infectious diseases trained pharmacist(s) or pharmacist(s) with experience practicing infectious diseases",
        "Other clinical pharmacist(s)", "Other staff pharmacist(s)", "Senior healthcare facility leader(s)",
        "Clinical microbiologist(s)", "Information technology specialist(s)", "Not applicable",
        "Other, please specify"],
    9: ["Infection prevention and control", "Infectious diseases", "Patient safety", "Quality",
        "Pharmacy", "Microbiology", "Drug and therapeutics committee", "HIV/tuberculosis (TB) team",
        "Surgery or operating theater", "Not applicable", "Other, please specify"],
    11: ["Infectious diseases trained physician(s) or clinician(s) with experience practicing infectious diseases",
         "Infectious diseases trained pharmacist(s) or pharmacist(s) with experience practicing infectious diseases",
         "Other clinical pharmacist(s)", "Other staff pharmacist(s)",
         "Member(s) of antibiotic stewardship team", "Clinical microbiologist(s)", "Not applicable",
         "Other, please specify"],
    14: ["Infectious diseases trained physician(s) or clinician(s) with experience practicing infectious diseases",
         "Infectious diseases trained pharmacist(s) or pharmacist(s) with experience practicing infectious diseases",
         "Other clinical pharmacist(s)", "Other staff pharmacist(s)", "Clinical microbiologist(s)",
         "Not applicable", "Other, please specify"],
    18: ["Electronic medical record", "List of antibiotics purchased", "List of antibiotics dispensed",
         "Antibiotic administration records", "Syndromic antibiogram", "Cumulative antibiogram",
         "Not applicable"],
    19: ["Antibiotic consumption", "Antibiotic use", "Antibiotic resistance", "Antibiotic cost",
         "Administrative data", "Not applicable", "Other, please specify"],
    31: ["Urinary tract infection", "Community-acquired pneumonia", "Hospital-acquired pneumonia",
         "Ventilator-associated pneumonia", "Sepsis", "Skin and soft tissue infection",
         "Surgical site infection", "Central line-associated bloodstream infection", "Surgical prophylaxis",
         "Intra-abdominal infection", "Febrile neutropenia", "Management of multidrug-resistant organisms",
         "Bacterial meningitis", "Infective endocarditis", "Not applicable", "Other, please specify"],
    32: ["First-line antibiotic agent", "Dose", "Duration", "Alternative antibiotic agents",
         "Antibiotic agents categorized by WHO AWaRe classification", "Not applicable",
         "Other, please specify"],
    37: ["Current antibiotic stewardship resources and activity",
         "Performance against process and outcome indicators for antibiotic use",
         "Antibiotic appropriateness", "Antibiotic resistance", "Key areas of improvement",
         "Areas for further improvement or priority",
         "Areas in which guidance or support from executive and governance units is needed",
         "Not applicable", "Other, please specify"],
    38: ["Healthcare facility management", "Other healthcare facility team members",
         "National authorities (e.g., ministry of health)", "Not applicable", "Other, please specify"],
    43: ["Collect urine and/or respiratory cultures based on appropriate criteria",
         "Initiate discussions about converting from intravenous to oral formulation",
         "Initiate antibiotic \u201ctime outs\u201d", "Antibiotic allergy assessment",
         "Not applicable", "Other, please specify"],
    54: ["Days of therapy", "Defined daily doses", "Not applicable", "Other, please specify"],
    58: ["Antibiotic use or consumption", "Antibiotic appropriateness (agent, dose, duration)",
         "Time to appropriate antibiotic therapy", "Cost-savings", "In-hospital mortality",
         "Length of stay", "Clostridioides difficile infection rates", "Rehospitalization",
         "Antibiotic-related adverse events", "Antibiotic-related near misses", "Antibiotic costs",
         "Not applicable", "Other, please specify"],
    59: ["Antibiotic consumption", "Antibiotic use", "Antibiotic resistance", "Antibiotic cost",
         "Administrative data", "Not applicable", "Other, please specify"],
}
SIX_A_LABELS = ["Not applicable (no antibiotic stewardship team)",
                "Infectious diseases trained physician(s) or clinician(s) with experience practicing infectious diseases",
                "Other physician(s)",
                "Infectious diseases trained pharmacist(s) or pharmacist(s) with experience practicing infectious diseases",
                "Other clinical pharmacist(s)", "Other staff pharmacist(s)",
                "Infection prevention and control (IPC) physician(s)", "IPC Nurse(s)", "Non-IPC Nurse(s)",
                "Clinical microbiologist(s)", "Information technology specialist(s)",
                "Administrative support", "Other(s)"]

# ---- Scoring rules (index-based) ----
SCORING = {
    4:  {"rule": "count_range", "full": 8, "partial": 1},
    9:  {"rule": "count", "full": 2, "partial": 1},
    18: {"rule": "count", "full": 2, "partial": 1},
    19: {"rule": "count", "full": 2, "partial": 1},
    31: {"rule": "count_range", "full": 4, "partial": 1},
    37: {"rule": "count", "full": 2, "partial": 1},
    38: {"rule": "count", "full": 2, "partial": 1},
    43: {"rule": "count", "full": 2, "partial": 1},
    54: {"rule": "count_any1"},
    58: {"rule": "count", "full": 2, "partial": 1},
    59: {"rule": "count", "full": 2, "partial": 1},
    32: {"rule": "keywords"},
    11: {"rule": "triad"},
    14: {"rule": "triad"},
}
# 0-based index of the "Not applicable" option (excluded from counts)
NA_INDEX = {4: 14, 9: 9, 11: 6, 14: 5, 18: 6, 19: 5, 31: 14, 32: 5,
            37: 7, 38: 3, 43: 4, 54: 2, 58: 11, 59: 5}
# triad membership (0-based) — physician / pharmacist / microbiologist
TRIAD = {
    6:  {"phys": {1}, "pharm": {3, 4, 5}, "micro": {9}, "na": 0},
    11: {"phys": {0}, "pharm": {1, 2, 3}, "micro": {5}, "na": 6},
    14: {"phys": {0}, "pharm": {1, 2, 3}, "micro": {4}, "na": 5},
}
REQUIRED_IDX = {32: {0, 1, 2, 3}}  # first-line, dose, duration, alternative

DOMAIN_ITEMS = {1: range(1, 13), 2: range(13, 26), 3: range(26, 31),
                4: range(31, 52), 5: range(52, 67)}
DOMAIN_TOTALS = {1: 60, 2: 65, 3: 25, 4: 105, 5: 75}
DOMAIN_TITLES = {
    1: "Domain 1: Leadership Commitment & Accountability",
    2: "Domain 2: Resources",
    3: "Domain 3: Education & Training",
    4: "Domain 4: Antibiotic Stewardship Actions",
    5: "Domain 5: Antibiotic Use Tracking, Monitoring, & Reporting",
}
MAX_PER_ITEM = 5.0

# ---------- Language detection ----------
def detect_language(text):
    sample = text[:6000]
    scores = {}
    for code, cfg in LANGS.items():
        s = sum(1 for kw in (cfg["domain_kw"], re.escape(cfg["partial"]), cfg["no"], cfg["yes"])
                if re.search(kw, sample, re.IGNORECASE))
        scores[code] = s
    best = max(scores, key=scores.get)
    if scores[best] >= 3:
        return best
    if HAS_LANGDETECT:
        try:
            code = detect(sample)
            if code in LANGS:
                return code
        except Exception:
            pass
    return best if scores[best] >= 2 else "en"

# ---------- Reading form values by field name ----------
def _decode_radio(v):
    if v is None:
        return None
    s = str(v).lstrip("/").strip()
    return {"0": "yes", "1": "partial", "2": "no"}.get(s)

def _cb_on(v):
    if v is None:
        return False
    return str(v).lstrip("/").strip().lower() not in ("", "off", "none")

def _is_35a_yes(v):
    return v is not None and str(v).lstrip("/").strip() == "0"

def read_by_schema(reader):
    fields = reader.get_fields() or {}

    def fv(name):
        f = fields.get(name)
        return f.get("/V") if f else None

    options, defaults, special = {}, {}, {}
    for n, fld in RADIO_FIELDS.items():
        defaults[n] = _decode_radio(fv(fld))
    for n, flds in CHECKBOX_FIELDS.items():
        labels = CHECKBOX_LABELS[n]
        options[n] = labels
        defaults[n] = [labels[i] for i, fn in enumerate(flds) if _cb_on(fv(fn))]
    special[6] = [i for i, fn in enumerate(SIX_A_FIELDS) if _cb_on(fv(fn))]  # selected indices
    special[35] = sum(1 for fn in THIRTYFIVE_A_FIELDS if _is_35a_yes(fv(fn)))
    return options, defaults, special

def schema_applies(reader):
    try:
        names = set((reader.get_fields() or {}).keys())
    except Exception:
        return False
    return "Assess 1" in names and "D1_4 Check" in names

# ---------- Scoring (index-based) ----------
def _ypn(val):
    return 5.0 if val == "yes" else (2.5 if val == "partial" else 0.0)

def _score_checkbox(num, selected_labels):
    labels = CHECKBOX_LABELS[num]
    idxs = set()
    for l in (selected_labels or []):
        try:
            idxs.add(labels.index(l))
        except ValueError:
            pass
    na = NA_INDEX.get(num)
    real = len([i for i in idxs if i != na])
    rule = SCORING.get(num, {})
    r = rule.get("rule")
    if r in ("count", "count_range"):
        return 5.0 if real >= rule["full"] else (2.5 if real >= rule["partial"] else 0.0)
    if r == "count_any1":
        return 5.0 if real >= 1 else 0.0
    if r == "triad":
        spec = TRIAD[num]
        ok = all(any(i in idxs for i in spec[g]) for g in ("phys", "pharm", "micro"))
        return 5.0 if ok else (2.5 if real >= 1 else 0.0)
    if r == "keywords":
        return 5.0 if REQUIRED_IDX[num].issubset(idxs) else (2.5 if real >= 1 else 0.0)
    return 0.0

def _score_6(indices):
    spec = TRIAD[6]
    idxs = set(indices or [])
    ok = all(any(i in idxs for i in spec[g]) for g in ("phys", "pharm", "micro"))
    real = len([i for i in idxs if i != spec["na"]])
    return 5.0 if ok else (2.5 if real >= 1 else 0.0)

def score_item(num, val):
    t = CANONICAL[num]["type"]
    if t == "ypn":
        return (_ypn(val), MAX_PER_ITEM)
    if t == "table6":
        return (_score_6(val or []), MAX_PER_ITEM)
    if t == "table35":
        n = int(val or 0)
        return (5.0 if n >= 9 else (2.5 if n >= 1 else 0.0), MAX_PER_ITEM)
    return (_score_checkbox(num, val or []), MAX_PER_ITEM)

def score_color(earned, possible):
    if earned is None or not possible:
        return "#9e9e9e"
    ratio = earned / possible
    return "#2e7d32" if ratio >= 0.99 else ("#ef6c00" if ratio >= 0.49 else "#c62828")

# ---------- Question stems (localized display text) ----------
def parse_stems_all(text, cfg):
    if "footer_re" in cfg:
        text = re.sub(cfg["footer_re"], "\n", text, flags=re.DOTALL | re.IGNORECASE)
    text = re.sub(r"[ \t]+", " ", text)
    item_re = re.compile(r"(?:^|\n)\s*(\d{1,3})\.\s+(.+?)(?=(?:\n\s*\d{1,3}\.\s)|\Z)", re.DOTALL)
    yes, partial = cfg["yes"], re.escape(cfg["partial"])
    out = {}
    for m in item_re.finditer(text):
        num = int(m.group(1))
        if not (1 <= num <= 66) or num in out:
            continue
        raw = m.group(2).strip()
        if len(raw) < 8:
            continue
        cuts = [re.search(cfg["select_all"], raw, re.IGNORECASE),
                re.search(cfg["answer_questions"], raw, re.IGNORECASE),
                re.search(rf"{yes}\s+{partial}", raw, re.IGNORECASE),
                re.search(rf"\n\s*{yes}\b", raw, re.IGNORECASE)]
        pos = [c.start() for c in cuts if c]
        cut = min(pos) if pos else len(raw)
        stem = re.sub(r"\s+", " ", raw[:cut]).strip()
        stem = re.sub(rf"\s*\(\s*{cfg['select_all']}\s*\)\s*\??\s*$", "?", stem, flags=re.IGNORECASE)
        if len(stem) >= 5:
            out[num] = f"{num}. {stem}"
    return out

# ---------- Field dump (diagnostic) ----------
def dump_fields(reader):
    rows = []
    try:
        fields = reader.get_fields() or {}
    except Exception:
        fields = {}
    for name, f in fields.items():
        rows.append({"name": str(name), "type": str(f.get("/FT")),
                     "value": str(f.get("/V")), "states": str(f.get("/_States_"))})
    return rows

# ---------- Reactive state ----------
parsed_domains = reactive.value([])
pdf_meta = reactive.value(None)
current_lang = reactive.value("en")
geo_defaults = reactive.value({})
pdf_special = reactive.value({})
field_dump = reactive.value([])
form_locked = reactive.value(True)
reset_counter = reactive.value(0)

def _process_pdf(file_info, lang_choice):
    try:
        path = file_info["datapath"]
        reader = PdfReader(path)
        text = "\n".join((p.extract_text() or "") for p in reader.pages)
        lang = lang_choice if lang_choice and lang_choice != "auto" else detect_language(text)
        current_lang.set(lang)
        cfg = LANGS[lang]

        field_dump.set(dump_fields(reader))
        recognized = schema_applies(reader)

        if not recognized:
            parsed_domains.set([])
            geo_defaults.set({}); pdf_special.set({})
            pdf_meta.set({"name": file_info["name"], "size": file_info["size"],
                          "pages": len(reader.pages), "lang": cfg["name"],
                          "recognized": False, "n_fields": len(field_dump.get())})
            return

        options, defaults, special = read_by_schema(reader)
        geo_defaults.set(defaults)
        pdf_special.set(special)

        stems = parse_stems_all(text, cfg)
        radio_choices = {
            "yes": next((c for c in ["Sí", "Si", "Yes", "Oui", "Sim"]
                         if re.fullmatch(cfg["yes"], c, re.IGNORECASE)), "Yes"),
            "partial": cfg["partial"], "no": cfg["no"]}

        domains, nq = [], 0
        for dnum, items in DOMAIN_ITEMS.items():
            qs = []
            for num in items:
                if num in (6, 35):
                    continue
                meta = CANONICAL[num]
                stem = stems.get(num, f"{num}.")
                if meta["type"] == "ypn":
                    qs.append({"id": f"q_{num}", "number": num, "text": stem, "type": "radio",
                               "options": radio_choices, "default": defaults.get(num)})
                else:
                    qs.append({"id": f"q_{num}", "number": num, "text": stem, "type": "checkbox",
                               "options": CHECKBOX_LABELS[num], "default": defaults.get(num, [])})
                nq += 1
            domains.append({"name": DOMAIN_TITLES[dnum], "questions": qs})
        parsed_domains.set(domains)

        pdf_meta.set({"name": file_info["name"], "size": file_info["size"],
                      "pages": len(reader.pages), "lang": cfg["name"], "recognized": True,
                      "n_fields": len(field_dump.get()), "n_questions": nq})
    except Exception as e:
        import traceback
        pdf_meta.set({"error": f"{e}\n{traceback.format_exc()}"})
        parsed_domains.set([]); geo_defaults.set({}); pdf_special.set({})

@reactive.effect
@reactive.event(input.pdf_file)
def _on_upload():
    f = input.pdf_file()
    if not f:
        return
    try:
        lang_choice = input.lang_override()
    except Exception:
        lang_choice = "auto"
    _process_pdf(f[0], lang_choice)

@reactive.effect
@reactive.event(input.lang_override)
def _on_lang_change():
    f = input.pdf_file()
    if not f:
        return
    try:
        lang_choice = input.lang_override()
    except Exception:
        lang_choice = "auto"
    _process_pdf(f[0], lang_choice)

@reactive.effect
@reactive.event(input.toggle_lock)
def _on_toggle_lock():
    form_locked.set(not form_locked.get())

@reactive.effect
@reactive.event(input.reset_form)
def _on_reset():
    reset_counter.set(reset_counter.get() + 1)

@reactive.effect
def _update_lock_button_label():
    cfg = LANGS[current_lang.get()]
    core_ui.update_action_button(
        "toggle_lock", label=cfg["ui_unlock_btn"] if form_locked.get() else cfg["ui_lock_btn"])

@reactive.effect
async def _push_lock_state():
    locked = form_locked.get()
    _ = parsed_domains.get(); _ = reset_counter.get()
    session = get_current_session()
    if session is not None:
        await session.send_custom_message("set_form_lock", {"locked": locked})

# ---------- Scoring calc ----------
@reactive.calc
def all_scores():
    special = pdf_special.get()
    defs = geo_defaults.get()
    per = {}
    for num in CANONICAL:
        if num == 6:
            val = special.get(6, [])
        elif num == 35:
            val = special.get(35, 0)
        else:
            try:
                val = input[f"q_{num}"]()
            except Exception:
                val = None
            if val is None:
                val = defs.get(num)
        per[num] = score_item(num, val)
    domains, te, tp = [], 0.0, 0.0
    for dnum, items in DOMAIN_ITEMS.items():
        de = sum(per[n][0] for n in items if per.get(n) and per[n][0] is not None)
        dp = DOMAIN_TOTALS[dnum]
        domains.append((dnum, DOMAIN_TITLES[dnum], de, dp))
        te += de; tp += dp
    return per, domains, te, tp

@reactive.effect
async def _push_badges():
    _ = parsed_domains.get()   # re-run when the form is (re)rendered
    _ = reset_counter.get()    # re-run after a reset
    per, _d, _e, _t = all_scores()
    session = get_current_session()
    if session is None:
        return
    items = {}
    for num in CANONICAL:
        if num in (6, 35):
            continue
        e, p = per.get(num, (None, None))
        items[f"badge_q_{num}"] = {"html": "—" if e is None else f"{e:g} / {p:g}",
                                   "bg": score_color(e, p)}
    await session.send_custom_message("update_badges", {"items": items})
# ---------- UI: sidebar ----------
with ui.sidebar():
    @render.ui
    def sidebar_title():
        return core_ui.h4(LANGS[current_lang.get()]["ui_upload"])

    ui.input_file("pdf_file", "PDF", accept=[".pdf"], multiple=False)
    ui.input_select("lang_override", "Language / Idioma / Langue / Idioma:",
                    choices={"auto": "Auto-detect", **{c: v["name"] for c, v in LANGS.items()}},
                    selected="auto")

    @render.ui
    def sidebar_desc():
        return core_ui.markdown(LANGS[current_lang.get()]["ui_desc"])

    ui.input_action_button("toggle_lock", "🔒 Unlock form", class_="btn-warning", width="100%")
    ui.input_action_button("reset_form", "↺ Reset to PDF values", class_="btn-secondary", width="100%")

    @render.ui
    def lock_status():
        cfg = LANGS[current_lang.get()]
        msg, color = ((cfg["ui_locked_msg"], "#c62828") if form_locked.get()
                      else (cfg["ui_unlocked_msg"], "#2e7d32"))
        return core_ui.p(msg, style=f"color:{color}; font-weight:600; margin-top:8px;")

# ---------- UI: status ----------
with ui.card():
    @render.ui
    def status_header():
        return core_ui.card_header(LANGS[current_lang.get()]["ui_status"])

    @render.ui
    def pdf_status():
        meta = pdf_meta.get()
        cfg = LANGS[current_lang.get()]
        if meta is None:
            return core_ui.p(cfg["ui_no_pdf"], class_="text-muted")
        if "error" in meta:
            return core_ui.tags.pre(meta["error"], style="color:red; white-space:pre-wrap;")
        if not meta.get("recognized"):
            return core_ui.TagList(
                core_ui.p(core_ui.strong("File: "), meta["name"], " | ",
                          core_ui.strong("Pages: "), str(meta["pages"])),
                core_ui.p("⚠️ This PDF was not recognized as the standard G-ASET fillable form "
                          f"(found {meta.get('n_fields', 0)} fields, but not the expected names). "
                          "Scoring is unavailable. See the field map below.",
                          style="color:#c62828; font-weight:600;"))
        return core_ui.TagList(
            core_ui.p(core_ui.strong("File: "), meta["name"], " | ",
                      core_ui.strong("Pages: "), str(meta["pages"]), " | ",
                      core_ui.strong("Size: "), f"{meta['size']:,} bytes"),
            core_ui.p(cfg["ui_parsed"].format(nq=meta.get("n_questions", 0), lang=meta["lang"])),
            core_ui.p(f"📝 {meta.get('n_fields', 0)} AcroForm fields read deterministically by name."))

# ---------- Dynamic form ----------
core_ui.div(id="dynamic_form_container")

@reactive.effect
def _render_dynamic_form():
    domains = parsed_domains.get()
    _ = reset_counter.get()
    cfg = LANGS[current_lang.get()]
    ui.remove_ui(selector="#dynamic_form_container > *", multiple=True)
    if not domains:
        ui.insert_ui(core_ui.p(cfg["ui_upload_prompt"], class_="text-muted p-3"),
                     selector="#dynamic_form_container", where="beforeEnd")
        return
    for d in domains:
        items = []
        for q in d["questions"]:
            badge_id = f"badge_{q['id']}"
            label_html = core_ui.HTML(
                f'{q["text"]} <span id="{badge_id}" style="display:inline-block;margin-left:8px;'
                f'padding:2px 8px;border-radius:10px;background:#9e9e9e;color:white;font-size:0.80em;'
                f'font-weight:600;vertical-align:middle;">—</span>')
            if q["type"] == "radio":
                items.append(core_ui.input_radio_buttons(
                    q["id"], label_html, choices=q["options"], selected=q["default"], inline=True))
            else:
                default = q["default"] if isinstance(q["default"], list) else []
                items.append(core_ui.input_checkbox_group(
                    q["id"], label_html, choices=q["options"], selected=default))
        ui.insert_ui(core_ui.card(core_ui.card_header(d["name"]), *items),
                     selector="#dynamic_form_container", where="beforeEnd")

# ---------- Scores summary ----------
with ui.card():
    @render.ui
    def scores_header():
        return core_ui.card_header(LANGS[current_lang.get()]["ui_scores"])

    @render.ui
    def score_table():
        per, domains, te, tp = all_scores()
        cfg = LANGS[current_lang.get()]
        if not parsed_domains.get():
            return core_ui.p(cfg["ui_scores_later"], class_="text-muted")
        rows = []
        for _, name, de, dp in domains:
            pct = (de / dp * 100) if dp else 0
            rows.append(core_ui.tags.tr(
                core_ui.tags.td(name),
                core_ui.tags.td(f"{de:g} / {dp}", style="text-align:center;"),
                core_ui.tags.td(f"{pct:.1f}%", style="text-align:center;")))
        overall = (te / tp * 100) if tp else 0
        rows.append(core_ui.tags.tr(
            core_ui.tags.td(core_ui.strong(cfg["ui_overall"])),
            core_ui.tags.td(core_ui.strong(f"{te:g} / {tp:g}"), style="text-align:center;"),
            core_ui.tags.td(core_ui.strong(f"{overall:.1f}%"), style="text-align:center;"),
            style="background:#e8f4f8;"))
        return core_ui.tags.table(
            core_ui.tags.thead(core_ui.tags.tr(
                core_ui.tags.th(cfg["ui_domain"]),
                core_ui.tags.th(cfg["ui_score"], style="text-align:center;"),
                core_ui.tags.th(cfg["ui_pct"], style="text-align:center;"))),
            core_ui.tags.tbody(*rows),
            class_="table table-striped table-bordered")

    @render.download(label="⬇️ Download scores (CSV)", filename="gaset_scores.csv")
    def download_scores():
        per, domains, te, tp = all_scores()
        buf = io.StringIO(); w = csv.writer(buf)
        w.writerow(["Item", "Earned", "Possible"])
        for num in sorted(CANONICAL):
            e, p = per.get(num, (None, None))
            w.writerow([num, "" if e is None else f"{e:g}", f"{p:g}"])
        w.writerow([])
        w.writerow(["Domain", "Earned", "Possible", "Percentage"])
        for _, name, de, dp in domains:
            w.writerow([name, f"{de:g}", dp, f"{(de/dp*100 if dp else 0):.1f}%"])
        w.writerow(["OVERALL", f"{te:g}", f"{tp:g}", f"{(te/tp*100 if tp else 0):.1f}%"])
        yield buf.getvalue()
        
# ---------- Table items 6A / 35A ----------
with ui.card():
    ui.card_header("🧩 Table items scored from the PDF (6A, 35A)")

    @render.ui
    def special_view():
        special = pdf_special.get()
        per, _, _, _ = all_scores()
        if not parsed_domains.get():
            return core_ui.p("Upload a recognized G-ASET PDF to see these.", class_="text-muted")
        e6, _ = per.get(6, (None, None))
        e35, _ = per.get(35, (None, None))
        role_idx = special.get(6, [])
        roles = [SIX_A_LABELS[i] for i in role_idx]
        n35 = special.get(35, 0)
        return core_ui.TagList(
            core_ui.p(core_ui.strong("Item 6A "), f"→ {e6:g} / 5" if e6 is not None else "—",
                      core_ui.tags.br(),
                      core_ui.tags.small(f"Selected roles: {', '.join(roles) if roles else 'none'}")),
            core_ui.p(core_ui.strong("Item 35A "), f"→ {e35:g} / 5" if e35 is not None else "—",
                      core_ui.tags.br(),
                      core_ui.tags.small(f"'Yes' responses in 35A column: {n35} / 18")))

# ---------- Field dump ----------
with ui.card():
    ui.card_header("🔧 AcroForm field map (diagnostic)")

    @render.download(label="⬇️ Download field map (CSV)", filename="gaset_field_dump.csv")
    def download_field_dump():
        rows = field_dump.get()
        buf = io.StringIO(); w = csv.writer(buf)
        w.writerow(["name", "type", "value", "states"])
        for r in rows:
            w.writerow([r["name"], r["type"], r["value"], r["states"]])
        yield buf.getvalue()

    @render.ui
    def field_dump_view():
        rows = field_dump.get()
        if not rows:
            return core_ui.p("Upload a PDF to list its form fields.", class_="text-muted")
        body = [core_ui.tags.tr(core_ui.tags.td(r["name"]), core_ui.tags.td(r["type"]),
                                core_ui.tags.td(r["value"]), core_ui.tags.td(r["states"]))
                for r in rows]
        return core_ui.tags.details(
            core_ui.tags.summary(f"Show {len(rows)} fields"),
            core_ui.tags.table(
                core_ui.tags.thead(core_ui.tags.tr(
                    core_ui.tags.th("Field name"), core_ui.tags.th("Type"),
                    core_ui.tags.th("Value"), core_ui.tags.th("States"))),
                core_ui.tags.tbody(*body),
                class_="table table-sm table-striped", style="font-size:0.8em;"))