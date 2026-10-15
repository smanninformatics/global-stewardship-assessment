# G-ASET Multilingual PDF Assessment — deterministic field-name mapping
# Tabs: Assessment | Scores | Action Plan | Trends (multi-assessment time series) | Diagnostics
# Runs fully in-browser (Pyodide / shinylive / GitHub Pages). Pure-Python deps only.
#
# shinylive requirements: pypdf   (langdetect optional)

import re
import io
import csv
import html as _html
from datetime import date, timedelta
from pathlib import Path

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
NA_INDEX = {4: 14, 9: 9, 11: 6, 14: 5, 18: 6, 19: 5, 31: 14, 32: 5,
            37: 7, 38: 3, 43: 4, 54: 2, 58: 11, 59: 5}
TRIAD = {
    6:  {"phys": {1}, "pharm": {3, 4, 5}, "micro": {9}, "na": 0},
    11: {"phys": {0}, "pharm": {1, 2, 3}, "micro": {5}, "na": 6},
    14: {"phys": {0}, "pharm": {1, 2, 3}, "micro": {4}, "na": 5},
}
REQUIRED_IDX = {32: {0, 1, 2, 3}}

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
DOMAIN_SHORT = {1: "D1 Leadership", 2: "D2 Resources", 3: "D3 Education",
                4: "D4 Actions", 5: "D5 Tracking"}
ITEM_DOMAIN = {n: d for d, items in DOMAIN_ITEMS.items() for n in items}
ITEM_FALLBACK = {6: "6. Antibiotic stewardship team composition (6A)",
                 35: "35. Stewardship interventions currently performed (35A)"}
MAX_PER_ITEM = 5.0

# ---------- Action plan engine (item-aware) ----------
PHASES = [("short", "Phase 1 — Quick wins (0–3 months)"),
          ("medium", "Phase 2 — Build capacity (3–12 months)"),
          ("long", "Phase 3 — Advance & sustain (12+ months)")]
PRIO_RANK = {"high": 0, "med": 1, "medium": 1, "low": 2}
STATUS_LABEL = {"met": "✅ Met", "partial": "🟠 Partial", "not_met": "🔴 Not met"}

def _rec_title(body):
    m = re.search(r"^###\s*(.+)$", body, re.MULTILINE)
    return m.group(1).strip() if m else "(untitled)"

def parse_action_template(text):
    meta = {"tiers": [("foundational", 0, 40), ("developing", 40, 70), ("advanced", 70, 100.01)],
            "domain_priority": [1, 2, 4, 5, 3]}
    m = re.search(r"@@meta\s*(.*?)@@endmeta", text, re.DOTALL)
    if m:
        for line in m.group(1).splitlines():
            line = line.strip()
            if line.startswith("tiers:"):
                tiers = []
                for part in line[6:].split("|"):
                    mm = re.match(r"\s*(\w+)\s+(\d+)-(\d+)", part)
                    if mm:
                        hi = float(mm.group(3)) + (0.01 if mm.group(3) == "100" else 0)
                        tiers.append((mm.group(1), float(mm.group(2)), hi))
                if tiers:
                    meta["tiers"] = tiers
            elif line.startswith("domain_priority:"):
                nums = [int(x) for x in re.findall(r"\d+", line)]
                if nums:
                    meta["domain_priority"] = nums
        text = text[m.end():]
    recs = []
    for part in re.split(r"(?m)^@@rec\s+", text)[1:]:
        header, _, body = part.partition("\n")
        hm = dict(re.findall(r"(\w+)=(\S+)", header))
        body = re.sub(r"<!--.*?-->", "", body, flags=re.DOTALL).strip()   # drop authoring comments
        recs.append({
            "id": hm.get("id", ""),
            "domain": int(hm.get("domain", "0")),
            "tier": [t for t in hm.get("tier", "").split(",") if t],
            "when": hm.get("when", "short"),
            "priority": hm.get("priority", "med"),
            "show_if": hm.get("show_if", ""),
            "met_if": hm.get("met_if", ""),
            "items": [int(x) for x in re.findall(r"\d+", hm.get("items", ""))],
            "title": _rec_title(body),
            "body": body,
        })
    return meta, recs

def _tier_of(pct, tiers):
    for name, lo, hi in tiers:
        if lo <= pct < hi:
            return name
    return tiers[-1][0]

def _eval_and(expr, env):
    for term in expr.split("&"):
        mm = re.match(r"\s*([\w.]+)\s*(==|!=|<=|>=|<|>)\s*(.+?)\s*$", term)
        if not mm:
            return False
        left, op, rhs = env.get(mm.group(1)), mm.group(2), mm.group(3)
        if left is None:
            return False
        try:
            l, r, num = float(left), float(rhs), True
        except (ValueError, TypeError):
            l, r, num = str(left), str(rhs), False
        ok = {"==": l == r, "!=": l != r,
              "<": num and l < r, "<=": num and l <= r,
              ">": num and l > r, ">=": num and l >= r}[op]
        if not ok:
            return False
    return True

def _eval_condition(expr, env):
    """Supports '&' (and) and '|' (or); '&' binds tighter."""
    if not expr:
        return True
    return any(_eval_and(alt, env) for alt in expr.split("|"))

def _item_status(n, per_item):
    e, p = per_item.get(n, (None, MAX_PER_ITEM))
    e, p = (e or 0.0), (p or MAX_PER_ITEM)
    if e >= p:
        return "met", e, p
    if e > 0:
        return "partial", e, p
    return "not_met", e, p

def _focus_domains(dinfo, dprio):
    order = {d: i for i, d in enumerate(dprio)}
    def key(d):
        info = dinfo[d]
        enabler = d in (1, 2) and info["tier"] == "foundational"
        return (0 if enabler else 1, info["pct"], order.get(d, 99))
    return sorted(dinfo.keys(), key=key)

def _rationale(d, info):
    if d in (1, 2) and info["tier"] == "foundational":
        return "foundational enabler — must be in place to sustain gains elsewhere"
    if info["tier"] == "foundational":
        return "largest gap; establish core structures first"
    if info["tier"] == "developing":
        return "partial capability — consolidate and expand"
    return "advanced — focus on sustaining and refining"

def evaluate_recommendations(per_item, domain_rows, ctx, template_text):
    """Decide, for every template rule, whether it is shown, already in place, or not applicable."""
    meta, recs = parse_action_template(template_text)
    tiers, dprio = meta["tiers"], meta["domain_priority"]
    rank = {name: i for i, (name, _lo, _hi) in enumerate(tiers)}

    dinfo, oe, op = {}, 0.0, 0.0
    for dnum, name, de, dp in domain_rows:
        pct = de / dp * 100 if dp else 0
        dinfo[dnum] = {"pct": pct, "tier": _tier_of(pct, tiers),
                       "name": name, "earned": de, "poss": dp}
        oe += de; op += dp
    overall_pct = oe / op * 100 if op else 0
    overall_tier = _tier_of(overall_pct, tiers)

    env = {f"item{n}": (0 if e is None else e) for n, (e, _p) in per_item.items()}
    env.update({f"domain{d}": i["pct"] for d, i in dinfo.items()})
    env["overall"] = overall_pct
    env.update({f"ctx.{k}": v for k, v in (ctx or {}).items()})

    shown, in_place, skipped = [], [], []
    for base in recs:
        cur_tier = overall_tier if base["domain"] == 0 else dinfo.get(base["domain"], {}).get("tier")
        r = dict(base, cur_tier=cur_tier, carried=False, partial=False,
                 statuses=[(n, *_item_status(n, per_item)) for n in base["items"]])

        # 1) Maturity-tier eligibility
        rec_ranks = [rank[t] for t in r["tier"] if t in rank]
        if rec_ranks and cur_tier in rank:
            if r["items"]:
                # Item-linked: tier is a FLOOR — show documented gaps even at higher maturity
                if rank[cur_tier] < min(rec_ranks):
                    skipped.append((r, f"domain is '{cur_tier}'; rule starts at '{r['tier'][0]}'"))
                    continue
                r["carried"] = rank[cur_tier] > max(rec_ranks)
            elif cur_tier not in r["tier"]:
                skipped.append((r, f"domain tier '{cur_tier}' not targeted ({', '.join(r['tier'])})"))
                continue

        # 2) Context / explicit eligibility
        if not _eval_condition(r["show_if"], env):
            skipped.append((r, f"show_if not satisfied: {r['show_if']}"))
            continue

        # 3) Already in place?
        if r["met_if"]:
            met = _eval_condition(r["met_if"], env)
        elif r["statuses"]:
            met = all(st == "met" for _n, st, _e, _p in r["statuses"])
        else:
            met = False
        if met:
            in_place.append(r)
            continue

        r["partial"] = any(st != "not_met" for _n, st, _e, _p in r["statuses"])
        shown.append(r)

    return {"dinfo": dinfo, "oe": oe, "op": op, "overall_pct": overall_pct,
            "overall_tier": overall_tier, "dprio": dprio,
            "shown": shown, "in_place": in_place, "skipped": skipped}

def _status_line(r):
    if not r["statuses"]:
        return ""
    return "> **Current G‑ASET status:** " + " · ".join(
        f"Item {n} {STATUS_LABEL[st]} ({e:g}/{p:g})" for n, st, e, p in r["statuses"])

def _render_rec(r, dinfo):
    dom = dinfo.get(r["domain"], {}).get("name", "Cross-cutting") if r["domain"] else "Cross-cutting"
    flags = [dom.split(":")[0], r["priority"].upper()]
    if r["partial"]:
        flags.append("PARTIALLY IN PLACE")
    if r["carried"]:
        flags.append("EARLIER-STAGE GAP")
    title = f"Strengthen: {r['title']}" if r["partial"] else r["title"]
    _first, _, rest = r["body"].partition("\n")
    parts = [f"### `[{' · '.join(flags)}]` {title}"]
    status = _status_line(r)
    if status:
        parts.append(status)
    if rest.strip():
        parts.append(rest.strip())
    return "\n\n".join(parts) + "\n"

def build_action_plan(ev, facility=""):
    dinfo, oe, op = ev["dinfo"], ev["oe"], ev["op"]
    overall_pct, overall_tier = ev["overall_pct"], ev["overall_tier"]
    focus = _focus_domains(dinfo, ev["dprio"])
    dorder = {d: i for i, d in enumerate(focus)}

    out = [f"# G-ASET Antibiotic Stewardship Action Plan" + (f" — {facility}" if facility else ""),
           f"*Generated {date.today().isoformat()}. **Draft decision‑support output for SME review** — "
           f"not a substitute for clinical judgment or local guideline alignment.*\n",
           "## Summary",
           f"- **Overall:** {oe:g} / {op:g} ({overall_pct:.0f}%) — **{overall_tier.title()}**\n",
           "| Domain | Score | % | Tier |", "|---|---|---|---|"]
    for d in sorted(dinfo):
        i = dinfo[d]
        out.append(f"| {i['name']} | {i['earned']:g}/{i['poss']:g} | {i['pct']:.0f}% | {i['tier'].title()} |")
    out.append("")

    out.append("## Recommended focus sequence")
    for n, d in enumerate(focus, 1):
        i = dinfo[d]
        out.append(f"{n}. **{i['name']}** ({i['pct']:.0f}%, {i['tier'].title()}) — {_rationale(d, i)}")
    out.append("")

    if ev["shown"]:
        out.append("*Each recommendation shows the current G‑ASET responses for the items it addresses. "
                   "🟠 Partial = strengthen what exists · 🔴 Not met = new action. "
                   "Practices already fully in place are listed at the end and not repeated.*\n")

    for phase_key, phase_title in PHASES:
        items = [r for r in ev["shown"] if r["when"] == phase_key]
        if not items:
            continue
        items.sort(key=lambda r: (PRIO_RANK.get(r["priority"], 1),
                                  dorder.get(r["domain"], 99), r["id"]))
        out.append(f"## {phase_title}")
        out.extend(_render_rec(r, dinfo) for r in items)

    if ev["in_place"]:
        out.append("## ✅ Already in place — maintain")
        out.append("*These recommendations were not repeated because the G‑ASET responses show "
                   "the underlying practices are already established.*\n")
        for r in sorted(ev["in_place"], key=lambda r: (r["domain"], r["id"])):
            dom = f"D{r['domain']}" if r["domain"] else "Cross-cutting"
            basis = ", ".join(f"item {n}" for n, *_ in r["statuses"]) or r["met_if"]
            out.append(f"- **{r['title']}** ({dom}) — evidence: {basis}")
        out.append("")

    if not ev["shown"] and not ev["in_place"]:
        out.append("_No recommendations matched. Check the template's tier/context bindings._")
    return "\n".join(out)

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
    special[6] = [i for i, fn in enumerate(SIX_A_FIELDS) if _cb_on(fv(fn))]
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

def score_values(values, special):
    """Score every canonical item from a {num: value} dict + special (6A/35A) data."""
    per = {}
    for num in CANONICAL:
        if num == 6:
            val = special.get(6, [])
        elif num == 35:
            val = special.get(35, 0)
        else:
            val = values.get(num)
        per[num] = score_item(num, val)
    return per

def aggregate_scores(per):
    """Roll per-item scores up into domain rows + overall totals."""
    domains, te, tp = [], 0.0, 0.0
    for dnum, items in DOMAIN_ITEMS.items():
        de = sum((per.get(n, (None, 0))[0] or 0.0) for n in items)
        dp = DOMAIN_TOTALS[dnum]
        domains.append((dnum, DOMAIN_TITLES[dnum], de, dp))
        te += de; tp += dp
    return domains, te, tp

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

# =====================================================================
# ---------- Time-series helpers (Trends tab) ----------
# =====================================================================
TREND_STABLE_PP = 2.0     # |slope| below this (pp/year) is reported as "stable"
TARGET_PCT = 80.0         # "green" threshold used for projections
SERIES_COLORS = {1: "#0072B2", 2: "#E69F00", 3: "#009E73", 4: "#CC79A7",
                 5: "#56B4E9", "overall": "#000000"}   # Okabe-Ito (color-blind safe)

_DATE_PATTERNS = [
    (re.compile(r"(20\d{2})[-_.](0[1-9]|1[0-2])[-_.](0[1-9]|[12]\d|3[01])"), True),
    (re.compile(r"(?<!\d)(20\d{2})(0[1-9]|1[0-2])(0[1-9]|[12]\d|3[01])(?!\d)"), True),
    (re.compile(r"(20\d{2})[-_.](0[1-9]|1[0-2])(?![-_.]?\d)"), False),
]

def date_from_filename(name):
    for pat, has_day in _DATE_PATTERNS:
        m = pat.search(name)
        if m:
            try:
                return date(int(m.group(1)), int(m.group(2)),
                            int(m.group(3)) if has_day else 1)
            except ValueError:
                continue
    return None

def date_from_pdf_metadata(reader):
    """Use the PDF's /ModDate (when the filled form was last saved)."""
    try:
        meta = reader.metadata or {}
        raw = str(meta.get("/ModDate") or "")
        m = re.search(r"(\d{4})(\d{2})(\d{2})", raw)
        if m:
            return date(int(m.group(1)), int(m.group(2)), int(m.group(3)))
    except Exception:
        pass
    return None

def parse_scores_csv(path):
    """Read a gaset_scores.csv exported from the Scores tab (item-level section)."""
    with open(path, newline="", encoding="utf-8-sig") as fh:
        rows = list(csv.reader(fh))
    if not rows or [c.strip().lower() for c in rows[0][:3]] != ["item", "earned", "possible"]:
        raise ValueError("Not a G-ASET scores export (expected header 'Item, Earned, Possible').")
    per = {}
    for row in rows[1:]:
        if not row or not row[0].strip():
            break
        try:
            num = int(row[0])
        except ValueError:
            break
        if num not in CANONICAL:
            continue
        e = float(row[1]) if len(row) > 1 and row[1].strip() else None
        p = float(row[2]) if len(row) > 2 and row[2].strip() else MAX_PER_ITEM
        per[num] = (e, p)
    for num in CANONICAL:
        per.setdefault(num, (None, MAX_PER_ITEM))
    return per

def slope_per_year(dates, ys):
    """Ordinary least-squares slope in percentage points per year."""
    if len(dates) < 2:
        return None
    t0 = min(dates)
    xs = [(d - t0).days / 365.25 for d in dates]
    mx, my = sum(xs) / len(xs), sum(ys) / len(ys)
    sxx = sum((x - mx) ** 2 for x in xs)
    if sxx == 0:
        return None
    return sum((x - mx) * (y - my) for x, y in zip(xs, ys)) / sxx

def trend_direction(slope):
    if slope is None:
        return "—"
    if slope > TREND_STABLE_PP:
        return "▲ Improving"
    if slope < -TREND_STABLE_PP:
        return "▼ Declining"
    return "► Stable"

def project_target_date(last_date, last_pct, slope, target=TARGET_PCT):
    if last_pct > target:
        return "Reached"
    if slope is None:
        return "—"
    if slope <= 0:
        return "Not on track"
    years = (target - last_pct) / slope
    if years > 10:
        return "> 10 years"
    return (last_date + timedelta(days=round(years * 365.25))).isoformat()

def trend_summary(pts):
    dates = [p["date"] for p in pts]
    rows = []
    for k in list(DOMAIN_ITEMS) + ["overall"]:
        ys = [p["overall"] if k == "overall" else p["dpct"][k] for p in pts]
        slope = slope_per_year(dates, ys)
        rows.append({
            "key": k,
            "name": "OVERALL" if k == "overall" else DOMAIN_TITLES[k],
            "baseline": ys[0], "latest": ys[-1],
            "d_base": ys[-1] - ys[0],
            "d_prev": (ys[-1] - ys[-2]) if len(ys) > 1 else None,
            "slope": slope, "direction": trend_direction(slope),
            "projection": project_target_date(dates[-1], ys[-1], slope),
        })
    return rows

def item_changes(prev, last):
    up, down = [], []
    for n in sorted(CANONICAL):
        a = prev["per"].get(n, (None, 0))[0] or 0.0
        b = last["per"].get(n, (None, 0))[0] or 0.0
        if b > a:
            up.append((n, a, b))
        elif b < a:
            down.append((n, a, b))
    return up, down

def band_color(pct):
    """≤50% red · 51–80% yellow · >80% green."""
    if pct > 80:
        return "#2e7d32"
    if pct > 50:
        return "#f9a825"
    return "#c62828"

def band_text_color(pct):
    return "#212121" if 50 < pct <= 80 else "#ffffff"

def svg_trend_chart(pts, show_domains=True, width=900, height=420):
    """Dependency-free SVG line chart of domain/overall % over time."""
    esc = _html.escape
    L, R, T, B = 55, 175, 20, 80
    pw, ph = width - L - R, height - T - B
    dates = [p["date"] for p in pts]
    d0, d1 = min(dates), max(dates)
    span = (d1 - d0).days

    def X(d):
        return L + pw / 2 if span == 0 else L + (d - d0).days / span * pw

    def Y(v):
        return T + ph * (1 - max(0.0, min(100.0, v)) / 100)

    s = [f'<svg viewBox="0 0 {width} {height}" width="100%" xmlns="http://www.w3.org/2000/svg" '
         f'style="max-width:{width}px;font-family:system-ui,-apple-system,Segoe UI,sans-serif;'
         f'font-size:12px;" role="img" aria-label="G-ASET score trends over time">']

    # Traffic-light bands
    for lo, hi, col in ((0, 50, "#c62828"), (50, 80, "#f9a825"), (80, 100, "#2e7d32")):
        s.append(f'<rect x="{L}" y="{Y(hi):.1f}" width="{pw}" height="{Y(lo) - Y(hi):.1f}" '
                 f'fill="{col}" fill-opacity="0.08"/>')
    # Gridlines + y labels
    for v in range(0, 101, 20):
        y = Y(v)
        s.append(f'<line x1="{L}" y1="{y:.1f}" x2="{L + pw}" y2="{y:.1f}" stroke="#e0e0e0"/>')
        s.append(f'<text x="{L - 8}" y="{y + 4:.1f}" text-anchor="end" fill="#555">{v}%</text>')
    for v in (50, 80):
        s.append(f'<line x1="{L}" y1="{Y(v):.1f}" x2="{L + pw}" y2="{Y(v):.1f}" '
                 f'stroke="#888" stroke-dasharray="4 3"/>')
    # Axes
    s.append(f'<line x1="{L}" y1="{T}" x2="{L}" y2="{T + ph}" stroke="#555"/>')
    s.append(f'<line x1="{L}" y1="{T + ph}" x2="{L + pw}" y2="{T + ph}" stroke="#555"/>')
    s.append(f'<text x="14" y="{T + ph / 2:.1f}" text-anchor="middle" fill="#333" '
             f'transform="rotate(-90 14 {T + ph / 2:.1f})">Score (%)</text>')

    # X ticks (one per distinct assessment date)
    uniq = sorted(set(dates))
    rotate = len(uniq) > 5
    for d in uniq:
        x = X(d)
        s.append(f'<line x1="{x:.1f}" y1="{T + ph}" x2="{x:.1f}" y2="{T + ph + 5}" stroke="#555"/>')
        if rotate:
            ty = T + ph + 18
            s.append(f'<text x="{x:.1f}" y="{ty}" text-anchor="end" fill="#333" '
                     f'transform="rotate(-35 {x:.1f} {ty})">{d.isoformat()}</text>')
        else:
            s.append(f'<text x="{x:.1f}" y="{T + ph + 20}" text-anchor="middle" fill="#333">'
                     f'{d.isoformat()}</text>')
    s.append(f'<text x="{L + pw / 2:.1f}" y="{height - 8}" text-anchor="middle" fill="#333">'
             f'Assessment date</text>')

    # Series
    keys = (list(DOMAIN_ITEMS) if show_domains else []) + ["overall"]
    for k in keys:
        is_o = k == "overall"
        col = SERIES_COLORS[k]
        name = "Overall" if is_o else DOMAIN_SHORT[k]
        xy = [(X(p["date"]), Y(p["overall"] if is_o else p["dpct"][k]),
               p["overall"] if is_o else p["dpct"][k], p) for p in pts]
        if len(xy) > 1:
            path = " ".join(f"{x:.1f},{y:.1f}" for x, y, _, _ in xy)
            width_attr = "3.5" if is_o else "2"
            opacity = "1" if is_o else "0.85"
            s.append(f'<polyline points="{path}" fill="none" stroke="{col}" '
                     f'stroke-width="{width_attr}" stroke-opacity="{opacity}"/>')
        for x, y, v, p in xy:
            tip = esc(f"{name}\n{p['date'].isoformat()} — {p['label']}\n{v:.1f}%")
            s.append(f'<circle cx="{x:.1f}" cy="{y:.1f}" r="{5 if is_o else 4}" fill="{col}" '
                     f'stroke="white" stroke-width="1.5"><title>{tip}</title></circle>')

    # Legend
    lx, ly = L + pw + 20, T + 10
    for i, k in enumerate(keys):
        name = "Overall" if k == "overall" else DOMAIN_SHORT[k]
        y = ly + i * 22
        s.append(f'<line x1="{lx}" y1="{y}" x2="{lx + 22}" y2="{y}" stroke="{SERIES_COLORS[k]}" '
                 f'stroke-width="{3.5 if k == "overall" else 2}"/>')
        s.append(f'<circle cx="{lx + 11}" cy="{y}" r="4" fill="{SERIES_COLORS[k]}"/>')
        s.append(f'<text x="{lx + 30}" y="{y + 4}" fill="#222">{esc(name)}</text>')
    s.append("</svg>")
    return "".join(s)

def _item_label(n, stems, max_len=110):
    txt = stems.get(n) or ITEM_FALLBACK.get(n, f"Item {n}")
    return txt if len(txt) <= max_len else txt[:max_len - 1] + "…"

def _delta_span(v):
    if v is None:
        return "—"
    col = "#2e7d32" if v > 0.05 else ("#c62828" if v < -0.05 else "#555")
    return core_ui.span(f"{v:+.1f} pp", style=f"color:{col};font-weight:600;")

def _pct_cell(pct, title=""):
    return core_ui.tags.td(
        f"{pct:.0f}%", title=title,
        style=(f"background:{band_color(pct)};color:{band_text_color(pct)};text-align:center;"
               f"font-weight:600;-webkit-print-color-adjust:exact;print-color-adjust:exact;"))

# ---------- Action plan template ----------
try:
    APP_DIR = Path(__file__).resolve().parent
except NameError:
    APP_DIR = Path.cwd()

TEMPLATE_PATH = APP_DIR / "ga_action_plan.md"

_FALLBACK_TEMPLATE = """@@meta
tiers: foundational 0-40 | developing 40-70 | advanced 70-100
domain_priority: 1 2 4 5 3
@@endmeta

@@rec id=FALLBACK domain=0 when=short priority=high
### Template file not found
- `ga_action_plan.md` was not bundled with the app. Add it to the app folder.
"""

def load_action_template():
    try:
        return TEMPLATE_PATH.read_text(encoding="utf-8")
    except Exception:
        return _FALLBACK_TEMPLATE

ACTION_PLAN_TEMPLATE = load_action_template()

# =====================================================================
# ---------- Reactive state ----------
# =====================================================================
parsed_domains = reactive.value([])
pdf_meta = reactive.value(None)
current_lang = reactive.value("en")
geo_defaults = reactive.value({})
pdf_special = reactive.value({})
field_dump = reactive.value([])
form_locked = reactive.value(True)
reset_counter = reactive.value(0)
item_stems = reactive.value({})          # {item_num: localized stem} from the sidebar PDF

ts_records = reactive.value([])          # assessments uploaded on the Trends tab
_ts_uid = {"n": 0}                       # per-session id counter for date inputs

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
        item_stems.set(stems)
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

def _load_trend_file(fi):
    """Score one uploaded file (PDF or scores CSV) for the Trends tab."""
    _ts_uid["n"] += 1
    rec = {"uid": _ts_uid["n"], "name": fi["name"], "size": fi.get("size", 0),
           "ok": False, "error": "", "date": None, "date_source": "", "per": {}, "overall": 0.0}
    try:
        reader = None
        if fi["name"].lower().endswith(".csv"):
            per = parse_scores_csv(fi["datapath"])
        else:
            reader = PdfReader(fi["datapath"])
            if not schema_applies(reader):
                rec["error"] = "Not a recognized G-ASET fillable form"
                return rec
            _opts, defaults, special = read_by_schema(reader)
            per = score_values(defaults, special)

        d, src = date_from_filename(fi["name"]), "filename"
        if d is None and reader is not None:
            d, src = date_from_pdf_metadata(reader), "PDF modified date — please verify"
        _doms, te, tp = aggregate_scores(per)
        rec.update({"ok": True, "per": per, "date": d, "date_source": src if d else "",
                    "overall": te / tp * 100 if tp else 0.0})
    except Exception as e:
        rec["error"] = f"Could not read file: {e}"
    return rec

# ---------- Event handlers ----------
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

@reactive.effect
@reactive.event(input.ts_files)
def _on_ts_upload():
    files = input.ts_files() or []
    existing = list(ts_records.get())
    seen = {(r["name"], r["size"]) for r in existing}
    for fi in files:
        if (fi["name"], fi.get("size", 0)) in seen:
            continue
        existing.append(_load_trend_file(fi))
    ts_records.set(existing)

@reactive.effect
@reactive.event(input.ts_clear)
def _on_ts_clear():
    ts_records.set([])

# ---------- Calcs ----------
@reactive.calc
def all_scores():
    special = pdf_special.get()
    defs = geo_defaults.get()
    values = {}
    for num in CANONICAL:
        if num in (6, 35):
            continue
        try:
            val = input[f"q_{num}"]()
        except Exception:
            val = None
        values[num] = defs.get(num) if val is None else val
    per = score_values(values, special)
    domains, te, tp = aggregate_scores(per)
    return per, domains, te, tp

@reactive.calc
def action_plan_ctx():
    return {"setting": input.ctx_setting(), "micro": input.ctx_micro(),
            "ehr": input.ctx_ehr(), "team": input.ctx_team(),
            "funding": input.ctx_funding(), "national": input.ctx_national()}

@reactive.calc
def action_plan_eval():
    per, domains, _te, _tp = all_scores()
    return evaluate_recommendations(per, domains, action_plan_ctx(), ACTION_PLAN_TEMPLATE)

@reactive.calc
def action_plan_md():
    return build_action_plan(action_plan_eval(), facility=(input.ctx_facility() or "").strip())

@reactive.calc
def ts_dataset():
    """Dated, scored, chronologically sorted assessments for trend analysis."""
    pts = []
    for r in ts_records.get():
        if not r["ok"]:
            continue
        try:
            d = input[f"ts_date_{r['uid']}"]()
        except Exception:
            d = None
        d = d or r["date"]
        if d is None:
            continue
        pts.append({"label": r["name"], "date": d, "per": r["per"]})

    if input.ts_include_current() and parsed_domains.get():
        per, _d, _e, _t = all_scores()
        name = (pdf_meta.get() or {}).get("name", "Current assessment")
        pts.append({"label": f"{name} (live)",
                    "date": input.ts_current_date() or date.today(), "per": dict(per)})

    for p in pts:
        p["domains"], p["te"], p["tp"] = aggregate_scores(p["per"])
        p["dpct"] = {dn: (de / dp * 100 if dp else 0) for dn, _n, de, dp in p["domains"]}
        p["overall"] = p["te"] / p["tp"] * 100 if p["tp"] else 0
    pts.sort(key=lambda p: (p["date"], p["label"]))
    return pts

@reactive.effect
async def _push_badges():
    _ = parsed_domains.get()
    _ = reset_counter.get()
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

# =====================================================================
# ---------- UI: sidebar (visible on every tab) ----------
# =====================================================================
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

# =====================================================================
# ---------- UI: main tabs ----------
# =====================================================================
with ui.navset_card_tab(id="main_tabs"):

    # ---------------- Tab 1: Assessment ----------------
    with ui.nav_panel("📝 Assessment"):
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
                                  "Scoring is unavailable. See the Diagnostics tab.",
                                  style="color:#c62828; font-weight:600;"))
                return core_ui.TagList(
                    core_ui.p(core_ui.strong("File: "), meta["name"], " | ",
                              core_ui.strong("Pages: "), str(meta["pages"]), " | ",
                              core_ui.strong("Size: "), f"{meta['size']:,} bytes"),
                    core_ui.p(cfg["ui_parsed"].format(nq=meta.get("n_questions", 0), lang=meta["lang"])),
                    core_ui.p(f"📝 {meta.get('n_fields', 0)} AcroForm fields read deterministically by name."))

        core_ui.div(id="dynamic_form_container")

    # ---------------- Tab 2: Scores ----------------
    with ui.nav_panel("📊 Scores"):
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
                roles = [SIX_A_LABELS[i] for i in special.get(6, [])]
                n35 = special.get(35, 0)
                return core_ui.TagList(
                    core_ui.p(core_ui.strong("Item 6A "), f"→ {e6:g} / 5" if e6 is not None else "—",
                              core_ui.tags.br(),
                              core_ui.tags.small(f"Selected roles: {', '.join(roles) if roles else 'none'}")),
                    core_ui.p(core_ui.strong("Item 35A "), f"→ {e35:g} / 5" if e35 is not None else "—",
                              core_ui.tags.br(),
                              core_ui.tags.small(f"'Yes' responses in 35A column: {n35} / 18")))

    # ---------------- Tab 3: Action Plan ----------------
    with ui.nav_panel("🧭 Action Plan"):
        with ui.layout_columns(col_widths=[4, 8]):
            with ui.card():
                ui.card_header("⚙️ Facility context")
                ui.input_text("ctx_facility", "Facility name (optional)", "")
                ui.input_select("ctx_setting", "Resource setting",
                                {"resource_limited": "Resource-limited", "well_resourced": "Well-resourced"})
                ui.input_select("ctx_micro", "Clinical microbiology access",
                                {"none": "None", "offsite": "Off-site / referral", "onsite": "On-site"})
                ui.input_select("ctx_ehr", "Electronic health record",
                                {"none": "None", "partial": "Partial", "full": "Full"})
                ui.input_select("ctx_team", "Formal AMS team",
                                {"none": "None", "informal": "Informal", "formal": "Formal"})
                ui.input_select("ctx_funding", "Dedicated AMS time/funding",
                                {"none": "None", "some": "Some", "dedicated": "Dedicated"})
                ui.input_select("ctx_national", "National AMS policy to align to",
                                {"no": "No", "yes": "Yes"})

            with ui.card():
                ui.card_header("🧭 Action Plan")

                @render.download(label="⬇️ Download action plan (.md)",
                                 filename="gaset_action_plan.md")
                def download_action_plan():
                    yield action_plan_md()

                @render.ui
                def action_plan_view():
                    if not parsed_domains.get():
                        return core_ui.p("Upload a recognized G-ASET PDF to generate a plan.",
                                         class_="text-muted")
                    return core_ui.markdown(action_plan_md())
            with ui.card():
                ui.card_header("🔍 Why these recommendations? (rule trace)")

                @render.ui
                def action_plan_trace():
                    if not parsed_domains.get():
                        return core_ui.p("Upload a recognized G-ASET PDF first.", class_="text-muted")
                    ev = action_plan_eval()
                    stems = item_stems.get()
                    rows = []

                    def add(r, status, color, reason):
                        if r["statuses"]:
                            items_cell = core_ui.TagList(*[
                                core_ui.div(f"{STATUS_LABEL[st]} ({e:g}/{p:g}) ",
                                            core_ui.tags.small(_item_label(n, stems, 80)))
                                for n, st, e, p in r["statuses"]])
                        else:
                            items_cell = core_ui.tags.small("— no linked items (tier/context only)",
                                                            class_="text-muted")
                        rows.append(core_ui.tags.tr(
                            core_ui.tags.td(core_ui.tags.code(r["id"])),
                            core_ui.tags.td(r["title"]),
                            core_ui.tags.td(core_ui.span(status, style=f"color:{color};font-weight:600;")),
                            core_ui.tags.td(items_cell),
                            core_ui.tags.td(core_ui.tags.small(reason))))

                    for r in ev["shown"]:
                        reason = ("gap from an earlier tier, still open" if r["carried"]
                                    else f"domain tier: {r['cur_tier']}")
                        add(r, "Shown (strengthen)" if r["partial"] else "Shown", "#1565c0", reason)
                    for r in ev["in_place"]:
                        add(r, "Already in place", "#2e7d32",
                            f"met_if: {r['met_if']}" if r["met_if"] else "all linked items 5/5")
                    for r, why in ev["skipped"]:
                        add(r, "Not applicable", "#757575", why)

                    return core_ui.tags.details(
                        core_ui.tags.summary(f"{len(ev['shown'])} shown · {len(ev['in_place'])} already in "
                                                f"place · {len(ev['skipped'])} not applicable"),
                        core_ui.tags.table(
                            core_ui.tags.thead(core_ui.tags.tr(
                                core_ui.tags.th("Rule"), core_ui.tags.th("Recommendation"),
                                core_ui.tags.th("Outcome"), core_ui.tags.th("Linked G-ASET items"),
                                core_ui.tags.th("Reason"))),
                            core_ui.tags.tbody(*rows),
                            class_="table table-sm", style="font-size:0.85em;"))

    # ---------------- Tab 4: Trends (time series) ----------------
    with ui.nav_panel("📈 Trends"):
        with ui.layout_columns(col_widths=[5, 7]):
            with ui.card():
                ui.card_header("📥 Add assessments")
                ui.input_file("ts_files", "G-ASET PDFs and/or score CSVs",
                              accept=[".pdf", ".csv"], multiple=True)
                core_ui.markdown(
                    "Upload multiple completed G-ASET forms (or `gaset_scores.csv` exports from the "
                    "Scores tab). Files accumulate across uploads.\n\n"
                    "**Dates** are detected from the filename (e.g. `Facility_2024-03-15.pdf`, "
                    "`20240315`, `2024-03`), then from the PDF's modified date. "
                    "Check and correct each date in the table →")
                ui.input_switch("ts_include_current",
                                "Include the assessment loaded in the sidebar (with live edits)", False)
                ui.input_date("ts_current_date", "Date of that assessment", value=date.today())
                ui.input_switch("ts_show_domains", "Show individual domains on chart", True)
                ui.input_action_button("ts_clear", "🗑 Clear all uploaded assessments",
                                       class_="btn-outline-danger btn-sm")

            with ui.card():
                ui.card_header("🗂 Assessments & dates")

                @render.ui
                def ts_file_table():
                    recs = ts_records.get()
                    if not recs:
                        return core_ui.p("No assessments added yet.", class_="text-muted")
                    rows = []
                    for r in recs:
                        if r["ok"]:
                            iid = f"ts_date_{r['uid']}"
                            with reactive.isolate():          # keep user edits across re-renders
                                try:
                                    cur = input[iid]()
                                except Exception:
                                    cur = None
                            val = cur or r["date"]
                            date_cell = core_ui.input_date(
                                iid, None, value=val.isoformat() if val else None, width="150px")
                            status = "✅"
                            score = f"{r['overall']:.0f}%"
                            src = r["date_source"] or "⚠️ date not detected — please set"
                        else:
                            date_cell, status, score, src = "—", "❌", "—", r["error"]
                        rows.append(core_ui.tags.tr(
                            core_ui.tags.td(r["name"], style="word-break:break-all;"),
                            core_ui.tags.td(status, style="text-align:center;"),
                            core_ui.tags.td(score, style="text-align:center;"),
                            core_ui.tags.td(date_cell),
                            core_ui.tags.td(core_ui.tags.small(src))))
                    return core_ui.tags.table(
                        core_ui.tags.thead(core_ui.tags.tr(
                            core_ui.tags.th("File"), core_ui.tags.th("OK"),
                            core_ui.tags.th("Overall"), core_ui.tags.th("Assessment date"),
                            core_ui.tags.th("Date source / note"))),
                        core_ui.tags.tbody(*rows),
                        class_="table table-sm align-middle", style="font-size:0.9em;")

        with ui.card():
            ui.card_header("🔎 Key findings")

            @render.ui
            def ts_insights():
                pts = ts_dataset()
                if not pts:
                    return core_ui.p("Add two or more dated G-ASET assessments to see trends.",
                                     class_="text-muted")
                if len(pts) < 2:
                    return core_ui.p("Only one dated assessment so far — add at least one more "
                                     "to compute change and trend.", class_="text-muted")
                first, last = pts[0], pts[-1]
                months = (last["date"] - first["date"]).days / 30.44
                summ = {r["key"]: r for r in trend_summary(pts)}
                dom_rows = [summ[d] for d in DOMAIN_ITEMS]
                best = max(dom_rows, key=lambda r: r["d_base"])
                worst = min(dom_rows, key=lambda r: r["d_base"])
                below = [DOMAIN_SHORT[r["key"]] for r in dom_rows if r["latest"] <= 50]
                up, down = item_changes(pts[-2], last)
                o = summ["overall"]

                lines = [
                    f"- **Overall:** {o['baseline']:.1f}% → {o['latest']:.1f}% "
                    f"(**{o['d_base']:+.1f} pp**) across **{len(pts)}** assessments "
                    f"spanning **{months:.1f} months**.",
                    f"- **Trend:** {o['direction']}"
                    + (f" ({o['slope']:+.1f} pp/year)" if o["slope"] is not None else "")
                    + f" · projected to reach {TARGET_PCT:.0f}%: **{o['projection']}**.",
                    f"- **Largest gain:** {DOMAIN_SHORT[best['key']]} ({best['d_base']:+.1f} pp).",
                ]
                if worst["d_base"] < 0:
                    lines.append(f"- **Largest decline:** {DOMAIN_SHORT[worst['key']]} "
                                 f"({worst['d_base']:+.1f} pp).")
                lines.append("- **Domains at or below 50% in latest assessment:** "
                             + (", ".join(below) if below else "none 🎉"))
                lines.append(f"- **Since previous assessment:** {len(up)} items improved, "
                             f"{len(down)} regressed.")
                lines.append("\n*pp = percentage points. Slopes are descriptive (least-squares across "
                             "all assessments) and are not statistical forecasts; interpret with "
                             "caution when there are few assessments.*")
                return core_ui.markdown("\n".join(lines))

        with ui.card():
            ui.card_header("📈 Scores over time")

            @render.ui
            def ts_chart():
                pts = ts_dataset()
                if not pts:
                    return core_ui.p("Chart will appear once assessments are added.",
                                     class_="text-muted")
                return core_ui.HTML(svg_trend_chart(pts, show_domains=input.ts_show_domains()))

        with ui.card():
            ui.card_header("🟥🟨🟩 Domain score matrix")

            @render.ui
            def ts_heatmap():
                pts = ts_dataset()
                if not pts:
                    return core_ui.p("No dated assessments yet.", class_="text-muted")
                head = [core_ui.tags.th("Date"), core_ui.tags.th("Assessment")]
                head += [core_ui.tags.th(DOMAIN_SHORT[d], style="text-align:center;")
                         for d in DOMAIN_ITEMS]
                head.append(core_ui.tags.th("Overall", style="text-align:center;"))
                rows = []
                for p in pts:
                    cells = [core_ui.tags.td(p["date"].isoformat()),
                             core_ui.tags.td(p["label"], style="word-break:break-all;")]
                    for dn, _n, de, dp in p["domains"]:
                        cells.append(_pct_cell(p["dpct"][dn], title=f"{de:g} / {dp}"))
                    cells.append(_pct_cell(p["overall"], title=f"{p['te']:g} / {p['tp']:g}"))
                    rows.append(core_ui.tags.tr(*cells))
                return core_ui.TagList(
                    core_ui.tags.table(core_ui.tags.thead(core_ui.tags.tr(*head)),
                                       core_ui.tags.tbody(*rows),
                                       class_="table table-bordered table-sm"),
                    core_ui.tags.small("≤ 50% red · 51–80% yellow · > 80% green. "
                                       "Hover a cell for earned / possible points.",
                                       class_="text-muted"))

        with ui.card():
            ui.card_header("📐 Trend summary by domain")

            @render.ui
            def ts_trend_table():
                pts = ts_dataset()
                if len(pts) < 2:
                    return core_ui.p("Requires at least two dated assessments.", class_="text-muted")
                rows = []
                for r in trend_summary(pts):
                    is_o = r["key"] == "overall"
                    rows.append(core_ui.tags.tr(
                        core_ui.tags.td(core_ui.strong(r["name"]) if is_o else r["name"]),
                        _pct_cell(r["baseline"]), _pct_cell(r["latest"]),
                        core_ui.tags.td(_delta_span(r["d_base"]), style="text-align:center;"),
                        core_ui.tags.td(_delta_span(r["d_prev"]), style="text-align:center;"),
                        core_ui.tags.td("—" if r["slope"] is None else f"{r['slope']:+.1f}",
                                        style="text-align:center;"),
                        core_ui.tags.td(r["direction"], style="text-align:center;"),
                        core_ui.tags.td(r["projection"], style="text-align:center;"),
                        style="background:#e8f4f8;" if is_o else None))
                return core_ui.tags.table(
                    core_ui.tags.thead(core_ui.tags.tr(
                        core_ui.tags.th("Domain"),
                        core_ui.tags.th("Baseline", style="text-align:center;"),
                        core_ui.tags.th("Latest", style="text-align:center;"),
                        core_ui.tags.th("Δ since baseline", style="text-align:center;"),
                        core_ui.tags.th("Δ since previous", style="text-align:center;"),
                        core_ui.tags.th("Slope (pp/yr)", style="text-align:center;"),
                        core_ui.tags.th("Direction", style="text-align:center;"),
                        core_ui.tags.th(f"Projected {TARGET_PCT:.0f}%", style="text-align:center;"))),
                    core_ui.tags.tbody(*rows),
                    class_="table table-bordered table-sm")

        with ui.card():
            ui.card_header("🔁 Item-level changes (previous → latest)")

            @render.ui
            def ts_item_changes():
                pts = ts_dataset()
                if len(pts) < 2:
                    return core_ui.p("Requires at least two dated assessments.", class_="text-muted")
                prev, last = pts[-2], pts[-1]
                up, down = item_changes(prev, last)
                stems = item_stems.get()

                def _list(items, col):
                    if not items:
                        return core_ui.p("None.", class_="text-muted")
                    return core_ui.tags.ul(*[core_ui.tags.li(
                        core_ui.span(f"{a:g} → {b:g}",
                                     style=f"display:inline-block;padding:1px 7px;border-radius:9px;"
                                           f"background:{col};color:white;font-size:0.8em;"
                                           f"font-weight:600;margin-right:6px;"),
                        core_ui.strong(f"D{ITEM_DOMAIN[n]} · "), _item_label(n, stems))
                        for n, a, b in items], style="padding-left:1.1em;")

                return core_ui.TagList(
                    core_ui.p(core_ui.tags.small(
                        f"Comparing {prev['date'].isoformat()} ({prev['label']}) → "
                        f"{last['date'].isoformat()} ({last['label']})", class_="text-muted")),
                    core_ui.div(
                        core_ui.div(core_ui.h6(f"▼ Regressed ({len(down)})", style="color:#c62828;"),
                                    _list(down, "#c62828"), class_="col-md-6"),
                        core_ui.div(core_ui.h6(f"▲ Improved ({len(up)})", style="color:#2e7d32;"),
                                    _list(up, "#2e7d32"), class_="col-md-6"),
                        class_="row"))

        with ui.card():
            ui.card_header("⬇️ Export trend data")

            @render.download(label="⬇️ Domain trends (CSV, long format)",
                             filename=lambda: f"gaset_trends_{date.today().isoformat()}.csv")
            def download_trends():
                pts = ts_dataset()
                buf = io.StringIO(); w = csv.writer(buf)
                w.writerow(["date", "assessment", "domain", "earned", "possible", "percent"])
                for p in pts:
                    for _dn, name, de, dp in p["domains"]:
                        w.writerow([p["date"].isoformat(), p["label"], name,
                                    f"{de:g}", dp, f"{(de / dp * 100 if dp else 0):.1f}"])
                    w.writerow([p["date"].isoformat(), p["label"], "OVERALL",
                                f"{p['te']:g}", f"{p['tp']:g}", f"{p['overall']:.1f}"])
                yield buf.getvalue()

            @render.download(label="⬇️ Item-level matrix (CSV)",
                             filename=lambda: f"gaset_trend_items_{date.today().isoformat()}.csv")
            def download_trend_items():
                pts = ts_dataset()
                buf = io.StringIO(); w = csv.writer(buf)
                w.writerow(["item", "domain"] + [f"{p['date'].isoformat()} | {p['label']}" for p in pts])
                for n in sorted(CANONICAL):
                    w.writerow([n, ITEM_DOMAIN[n]] + [
                        "" if p["per"].get(n, (None, 0))[0] is None
                        else f"{p['per'][n][0]:g}" for p in pts])
                yield buf.getvalue()

    # ---------------- Tab 5: Diagnostics ----------------
    with ui.nav_panel("🔧 Diagnostics"):
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


# ---------- Dynamic form (renders into the Assessment tab) ----------
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