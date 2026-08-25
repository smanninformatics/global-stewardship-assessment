@@meta
version: 2026-08 (DRAFT — pending SME validation & local guideline alignment)
maintainers: AMS/IPC SME working group
tiers: foundational 0-40 | developing 40-70 | advanced 70-100
domain_priority: 1 2 4 5 3
@@endmeta

<!-- ============ DOMAIN 1: LEADERSHIP ============ -->

@@rec id=D1-F1 domain=1 tier=foundational when=short priority=high
### Secure written leadership commitment and name accountable leads
- Obtain a brief **written statement** from facility leadership naming antibiotic stewardship (AS) as a priority.
- Designate **co‑leads** (ideally a physician + a pharmacist); if unavailable, name the HCWs responsible for improving antibiotic use.
- Charter an **AS committee** — stand‑alone or embedded in an existing IPC / Drug & Therapeutics committee — with multidisciplinary membership.

@@rec id=D1-F2 domain=1 tier=foundational,developing when=short priority=high show_if=item2<5
### Add stewardship to the facility annual plan with at least one KPI
- Insert an AS objective into the annual operating plan.
- Define **one measurable KPI** (e.g., % of priority prescriptions with documented indication) and a reporting cadence to leadership.

@@rec id=D1-F3 domain=1 tier=foundational,developing when=short priority=med show_if=item5<5
### Establish a regular committee/team meeting cadence
- Schedule **at least quarterly** committee meetings (monthly for the working team where feasible) with standing agenda items and minutes.

@@rec id=D1-D1 domain=1 tier=developing when=medium priority=high
### Formalize authority and protected time
- Give the committee explicit **decision authority** (formulary, restrictions, order‑set changes).
- Specify **protected time** for AS leads in job descriptions; pursue financial support where possible.

@@rec id=D1-A1 domain=1 tier=advanced when=long priority=med
### Embed accountability and external engagement
- Add AS KPIs to leadership scorecards; publish an **annual accountability report**.
- Join/lead **external networks or collaboratives** and contribute to national AS efforts.

<!-- ============ DOMAIN 2: RESOURCES ============ -->

@@rec id=D2-F1 domain=2 tier=foundational when=short priority=high
### Provide the minimum working resources
- Ensure the team has basic **workspace, communications, and reference access** (facility guidelines, WHO AWaRe classification).
- Secure reliable access to **pharmacy data** (antibiotics purchased/dispensed) as the starting data source.

@@rec id=D2-F2 domain=2 tier=foundational,developing when=medium priority=high show_if=ctx.micro==none
### Establish specimen referral for microbiology
- Where no on‑site laboratory exists, set up a **specimen transport/referral pathway** to a reference lab with a defined turnaround and reporting route.
- In the interim, base decisions on **syndrome‑specific empiric guidance** and local epidemiology.

@@rec id=D2-D1 domain=2 tier=developing when=medium priority=med show_if=ctx.micro!=none
### Strengthen the clinical microbiology laboratory
- Advance toward **quality control, accreditation, and a laboratory information system (LIS)**.
- Work toward timely culture & susceptibility reporting to prescribers.

@@rec id=D2-D2 domain=2 tier=developing when=medium priority=med show_if=ctx.ehr==none
### Deploy low‑tech decision support
- Introduce **printed order sets, pocket cards, and paper audit forms**; defer electronic CDSS until an EHR is available.

@@rec id=D2-A1 domain=2 tier=advanced when=long priority=med show_if=ctx.ehr==full
### Integrate electronic decision support
- Implement **CDSS in the EHR** (prospective review prompts, pre‑authorization, IV‑to‑oral triggers) and generate **syndromic/cumulative antibiograms**.

<!-- ============ DOMAIN 3: EDUCATION ============ -->

@@rec id=D3-F1 domain=3 tier=foundational when=short priority=med
### Add stewardship to onboarding and prescriber basics
- Include AS in **new‑hire induction**.
- Deliver a short **prescriber briefing** on facility treatment guidelines and the AWaRe approach.

@@rec id=D3-D1 domain=3 tier=developing when=medium priority=med
### Provide continuous training for staff and the AS team
- Offer **continuing professional development** on AS *and* IPC to clinical staff.
- Train the **AS team** specifically; extend training to rotating students/trainees.
- Provide **patient/family** education materials on appropriate antibiotic use.

@@rec id=D3-A1 domain=3 tier=advanced when=long priority=low
### Move to competency‑based, tracked education
- Adopt **role‑specific competencies**, track training coverage, and refresh curricula against updated guidelines.

<!-- ============ DOMAIN 4: STEWARDSHIP ACTIONS ============ -->

@@rec id=D4-F1 domain=4 tier=foundational when=short priority=high show_if=item31<5
### Develop 2–3 high‑yield local treatment guidelines
- Start with the **commonest syndromes** (e.g., community‑acquired pneumonia, UTI, sepsis, surgical prophylaxis).
- Each guideline must specify **first‑line agent, dose, duration, and alternatives** (e.g., penicillin allergy, oral options); align to the WHO AWaRe categories and any national guidance.

@@rec id=D4-F2 domain=4 tier=foundational,developing when=short priority=high show_if=item44==0
### Implement a documentation policy (quick win)
- Require prescribers to document **indication, dose, and planned duration** in the record for every antibiotic. High impact, low cost, no technology required.

@@rec id=D4-F3 domain=4 tier=foundational,developing when=short priority=high show_if=item39<5
### Establish a facility formulary / approved antibiotic list
- Create an **approved list** based on the national formulary and AWaRe; identify a small set of **restricted agents** for later pre‑authorization.

@@rec id=D4-F4 domain=4 tier=foundational,developing when=short priority=med show_if=item36==0
### Write SOPs for at least one core activity
- Draft a **standard operating procedure** for one activity (audit & feedback, guideline development, or a testing protocol) to make practice repeatable.

@@rec id=D4-F5 domain=4 tier=foundational when=medium priority=high
### Launch one core prescriber‑facing intervention
- Choose **prospective audit & feedback** *or* **antibiotic time‑outs (48–72h review)** based on staffing — begin on 1–2 high‑use units before scaling.

@@rec id=D4-D1 domain=4 tier=developing when=medium priority=med
### Expand facility‑wide interventions
- Add **IV‑to‑oral conversion, antibiotic allergy assessment/de‑labelling, duplicate‑therapy alerts**, and **nurse‑enabled** actions (culturing criteria, time‑out prompts).
- Operationalize **pre‑authorization** for restricted agents.

@@rec id=D4-A1 domain=4 tier=advanced when=long priority=med show_if=ctx.micro==onsite
### Deploy advanced diagnostic‑linked actions
- Integrate **rapid diagnostics, cascade/selective susceptibility reporting, TDM & PK/PD‑based dosing**, and **peer‑comparison feedback**.

<!-- ============ DOMAIN 5: TRACKING & REPORTING ============ -->

@@rec id=D5-F1 domain=5 tier=foundational when=short priority=high show_if=item54==0
### Begin measuring antibiotic use with one metric
- Start with a feasible metric: **Days of Therapy (DOT)** or **Defined Daily Doses (DDD)**, or a periodic **point‑prevalence survey (PPS)** if denominators are hard to obtain.

@@rec id=D5-F2 domain=5 tier=foundational,developing when=medium priority=med
### Track shortages and key resistance signals
- Monitor **antibiotic shortages/stockouts**; report **susceptibility/resistance rates** for key indicator organisms where data exist.

@@rec id=D5-F3 domain=5 tier=foundational,developing when=medium priority=high show_if=item66==0
### Develop and regularly update an antibiogram
- Produce a **cumulative antibiogram**; update at least annually to inform empiric guidelines.

@@rec id=D5-D1 domain=5 tier=developing when=medium priority=med show_if=item52<5
### Institute routine audits with actionable feedback
- Run regular **appropriateness audits / PPS** and return **specific action points** to prescribers, not just aggregate numbers.

@@rec id=D5-A1 domain=5 tier=advanced when=long priority=med
### Advance to outcome and unit‑level reporting
- Stratify metrics **by unit/ward**; add outcome measures (**C. difficile rates, length of stay, mortality**); report to leadership on a fixed cycle.

<!-- ============ CROSS‑CUTTING / CONTEXT ============ -->

@@rec id=CTX-TEAM domain=1 when=short priority=high show_if=ctx.team==none
### No formal AS team — designate responsibility now
- Formally name the **HCWs responsible** for antibiotic use improvement and route their work through the existing IPC or Drug & Therapeutics committee until a dedicated team is feasible.

@@rec id=CTX-FUND domain=1 when=medium priority=med show_if=ctx.funding==none
### Build the business case for dedicated time/funding
- Use these **G‑ASET results** and locally relevant metrics (consumption, appropriateness) to make a costed case to leadership for protected AS time.

@@rec id=CTX-RLS domain=4 when=short priority=med show_if=ctx.setting==resource_limited
### Prioritize high‑yield, low‑cost actions
- Emphasize **empiric syndrome‑based guidelines, an AWaRe‑based formulary, documentation of indication/duration**, and **pharmacy‑based consumption metrics** over technology‑dependent interventions.