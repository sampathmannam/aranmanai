# Kishore Review — Tracking

A second, numbered review pass distinct from the P0-P2 `SECURITY_AUDIT_2026-08.md`
findings (the numbering is unfortunately reused — "item 5" below is not the same
thing as security finding H-5). Never had its own tracking doc before now; this
consolidates what previously had to be reconstructed from commit messages alone.
Created 2026-08-26.

| # | Item | Status | Commit(s) |
|---|---|---|---|
| 1 | `PPBriefing.read_at` → `recorded_at` rename | **Done** | `7bda000` |
| 2 | `UNIQUE(fir_no, district)` constraint on `Case` + migration | **Done** | `27305fd` |
| 3 | `is_pocso_or_304b_case` settable via API | **Done** | `53c5240` |
| 4 | F6 district-match enforcement | **Done** (was already correct; verified, not re-fixed) | pre-existing, verified in `api/v1/kishore_review.py:510` |
| 5 | FIR-number normalizer + `AuditLog.verify_all()` walks rotated log files | **Done** | `53c5240` (normalizer), `165f053` (verify_all rotation walk) |
| 6 | Rate-limit state is per-process; multi-worker deployment multiplies the effective limit | **Done (2026-08-26)** — was documented-only as of `954a9ce` | `954a9ce` (caveat documented), fixed this session: `security/rate_limit.py`'s `SqliteRateLimiter` (WAL-mode SQLite, atomic increment-and-check) replaces the in-process `dict`/`threading.Lock` design in `api/v1/safety.py`. Proven cross-process-safe by a test constructing two independent limiter instances against the same DB file. |

Supporting test commit: `730a38f` (7 tests covering items 1-5).

**Status as of 2026-08-26: 6/6 done.** No open items remain in this pass.
