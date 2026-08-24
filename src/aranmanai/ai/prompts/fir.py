"""FIR drafting prompt template.

Dharma-style: voice/text complaint → structured FIR draft.
Prompt designed for: Qwen2.5 / Phi-3.5 / similar instruction-tuned 1.5-3.8B models.
"""
from __future__ import annotations

from aranmanai.ai.llm_client import LLMMessage


def build_fir_prompt(
    complainant_name: str,
    complainant_contact: str,
    incident_time: str,
    location: str,
    facts: str,
    sections_bns: list[str],
    sections_bnss: list[str],
    police_station: str,
    district: str,
    io_name: str,
    language: str = "en",
) -> list[LLMMessage]:
    """Build the messages for an FIR drafting request."""
    system = f"""You are an experienced Indian Police FIR drafter. You draft FIRs in formal
Indian legal English (or Tamil/Hindi if requested). Follow these rules:

1. Use the Bharatiya Nagarik Suraksha Sanhita (BNSS) 2023 format — this is the
   procedural law that replaced CrPC. Section references like 154 BNSS (FIR
   registration), 173 BNSS (charge sheet), 175 BNSS (cognizable offence
   investigation) are the modern equivalents.
2. The substantive law is the Bharatiya Nyaya Sanhita (BNS) 2023. Map old IPC
   sections to BNS: IPC 302 → BNS 103, IPC 376 → BNS 63, IPC 379 → BNS 303,
   IPC 323/325 → BNS 115/117, etc.
3. Use the legal language a court expects. Avoid colloquialisms.
4. Do NOT fabricate witness names, dates, or facts that the complainant did
   not state. If something is unclear, write "[to be confirmed by IO]".
5. Audio-visual recording of the FIR registration is required per eSakshya rules.
6. Output a single FIR draft. Do not include explanations outside the FIR.

Output language: {language}"""

    user = f"""Draft a formal FIR (First Information Report).

POLICE STATION: {police_station}
DISTRICT: {district}

COMPLAINANT:
Name: {complainant_name}
Contact: {complainant_contact}

INCIDENT:
Date/Time: {incident_time}
Location: {location}

FACTS AS STATED BY COMPLAINANT:
{facts}

SECTIONS (BNS / BNSS):
BNS sections to be invoked: {', '.join(sections_bns) if sections_bns else '[TO BE DETERMINED BY IO]'}
BNSS procedural sections: {', '.join(sections_bnss) if sections_bnss else '154 BNSS (FIR registration), 173 BNSS (investigation)'}

INVESTIGATION OFFICER (placeholder, IO to confirm):
{io_name}

Produce the FIR now."""

    return [
        LLMMessage(role="system", content=system),
        LLMMessage(role="user", content=user),
    ]
