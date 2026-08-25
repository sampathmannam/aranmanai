"""Investigation recommendations prompt. Lapse-driven cure actions."""
from __future__ import annotations

from aranmanai.ai.llm_client import LLMMessage


def build_investigation_prompt(
    case_id: str,
    lapses: list[dict],
    case_facts: str,
    evidence_list: list[str],
    witness_list: list[str],
    language: str = "en",
) -> list[LLMMessage]:
    """Build messages for investigation recommendations based on detected lapses."""
    system = f"""You are an experienced Indian Police supervisory officer
(SP / DSP level) reviewing an investigation. The IO has a set of detected
lapses (procedural gaps). Your job is to suggest concrete, ordered
actions to cure each lapse.

Each lapse has: key, tier (FATAL / SERIOUS / MINOR), description.

Rules:
1. FATAL lapses go first. These will likely cause acquittal.
2. For each lapse, give ONE specific action the IO should take this week.
   Vague advice ("investigate further") is useless. The action should
   have a deliverable (e.g., "record 161 statement of witness X by
   Friday", "file application for FSL urgency", "get panchnama
   re-signed by independent witness").
3. Reference the relevant section: BNSS for procedural, BNS for
   substantive, BSA for evidence.
4. Note procedural deadlines to watch.
5. Don't invent. If you don't know how to cure a lapse, say "consult
   DSP / legal advisor".

Output language: {language}"""

    lapse_section = "\n".join(
        f"- [{lapse.get('tier', 'UNKNOWN')}] {lapse.get('key', '?')}: {lapse.get('description', '')}"
        for lapse in lapses
    )
    if not lapse_section:
        lapse_section = "(no lapses detected)"

    user = f"""Generate investigation recommendations for this case.

CASE: {case_id}

DETECTED LAPSES:
{lapse_section}

CASE FACTS:
\"\"\"{case_facts}\"\"\"

EVIDENCE CURRENTLY ON FILE:
{chr(10).join('- ' + e for e in evidence_list) if evidence_list else '(none)'}

WITNESSES CURRENTLY ON FILE:
{chr(10).join('- ' + w for w in witness_list) if witness_list else '(none)'}

Generate the recommendations now."""

    return [
        LLMMessage(role="system", content=system),
        LLMMessage(role="user", content=user),
    ]
