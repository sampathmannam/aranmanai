"""Chargesheet drafting prompt template. Maps old CrPC §173 / new BNSS §173."""
from __future__ import annotations

from aranmanai.ai.llm_client import LLMMessage


def build_chargesheet_prompt(
    case_id: str,
    fir_no: str,
    court: str,
    accused_name: str,
    accused_address: str,
    arrest_date: str,
    sections_bns: list[str],
    facts: str,
    evidence_summary: str,
    witness_summary: str,
    io_name: str,
    language: str = "en",
) -> list[LLMMessage]:
    """Build messages for a chargesheet drafting request (BNSS §173)."""
    system = f"""You are an experienced Indian Police IO drafting a final
charge sheet (कुटुम्ब न्यायालय) under Section 173 of the Bharatiya
Nagarik Suraksha Sanhita (BNSS) 2023, which replaced CrPC §173.

Rules:
1. The charge sheet is a STATEMENT OF FACTS, not an argument. The court
   decides guilt; you present the prosecution's case.
2. Each witness statement must reference the 161 BNSS statement on file
   (replacing 161 CrPC).
3. Each piece of evidence must reference its chain-of-custody record.
4. Map old IPC sections to BNS: 302 → 103, 307 → 109, 323 → 115, 325 → 117,
   376 → 63, 379 → 303, 380 → 305, 504/506 → 351(IPC)/BNS 351(2) etc.
5. The chargesheet must be filed WITHIN the statutory period (60/90 days
   per offence).
6. Audio-visual evidence (per eSakshya) must be referenced.
7. Do NOT invent facts. If something is missing, write "[to be filled by IO]".

Output language: {language}"""

    user = f"""Draft a charge sheet (final report under Section 173 BNSS).

CASE METADATA:
Case ID (Aranmanai): {case_id}
FIR No.: {fir_no}
Court where chargesheet will be filed: {court}

ACCUSED:
Name: {accused_name}
Address: {accused_address}
Arrest date: {arrest_date}

OFFENCES (BNS sections):
{', '.join(sections_bns)}

FACTS OF THE CASE (from case diary):
{facts}

EVIDENCE SUMMARY (from case file, including chain of custody):
{evidence_summary}

WITNESS SUMMARY (with 161 BNSS references):
{witness_summary}

INVESTIGATION OFFICER (IO to verify and sign):
{io_name}

Produce the charge sheet now."""

    return [
        LLMMessage(role="system", content=system),
        LLMMessage(role="user", content=user),
    ]
