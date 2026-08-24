"""Acquittal-risk scoring prompt. ADVISORY only — IO/PP/SP make final calls."""
from __future__ import annotations

from aranmanai.ai.llm_client import LLMMessage


def build_risk_prompt(
    case_id: str,
    case_facts: str,
    lapses: list[dict],
    evidence_strength: str,
    witness_count: int,
    hostile_witness_count: int,
    fsl_status: str,
    bnss_173_compliant: bool,
    language: str = "en",
) -> list[LLMMessage]:
    """Build messages for the AI-side risk score commentary.

    Note: the ACTUAL numeric risk score comes from LightGBM in src/core/risk/.
    The LLM is used to provide a NARRATIVE explanation of the contributing
    factors, which is more useful for IO/PP than a bare number.
    """
    system = f"""You are an experienced Indian Police SP/DSP-level officer
reviewing a case for acquittal risk. You produce a SHORT narrative
(2-3 paragraphs max) explaining the case's main conviction risks
and the top 3 actions that would most reduce risk.

THIS IS ADVISORY ONLY. The numerical risk score is computed by a separate
calibrated model. Your job is to explain the reasoning in human terms.

Rules:
1. Reference specific evidence and witness facts (not abstractions).
2. List the top 3 cures — concrete actions, not vague advice.
3. Be honest. Don't inflate confidence. If the case is high-risk,
   say so directly.
4. If the case is strong, say so. Don't manufacture risks to seem
   thorough.

Output language: {language}"""

    lapse_section = "\n".join(
        f"- [{l.get('tier', 'UNKNOWN')}] {l.get('key', '?')}: {l.get('description', '')}"
        for l in lapses
    ) or "(no lapses detected)"

    user = f"""Generate the acquittal-risk narrative for this case.

CASE: {case_id}

CASE FACTS:
\"\"\"{case_facts}\"\"\"

QUANTITATIVE FEATURES (already computed by the model):
- Evidence strength: {evidence_strength}
- Witness count: {witness_count}
- Hostile witness count: {hostile_witness_count}
- FSL status: {fsl_status}
- BNSS §173 compliance (AV recording done): {bnss_173_compliant}

DETECTED LAPSES:
{lapse_section}

Generate the narrative now."""

    return [
        LLMMessage(role="system", content=system),
        LLMMessage(role="user", content=user),
    ]
