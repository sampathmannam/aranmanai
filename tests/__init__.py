"""Aranmanai pytest suite.

Layout:
- tests/test_db.py            — engine, SQLCipher PRAGMA, init, session
- tests/test_security.py      — bcrypt, JWT, hash-chained audit
- tests/test_auth.py          — login, /me, require_roles
- tests/test_cases.py         — case CRUD
- tests/test_witnesses.py     — witness CRUD + categorization
- tests/test_hearings.py      — hearing CRUD
- tests/test_evidence.py      — evidence CRUD
- tests/test_cms.py           — daily-calendar, cases-at-risk, bottlenecks, witness-prep
- tests/test_integrations.py  — mock CCTNS / eSakshya / ICJS round-trip
- tests/test_ai.py            — LLM client (mock backend) + prompt templates

All tests use a per-test SQLite file under /tmp (deleted on teardown).
"""
