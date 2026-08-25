"""Case diary entry prompt. Section 174 BNSS (renumbered from CrPC §172)."""
from __future__ import annotations

from aranmanai.ai.llm_client import LLMMessage
from aranmanai.ai.prompts._sanitize import delimit, sanitize_for_llm



def build_case_diary_prompt(
    case_id: str,
    fir_no: str,
    io_name: str,
    date: str,
    progress_notes: str,
    investigation_steps: str,
    language: str = "en",
) -> list[LLMMessage]:
    """Build messages for a case diary entry draft."""
    system = f"""You are an experienced IO drafting a case diary entry under
Section 174 of the Bharatiya Nagarik Suraksha Sanhita (BNSS) 2023 (which
renumbered CrPC §172). The case diary is the IO's chronological record
of every investigative step.

Rules:
1. Use first-person past tense ("I proceeded to...", "I recorded...").
2. Each entry must be dated, timed, and signed.
3. Reference the specific BNSS section under which the action was taken
   (e.g., 161 BNSS for witness statement, 174 BNSS for case diary).
4. Note all persons present, all documents generated, all evidence
   recovered.
5. Do NOT invent facts. Use the IO's actual progress notes.

Output language: {language}"""

    user = f"""Draft a case diary entry.

CASE: {case_id} (FIR {fir_no})
DATE OF ENTRY: {date}
IO: {io_name}

PROGRESS NOTES FROM IO:
{progress_notes}

INVESTIGATION STEPS TAKEN TODAY:
{investigation_steps}

Produce the case diary entry now."""

    return [
        LLMMessage(role="system", content=system),
        LLMMessage(role="user", content=user),
    ]
