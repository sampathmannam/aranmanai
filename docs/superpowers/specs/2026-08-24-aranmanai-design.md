# Aranmanai — Design Spec

**Date**: 2026-08-24
**Status**: Approved (user "go" confirmed)
**Author**: Sampath M (IPS, SP), with Mavis/Kaavalan-OS assist
**Scope**: Lean solo v1, single district, 8-12 weeks, no state-platform integration

## 1. Mission and name

**Name**: Aranmanai (அரண்மனை — "Citadel/Fortress", Tamil). District-scoped conviction-rate management platform.

**Mission**: increase the district conviction rate 30-50% within 12 months by tracking every case from charge sheet to judgment, coordinating with prosecutors daily, preparing witnesses for cross-examination, and using AI to draft FIRs/chargesheets in minutes instead of hours.

**Why Aranmanai**: Tamil name, fits an SP's voice-first + multilingual + IPS register, signals the system's role as the operational fortress that protects the case through the trial.

## 2. Scope (Lean v1)

- 1 SP's district only
- ~50 active cases
- 5-10 IOs
- 1-2 Public Prosecutors (PP)
- Workstation deployment: Ryzen 7 7435HS + 16GB RAM + RTX 2050 4GB + 123GB disk
- Free stack only
- No real CCTNS / eSakshya / ICJS integration in v1 (mock adapters only, swap when DGP/SCRB approves)

## 3. Architecture (8 components)

### 3.1 Case database (SQLite + SQLCipher)

| Table | Key columns |
|---|---|
| `case` | `case_id` (PK), `FIR_no`, `BNS_sections[]`, `BNSS_sections[]`, `BSA_sections[]`, `IO_id` (FK), `district`, `court`, `judge`, `PP_id` (FK), `status` (open/hearing/judgment/appeal), `stage` (investigation/charge_sheet/trial/argument/judgment), `next_hearing`, `last_update` |
| `witness` | `witness_id` (PK), `case_id` (FK), `name`, `type` (eyewitness/victim/expert/official), `category` (Supportive/Neutral/Hostile), `contact`, `language`, `last_contact`, `prep_status` (untouched/prepped/ready/testified), `hostile_reason` |
| `hearing` | `hearing_id` (PK), `case_id` (FK), `date`, `stage`, `accused_present` (bool), `witness_present_ids[]`, `PP_present` (bool), `defense_present` (bool), `outcome`, `next_action` |
| `evidence` | `evidence_id` (PK), `case_id` (FK), `type` (document/witness/FSL/electronic), `chain_status` (sealed/broken/pending), `fsl_status` (sent/returned/overdue), `CCTV_available` (bool) |
| `user` | `user_id` (PK), `name`, `role` (SP/IO/PP/Admin), `district`, `last_login` |
| `audit_log` | `log_id` (PK), `actor_id` (FK), `action`, `case_id` (FK nullable), `timestamp`, `prev_hash`, `hash` — hash-chained, SHA256 |

**Storage**: `~/Aranmanai/data/aranmanai.db` SQLCipher-encrypted, AES-256. Backup daily to encrypted USB (DPDP §8(4)).

### 3.2 Court Monitoring System (CMS) — operational core

This is the module Dheeraj and Kishore proved moves conviction rate. Pattern sources:
- Dheeraj Kunubilli (Annamayya SP, IPS 2020): daily case calendar, witness categorization, bottleneck detection, monthly review.
- Kishore Kommi (Eluru SP, IPS 2019): Court Monitoring Cell with accountability from charge-sheet to judgment, daily review, witness production, prosecutor coordination.

| Sub-module | Function |
|---|---|
| Daily case calendar | Today's hearings + this week + this month, sortable by case/court/judge |
| Per-case timeline | FIR → charge sheet → every hearing → next action, visual progress |
| Witness categorization | Per case: mark each witness Supportive/Neutral/Hostile + reason |
| Bottleneck detector | Cases stuck at stage X > Y days (configurable threshold) |
| Witness presence tracker | For each upcoming hearing, which witnesses confirmed to attend |
| Prosecutor coordination | Per-case chat/notes; PP flags missing prep, IO flags missing evidence |
| SP daily review dashboard | Cases at risk, witnesses to prep today, hearings to attend |

### 3.3 AI assist module (Ollama + local LLM)

Dharma-style AI. Runs on RTX 2050. Pattern source: Kishore's Dharma App (complaint intake, FIR drafting, case diary drafting, chargesheet drafting, investigation recommendations, "first truth" preservation).

| Sub-module | Input | Output | Model |
|---|---|---|---|
| Complaint intake | Voice (Tamil/English/Hindi) or text | Structured complaint draft | Phi-3.5-mini |
| FIR drafting | Structured complaint + BNS/BNSS/BSA sections | FIR draft (reviewable, editable) | Phi-3.5-mini + RAG |
| Case diary drafting | Investigation timeline + witness statements | Case diary entry (editable) | Phi-3.5-mini + RAG |
| Chargesheet drafting | Facts + evidence + sections | Chargesheet draft (editable) | Phi-3.5-mini + RAG |
| Investigation recommendations | Case type + detected lapses | Cure suggestions | Phi-3.5-mini + RAG on BPRD/Vidhi/Quint |
| Cross-examination prep | Witness statement + case facts | Likely defense questions + suggested talking points | Phi-3.5-mini + RAG on prior judgments |
| Acquittal-risk score (advisory) | Case features | Risk score 0-1 + ranked case list + cure actions | LightGBM + RAG |

**Rule**: every AI output requires IO/PP review and approval before persistence. No auto-apply.

### 3.4 Witness preparation module

The Nyaya Sahayak layer. Pattern source: Kishore's witness-prep system (cross-examination prep for hostile-witness mitigation). Academic evidence base: Leeds 60-mock-witness study showed "prepared witnesses significantly more likely than their unprepared counterparts to provide correct responses" (Ellison et al.).

| Sub-module | Function |
|---|---|
| Witness file | Name, contact, 157 CrPC/161 BNSS statement, hostile_reason, prep_status |
| Cross-examination prep | AI generates 10-15 likely defense questions; IO/PP review + customize |
| Witness protection tracking | Location, risk level, support provided (escort, identity protection, in-camera per BNSS §327) |
| Court attendance history | Which hearings witness attended, performance (calm/nervous/contradicted), defense questions asked, judge notes |
| Voice/text notes per witness | IO/PP voice notes via mobile browser |

### 3.5 Voice + Tamil support

- **Voice intake** for complaint (Whisper.cpp, Tamil + English + Hindi)
- **Voice transcription** for witness statements
- **Voice daily review** (SP dictates notes; system transcribes + indexes)
- **Tamil UI** via IndicTrans2 (auto-translate English UI strings, switchable per user)
- **TTS** for CMS calendar readouts (Silero / Piper)

### 3.6 Acquittal-risk predictor (lightweight, advisory)

Kishore's system doesn't have explicit P(conviction). nyaya-ai has it. Carry the nyaya-ai version as **advisory output only**, not a hard gate.

Features (5-7):
1. Witness count (int)
2. Hostile witness ratio (float 0-1)
3. FSL evidence gaps (bool)
4. CCTV available (bool)
5. Section 173 BNSS compliance (bool — eSakshya AV recording done)
6. IO experience (years)
7. Court + judge (one-hot or embedding)

Model: LightGBM regression → probability. Calibrated on synthetic + 178 real HC/SC judgments. **Advisory, not deterministic.** IO/PP make final calls.

### 3.7 Mock state-platform integration layer

Shaped to real contracts. Real integration deferred to v2 (after DGP sign-off). Pattern source: state platforms exist (eSakshya, Nyaya Shruti, ICJS) but none fill the conviction-probability axis.

| Mock adapter | Real contract | Use |
|---|---|---|
| `mock_cctns.py` | CCTNS Core Application Software JSON schema (CAS v5.0) | Case import + export |
| `mock_esakshya.py` | SID packet schema (16-digit SID + hash + geo + timestamps) | Evidence chain validation |
| `mock_icjs.py` | ICJS CNR/case_id cross-reference | Match local cases to court CNRs; sync hearing dates |

v1 reads/writes local JSON shaped like the real API. Swap-in the real adapter when DGP/SCRB approves. v1 never claims to integrate with state — the mock is honest.

### 3.8 DPDP / audit compliance

- **Hash-chained audit log** of every read/write (hashlib SHA256, prev_hash in each entry)
- **DPDP §8(3) fields**: subject_id (case_id or witness_id), fields_used, success flag, timestamp
- **Encryption at rest**: SQLCipher AES-256
- **No cloud upload of PII**: all storage local; cloud only for anonymous aggregate analytics
- **Data subject rights** (DPDP §12): one-click export + delete a witness's data on request

## 4. Tech stack

| Layer | Choice | Why |
|---|---|---|
| Backend | Python 3.11 + FastAPI | Standard, fast, async, free |
| DB | SQLite + SQLCipher | Single-file, no ops, encrypted, workstation-ready |
| LLM | Ollama + Phi-3.5-mini (3.8B, 4-bit Q4_K_M) | Runs on RTX 2050 4GB, multilingual, good instruction following |
| Vector store | ChromaDB | For RAG on BNS/BNSS/BSA + similar-case retrieval |
| ML | LightGBM + scikit-learn | Acquittal-risk model, 5-7 features, fast, interpretable |
| STT | Whisper.cpp (small) | Local, multilingual, accurate |
| TTS | Silero / Piper | Local, Tamil-friendly |
| Translation | IndicTrans2 (AI4Bharat) | Tamil ↔ English, free |
| Frontend | Streamlit (v1) → plain HTML+JS (v2) | Streamlit is faster to build, HTML+JS more deployable |
| Encryption | SQLCipher, hashlib | DPDP §8(4) |
| Backup | rclone + S3 (optional, encrypted) | DPDP §8(4) |
| Testing | pytest | Standard |

**Hardware target**: Ryzen 7 7435HS + 16GB RAM + RTX 2050 4GB + 123GB free disk. All of the above runs on this. Inference on GPU (4-bit Q4_K_M), DB on disk, vector store in memory.

## 5. Honest trade-offs (so the user can decide)

| Trade-off | v1 Lean choice | Cost | Mitigation |
|---|---|---|---|
| No real CCTNS | Mock JSON adapter | You enter cases manually from CCTNS data | DGP sign-off swaps real in; meanwhile the mock shapes your data to the real contract |
| No real eSakshya | Mock SID validation | You don't get immutable eSakshya storage for evidence | Evidence still stored locally; eSakshya is the *court-facing* store, not the *investigation* store |
| Single SP district | No multi-tenant | Can't deploy to other districts without code changes | v2 multi-tenant designed in (DB has `district` column from day 1) |
| Phi-3.5-mini 4-bit | Lower accuracy than GPT-4 / Claude | AI drafts need more IO review | Prompts include 5-shot examples; IO must approve every output |
| Local-only LLM | No GPU cloud burst | Long generation on big cases | RTX 2050 handles 1-2 concurrent requests fine; queue if more |
| Workstation-only | No tablet/mobile in court | IOs use laptop/phone browser | Streamlit renders mobile-friendly; voice input works on phone browser |
| 1 SP, 0 team | Single point of failure | If you stop, work stops | Plan: train 1 IO as backup by month 6; if pilot succeeds, get DGP to fund 1 engineer |
| 8-12 week build | Steep ramp | Lots to do at once | Phased, with weekly demo; not a 12-month waterfall |
| Mock state integration | Real ADSI/eSakshya/ICJS don't sync | You re-enter data from CCTNS | Data shapes match real contracts; swap is a 1-line adapter change |

## 6. Quality gates (run at each phase end)

- Unit tests on every CRUD operation (pytest)
- AI eval: 20-sample eval of FIR/chargesheet draft quality (graded 1-5 by user)
- DPDP audit log check: every action recorded with hash chain intact
- Mock integration test: import sample CCTNS JSON, verify local schema matches
- Weekly demo: user sees the system run on a real case for 10 minutes
