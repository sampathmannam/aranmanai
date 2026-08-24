# Aranmanai — Implementation Plan

**Date**: 2026-08-24
**Status**: Approved (user "go" confirmed)
**Companion to**: `2026-08-24-aranmanai-design.md`
**Scope**: 12-week build (Phases 0-6) + 12-month end-to-end lifecycle

## 1. Step-by-step build procedure (12 weeks)

### Phase 0 — Setup (week 1)

| Day | Task | Deliverable |
|---|---|---|
| D1-2 | Python venv, install FastAPI, SQLite, SQLCipher, pytest | `requirements.txt` + venv at `~/Aranmanai/venv/` |
| D3 | Ollama + Phi-3.5-mini pull + test inference (English + Tamil + Hindi) | LLM serving on `localhost:11434` |
| D4 | ChromaDB + ingest BNS, BNSS, BSA, BPRD studies, Vidhi POCSO study | Vector store at `~/Aranmanai/data/chroma/` |
| D5 | Whisper.cpp + Silero VAD setup + Tamil test | STT pipeline at `~/Aranmanai/stt/` |

**Phase 0 exit gate**: 3 sample inferences (FIR draft, witness prep, complaint intake) run successfully on real test data.

### Phase 1 — Database + CMS core (weeks 2-3)

| Day | Task | Deliverable |
|---|---|---|
| W2 D1-3 | SQLite schema (6 tables) + migrations | `src/db/schema.py` + `src/db/migrations/0001_initial.sql` |
| W2 D4-5 | Case CRUD APIs | `POST /case`, `GET /case/:id`, `PUT /case/:id`, `DELETE /case/:id` |
| W3 D1-3 | Witness CRUD + categorization | `POST /witness`, `PUT /witness/:id/category` |
| W3 D4-5 | Hearing log + daily calendar query | `POST /hearing`, `GET /calendar?date=YYYY-MM-DD` |

**Phase 1 exit gate**: 20 cases imported, 50 witnesses categorized, daily calendar shows correct hearings for a given date.

### Phase 2 — AI assist (weeks 4-6)

| Day | Task | Deliverable |
|---|---|---|
| W4 D1-3 | Ollama serving + RAG pipeline + LLM eval (20 test cases) | `src/ai/llm_client.py`, `src/ai/rag.py` |
| W4 D4-5 | Complaint intake (voice + text) → structured | `POST /ai/complaint-intake` |
| W5 D1-3 | FIR drafting (RAG on BNS/BNSS/BSA + sample FIRs) | `POST /ai/fir-draft` |
| W5 D4-5 | Case diary drafting | `POST /ai/case-diary-draft` |
| W6 D1-3 | Chargesheet drafting | `POST /ai/chargesheet-draft` |
| W6 D4-5 | Investigation recommendations | `POST /ai/invest-recommendations` |

**Phase 2 exit gate**: AI-graded by user on 1-5 scale; mean ≥ 3.5 on 20 test cases.

### Phase 3 — Witness preparation (weeks 7-8)

| Day | Task | Deliverable |
|---|---|---|
| W7 D1-3 | Witness file + prep_status | `PUT /witness/:id/prep` |
| W7 D4-5 | Cross-examination prep (RAG on prior cases + witness statement) | `POST /ai/cross-exam-prep` |
| W8 D1-3 | Witness protection tracking | `PUT /witness/:id/protection` |
| W8 D4-5 | Court attendance history + voice notes | `POST /witness/:id/attendance`, `POST /witness/:id/voice-note` |

**Phase 3 exit gate**: 5 witnesses cross-exam-prepped, IO/PP review shows the prep surfaces questions they hadn't thought of.

### Phase 4 — Acquittal-risk + Voice + Tamil (weeks 9-10)

| Day | Task | Deliverable |
|---|---|---|
| W9 D1-3 | LightGBM acquittal-risk model (synthetic + 178 real cases), calibration | `src/ml/risk_model.py`, `models/risk_v1.pkl` |
| W9 D4-5 | Voice intake (Whisper) for complaint | Wired to `POST /ai/complaint-intake` |
| W10 D1-3 | Tamil UI (IndicTrans2 + translated templates) | Streamlit i18n layer |
| W10 D4-5 | SP voice dashboard (Whisper for daily review) | `POST /sp/voice-review` |

**Phase 4 exit gate**: model AUC-ROC ≥ 0.7 on held-out 178 real cases; Tamil UI renders correctly; voice daily review transcribes with WER ≤ 15% on Tamil.

### Phase 5 — Mock state integration + DPDP (week 11)

| Day | Task | Deliverable |
|---|---|---|
| W11 D1-2 | Mock CCTNS adapter (read/write local JSON shaped like CAS v5.0) | `src/integrations/mock_cctns.py` |
| W11 D3-4 | Mock eSakshya adapter (SID packet validation) | `src/integrations/mock_esakshya.py` |
| W11 D5 | Mock ICJS adapter (CNR cross-reference) | `src/integrations/mock_icjs.py` |

**Phase 5 exit gate**: import a sample CCTNS JSON, verify local schema matches; SID packet round-trips; CNR cross-references a test case.

### Phase 6 — Pilot + iterate (week 12)

| Day | Task | Deliverable |
|---|---|---|
| W12 D1-3 | Pilot with 5-10 real cases in your district | `pilot_v1/` directory in `data/` with real cases |
| W12 D4-5 | Bug fixes + UX polish | Bug list + UX issues |
| W12 D6 | First weekly review of pilot data | Pilot review notes |

**Phase 6 exit gate**: 5-10 real cases fully processed (FIR + case diary + chargesheet + witnesses + 1 hearing cycle each).

## 2. End-to-end plan (12 months)

### Months 1-2: Build (per Phase 0-6 above)
**Deliverable**: Aranmanai v1.0 running on your workstation, 5-10 cases in pilot, all 8 components functional.

### Months 3-4: Real pilot in your district
- 20-30 real cases across POCSO, NDPS, murder, SC/ST, dowry
- 5-10 IOs actively using the system
- Weekly SP review
- Daily court calendar + witness prep
- **Measure**:
  - Did witness hostility decrease? (categorize all witnesses at intake, re-categorize after 1 hearing cycle)
  - Did SP dashboard surface real bottlenecks? (compare with SP's manual notes)
  - Did FIR/chargesheet drafting save IO time? (measure minutes saved per document)
- **Iterate**: UX fixes, model improvements, bug fixes

### Months 5-6: First measurement (the make-or-break moment)
- **Conviction rate** of pilot cases vs same period last year (control: similar cases not in pilot)
- **Witness hostility rate** vs baseline
- **FIR/chargesheet drafting time** (target: 50% reduction)
- **Daily SP review compliance** (target: 100%)
- **Decision**: did the system move the needle?
  - Yes → continue + scale (Months 7-9)
  - No → diagnose which layer failed and fix (e.g., IO didn't use the action plan → training; AI drafts were bad → more RAG; bottlenecks weren't real → drop the dashboard)

### Months 7-9: State conversation (if pilot succeeds)
- Pitch to TN DGP with pilot data: conviction rate change, IO time saved, witness prep effectiveness
- Negotiate CCTNS integration (real, not mock) — needs DGP sign-off + SCRB cooperation
- Negotiate eSakshya integration — NIC owns the codebase; needs state request
- **If state says yes**: swap mocks for real adapters, expand to 2-3 neighboring districts
- **If state says no**: stay solo, demonstrate at IAS/IPS academy, build reputation

### Months 10-12: Multi-district scale (if DGP approved)
- Add multi-tenant
- Onboard 2-3 neighboring SPs
- Real CCTNS/eSakshya sync
- Build prosecutor coordination module (per-case notes, witness prep sharing)
- Quarterly publication of conviction rate data (anonymized)
- Pitch for state-wide adoption (Kishore-style: AP CMS × 36 states)

## 3. What we measure at each gate

| Gate | Metric | Target |
|---|---|---|
| Phase 0 | LLM responds to 3 test cases correctly | 3/3 pass |
| Phase 1 | 20 cases imported + 50 witnesses categorized + daily calendar correct | 100% pass |
| Phase 2 | AI FIR/chargesheet draft quality (user 1-5) | Mean ≥ 3.5 on 20 cases |
| Phase 3 | Cross-exam prep surfaces novel questions | ≥ 5 novel questions per witness (PP judge) |
| Phase 4 | Acquittal-risk model AUC-ROC | ≥ 0.7 on held-out |
| Phase 4 | Tamil UI + voice WER | WER ≤ 15% on Tamil |
| Phase 5 | Mock integration round-trip | 100% pass on test JSON |
| Phase 6 | Pilot real cases fully processed | 5-10 cases end-to-end |
| Month 3 | IO time saved on FIR/chargesheet | ≥ 50% reduction |
| Month 6 | Conviction rate of pilot cases | +10% absolute vs control (≥ 20% relative) |
| Month 12 | Conviction rate, district-wide | +30-50% vs year-prior baseline |

## 4. Risk register (so the user knows what to watch)

| Risk | Likelihood | Impact | Mitigation |
|---|---|---|---|
| Phi-3.5-mini 4-bit output quality is poor on Tamil | Medium | High | Have Qwen2.5-7B-Instruct (better Tamil) as backup; benchmark W4 |
| Ollama crashes under load | Low | Medium | Limit concurrent requests to 1-2; queue the rest |
| IOs refuse to use the system | Medium | High | Onboard the 2-3 friendliest IOs first; show them a case where Aranmanai surfaced a witness they forgot to prep |
| CCTNS mock schema diverges from real schema | Medium | Medium | When DGP sign-off is in sight, get the real CAS v5.0 JSON schema from NIC and validate |
| Pilot cases show no conviction-rate change | Medium | High | This is the make-or-break moment. If it fails, the AI wasn't the bottleneck — operational coordination was. Pivot to "Aranmanai is a coordination tool" not "Aranmanai is a conviction-rate tool" |
| User loses access to workstation (hardware failure) | Low | High | Daily encrypted USB backup; second copy optional cloud KMS-encrypted |
| DPDP audit fails review | Low | Medium | Every action logs subject_id + fields_used + success; hash chain validates on read |

## 5. Out of scope (v1)

These are explicitly NOT in v1, to keep the scope tight:

- Real CCTNS / eSakshya / ICJS integration (mock only)
- Multi-tenant (single district only)
- Multi-LLM (Phi-3.5-mini only; no GPT-4 fallback)
- Mobile native apps (Streamlit browser only; responsive on phone)
- Real-time push notifications (Streamlit polls)
- Automated FIR/chargesheet filing (every AI output requires human approval)
- Witness protection operations (we track, not deliver)
- Prosecutor case management (we coordinate, they own their work)
- Court-side systems (we surface prep; we don't talk to courts directly)

## 6. Dependencies (what you need to start)

- Python 3.11.9 (you have it)
- Ollama (free, install on workstation)
- Phi-3.5-mini model pull (free, ~2GB download)
- ChromaDB (free, pip)
- Whisper.cpp (free, build from source)
- Silero VAD (free, pip)
- IndicTrans2 (free, pip; downloads ~1GB models on first use)
- BNS / BNSS / BSA PDFs (free, public — MoLJ website)
- BPRD 2012 AP study + Quint 500 dowry corpus (free, public)
- 178 real HC/SC judgments for acquittal-risk model calibration (public, from Indian Kanoon)
- CCTNS CAS v5.0 JSON schema (need to request from NIC if doing mock integration realistically; for v1 a hand-written plausible schema is enough)

## 7. Open items (for next conversation)

- Acquittal-risk model feature list — finalized in v1, can iterate
- Mock CCTNS JSON schema — write a plausible one based on NIC docs
- IndicTrans2 setup — first-time download is heavy; cache in `models/`
- DPDP §12 data subject rights — UI for "export my data" / "delete my data" — can defer to v2 if v1 only has SP/IO/PP
- Tamil voice daily review — depends on STT quality; can defer to v1.5 if WER is too high
- Calibration of acquittal-risk model — needs the 178 real cases + their outcomes; if you have those, share them in week 9
