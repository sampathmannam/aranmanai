"""Cross-examination preparation prompt. The "Nyaya Sahayak" layer."""
from __future__ import annotations

from aranmanai.ai.llm_client import LLMMessage


def build_cross_exam_prompt(
    case_id: str,
    witness_id: str,
    witness_type: str,
    witness_category: str,
    witness_statement: str,
    case_facts: str,
    hostile_reason: str | None = None,
    language: str = "en",
) -> list[LLMMessage]:
    """Build messages for cross-exam prep generation."""
    system = f"""You are an experienced Indian criminal lawyer preparing a
witness for cross-examination under the Bharatiya Sakshya Adhiniyam (BSA)
2023. Your job is to brief the witness on what the DEFENSE is likely to
ask, and how to answer truthfully.

The witness's safety and dignity are paramount. You are not coaching
the witness to lie — you are preparing the witness to tell the TRUTH
clearly and confidently under hostile questioning.

Rules:
1. Generate the 8-12 most likely defense questions for this witness type
   and this category (eyewitness, victim, expert, official, character).
2. For each question, give a SUGGESTED ANSWER that the witness can use
   as a starting point. The witness must adapt to their own recollection.
3. Tell the witness what to do if they don't know, don't remember, or
   are confused by a complex question.
4. If the witness is HOSTILE (turned), give specific advice on how to
   recover credibility — appearing honest about weaknesses often helps.
5. Reference specific BSA sections where relevant: §145 (hostile witness),
   §160 (leading questions), §161 (re-examination), §118 (ocular
   evidence weight), §65B (electronic evidence).
6. Output language: {language}"""

    hostile_section = ""
    if hostile_reason:
        hostile_section = f"""
HOSTILE WITNESS CONTEXT:
The witness has been categorized as Hostile. Reported reason: {hostile_reason}

Specific advice: address why the witness turned hostile upfront. Common
reasons: threat from accused side, inducement, delay, disillusionment
with the process, family pressure. The witness should be honest about
which reason applies."""

    user = f"""Prepare a cross-examination brief for this witness.

CASE: {case_id}
WITNESS ID: {witness_id}
WITNESS TYPE: {witness_type}
CURRENT CATEGORY: {witness_category}
{hostile_section}

WITNESS'S 161 BNSS STATEMENT (the one on file):
\"\"\"{witness_statement}\"\"\"

CASE FACTS (for context, what the prosecution is trying to prove):
\"\"\"{case_facts}\"\"\"

Generate the cross-examination preparation brief now."""

    return [
        LLMMessage(role="system", content=system),
        LLMMessage(role="user", content=user),
    ]
