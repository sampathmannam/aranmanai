# Changelog

Consolidates three consecutive production-readiness passes. Not every commit
is listed individually — see `git log` for the full history.

## 2026-08-26 (follow-up) — sp_voice_dashboard prompt sanitization

Closed the one item the previous entry left explicitly unverified: H-4's
`sp_voice_dashboard.py` half. `_parse_command` now sanitizes the SP's command
text via `sanitize_for_llm()` before it reaches the LLM (the original,
unsanitized text is still kept on `raw_text` for audit fidelity). The
exploitable surface was already narrow — SP-authenticated only, and the LLM's
`intent` output is constrained to a fixed whitelist — but this closes it
anyway for defense-in-depth and consistency with every other prompt builder.
1 new test. 256/256 passing, mypy/ruff clean.

## 2026-08-26 — Remaining audit findings + real-bug cleanup

Closed out everything still open after the 2026-08-25 pass: the two partially-applied
High security findings, one crashing service with zero test coverage, a real
UTC/local date-boundary bug, and the mypy backlog (70 → 0 errors).

**Security**
- H-2 IDOR: `GET /cmc/pilot-metrics` now enforces district match for non-admin
  callers (the fix `sp_review_case` already had, extended to the other named
  exploit in the same finding).
- H-1/H-4 prompt injection: sanitization (`ai/prompts/_sanitize.py`) wired into
  the 5 drafting endpoints that never got it — `fir.py`, `chargesheet.py`,
  `investigation.py`, `case_diary.py`, `cross_exam.py`.
- H-5: `AuditLog.append()` now validates `actor_id` (rejects empty, oversized,
  or control-character values) before it enters the hash chain.
- Kishore-review item 6: rate limiting (`api/v1/safety.py`) is now
  cross-process-safe via a new `security/rate_limit.py` (`SqliteRateLimiter`,
  WAL-mode, atomic increment-and-check) — the previous in-process `dict` design
  effectively multiplied the limit by worker count under multi-process
  deployment.

**Correctness**
- Fixed a crash bug in `ai/services/sp_voice_dashboard.py`: it referenced
  attributes (`.time`, `.court`, `.ready_witnesses`, `.case_stuck`,
  `.days_since_last`, `.reason`) that don't exist on `DailyCalendarEntry` /
  `Bottleneck` — this would `AttributeError` on the first non-empty query.
  Zero test coverage previously existed for this module; 6 tests added.
- Fixed a UTC/local calendar-day boundary bug affecting "today" queries against
  UTC-stored hearing timestamps: India Standard Time is UTC+5:30, so treating a
  local date's midnight as UTC midnight misclassified ~5.5 hours of every day.
  New `core/time_utils.py` (`local_today()`, `local_day_utc_range()`) is now
  used consistently in `core/cms/{daily_calendar,sp_dashboard}.py`,
  `api/v1/{cms,cmc,coordination}.py`, and `ai/services/{cmc_loop,sp_voice_dashboard}.py`.
- Fixed a real attribute typo in `ai/ollama_client.py` (`self._model_name` —
  never defined — should have been the `model_name` property; would have
  raised `AttributeError` on the first real Ollama completion).
- Fixed a variable-reuse bug in `api/v1/coordination.py`'s daily-review builder
  where a `Witness` ORM row and a derived `DailyReviewWitness` value shared one
  variable name, risking reading the wrong object's fields.

**Type safety** — mypy: 70 errors → 0 across all 103 source files.
- `witnesses.py`: removed invalid `= None` defaults on FastAPI `Depends` params;
  `_to_response` now returns a real `WitnessResponse` instead of a bare dict.
  Same dict-vs-response-model fix applied to `cases.py` and `hearings.py`.
- `cases.py`/`hearings.py`: `class Config:` → `model_config = ConfigDict(...)`
  (Pydantic v2).
- Assorted smaller fixes: a dict-annotation, a module-attribute-as-cache
  pattern mypy correctly flagged, several `Optional`-before-`.isoformat()`
  guards, a `Literal` type alignment, and an exception-variable
  read-after-scope-exit bug in the frontend.

**Frontend**
- F-8: added a 2-second debounce cache for read-only tab GETs (any mutation
  invalidates it immediately, so refresh-after-action behavior is never
  masked).
- U-2: the full value is now recoverable in the expander body wherever the
  header truncates it (the original fix only did the truncation half).
- Found and fixed a second, previously undocumented `st.json()` PII leak in
  the AI Assist tab's "last result" replay (the audit only named the Cases tab
  instance).
- 33 new regression tests across 8 new files locking in fixes that previously
  had zero coverage (W-1/W-2 dead tabs, S-6/S-8 session handling, U-4/U-5/U-6
  PII/display gates, U-2, F-8).

**Docs**: `SECURITY_AUDIT_2026-08.md` and `FRONTEND_QA_AUDIT_2026-08.md` status
notes refreshed to match actual code state; new `KISHORE_REVIEW_TRACKING.md`
consolidates the previously commit-message-only numbered review pass.

**Still open** (deliberately not touched — needs a decision, not a fix):
- `sp_voice_dashboard.py`'s command-parsing prompt is not yet sanitized
  (lower risk by construction — see `SECURITY_AUDIT_2026-08.md` H-4 — but
  unverified, not confirmed safe).
- Tamil translation uses Helsinki-NLP/Opus-MT in code vs. IndicTrans2 in the
  original design doc — functioning, but worth confirming the substitution was
  deliberate.
- No real pilot has run yet (expected — endpoints work, zero enrolled cases).

## 2026-08-25 — Production-readiness push

- **C-4** (audit log concurrency): cross-process `filelock.FileLock` +
  bounded tail-read of the true on-disk last hash inside the lock on every
  append — the actual bug was trusting a stale in-memory `_last_hash`, not
  just "missing a lock". Crash-safety empirically verified.
- **C-5**: helpline/anonymous-report/patrol-dispatch storage moved from
  in-memory lists to real DB tables; **H-3**: rate limiting added on the same
  routes (later hardened to cross-process, see above).
- Removed an entire abandoned v0 prototype (16 dead files, broken imports).
- Backup system fixed from fully-non-functional to verified working
  (wrong `BytesIO` import, nonexistent `Settings` attributes, a WAL-sidecar
  suffix check that never matched, silent key zero-padding — all real bugs).
- CI pipeline fixed (was red on ~7 of the last 9 runs): missing required env
  vars, and the live-server test suite ran with no server started.
- Every unprefixed/misnamed env var in `.env`/`.env.example` corrected.
- Frontend: dead state removed, honest responsive layout, sidebar recovery
  verified against the real Streamlit bundle, server-side audio validation,
  real complainant capture for voice complaint intake.
- ruff: 481 → 0 errors, including a real test-hygiene bug (a duplicate-FIR
  test's failure assertion lived inside the same `try` as the `except` meant
  to catch it, so it could never actually fail).
- Test suite: 140 → 172 passing, 0 failures.
