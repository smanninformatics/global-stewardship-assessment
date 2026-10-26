# G-ASET Multilingual PDF Assessment — deterministic field-name mapping
# Tabs: Assessment | Scores | Action Plan | Trends (multi-assessment time series) | Diagnostics
# Runs fully in-browser (Pyodide / shinylive / GitHub Pages). Pure-Python deps only.
#
# shinylive requirements: pypdf   (langdetect optional)

import re
import io
import csv
import html as _html
from datetime import date, datetime, timedelta
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

# ---------- Combined-PDF export (print engine) ----------
core_ui.tags.style("""
#gaset-print-root { display: none; }

@media print {
    body > *:not(#gaset-print-root) { display: none !important; }
    #gaset-print-root { display: block !important; font-size: 10.5pt; color: #000; }
    html, body { background: #fff !important; margin: 0 !important; padding: 0 !important; }

    #gaset-print-root, #gaset-print-root * {
        -webkit-print-color-adjust: exact !important;
        print-color-adjust: exact !important;
        box-shadow: none !important;
    }

    /* One section per tab, each starting on a new page (except the very first) */
    #gaset-print-root > .print-section { break-before: page; }
    #gaset-print-root > .print-section:first-child { break-before: auto; }
    .print-section-title {
        font-size: 1.35em; font-weight: 700; border-bottom: 2px solid #333;
        padding-bottom: 4px; margin: 0 0 10px 0; break-after: avoid;
    }

    /* Flatten bslib layouts so content flows naturally on paper */
    #gaset-print-root .bslib-grid,
    #gaset-print-root .html-fill-container,
    #gaset-print-root .html-fill-item {
        display: block !important; height: auto !important; flex: none !important;
    }
    #gaset-print-root .bslib-grid > * { width: 100% !important; margin-bottom: 8px; }
    #gaset-print-root .card, #gaset-print-root .card-body {
        height: auto !important; max-height: none !important; overflow: visible !important;
        border: 1px solid #bbb !important; margin-bottom: 8px !important;
    }
    #gaset-print-root .card-header {
        background: #e8eef7 !important; font-weight: 700; break-after: avoid;
    }

    /* Hide interactive-only elements */
    #gaset-print-root .btn,
    #gaset-print-root .shiny-download-link,
    #gaset-print-root input[type="file"],
    #gaset-print-root .shiny-input-container:has(input[type="file"]),
    #gaset-print-root .bslib-full-screen-enter,
    #gaset-print-root .nav { display: none !important; }

    #gaset-print-root .shiny-input-container,
    #gaset-print-root tr,
    #gaset-print-root svg { break-inside: avoid; }
    #gaset-print-root table { width: 100% !important; border-collapse: collapse; }
    #gaset-print-root .print-select-value { font-weight: 600; }

    /* Cover page */
    .print-cover { break-after: page; padding-top: 1.5in; }
    .print-cover h1 { font-size: 2em; margin-bottom: 0.4in; border-bottom: 3px solid #1f4e79; }
    .print-cover-table th { text-align: left; padding: 6px 18px 6px 0; width: 30%; color: #333; }
    .print-cover-table td { padding: 6px 0; }
    .print-cover-note { margin-top: 0.6in; font-style: italic; color: #555; }
}
""")

core_ui.tags.script("""
(function () {
    const sleep = ms => new Promise(r => setTimeout(r, ms));

    // Resolve once Shiny has stopped recalculating for ~400 ms (or after maxMs)
    async function waitForShinyIdle(maxMs) {
        const start = Date.now();
        await sleep(250);
        let calm = 0;
        while (Date.now() - start < maxMs) {
            const busy = document.documentElement.classList.contains('shiny-busy');
            calm = busy ? 0 : calm + 100;
            if (calm >= 400) return;
            await sleep(100);
        }
    }

    function linkFor(value) {
        const sel = '.nav-link[data-value="' + CSS.escape(value) + '"]';
        return document.querySelector('#main_tabs ' + sel) || document.querySelector(sel);
    }
    function paneFor(link) {
        const target = link.getAttribute('data-bs-target') || link.getAttribute('href');
        return target ? document.querySelector(target) : null;
    }
    function showTab(link) {
        if (window.bootstrap && bootstrap.Tab) bootstrap.Tab.getOrCreateInstance(link).show();
        else link.click();
    }

    // Replace <select> clones with the selected text (clones lose their selection)
    function freezeSelects(original, clone) {
        const os = original.querySelectorAll('select');
        clone.querySelectorAll('select').forEach((c, i) => {
            const o = os[i];
            const span = document.createElement('span');
            span.className = 'print-select-value';
            span.textContent = o ? Array.from(o.selectedOptions).map(x => x.text).join(', ') : '';
            c.replaceWith(span);
        });
    }

    // Make a clone inert so it can't interfere with the live app
    function sanitize(clone, k, expand) {
        clone.removeAttribute('id');
        clone.querySelectorAll('[id]').forEach(el => el.removeAttribute('id'));
        // Rename radio groups BEFORE insertion, so checked clones don't uncheck the live form
        clone.querySelectorAll('input[type="radio"]').forEach(el => {
            el.name = 'print_' + k + '_' + el.name;
        });
        clone.querySelectorAll('input, textarea, button').forEach(el => { el.disabled = true; });
        clone.querySelectorAll('script').forEach(s => s.remove());
        const shinyClasses = ['shiny-bound-input', 'shiny-bound-output', 'shiny-input-radiogroup',
                              'shiny-input-checkboxgroup', 'shiny-html-output', 'recalculating'];
        [clone, ...clone.querySelectorAll('[class]')].forEach(el => el.classList.remove(...shinyClasses));
        // Undo the form-lock fade
        clone.querySelectorAll('[style*="opacity"]').forEach(el => {
            el.style.opacity = ''; el.style.pointerEvents = '';
        });
        if (expand) clone.querySelectorAll('details').forEach(d => { d.open = true; });
        clone.classList.remove('tab-pane', 'fade');
        clone.style.display = 'block';
    }

    function buildCover(cover) {
        const c = document.createElement('div');
        c.className = 'print-cover';
        const h = document.createElement('h1');
        h.textContent = cover.title;
        c.appendChild(h);
        const tbl = document.createElement('table');
        tbl.className = 'print-cover-table';
        (cover.rows || []).forEach(([k, v]) => {
            const tr = tbl.insertRow();
            const th = document.createElement('th'); th.textContent = k; tr.appendChild(th);
            tr.insertCell().textContent = v;
        });
        c.appendChild(tbl);
        if (cover.note) {
            const p = document.createElement('p');
            p.className = 'print-cover-note';
            p.textContent = cover.note;
            c.appendChild(p);
        }
        return c;
    }

    Shiny.addCustomMessageHandler('gaset_export_pdf', async function (msg) {
        const prevTitle = document.title;
        const active = document.querySelector('.nav-link.active[data-value]');
        const old = document.getElementById('gaset-print-root');
        if (old) old.remove();

        // Page size / orientation for this export
        let pageStyle = document.getElementById('gaset-print-page');
        if (!pageStyle) {
            pageStyle = document.createElement('style');
            pageStyle.id = 'gaset-print-page';
            document.head.appendChild(pageStyle);
        }
        pageStyle.textContent = '@page { size: ' + (msg.paper || 'letter') + ' ' +
                                (msg.orientation || 'portrait') + '; margin: 0.5in; }';

        const root = document.createElement('div');
        root.id = 'gaset-print-root';
        if (msg.cover) root.appendChild(buildCover(msg.cover));

        for (let k = 0; k < msg.tabs.length; k++) {
            const t = msg.tabs[k];
            const link = linkFor(t.value);
            if (!link) continue;
            showTab(link);                       // forces Shiny to render hidden outputs
            await waitForShinyIdle(msg.max_wait_ms || 8000);
            const pane = paneFor(link);
            if (!pane) continue;

            const section = document.createElement('section');
            section.className = 'print-section';
            const h = document.createElement('h2');
            h.className = 'print-section-title';
            h.textContent = t.label;
            section.appendChild(h);

            const clone = pane.cloneNode(true);
            freezeSelects(pane, clone);
            sanitize(clone, k, msg.expand);
            section.appendChild(clone);
            root.appendChild(section);
        }

        if (active) showTab(active);             // restore the user's tab
        document.body.appendChild(root);
        if (msg.filename) document.title = msg.filename;   // default PDF filename

        const cleanup = function () {
            root.remove();
            document.title = prevTitle;
            window.removeEventListener('afterprint', cleanup);
        };
        window.addEventListener('afterprint', cleanup);

        await sleep(300);
        window.print();
    });
})();
""")

# ---------- Custom Action Plan helper -----------

core_ui.tags.style("""
.ap-card:not(.ap-selected) .ap-fields { display: none; }
.ap-card.ap-selected { background: #f5f9ff; }
.ap-card .shiny-input-container:has(input[type="checkbox"]) { margin-bottom: 0; }
.ap-only-selected .ap-card:not(.ap-selected),
.ap-only-selected .ap-tier-empty,
.ap-only-selected .ap-hidden-list,
.ap-only-selected .ap-tier-allmet { display: none !important; }
.print-field-value {
    white-space: pre-wrap; border: 1px solid #ccc; border-radius: 4px;
    padding: 4px 6px; min-height: 1.6em; background: #fff;
}
""")

core_ui.tags.script("""
(function () {
    window._apOnly = false;
    function refresh() {
        const root = document.getElementById('action_plan_view');
        if (!root) return;
        root.classList.toggle('ap-only-selected', !!window._apOnly);
        root.querySelectorAll('.ap-card').forEach(card => {
            const cb = card.querySelector('input[type="checkbox"][id^="ap_sel_"]');
            card.classList.toggle('ap-selected', !!(cb && cb.checked));
        });
        root.querySelectorAll('.ap-tier').forEach(t =>
            t.classList.toggle('ap-tier-empty', !t.querySelector('.ap-card.ap-selected')));
        if (window._apOnly) {
            root.querySelectorAll('details').forEach(d => {
                if (d.querySelector('.ap-card.ap-selected')) d.open = true;
            });
        }
    }
    document.addEventListener('change', function (e) {
        if (e.target && e.target.id && e.target.id.startsWith('ap_sel_')) refresh();
    });
    $(document).on('shiny:value', function (e) {
        if (e.name === 'action_plan_view') setTimeout(refresh, 50);
    });
    Shiny.addCustomMessageHandler('ap_only_selected', function (msg) {
        window._apOnly = !!msg.on;
        refresh();
    });
})();
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

# ---------- Action plan engine (four-tier model) ----------
DEFAULT_TIERS = [("core_essential", "Core Essential"), ("core_standard", "Core Standard"),
                 ("enhancement", "Enhancement"), ("advanced_enhancement", "Advanced Enhancement")]
TIER_COLORS = {"core_essential": "#1f3864", "core_standard": "#2f5597",
               "enhancement": "#3a7d44", "advanced_enhancement": "#6a3d9a"}
CONTEXT_LABELS = {"micro": "access to a clinical microbiology laboratory",
                  "ehr": "access to electronic data sources"}
ACT_LETTERS = "ABCDEFGHIJKLMNOPQR"                  # item 35 activities (35A fields 1..18)
ACT_POINTS = MAX_PER_ITEM / len(ACT_LETTERS)         # tier-progress weight per activity
SIX_C_POINTS = MAX_PER_ITEM                          # 6C counted as a 5-point practice
COMP_STATUS = {"met": "✅", "partial": "🟠", "not_met": "🔴", "unknown": "❓"}
SLICE_LABELS = {"4@0-2.5": "Item 4 · at least 1 committee member role",
                "4@2.5-5": "Item 4 · 8 or more committee member roles"}
_TOKEN_RE = re.compile(r"^(\d+)(?:(C)|@([\d.]+)-([\d.]+)|:([A-R]+))?$")
_ACT_LINE = re.compile(r"^\s*[-*]\s*\*\*([A-R])\.\*\*")

def _pts(x):
    return f"{round(x, 1):g}"

def _parse_components(spec):
    comps, bad = [], []
    for tok in [t.strip().upper() for t in spec.split(",") if t.strip()]:
        m = _TOKEN_RE.match(tok)
        if not m:
            bad.append(tok)
            continue
        n = int(m.group(1))
        if m.group(2):
            comps.append({"kind": "flag6c", "item": n, "key": f"{n}C"})
        elif m.group(3):
            lo, hi = float(m.group(3)), float(m.group(4))
            comps.append({"kind": "slice", "item": n, "lo": lo, "hi": hi, "key": f"{n}@{lo:g}-{hi:g}"})
        elif m.group(5):
            acts = sorted(set(m.group(5)))
            comps.append({"kind": "acts", "item": n, "acts": acts, "key": f"{n}:{''.join(acts)}"})
        else:
            comps.append({"kind": "item", "item": n, "key": str(n)})
    return comps, bad

def parse_action_template(text):
    meta = {"version": "", "tiers": list(DEFAULT_TIERS)}
    m = re.search(r"@@meta\s*(.*?)@@endmeta", text, re.DOTALL)
    if m:
        for line in m.group(1).splitlines():
            line = line.strip()
            if line.startswith("version:"):
                meta["version"] = line[8:].strip()
            elif line.startswith("tiers:"):
                tiers = [tuple(s.strip() for s in part.split("=", 1))
                         for part in line[6:].split("|") if "=" in part]
                if tiers:
                    meta["tiers"] = tiers
        text = text[m.end():]
    recs = []
    for part in re.split(r"(?m)^@@rec\s+", text)[1:]:
        header, _, body = part.partition("\n")
        hm = dict(re.findall(r"(\w+)=(\S+)", header))
        body = re.sub(r"<!--.*?-->", "", body, flags=re.DOTALL).strip()
        first, _, rest = body.partition("\n")
        if first.startswith("###"):
            title, text_ = first.lstrip("#").strip(), rest.strip()
        else:
            title, text_ = "(untitled)", body
        comps, bad = _parse_components(hm.get("items", ""))
        recs.append({
            "id": hm.get("id", ""), "tier": hm.get("tier", ""),
            "domain": int(hm["domain"]) if hm.get("domain", "").isdigit() else None,
            "needs": [x for x in hm.get("needs", "").lower().split(",") if x],
            "show_if": hm.get("show_if", ""), "met_if": hm.get("met_if", ""),
            "components": comps, "bad_tokens": bad, "title": title, "text": text_,
        })
    return meta, recs

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
    if not expr:
        return True
    return any(_eval_and(alt, env) for alt in expr.split("|"))

def _eval_component(c, per_item, special):
    n = c["item"]
    if c["kind"] == "flag6c":
        v = special.get("6C")
        if v is None:
            return dict(c, earned=0.0, possible=SIX_C_POINTS, status="unknown",
                        label="6C · team leader designated (not readable from PDF)")
        return dict(c, earned=SIX_C_POINTS if v else 0.0, possible=SIX_C_POINTS,
                    status="met" if v else "not_met", label="6C · team leader designated")
    if c["kind"] == "acts":
        flags = list(special.get("35A") or [])
        flags += [False] * (len(ACT_LETTERS) - len(flags))
        done = [a for a in c["acts"] if flags[ACT_LETTERS.index(a)]]
        k, tot = len(done), len(c["acts"])
        status = "met" if k == tot else ("partial" if k else "not_met")
        return dict(c, earned=k * ACT_POINTS, possible=tot * ACT_POINTS, status=status, done=done,
                    label=f"35A · activities {', '.join(c['acts'])}: {k} of {tot} routinely conducted")
    e, p = per_item.get(n, (None, MAX_PER_ITEM))
    e, p = (e or 0.0), (p or MAX_PER_ITEM)
    if c["kind"] == "slice":
        pts = c["hi"] - c["lo"]
        earned = min(max(e - c["lo"], 0.0), pts)
        status = "met" if earned >= pts - 1e-9 else ("partial" if earned > 0 else "not_met")
        return dict(c, earned=earned, possible=pts, status=status,
                    label=SLICE_LABELS.get(c["key"], f"Item {n} (points {c['lo']:g}–{c['hi']:g})"))
    status = "met" if e >= p else ("partial" if e > 0 else "not_met")
    return dict(c, earned=e, possible=p, status=status, label=f"Item {n}")

def evaluate_tiers(per_item, special, ctx, template_text):
    """Score every recommendation, group by tier, and compute tier/domain attainment."""
    meta, recs = parse_action_template(template_text)
    tier_keys = [k for k, _ in meta["tiers"]]
    special = special or {}
    ctx = ctx or {}

    env = {f"item{n}": (0 if e is None else e) for n, (e, _p) in per_item.items()}
    env.update({f"ctx.{k}": v for k, v in ctx.items()})

    problems, seen, evaluated = [], {}, []
    for base in recs:
        r = dict(base)
        r["comps"] = [_eval_component(c, per_item, special) for c in r["components"]]
        if r["domain"] is None:
            r["domain"] = next((ITEM_DOMAIN[c["item"]] for c in r["comps"]
                                if c["item"] in ITEM_DOMAIN), 0)
        r["earned"] = sum(c["earned"] for c in r["comps"])
        r["possible"] = sum(c["possible"] for c in r["comps"])

        # Template consistency checks
        if r["tier"] not in tier_keys:
            problems.append(f"{r['id']}: unknown tier '{r['tier']}'")
        problems += [f"{r['id']}: unrecognized item token '{t}'" for t in r["bad_tokens"]]
        for c in r["comps"]:
            if c["item"] not in CANONICAL:
                problems.append(f"{r['id']}: item {c['item']} is not a G-ASET item")
            keys = [f"35:{a}" for a in c["acts"]] if c["kind"] == "acts" else [c["key"]]
            for k in keys:
                if k in seen:
                    problems.append(f"{k} is assigned to both {seen[k]} and {r['id']}")
                seen[k] = r["id"]

        missing = [k for k in r["needs"] if str(ctx.get(k, "yes")).lower() == "no"]
        if missing:
            r["outcome"] = "hidden"
            r["reason"] = "requires " + " and ".join(CONTEXT_LABELS.get(k, k) for k in missing)
        elif not _eval_condition(r["show_if"], env):
            r["outcome"] = "hidden"
            r["reason"] = f"show_if not satisfied: {r['show_if']}"
        else:
            if r["met_if"]:
                met = _eval_condition(r["met_if"], env)
            else:
                met = bool(r["comps"]) and all(c["status"] == "met" for c in r["comps"])
            if met:
                r["outcome"], r["reason"] = "met", (f"met_if: {r['met_if']}" if r["met_if"]
                                                    else "all linked practices in place")
            elif any(c["earned"] > 0 for c in r["comps"]):
                r["outcome"], r["reason"] = "partial", "some linked practices in place"
            else:
                r["outcome"], r["reason"] = "gap", "linked practices not in place"
        evaluated.append(r)

    # Coverage checks (every item and every 35 activity should be assigned once)
    covered = {c["item"] for r in evaluated for c in r["comps"]}
    uncovered = [n for n in sorted(CANONICAL) if n not in covered]
    if uncovered:
        problems.append("G-ASET items without a recommendation: " + ", ".join(map(str, uncovered)))
    acts_cov = {a for r in evaluated for c in r["comps"] if c["kind"] == "acts" for a in c["acts"]}
    if 35 in covered and len(acts_cov) < len(ACT_LETTERS):
        problems.append("Item 35 activities not assigned: "
                        + ", ".join(a for a in ACT_LETTERS if a not in acts_cov))

    tiers = []
    for key, label in meta["tiers"]:
        trs = [r for r in evaluated if r["tier"] == key]
        vis = [r for r in trs if r["outcome"] != "hidden"]
        e, p = sum(r["earned"] for r in vis), sum(r["possible"] for r in vis)
        by_dom = {}
        for r in vis:
            for c in r["comps"]:
                d = ITEM_DOMAIN.get(c["item"])
                if d is not None:
                    acc = by_dom.setdefault(d, [0.0, 0.0])
                    acc[0] += c["earned"]; acc[1] += c["possible"]
        order = lambda r: (r["domain"], r["id"])
        tiers.append({
            "key": key, "label": label, "earned": e, "possible": p,
            "pct": e / p * 100 if p else 0.0,
            "gaps": sorted([r for r in vis if r["outcome"] != "met"], key=order),
            "met": sorted([r for r in vis if r["outcome"] == "met"], key=order),
            "hidden": sorted([r for r in trs if r["outcome"] == "hidden"], key=order),
            "by_domain": by_dom,
        })
    return {"meta": meta, "tiers": tiers, "recs": evaluated, "problems": problems}

def _rec_body(r):
    """Drop item-35 activities that are already conducted and note them."""
    done = {a for c in r["comps"] if c["kind"] == "acts" for a in c.get("done", [])}
    if not done or r["outcome"] == "met":
        return r["text"]
    kept = []
    for ln in r["text"].splitlines():
        m = _ACT_LINE.match(ln)
        if m and m.group(1) in done:
            continue
        kept.append(ln)
    return "\n".join(kept) + f"\n\n*Already routinely conducted: {', '.join(sorted(done))}.*"

def _text_bar(pct, width=20):
    filled = int(round(max(0.0, min(100.0, pct)) / 100 * width))
    return "█" * filled + "░" * (width - filled)

def build_action_plan_md(ev, te, tp, facility="", ctx=None):
    ctx = ctx or {}
    yn = lambda k: "Yes" if str(ctx.get(k, "yes")).lower() != "no" else "No"
    overall = te / tp * 100 if tp else 0
    out = [f"# G-ASET Antibiotic Stewardship Action Plan" + (f" — {facility}" if facility else ""),
           "",
           f"*Generated {date.today().isoformat()}. **Draft decision‑support output for SME review** — "
           f"not a substitute for clinical judgment or local guideline alignment.*",
           "", "## Summary", "",
           f"- **Overall G-ASET score:** {te:g} / {tp:g} ({overall:.0f}%)",
           f"- **Context:** clinical microbiology laboratory access: **{yn('micro')}** · "
           f"electronic data sources: **{yn('ehr')}**", "",
           "| Tier | Progress | Points | Recommendations complete | "
           + " | ".join(f"D{d}" for d in DOMAIN_ITEMS) + " |",
           "|---|---|---|---|" + "---|" * len(DOMAIN_ITEMS)]
    for t in ev["tiers"]:
        doms = []
        for d in DOMAIN_ITEMS:
            e, p = t["by_domain"].get(d, (0.0, 0.0))
            doms.append(f"{e / p * 100:.0f}%" if p else "—")
        out.append(f"| {t['label']} | `{_text_bar(t['pct'], 10)}` {t['pct']:.0f}% | "
                   f"{_pts(t['earned'])}/{_pts(t['possible'])} | "
                   f"{len(t['met'])}/{len(t['met']) + len(t['gaps'])} | " + " | ".join(doms) + " |")
    out.append("")

    for t in ev["tiers"]:
        out += [f"## {t['label']} — {t['pct']:.0f}% complete", "",
                f"`{_text_bar(t['pct'])}` {_pts(t['earned'])} / {_pts(t['possible'])} points", ""]
        if not t["gaps"]:
            out += ["_All recommendations in this tier are in place._", ""]
        for r in t["gaps"]:
            partial = r["outcome"] == "partial"
            flag = "🟠 PARTIALLY IN PLACE" if partial else "🔴 NOT IN PLACE"
            title = f"Strengthen: {r['title']}" if partial else r["title"]
            out += [f"### `[D{r['domain']} · {flag}]` {title}", "",
                    "> **Current status:** " + " · ".join(
                        f"{COMP_STATUS[c['status']]} {c['label']} "
                        f"({_pts(c['earned'])}/{_pts(c['possible'])} pts)" for c in r["comps"]),
                    "", _rec_body(r), ""]
        if t["met"]:
            out += [f"#### ✅ Already in place ({len(t['met'])})", ""]
            out += [f"- {r['title']} (D{r['domain']})" for r in t["met"]] + [""]
        if t["hidden"]:
            out += [f"#### 🚫 Not applicable in this context ({len(t['hidden'])})", ""]
            out += [f"- {r['title']} — {r['reason']}" for r in t["hidden"]] + [""]
    return "\n".join(out)

def _custom_plan_rows(ev, store):
    recs = {r["id"]: r for r in ev["recs"]}
    tier_order = {k: i for i, (k, _l) in enumerate(ev["meta"]["tiers"])}
    tier_label = dict(ev["meta"]["tiers"])
    rows = []
    for rid, e in store.items():
        if not e.get("selected") or rid not in recs:
            continue
        r = recs[rid]
        rows.append({"r": r, "tier": tier_label.get(r["tier"], r["tier"]),
                     "owner": (e.get("owner") or "").strip(), "date": e.get("date") or "",
                     "notes": (e.get("notes") or "").strip(),
                     "status": _OUTCOME_STYLE[r["outcome"]][0]})
    rows.sort(key=lambda x: (tier_order.get(x["r"]["tier"], 99), x["r"]["domain"], x["r"]["id"]))
    return rows

def build_custom_plan_md(ev, store, facility=""):
    rows = _custom_plan_rows(ev, store)
    out = ["# Customized Antibiotic Stewardship Action Plan" + (f" — {facility}" if facility else ""),
           "", f"*Generated {date.today().isoformat()} from G-ASET results. "
               f"Draft for facility review and approval.*", ""]
    if not rows:
        return "\n".join(out + ["_No recommendations selected._"])
    out += ["## Plan overview", "",
            "| # | Recommendation | Tier | Domain | Current status | Accountable owner | Target date |",
            "|---|---|---|---|---|---|---|"]
    for i, x in enumerate(rows, 1):
        r = x["r"]
        due = x["date"] or "—"
        if _is_overdue(x["date"], r["outcome"]):
            due += " ⚠️ past due"
        out.append(f"| {i} | {_md_cell(r['title'])} | {x['tier']} | D{r['domain']} | {x['status']} | "
                   f"{_md_cell(x['owner']) or '—'} | {due} |")
    out += ["", "## Recommendation details", ""]
    for i, x in enumerate(rows, 1):
        r = x["r"]
        notes = x["notes"].replace("\n", "  \n  ") if x["notes"] else "—"
        out += [f"### {i}. {r['title']}", "",
                f"- **Tier / domain:** {x['tier']} · {DOMAIN_TITLES.get(r['domain'], 'Cross-cutting')}",
                f"- **Current status:** {x['status']}",
                f"- **Accountable owner:** {x['owner'] or '—'}",
                f"- **Target date of completion:** {x['date'] or '—'}",
                f"- **Implementation notes:** {notes}",
                "", "**Recommended action:**", "", _rec_body(r), ""]
    return "\n".join(out)

# ---------- Custom action plan state ----------
plan_store = reactive.value({})        # {rec_id: {"selected", "owner", "date", "notes"}}
plan_ui_version = reactive.value(0)    # bump to force the plan to re-render from plan_store
_plan_seen = {}                        # last value seen per input id (prevents stale overwrites)
_EMPTY_ENTRY = {"selected": False, "owner": "", "date": "", "notes": ""}
_PLAN_FIELDS = (("selected", "ap_sel_"), ("owner", "ap_own_"),
                ("date", "ap_date_"), ("notes", "ap_note_"))

def _sid(rec_id):
    """Rec id -> safe input-id suffix (e.g. 'CE-06C' -> 'CE_06C')."""
    return re.sub(r"\W", "_", rec_id)

def _md_cell(s):
    return (s or "").replace("|", "\\|").replace("\n", " ")

def _is_overdue(d, outcome):
    try:
        return outcome != "met" and date.fromisoformat(d) < date.today()
    except Exception:
        return False

def _parse_import_date(s):
    s = (s or "").strip()
    for fmt in ("%Y-%m-%d", "%m/%d/%Y"):
        try:
            return datetime.strptime(s, fmt).date().isoformat()
        except ValueError:
            continue
    return ""

@reactive.effect
def _sync_plan_inputs():
    """Copy changed plan inputs into plan_store (only genuine changes are accepted)."""
    if not parsed_domains.get():
        return
    ev = action_plan_eval()
    with reactive.isolate():
        store = dict(plan_store.get())
    changed = False
    for r in ev["recs"]:
        if r["outcome"] == "hidden":
            continue
        sid = _sid(r["id"])
        entry = dict(store.get(r["id"], _EMPTY_ENTRY))
        for field, prefix in _PLAN_FIELDS:
            key = prefix + sid
            try:
                v = input[key]()
            except Exception:
                continue                       # input not rendered yet
            v = bool(v) if field == "selected" else (v or "")
            if key in _plan_seen and _plan_seen[key] == v:
                continue                       # unchanged since last seen -> ignore
            _plan_seen[key] = v
            if entry.get(field) != v:
                entry[field] = v
                changed = True
        store[r["id"]] = entry
    if changed:
        plan_store.set(store)

@reactive.effect
async def _push_only_selected():
    on = bool(input.ap_only_selected())
    session = get_current_session()
    if session is not None:
        await session.send_custom_message("ap_only_selected", {"on": on})

@reactive.effect
@reactive.event(input.ap_clear)
def _on_plan_clear():
    plan_store.set({})
    plan_ui_version.set(plan_ui_version.get() + 1)
    core_ui.notification_show("All plan selections cleared.", duration=3)

@reactive.effect
@reactive.event(input.ap_import)
def _on_plan_import():
    f = input.ap_import()
    if not f:
        return
    valid = {r["id"] for r in parse_action_template(ACTION_PLAN_TEMPLATE)[1]}
    try:
        with open(f[0]["datapath"], newline="", encoding="utf-8-sig") as fh:
            rows = list(csv.DictReader(fh))
    except Exception as e:
        core_ui.notification_show(f"Could not read plan file: {e}", type="error", duration=6)
        return
    store, n_ok, unknown = dict(plan_store.get()), 0, []
    for row in rows:
        row = {(k or "").strip().lower(): (v or "").strip() for k, v in row.items()}
        rid = row.get("rec_id", "")
        if rid not in valid:
            if rid:
                unknown.append(rid)
            continue
        store[rid] = {
            "selected": row.get("selected", "yes").lower() not in ("no", "false", "0"),
            "owner": row.get("accountable_owner", ""),
            "date": _parse_import_date(row.get("target_date", "")),
            "notes": row.get("implementation_notes", ""),
        }
        n_ok += 1
    plan_store.set(store)
    plan_ui_version.set(plan_ui_version.get() + 1)
    msg = f"Loaded {n_ok} plan item(s)."
    if unknown:
        msg += f" Skipped unknown IDs: {', '.join(unknown[:5])}{'…' if len(unknown) > 5 else ''}"
    core_ui.notification_show(msg, type="warning" if unknown else "message", duration=6)

# ---------- Action plan UI helpers ----------
_OUTCOME_STYLE = {"gap": ("🔴 Not in place", "#c62828"), "partial": ("🟠 Partially in place", "#ef6c00"),
                  "met": ("✅ In place", "#2e7d32"), "hidden": ("🚫 Not applicable", "#757575")}
_PRINT_EXACT = "-webkit-print-color-adjust:exact;print-color-adjust:exact;"

def _chip(text, bg, fg="#fff"):
    return core_ui.span(text, style=f"display:inline-block;padding:1px 8px;border-radius:10px;"
                                    f"background:{bg};color:{fg};font-size:0.78em;font-weight:600;"
                                    f"margin-right:6px;{_PRINT_EXACT}")

def _progress(pct, dark=False, height=14):
    pct = max(0.0, min(100.0, pct))
    track = "rgba(255,255,255,0.3)" if dark else "#e9ecef"
    return core_ui.div(
        core_ui.div(
            core_ui.div(style=f"width:{pct:.1f}%;height:100%;background:{band_color(pct)};"
                              f"border-radius:7px;{_PRINT_EXACT}"),
            style=f"flex:1;height:{height}px;background:{track};border-radius:7px;"
                  f"overflow:hidden;{_PRINT_EXACT}"),
        core_ui.span(f"{pct:.0f}%", style=f"min-width:3em;text-align:right;font-weight:700;"
                                          f"color:{'#fff' if dark else '#212121'};"),
        style="display:flex;align-items:center;gap:8px;")

def _tier_banner(t):
    n_total = len(t["met"]) + len(t["gaps"])
    return core_ui.div(
        core_ui.div(
            core_ui.h4(t["label"], style="margin:0;color:#fff;"),
            core_ui.span(f"{_pts(t['earned'])} / {_pts(t['possible'])} pts · "
                         f"{len(t['met'])} of {n_total} recommendations complete",
                         style="color:#fff;opacity:0.9;font-size:0.9em;"),
            style="display:flex;justify-content:space-between;align-items:baseline;"
                  "flex-wrap:wrap;gap:8px;margin-bottom:6px;"),
        _progress(t["pct"], dark=True),
        style=f"background:{TIER_COLORS.get(t['key'], '#37474f')};padding:12px 16px;"
              f"border-radius:8px;margin:20px 0 10px 0;break-after:avoid;{_PRINT_EXACT}")

def _plan_fields(r, entry):
    sid = _sid(r["id"])
    did = f"ap_date_{sid}"
    return core_ui.div(
        core_ui.div(
            core_ui.div(
                core_ui.input_text(f"ap_own_{sid}", "Accountable owner",
                                   value=entry.get("owner", ""), placeholder="Name and/or role",
                                   width="100%"),
                class_="col-md-7"),
            core_ui.div(
                core_ui.tags.label("Target date of completion", for_=did, class_="form-label"),
                core_ui.tags.input(
                    type="date", id=did, value=entry.get("date", ""), class_="form-control",
                    onchange="Shiny.setInputValue(this.id, this.value, {priority: 'event'});"),
                class_="col-md-5 mb-3"),
            class_="row g-2"),
        core_ui.input_text_area(f"ap_note_{sid}", "Implementation notes",
                                value=entry.get("notes", ""), rows=3, width="100%",
                                placeholder="Approach, resources, milestones, barriers…"),
        class_="ap-fields",
        style="border-top:1px dashed #c5d3e3;margin-top:8px;padding-top:8px;")

def _rec_card(r, entry=None):
    label, col = _OUTCOME_STYLE[r["outcome"]]
    title = f"Strengthen: {r['title']}" if r["outcome"] == "partial" else r["title"]
    selectable = entry is not None
    selected = bool(selectable and entry.get("selected"))
    comp_lines = [core_ui.div(f"{COMP_STATUS[c['status']]} {c['label']} "
                              f"({_pts(c['earned'])}/{_pts(c['possible'])} pts)",
                              style="font-size:0.85em;") for c in r["comps"]]
    header = core_ui.div(
        core_ui.div(_chip(f"D{r['domain']}", "#455a64"), _chip(label, col),
                    _chip(r["id"], "#eceff1", "#37474f")),
        core_ui.input_checkbox(f"ap_sel_{_sid(r['id'])}", "Add to my plan", value=selected)
        if selectable else None,
        style="display:flex;justify-content:space-between;align-items:flex-start;"
              "gap:8px;flex-wrap:wrap;")
    return core_ui.div(
        header,
        core_ui.h5(title, style="margin:6px 0;"),
        core_ui.div(*comp_lines, style="background:#f7f9fb;border-radius:6px;"
                                       "padding:6px 10px;margin-bottom:6px;") if comp_lines else None,
        core_ui.markdown(_rec_body(r)),
        _plan_fields(r, entry) if selectable else None,
        class_="ap-card" + (" ap-selected" if selected else ""),
        style=f"border:1px solid #dde3ea;border-left:5px solid {col};border-radius:6px;"
              f"padding:10px 14px;margin-bottom:10px;break-inside:avoid;{_PRINT_EXACT}",
        **{"data-rec": r["id"]})

def _plan_summary(ev, te, tp, ctx):
    overall = te / tp * 100 if tp else 0
    yn = lambda k: "Yes" if str(ctx.get(k, "yes")).lower() != "no" else "No"
    head = [core_ui.tags.th("Tier"), core_ui.tags.th("Progress", style="min-width:180px;"),
            core_ui.tags.th("Points", style="text-align:center;"),
            core_ui.tags.th("Complete", style="text-align:center;")]
    head += [core_ui.tags.th(f"D{d}", style="text-align:center;") for d in DOMAIN_ITEMS]
    rows = []
    for t in ev["tiers"]:
        cells = [core_ui.tags.td(core_ui.strong(t["label"])), core_ui.tags.td(_progress(t["pct"])),
                 core_ui.tags.td(f"{_pts(t['earned'])}/{_pts(t['possible'])}", style="text-align:center;"),
                 core_ui.tags.td(f"{len(t['met'])}/{len(t['met']) + len(t['gaps'])}",
                                 style="text-align:center;")]
        for d in DOMAIN_ITEMS:
            e, p = t["by_domain"].get(d, (0.0, 0.0))
            cells.append(_pct_cell(e / p * 100, title=f"{_pts(e)}/{_pts(p)} pts") if p
                         else core_ui.tags.td("—", style="text-align:center;color:#999;"))
        rows.append(core_ui.tags.tr(*cells))
    return core_ui.div(
        core_ui.p(core_ui.strong("Overall G-ASET score: "), f"{te:g} / {tp:g} ({overall:.0f}%)",
                  core_ui.tags.br(),
                  core_ui.tags.small(f"Context — microbiology laboratory access: {yn('micro')} · "
                                     f"electronic data sources: {yn('ehr')}", class_="text-muted")),
        core_ui.tags.table(core_ui.tags.thead(core_ui.tags.tr(*head)), core_ui.tags.tbody(*rows),
                           class_="table table-sm table-bordered align-middle"),
        core_ui.tags.small("Tier progress = G-ASET points earned ÷ points possible for the practices "
                           "in that tier (context-excluded practices omitted). Hover a domain cell "
                           "for points.", class_="text-muted"))
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

def _read_6c(fields):
    """True if any 6C (team leader) answer is Yes; None if no 6C fields exist.
    VERIFY field names/values in the Diagnostics field map."""
    names = [n for n in fields if re.match(r"^\s*6\s*C\b", str(n), re.IGNORECASE)]
    if not names:
        return None
    for n in names:
        v = fields[n].get("/V")
        if v is None:
            continue
        s = str(v).lstrip("/").strip().lower()
        if s in ("0", "yes", "y", "on", "true"):
            return True
    return False

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
    special["35A"] = [_is_35a_yes(fv(fn)) for fn in THIRTYFIVE_A_FIELDS]   # A..R in order
    special[35] = sum(special["35A"])
    special["6C"] = _read_6c(fields)
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

def _truncate(s, n):
    return s if len(s) <= n else s[:n - 1] + "…"

def svg_domain_bar_chart(domains, te, tp, overall_label="OVERALL", width=900):
    """Horizontal bar chart of domain % with traffic-light colors (dependency-free SVG)."""
    esc = _html.escape
    rows = [(f"D{d} · {name.split(': ', 1)[-1]}", de, dp, False) for d, name, de, dp in domains]
    rows.append((overall_label, te, tp, True))

    L, R, T, BH, GAP, EXTRA = 330, 120, 16, 26, 12, 14
    pw = width - L - R
    ys, y = [], T
    for row in rows:
        if row[3]:                 # extra space before the OVERALL bar
            y += EXTRA
        ys.append(y)
        y += BH + GAP
    plot_top, plot_bottom = T - 6, y - GAP + 6
    height = plot_bottom + 64

    def X(v):
        return L + max(0.0, min(100.0, v)) / 100 * pw

    s = [f'<svg viewBox="0 0 {width} {height}" width="100%" xmlns="http://www.w3.org/2000/svg" '
         f'style="max-width:{width}px;font-family:system-ui,-apple-system,Segoe UI,sans-serif;'
         f'font-size:12px;" role="img" aria-label="G-ASET domain scores">']

    # Traffic-light bands
    for lo, hi, col in ((0, 50, "#c62828"), (50, 80, "#f9a825"), (80, 100, "#2e7d32")):
        s.append(f'<rect x="{X(lo):.1f}" y="{plot_top}" width="{X(hi) - X(lo):.1f}" '
                 f'height="{plot_bottom - plot_top}" fill="{col}" fill-opacity="0.07"/>')
    # Gridlines + x labels
    for v in range(0, 101, 20):
        x = X(v)
        s.append(f'<line x1="{x:.1f}" y1="{plot_top}" x2="{x:.1f}" y2="{plot_bottom}" stroke="#e0e0e0"/>')
        s.append(f'<text x="{x:.1f}" y="{plot_bottom + 16}" text-anchor="middle" fill="#555">{v}%</text>')
    for v in (50, 80):
        s.append(f'<line x1="{X(v):.1f}" y1="{plot_top}" x2="{X(v):.1f}" y2="{plot_bottom}" '
                 f'stroke="#888" stroke-dasharray="4 3"/>')
    # Separator above OVERALL
    sep_y = ys[-1] - (EXTRA + GAP) / 2
    s.append(f'<line x1="10" y1="{sep_y:.1f}" x2="{width - 10}" y2="{sep_y:.1f}" stroke="#bbb"/>')

    for (label, e, p, is_overall), y in zip(rows, ys):
        pct = e / p * 100 if p else 0.0
        tip = esc(f"{label}: {e:g} / {p:g} points ({pct:.1f}%)")
        weight = 700 if is_overall else 400
        stroke, sw = ("#000", 1.5) if is_overall else ("#333", 0.5)
        s.append(f'<text x="{L - 10}" y="{y + BH / 2 + 4:.1f}" text-anchor="end" fill="#222" '
                 f'font-weight="{weight}">{esc(_truncate(label, 48))}<title>{tip}</title></text>')
        s.append(f'<rect x="{L}" y="{y}" width="{max(X(pct) - L, 1.5):.1f}" height="{BH}" rx="3" '
                 f'fill="{band_color(pct)}" stroke="{stroke}" stroke-width="{sw}">'
                 f'<title>{tip}</title></rect>')
        s.append(f'<text x="{X(pct) + 6:.1f}" y="{y + BH / 2 + 4:.1f}" fill="#222" '
                 f'font-weight="{weight}">{pct:.0f}%  ({e:g}/{p:g})</text>')

    s.append(f'<text x="{L + pw / 2:.1f}" y="{plot_bottom + 34}" text-anchor="middle" '
             f'fill="#333">Score (%)</text>')
    # Legend
    lx, ly = L, plot_bottom + 54
    for i, (col, lab) in enumerate((("#c62828", "≤ 50%"), ("#f9a825", "51–80%"), ("#2e7d32", "> 80%"))):
        x = lx + i * 110
        s.append(f'<rect x="{x}" y="{ly - 10}" width="14" height="14" rx="2" fill="{col}"/>')
        s.append(f'<text x="{x + 20}" y="{ly + 1}" fill="#333">{lab}</text>')
    s.append("</svg>")
    return "".join(s)

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

# ---------- Report Export Reactive ----------


EXPORT_TABS = [("assessment", "📝 Assessment"), ("scores", "📊 Scores"),
               ("action_plan", "🧭 Action Plan"), ("trends", "📈 Trends"),
               ("diagnostics", "🔧 Diagnostics")]
export_prefs = reactive.value({"tabs": ["assessment", "scores", "action_plan", "trends"],
                               "cover": True, "expand": False, "orientation": "portrait"})

@reactive.effect
@reactive.event(input.export_pdf)
def _open_export_modal():
    prefs = export_prefs.get()
    core_ui.modal_show(core_ui.modal(
        core_ui.p("Select the tabs to combine into one PDF (exported in tab order):"),
        core_ui.input_checkbox_group("export_tabs", None, choices=dict(EXPORT_TABS),
                                     selected=prefs["tabs"]),
        core_ui.input_checkbox("export_cover", "Include cover page", prefs["cover"]),
        core_ui.input_checkbox("export_expand",
                               "Expand collapsed sections (rule trace, field map)", prefs["expand"]),
        core_ui.input_radio_buttons("export_orientation", "Orientation",
                                    {"portrait": "Portrait", "landscape": "Landscape"},
                                    selected=prefs["orientation"], inline=True),
        core_ui.tags.small("In the print dialog choose “Save as PDF” and enable "
                           "“Background graphics” to keep score colors.", class_="text-muted"),
        title="📄 Export to PDF", easy_close=True, size="m",
        footer=core_ui.TagList(
            core_ui.modal_button("Cancel"),
            core_ui.input_action_button("export_go", "📄 Create PDF", class_="btn-success"))))

@reactive.effect
@reactive.event(input.export_go)
async def _do_export():
    chosen = list(input.export_tabs() or [])
    if not chosen:
        core_ui.notification_show("Select at least one tab to export.", type="warning", duration=4)
        return
    export_prefs.set({"tabs": chosen, "cover": input.export_cover(),
                      "expand": input.export_expand(), "orientation": input.export_orientation()})
    core_ui.modal_remove()

    labels = dict(EXPORT_TABS)
    meta = pdf_meta.get() or {}
    facility = (input.ctx_facility() or "").strip()
    stamp = date.today().isoformat()

    overall = "—"
    if parsed_domains.get():
        _per, _domains, te, tp = all_scores()
        if tp:
            overall = f"{te:g} / {tp:g} ({te / tp * 100:.0f}%)"

    safe_fac = re.sub(r"[^A-Za-z0-9_-]+", "_", facility).strip("_")
    filename = "_".join(x for x in ["GASET_Report", safe_fac, stamp] if x)

    cover = None
    if input.export_cover():
        cover = {
            "title": "G-ASET Antibiotic Stewardship Assessment Report",
            "rows": [["Facility", facility or "—"],
                     ["Source PDF", meta.get("name", "—")],
                     ["Language", meta.get("lang", "—")],
                     ["Overall score", overall],
                     ["Generated", stamp],
                     ["Sections", ", ".join(labels[t] for t in chosen)]],
            "note": "Draft decision-support output for SME review — not a substitute for "
                    "clinical judgment or local guideline alignment.",
        }

    core_ui.notification_show("Preparing PDF — rendering selected tabs…", duration=3)
    session = get_current_session()
    if session is not None:
        await session.send_custom_message("gaset_export_pdf", {
            "tabs": [{"value": t, "label": labels[t]} for t in chosen],
            "cover": cover,
            "expand": bool(input.export_expand()),
            "orientation": input.export_orientation(),
            "paper": "letter",          # change to "A4" for international users
            "filename": filename,
            "max_wait_ms": 8000,
        })

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
    return {"micro": input.ctx_micro(), "ehr": input.ctx_ehr()}

@reactive.calc
def action_plan_eval():
    per, _domains, _te, _tp = all_scores()
    return evaluate_tiers(per, pdf_special.get(), action_plan_ctx(), ACTION_PLAN_TEMPLATE)

@reactive.calc
def action_plan_md():
    _per, _domains, te, tp = all_scores()
    return build_action_plan_md(action_plan_eval(), te, tp,
                                facility=(input.ctx_facility() or "").strip(),
                                ctx=action_plan_ctx())
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
    ui.input_action_button("export_pdf", "📄 Export to PDF", class_="btn-success", width="100%")

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
    with ui.nav_panel("📝 Assessment", value = "assessment"):
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

    # ---------------- Tab 2: Scores ----------------
    with ui.nav_panel("📊 Scores", value = "score"):
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
            ui.card_header("📊 Domain score chart")

            @render.ui
            def domain_score_chart():
                cfg = LANGS[current_lang.get()]
                if not parsed_domains.get():
                    return core_ui.p(cfg["ui_scores_later"], class_="text-muted")
                _per, domains, te, tp = all_scores()
                return core_ui.HTML(svg_domain_bar_chart(domains, te, tp, cfg["ui_overall"]))

    # ---------------- Tab 3: Action Plan ----------------
    with ui.nav_panel("🧭 Action Plan", value="action_plan"):
        with ui.layout_columns(col_widths=[3, 9]):
            with ui.card():
                ui.card_header("⚙️ Facility context")
                ui.input_text("ctx_facility", "Facility name (optional)", "")
                ui.input_radio_buttons(
                    "ctx_micro",
                    "Does the facility have access to a clinical microbiology laboratory "
                    "(on-site or off-site)?",
                    {"yes": "Yes", "no": "No"}, selected="yes", inline=True)
                ui.input_radio_buttons(
                    "ctx_ehr",
                    "Does the facility have access to electronic data sources "
                    "(e.g., electronic health record, electronic pharmacy or laboratory data)?",
                    {"yes": "Yes", "no": "No"}, selected="yes", inline=True)
                ui.input_switch("ap_show_completed", "Expand completed recommendations", False)
                core_ui.tags.small("Recommendations that depend on a resource answered “No” are "
                                   "hidden and excluded from tier progress.", class_="text-muted")
                core_ui.tags.hr()
                core_ui.h6("📝 My action plan")

                @render.ui
                def ap_plan_status():
                    store = plan_store.get()
                    sel = [k for k, v in store.items() if v.get("selected")]
                    if not sel:
                        return core_ui.p("Tick “Add to my plan” on any recommendation to start "
                                         "building a customized plan.", class_="text-muted small")
                    no_owner = sum(1 for k in sel if not (store[k].get("owner") or "").strip())
                    no_date = sum(1 for k in sel if not store[k].get("date"))
                    overdue = sum(1 for k in sel if _is_overdue(store[k].get("date", ""), "gap"))
                    notes = [f"{no_owner} without an owner"] if no_owner else []
                    notes += [f"{no_date} without a target date"] if no_date else []
                    notes += [f"⚠️ {overdue} past due"] if overdue else []
                    return core_ui.p(core_ui.strong(f"{len(sel)} recommendation(s) selected"),
                                     core_ui.tags.br(),
                                     core_ui.tags.small(" · ".join(notes) or "✅ All have owners and dates",
                                                        class_="text-muted"))

                ui.input_switch("ap_only_selected", "Show only my selected recommendations", False)

                @render.download(label="⬇️ My plan (.md)",
                                 filename=lambda: f"gaset_custom_plan_{date.today().isoformat()}.md")
                def download_custom_plan_md():
                    yield build_custom_plan_md(action_plan_eval(), plan_store.get(),
                                               facility=(input.ctx_facility() or "").strip())

                @render.download(label="⬇️ My plan (.csv)",
                                 filename=lambda: f"gaset_custom_plan_{date.today().isoformat()}.csv")
                def download_custom_plan_csv():
                    buf = io.StringIO(); w = csv.writer(buf)
                    w.writerow(["rec_id", "selected", "tier", "domain", "title", "current_status",
                                "accountable_owner", "target_date", "implementation_notes",
                                "recommended_action"])
                    for x in _custom_plan_rows(action_plan_eval(), plan_store.get()):
                        r = x["r"]
                        w.writerow([r["id"], "yes", x["tier"], r["domain"], r["title"],
                                    x["status"].split(" ", 1)[-1], x["owner"], x["date"],
                                    x["notes"], _rec_body(r)])
                    yield "\ufeff" + buf.getvalue()      # BOM so Excel shows accents correctly

                ui.input_file("ap_import", "Resume a saved plan (.csv)", accept=[".csv"], multiple=False)
                ui.input_action_button("ap_clear", "Clear all selections",
                                       class_="btn-outline-danger btn-sm")

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
                    ev = action_plan_eval()
                    _per, _d, te, tp = all_scores()
                    _ = plan_ui_version.get()                  # re-render after import / clear
                    with reactive.isolate():                   # typing never triggers a re-render
                        store = plan_store.get()
                    entry = lambda r: store.get(r["id"], _EMPTY_ENTRY)
                    open_attr = {"open": ""} if input.ap_show_completed() else {}

                    parts = [_plan_summary(ev, te, tp, action_plan_ctx())]
                    for t in ev["tiers"]:
                        tier_parts = [_tier_banner(t)]
                        if t["gaps"]:
                            tier_parts.extend(_rec_card(r, entry(r)) for r in t["gaps"])
                        else:
                            tier_parts.append(core_ui.p(
                                "✅ All recommendations in this tier are in place.",
                                class_="ap-tier-allmet", style="color:#2e7d32;font-weight:600;"))
                        if t["met"]:
                            tier_parts.append(core_ui.tags.details(
                                core_ui.tags.summary(f"✅ {len(t['met'])} completed recommendation(s) "
                                                     f"— click to show",
                                                     style="cursor:pointer;color:#2e7d32;font-weight:600;"),
                                *[_rec_card(r, entry(r)) for r in t["met"]],
                                style="margin:6px 0 10px 0;", **open_attr))
                        if t["hidden"]:
                            tier_parts.append(core_ui.tags.details(
                                core_ui.tags.summary(f"🚫 {len(t['hidden'])} not applicable in this context",
                                                     style="cursor:pointer;color:#757575;"),
                                core_ui.tags.ul(*[core_ui.tags.li(f"{r['title']} — {r['reason']}")
                                                  for r in t["hidden"]], style="font-size:0.9em;"),
                                class_="ap-hidden-list", style="margin:6px 0 10px 0;"))
                        parts.append(core_ui.div(*tier_parts, class_="ap-tier"))
                    return core_ui.TagList(*parts)

        with ui.card():
            ui.card_header("🔍 Why these recommendations? (rule trace)")

            @render.ui
            def action_plan_trace():
                if not parsed_domains.get():
                    return core_ui.p("Upload a recognized G-ASET PDF first.", class_="text-muted")
                ev = action_plan_eval()
                stems = item_stems.get()
                tier_label = dict(ev["meta"]["tiers"])
                rows = []
                for r in ev["recs"]:
                    label, col = _OUTCOME_STYLE[r["outcome"]]
                    comps = core_ui.TagList(*[core_ui.div(
                        f"{COMP_STATUS[c['status']]} {c['label']} "
                        f"({_pts(c['earned'])}/{_pts(c['possible'])}) ",
                        core_ui.tags.small(_item_label(c["item"], stems, 70), class_="text-muted"))
                        for c in r["comps"]])
                    rows.append(core_ui.tags.tr(
                        core_ui.tags.td(core_ui.tags.code(r["id"])),
                        core_ui.tags.td(tier_label.get(r["tier"], r["tier"])),
                        core_ui.tags.td(r["title"]),
                        core_ui.tags.td(core_ui.span(label, style=f"color:{col};font-weight:600;")),
                        core_ui.tags.td(comps),
                        core_ui.tags.td(core_ui.tags.small(r["reason"]))))
                problems = (core_ui.div(
                    core_ui.strong("⚠️ Template checks:"),
                    core_ui.tags.ul(*[core_ui.tags.li(p) for p in ev["problems"]]),
                    style="background:#fff3cd;border:1px solid #ffe08a;border-radius:6px;"
                          "padding:8px 12px;margin-bottom:8px;")
                    if ev["problems"] else
                    core_ui.p("✅ Template checks passed: every G-ASET item and item-35 activity "
                              "is assigned exactly once.", style="color:#2e7d32;"))
                counts = {k: sum(1 for r in ev["recs"] if r["outcome"] == k)
                          for k in ("gap", "partial", "met", "hidden")}
                return core_ui.TagList(problems, core_ui.tags.details(
                    core_ui.tags.summary(f"{counts['gap']} not in place · {counts['partial']} partial · "
                                         f"{counts['met']} complete · {counts['hidden']} not applicable"),
                    core_ui.tags.table(
                        core_ui.tags.thead(core_ui.tags.tr(
                            core_ui.tags.th("Rule"), core_ui.tags.th("Tier"),
                            core_ui.tags.th("Recommendation"), core_ui.tags.th("Outcome"),
                            core_ui.tags.th("Linked practices"), core_ui.tags.th("Reason"))),
                        core_ui.tags.tbody(*rows),
                        class_="table table-sm", style="font-size:0.85em;")))
            
    # ---------------- Tab 4: Trends (time series) ----------------
    with ui.nav_panel("📈 Trends", value = "trends"):
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
    with ui.nav_panel("🔧 Diagnostics", value = "diagnostics"):
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