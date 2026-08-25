from __future__ import annotations

from aranmanai.ai.prompts._sanitize import delimit, sanitize_for_llm

"""Prompt templates for every AI assist endpoint.

Each function returns (system_prompt, user_prompt) given the inputs.
The templates are short, explicit, and bias-corrected: every output
includes a 'review required' marker so the IO knows the AI did not
auto-apply. v2 will move the FBR/Quint/BPRD study citations into
RAG chunks passed in the context.
"""
from __future__ import annotations


SYSTEM_GENERIC = (
    "You are Aranmanai AI, an assistant to Indian Police IO/SP/PP officers. "
    "You help draft legal and investigative documents under BNS 2023, "
    "BNSS 2023, and BSA 2023. Your output is ALWAYS advisory — the IO/PP "
    "must review and approve before any document is filed. Be precise, "
    "cite specific section numbers, and flag any procedural concerns."
)


def complaint_intake(narrative: str, language: str = "Tamil") -> tuple[str, str]:
    """Voice/text complaint → structured FIR-ready complaint draft."""
    system = SYSTEM_GENERIC
    user = (
        f"Convert the following complainant narrative (in {language}) into a "
        f"structured complaint ready for FIR drafting. Output as JSON with keys: "
        f"complainant_name, complainant_address, complainant_phone, accused_names[], "
        f"accused_addresses[], incident_date, incident_time, incident_location, "
        f"incident_description (chronological, factual, no speculation), "
        f"sections_likely_applicable (BNS/BNSS/BSA), offence_category, witness_names[], "
        f"evidence_types_present[], flags[] (e.g. 'pocso_minor', 'sc_st_act', 'domestic_violence').\n\n"
        f"Narrative ({language}):\n{narrative}\n\n"
        f"Output: valid JSON only. No prose around it."
    )
    return system, user


def fir_draft(case_id: str, sections: list[str], facts: str) -> tuple[str, str]:
    """Case facts → FIR draft under BNS/BNSS/BSA."""
    system = SYSTEM_GENERIC
    user = (
        f"Draft a First Information Report (FIR) for the following case. "
        f"Output in formal FIR prose (Tamil Nadu state format acceptable; "
        f"or the user's preferred language). Include: complainant particulars, "
        f"date/time/place of offence, brief facts, sections invoked with BNS/BNSS/BSA "
        f"references, IO who registered the FIR, witness list, and a list of "
        f"evidence collected at registration time.\n\n"
        f"Case ID: {case_id}\n"
        f"Sections: {', '.join(sections) if sections else '(to be determined)'}\n"
        f"Facts: {facts}\n\n"
        f"Output: formal FIR draft in plain text. Add '[IO REVIEW REQUIRED]' "
        f"at the end so the officer knows to verify sections + facts before filing."
    )
    return system, user


def case_diary_draft(case_id: str, days: list[dict]) -> tuple[str, str]:
    """Investigation timeline → case diary entry."""
    system = SYSTEM_GENERIC
    user = (
        f"Draft a case diary entry for case {case_id} covering the following "
        f"investigation timeline. For each day, summarise: what was done, who "
        f"did it, what was found, next steps.\n\n"
        f"Timeline:\n"
    )
    for d in days:
        user += f"Day {d.get('day', '?')}: {d.get('note', '')}\n"
    user += (
        "\nOutput: case diary prose ready to copy into Case Diary. "
        "End with '[IO REVIEW REQUIRED]'."
    )
    return system, user


def chargesheet_draft(case_id: str, facts: str, evidence: list[str], sections: list[str]) -> tuple[str, str]:
    """Facts + evidence + sections → chargesheet draft."""
    system = SYSTEM_GENERIC
    user = (
        f"Draft a chargesheet (final report under Section 193 BNSS) for case {case_id}. "
        f"Include: accused particulars, offences charged with BNS/BNSS/BSA references, "
        f"brief facts of the case, list of witnesses, list of documents/evidence, "
        f"and the IO's recommendation. Output in formal chargesheet prose.\n\n"
        f"Sections: {', '.join(sections) if sections else '(to be determined)'}\n"
        f"Facts: {facts}\n"
        f"Evidence:\n"
    )
    for e in evidence:
        user += f"- {e}\n"
    user += (
        "\nOutput: chargesheet draft. End with '[IO REVIEW REQUIRED — verify "
        "each section reference and witness list with PP before filing under S.193 BNSS]'."
    )
    return system, user


def investigation_recommendations(case_id: str, detected_lapses: list[str]) -> tuple[str, str]:
    """Detected lapses → cure actions the IO should take."""
    system = SYSTEM_GENERIC
    user = (
        f"For case {case_id}, the system has detected these procedural lapses: "
        f"{', '.join(detected_lapses) if detected_lapses else '(none detected)'}.\n\n"
        f"For each lapse, give:\n"
        f"1. What the lapse is and why it matters for conviction\n"
        f"2. The cure action the IO should take (specific, actionable, with reference to "
        f"BNS / BNSS / BSA / BPRD study if applicable)\n"
        f"3. The deadline (in days from now) by which the cure should be in place\n\n"
        f"Output as a numbered list, one entry per lapse. Be specific. "
        f"End with '[IO REVIEW REQUIRED]'."
    )
    return system, user


def cross_exam_prep(witness_name: str, witness_category: str, witness_statement: str,
                     case_sections: list[str], focus: str | None = None) -> tuple[str, str]:
    """Witness statement + case sections → likely defense questions + talking points."""
    system = SYSTEM_GENERIC
    user = (
        f"Prepare a cross-examination brief for the PP for the following witness.\n\n"
        f"Witness: {witness_name} (category: {witness_category})\n"
        f"Statement under 161 BNSS: {witness_statement[:1500]}{'...' if len(witness_statement) > 1500 else ''}\n"
        f"Case sections: {', '.join(case_sections) if case_sections else '(unknown)'}\n"
        f"Focus area: {focus or 'general cross-exam'}\n\n"
        f"Output:\n"
        f"## Likely defense questions (10-15)\n"
        f"List each question, with a 1-line rationale (what the defense is testing).\n\n"
        f"## Suggested talking points for the witness\n"
        f"3-5 bullet points, written in the witness's voice (simple, calm, no jargon).\n\n"
        f"## Pre-emption advice\n"
        f"If the witness is hostile or likely-to-turn, give 1-2 sentences on how the PP "
        f"should sequence questions to extract helpful testimony before the witness turns.\n\n"
        f"Output: markdown. End with '[PP REVIEW REQUIRED]'."
    )
    return system, user
