"""Complaint intake prompt. Voice/text → structured complaint (Dharma-style)."""
from __future__ import annotations

from aranmanai.ai.llm_client import LLMMessage


def build_complaint_intake_prompt(
    raw_complaint: str,
    complainant_name: str | None = None,
    complainant_contact: str | None = None,
    language: str = "en",
) -> list[LLMMessage]:
    """Convert raw voice/text complaint into structured complaint record."""
    system = f"""You are an experienced Indian Police intake officer. A
complainant has just given you a free-form account of what happened.
Your job is to convert it into a structured complaint record that the
FIR drafter can use.

Rules:
1. Preserve the complainant's words where they are legally relevant.
   Do not paraphrase witness testimony — paraphrase the COMPLAINANT'S
   account of what the witness said.
2. Extract: time, place, persons involved, what was done, what was
   observed, what was said.
3. Identify likely BNS sections based on the facts (do not apply — that
   is the IO's call). Examples: murder (BNS 103), hurt (BNS 115/117),
   theft (BNS 303), criminal intimidation (BNS 351(2)/308).
4. Note gaps — what the complainant did NOT say but the IO should ask.
5. Do not invent facts. If the complainant said "I don't know", record
   "[complainant does not know]".
6. Note if the language is Tamil/Hindi/English and respond in same.

Output language: {language}"""

    complainant_section = ""
    if complainant_name:
        complainant_section += f"\nCOMPLAINANT NAME: {complainant_name}"
    if complainant_contact:
        complainant_section += f"\nCOMPLAINANT CONTACT: {complainant_contact}"

    user = f"""Convert the following free-form complaint into a structured
complaint record.
{complainant_section}

RAW COMPLAINT (transcribed from voice or written as text):
\"\"\"{raw_complaint}\"\"\"

Produce the structured complaint record now."""

    return [
        LLMMessage(role="system", content=system),
        LLMMessage(role="user", content=user),
    ]
