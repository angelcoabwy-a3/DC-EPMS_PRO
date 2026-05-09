# DC-EPMS PRO — LOTO Auditor Demo Script

**Target audience**: Microsoft CO+I CET Lead Architect panel
**Duration**: 10 minutes (8 min demo + 2 min Q&A buffer)
**Recording**: OBS Studio with split-screen (terminal left, browser/swagger right)
**Purpose**: Demonstrate Wilmer Y. Angel Beltran's V9 capabilities for the
hyperscale Tier IV AI factory operations role

---

## Pre-Recording Checklist (45 minutes prep)

### Environment Setup

```powershell
# 1. Verify clean state
cd C:\dev\DC-EPMS_PRO
git status                                       # should show working tree clean
.\validate_batch3.ps1                            # 8 of 8 layers PASS, 412 tests
git log --oneline --decorate -n 10               # show 10 commits with tags

# 2. Activate main.py if not done already
.\apply_main_py_activation.ps1                   # 2-line activation
.\verify_loto_endpoint.ps1                       # smoke test endpoints

# 3. Seed demo procedures (so live-demo is deterministic)
python demo_seed_procedures.py

# 4. Start FastAPI service (foreground for live recording)
.\.venv\Scripts\Activate.ps1
uvicorn backend.main:app --host 127.0.0.1 --port 8080 --log-level warning

# 5. In SECOND terminal: pre-warm the system
curl http://127.0.0.1:8080/api/health
curl http://127.0.0.1:8080/api/loto/audits/recent
```

### Recording Setup

- [ ] Resolution: 1920x1080 minimum (1440p ideal)
- [ ] Font: 14pt monospace, terminal background dark
- [ ] Notepad with talking points OPEN on second monitor (not visible in recording)
- [ ] Microphone test: 30-second voice memo, listen back
- [ ] Browser tab pinned: `http://127.0.0.1:8080/docs` (Swagger UI)
- [ ] Code editor tab pinned: `backend/loto_auditor_agent.py` open at `audit()` method
- [ ] ADR-009 file open in second editor tab

### Pre-Demo Sanity Check (run silently before recording)

```powershell
# Confirm all the live commands you will run actually work
Invoke-RestMethod -Uri http://127.0.0.1:8080/api/health
Invoke-RestMethod -Uri http://127.0.0.1:8080/api/loto/audits/recent
# Run each curl from Act 3 below to verify outputs match expectations
```

---

## Demo Arc — 5 Acts

### Act 1 — Context (45 seconds)

**Talking points** (paraphrase, do not read):

> *"Hi, I'm Wilmer. I'm a CET working on a personal project that simulates the
> Tier IV operational stack for a 67 MW AI factory — 368 racks, 800 VDC unipolar
> downstream from 35 kVAC. Path C2 sealed last week. What I want to show you in
> the next 8 minutes is a deterministic safety-critical agent I built that
> validates LOTO procedures against six engineering pillars before any CET ever
> approaches the equipment. It cites NFPA 70E, NEC 460.6, and CSA Z462-24
> verbatim. It preserves the IEC 62443 zone-and-conduit segregation by design:
> the AI is read-only and writes drafts in `pending_approval` status. The CET
> is always the approver. Let me show you."*

**Visual**: project root in terminal, `validate_batch3.ps1` running showing
8 of 8 layers PASS, 412 tests, 7 ADRs.

**On-screen text overlay** (post-production):
- *DC-EPMS PRO — Tier IV AI Factory Operations*
- *Wilmer Y. Angel Beltran*
- *Toronto Area, 2026*

---

### Act 2 — Architecture overview (90 seconds)

**Talking points**:

> *"The LOTO Auditor is one component of a larger platform with seven ADRs.
> Let me show you ADR-009 specifically — this is the architectural decision
> record for the auditor itself."*

**Commands**:

```powershell
# Show ADR-009
code docs\adr\ADR-009-loto-auditor-architecture.md
```

> *"Notice the structure: context, decision, alternatives considered (with
> reasons for rejection), consequences. This isn't a tutorial blog post —
> this is the artifact a Lead Architect produces when justifying a design
> choice to the rest of the team. Every ADR in this repo follows MADR
> formatting."*

```powershell
# Show the 7 ADRs together
ls docs\adr\
```

> *"Now let's look at the auditor architecture. Six pillars, each
> cross-checked against a different subsystem of the platform."*

**Show diagram or describe verbally**:
- **Pillar 1 — Topology Impact Radius**: cross-checked via `site_model.power_chain_for()` AND `graphrag_service.query_topology()` (defense in depth)
- **Pillar 2 — 2N Redundancy Survival**: uses `physics_engine.validate_site()` to compute SHI before and after the simulated LOTO
- **Pillar 3 — Capacitor Discharge**: enforces NEC 460.6 — minimum 60-second wait + CAT IV voltmeter verification — for any component with DC link or rated above 600V
- **Pillar 4 — Witness Gate**: classifies LOTO Level 1-4 by voltage and capacitance, enforces witness presence at Level 3+
- **Pillar 5 — Hybrid Sequential Order**: ELECTRICAL → HYDRAULIC → PURGE; mandatory PURGE for cooling chain components
- **Pillar 6 — PPE Category**: NFPA 70E §130 voltage matrix; HARD_FAIL if procedure under-specifies

```powershell
# Show file sizes to convey scope
Get-ChildItem backend\loto_auditor*.py | Select-Object Name, Length | Format-Table
```

> *"Roughly 3,200 lines of production code, 1,400 lines of tests, 60 unit
> and integration tests, all deterministic, all sub-second."*

---

### Act 3 — Live demo (4 minutes — the heart of the recording)

#### Scene 1: Audit a COMPLIANT procedure (60 seconds)

**Talking points**:

> *"Let me run an audit against a compliant procedure for a UPS unit on path A."*

**Command**:

```bash
curl -X POST http://127.0.0.1:8080/api/loto/audit `
    -H "Content-Type: application/json" `
    -d '{"procedure_id":"DEMO-UPS-COMPLIANT","target_component_id":"ups_a","cet_on_duty":"wilmer"}' `
    | python -m json.tool
```

**Expected output highlights** to point to:
- `"audit_id": "LOTO-AUDIT-..."`
- `"overall_outcome": "pass"`
- `"status": "pending_approval"`  ← *"Notice the status. The AI does NOT autonomously approve. ADR-006."*
- `"hard_fail_count": 0`
- `"decision_time_ms": <2000`
- All six pillars with `"outcome": "pass"`
- `"standards_cited": ["NFPA 70E §130", "NEC 460.6", "CSA Z462-24", ...]`

**Talking point**:
> *"Sub-2-second decision. Six pillars green. Status is pending_approval —
> per ADR-006, the agent never auto-promotes. A CET reviews and approves.
> That's the IEC 62443 zone-and-conduit boundary."*

#### Scene 2: Audit a procedure with MISSING capacitor discharge (90 seconds)

**Talking points**:

> *"Now let me run an audit against a procedure that's missing the
> capacitor discharge step. This is the kind of subtle defect that can
> kill a CET — the breaker is open, the lockout is on, but there are
> hundreds of joules sitting in the DC bus capacitors. Let's see what
> the auditor does."*

**Command**:

```bash
curl -X POST http://127.0.0.1:8080/api/loto/audit `
    -H "Content-Type: application/json" `
    -d '{"procedure_id":"DEMO-UPS-MISSING-DISCHARGE","target_component_id":"ups_a","cet_on_duty":"wilmer"}' `
    | python -m json.tool
```

**Expected output highlights**:
- `"overall_outcome": "hard_fail"`
- `"hard_fail_count": 1` (or more)
- Pillar 3 details with:
  - `"outcome": "hard_fail"`
  - `"required": true`
  - `"required_reason": "DC link present"` or `"voltage_nominal >= 600V"`
  - `"found_in_procedure": false`
  - `"citation": "NEC 460.6"`
- `"standards_cited"` includes `"NEC 460.6"`

**Talking point**:
> *"HARD_FAIL on Pillar 3. The auditor cites NEC 460.6 by section. It tells
> the CET specifically what's missing: the wait period and the voltmeter
> verification. This is **not** an LLM hallucinating — this is deterministic
> Python code that loaded the YAML procedure, scanned for the discharge
> step, and produced a verifiable verdict. I can show you the exact lines."*

#### Scene 3: Show the deterministic logic behind the verdict (90 seconds)

**Command**:

```powershell
# Open the agent at Pillar 3 method
code backend\loto_auditor_agent.py
# Navigate to: def _evaluate_capacitor_discharge(...)
```

**Talking points**:

> *"This is the Pillar 3 method. Notice: pure Python, no LLM in the
> critical path. The classification logic uses voltage_nominal and
> has_dc_link metadata from the site model. The procedure parsing uses
> a regex that finds words like 'discharge', 'wait', 'capacitor' AND
> a duration in seconds. If both are present and the duration is at
> least 60 seconds, the pillar passes. If not, HARD_FAIL with the
> NEC 460.6 citation. Every decision is traceable. Every code path is
> tested."*

```powershell
# Run the test suite for the agent
pytest tests\test_loto_auditor_pillars.py -v --tb=short -k "discharge"
```

**Talking point**:
> *"All discharge-related tests green in milliseconds. The full suite is
> 60 tests, all deterministic. CI runs them on every commit."*

#### Scene 4: Markdown report rendering (30 seconds)

**Command** (audit_id from Scene 2):

```bash
curl http://127.0.0.1:8080/api/loto/audit/$auditId/markdown
```

**Talking point**:
> *"The same report rendered as markdown. This is what the CET reads
> on the HMI tablet during shift handover. Notice the PENDING APPROVAL
> banner at the top — ADR-006 enforced visually. The CET clicks
> Approve or Reject; the audit transitions; the audit trail is preserved
> in PostgreSQL for the Tier IV seven-year retention requirement."*

---

### Act 4 — The defensive engineering (60 seconds)

**Talking points**:

> *"What I want to highlight isn't just that the auditor works — it's
> the defensive engineering around it."*

**Show**:

```powershell
# 1. The architecture diagram at /docs page
Start-Process "http://127.0.0.1:8080/docs"
# Show the 4 endpoints visible in Swagger
```

> *"Four REST endpoints. Pydantic schemas for request and response
> validation. FastAPI's automatic OpenAPI documentation. Dependency
> injection so the auditor can be tested without PostgreSQL or the
> physics engine."*

```powershell
# 2. The Honest Tech Debt Registry
code CHANGELOG.md
# Scroll to "Known Issues" or "Bug Registry"
```

> *"Honest tech debt registry. Twenty-four items. Thirteen resolved.
> Four mitigated. One open medium. Three accepted. Status precision
> matters when you're operating at Tier IV — there is no 'mostly
> fixed' — the panel needs to know exactly what they own."*

```powershell
# 3. Show that we caught 7 bugs in-session over 5 sessions
git log --oneline | findstr "fix(batch3.5)"
```

> *"Fix commits for Batch 3.5. Each one represents a bug I caught in my own
> code before it shipped. Discipline like this — caught seven bugs across
> five sessions — that's the difference between portfolio code and
> production code."*

---

### Act 5 — Wrap (30 seconds)

**Talking points**:

> *"To recap. Six pillars, each grounded in a specific standard or doctrine.
> Sixty deterministic tests. Sub-2-second decisions. ADR-006 enforced
> Deterministic Sandbox. PostgreSQL audit trail. IEC 62443 zone-and-conduit
> preserved by design. Seven ADRs documenting why each choice was made
> and what alternatives were rejected."*

> *"This is a personal project. I built it because I wanted to demonstrate
> what V9 AI-Factory speed plus Tier IV doctrine looks like in practice
> when applied to LOTO — the highest-stakes routine task in any data
> center. I'd be grateful for the opportunity to bring this discipline
> to your team."*

> *"Thank you."*

**Final visual**: terminal showing `git log --oneline -n 9` with all 9 commits
and 4 tags visible. Hold for 3 seconds before stopping recording.

---

## Fallback Scenarios (be prepared)

### If `curl` fails with connection refused
- Service not running. Restart with `uvicorn backend.main:app --port 8080`
- Always have a fallback: a JPEG of expected output ready to display

### If audit returns 404 for the demo target
- Demo seed didn't run. Run `python demo_seed_procedures.py` then retry
- Fallback: read from prepared `.json` files showing pre-recorded responses

### If LM Studio is offline (Pillar 7 LLM summary not in scope of demo)
- Don't include the `include_llm_summary=true` parameter in any curl
- The deterministic 6 pillars work without LLM

### If audio drops or noise spikes during recording
- Re-record only the affected act
- Use OBS scene transitions to mask the cut
- Final edit in DaVinci Resolve (free) or kdenlive

---

## Post-Production Notes

### Cuts to make
- Trim any "uh"s, "um"s, dead air longer than 1.5 seconds
- Cut the time spent typing curl commands — replace with cuts to clean output
- Add lower-third captions for technical terms on first use:
  - LOTO = Lockout-Tagout
  - SHI = Site Health Index
  - SPOF = Single Point of Failure
  - ADR = Architecture Decision Record
  - MOP = Method of Procedure

### Title card (3 seconds at start)
- *DC-EPMS PRO*
- *LOTO Auditor Agent — Live Demo*
- *Wilmer Y. Angel Beltran*

### End card (5 seconds)
- *Code: github.com/[your-handle]/dc-epms-pro* (only if public)
- Or: *Available for review on request*
- *wilmer.angel.beltran@email* (your professional contact)

### Length targets
- Total finished length: **8-10 minutes**
- If over 12: cut Act 4 to 30 seconds
- If under 7: extend Scene 3 with the test suite running

---

## Talking Points to Memorize (avoid reading)

1. *"Six pillars, each grounded in a specific standard"*
2. *"ADR-006 Deterministic Sandbox: AI drafts, CET approves"*
3. *"IEC 62443 zone-and-conduit preserved by design"*
4. *"Pure Python, no LLM in the critical path"*
5. *"Honest tech debt registry — twenty-four items, status precise"*
6. *"Tier IV seven-year retention requirement"*
7. *"V9 AI-Factory speed plus Tier IV doctrine"*

These are the phrases panel members will remember. Repeat them naturally.

---

## What This Demo Proves to a CO+I Panel

| Skill claimed | Demo evidence |
|---|---|
| **Architectural thinking** | 7 ADRs with alternatives + rejection rationale |
| **Standards literacy** | NFPA 70E, NEC 460.6, CSA Z462-24, IEC 62443 cited specifically |
| **Operational discipline** | 412 tests, 8/8 validation layers, atomic commits, --no-verify only when justified |
| **Safety-critical engineering** | Deterministic agent, no LLM in critical path, defense in depth (cross-checks) |
| **Honest scope reporting** | Tech debt registry, in-session bug catches, V10 deferrals documented |
| **Tier IV operational mindset** | Audit trail, pending_approval, retention awareness, IEC 62443 |
| **Hyperscale awareness** | 67 MW, 368 racks, 800 VDC, GB200 NVL72 + GB300 NVL144 specifics |

The panel walks away knowing **you can be trusted to own a problem**.

That's the bar.

---

**Good luck, Wilmer. Esto es el momento.**
