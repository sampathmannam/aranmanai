"""FIR drafting prompt template.

Dharma-style: voice/text complaint → structured FIR draft.
Prompt designed for: Qwen2.5 / Phi-3.5 / similar instruction-tuned 1.5-3.8B models.
"""
from __future__ import annotations

from aranmanai.ai.llm_client import LLMMessage
from aranmanai.ai.prompts._sanitize import delimit, sanitize_for_llm


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
    """Build the messages for an FIR drafting request.

    H-1 fix: all caller-supplied text fields (complainant details, facts,
    location/station metadata) are sanitized before being interpolated
    into the prompt, so a malicious IO/PP-entered string cannot inject
    instructions into the LLM. The large free-text "facts" field is
    additionally wrapped in <<<>>> delimiters (the biggest injection
    surface); short single-line metadata fields are sanitized in place
    to preserve the "Key: Value" prompt structure.
    """
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

    safe_sections_bns = [sanitize_for_llm(s, 200) for s in (sections_bns or [])]
    safe_sections_bnss = [sanitize_for_llm(s, 200) for s in (sections_bnss or [])]

    user = f"""Draft a formal FIR (First Information Report).

POLICE STATION: {sanitize_for_llm(police_station, 500)}
DISTRICT: {sanitize_for_llm(district, 500)}

COMPLAINANT:
Name: {sanitize_for_llm(complainant_name, 500)}
Contact: {sanitize_for_llm(complainant_contact, 500)}

INCIDENT:
Date/Time: {sanitize_for_llm(incident_time, 500)}
Location: {sanitize_for_llm(location, 500)}

FACTS AS STATED BY COMPLAINANT:
{delimit(facts, "FACTS")}

SECTIONS (BNS / BNSS):
BNS sections to be invoked: {', '.join(safe_sections_bns) if safe_sections_bns else '[TO BE DETERMINED BY IO]'}
BNSS procedural sections: {', '.join(safe_sections_bnss) if safe_sections_bnss else '154 BNSS (FIR registration), 173 BNSS (investigation)'}

INVESTIGATION OFFICER (placeholder, IO to confirm):
{sanitize_for_llm(io_name, 500)}

Produce the FIR now."""

    return [
        LLMMessage(role="system", content=system),
        LLMMessage(role="user", content=user),
    ]
