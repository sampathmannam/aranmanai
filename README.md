# Aranmanai (அரண்மனை)

District-scoped conviction-rate management platform for Indian police. Named after the Tamil word for "Citadel" / "Fortress".

**Mission**: increase district conviction rate 30-50% in 12 months by tracking every case from charge sheet to judgment, coordinating with prosecutors daily, preparing witnesses for cross-examination, and using AI to draft FIRs/chargesheets in minutes instead of hours.

**Status**: v1 in build (Phase 0 — setup).

**Specs**:
- [Design](docs/superpowers/specs/2026-08-24-aranmanai-design.md) — the architecture (8 components, tech stack, trade-offs)
- [Plan](docs/superpowers/specs/2026-08-24-aranmanai-plan.md) — 12-week build procedure + 12-month end-to-end lifecycle

**Hardware target**: Ryzen 7 7435HS + 16GB RAM + RTX 2050 4GB + 123GB disk (workstation).

**Stack**: Python 3.11, FastAPI, SQLite + SQLCipher, Ollama + Phi-3.5-mini, ChromaDB, LightGBM, Whisper.cpp, Silero, IndicTrans2, Streamlit. Free, all open-source.

**Pattern sources**:
- Kishore Kommi (K. Prathap Siva Kishore, IPS 2019, SP Eluru): Dharma App + Court Monitoring System + Nyaya Sahayak
- Dheeraj Kunubilli (IPS 2020, SP Annamayya): Court Monitoring System with daily case calendar + witness categorization

**Constraint**: no real CCTNS / eSakshya / ICJS integration in v1. Mock adapters only, shaped to real contracts. Swap when DGP/SCRB approves.

**Author**: Sampath M (IPS, SP), with Mavis/Kaavalan-OS assist.
