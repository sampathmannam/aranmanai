"""Mock LLM client. Returns canned responses for testing and v1 development
when no real LLM is downloaded yet. Production uses llama_cpp or ollama.

The mock is intentionally deterministic: same prompt + same config = same
response, every time. Tests rely on this.
"""
from __future__ import annotations

import json
import re

from aranmanai.ai.llm_client import LLMClient, LLMMessage, LLMResponse
from aranmanai.observability import get_logger

log = get_logger(__name__)


# Canned response templates per service. The mock uses a keyword router
# that matches the system prompt against longer, more specific phrases to
# pick a response. The router is order-sensitive: more specific patterns
# come first so the longest match wins.
_MOCK_TEMPLATES: list[tuple[re.Pattern[str], str]] = [
    (
        # Chargesheet: only the actual chargesheet service prompt
        re.compile(r"drafting a final charge sheet|charge sheet \(कुटुम्ब|Section 173 of the Bharatiya.*BNSS.*replaced CrPC", re.IGNORECASE),
        """CHARGE SHEET
=====================================
Case No.: {case_id}
Court: {court}
Under Section: BNSS §173

ACCUSED:
Name: {accused_name}
Address: {accused_address}
Arrest Date: {arrest_date}

OFFENCES:
{sections}

FACTS OF THE CASE:
{facts}

EVIDENCE:
{evidence}

WITNESSES:
{witnesses}

INVESTIGATION OFFICER: [{io_name}]

This charge sheet is filed under Section 173 of the Bharatiya Nagarik
Suraksha Sanhita, 2023, within the statutory period. All documentary
and oral evidence is attached herewith. The IO certifies that the
investigation has been conducted in accordance with the law.

[Note: DRAFT for IO review and approval before filing.]"""
    ),
    (
        # Cross-examination prep
        re.compile(r"cross.?examination preparation|hostile witness|witness prep|LIKELY DEFENSE QUESTIONS", re.IGNORECASE),
        """CROSS-EXAMINATION PREPARATION BRIEF
=====================================
Witness ID: {witness_id}
Case ID: {case_id}
Witness Type: {witness_type}
Current Category: {witness_category}

LIKELY DEFENSE QUESTIONS (with suggested answers):
1. Q: [Defense will challenge your sighting distance/lighting]
   A: [Stick to the facts. State the distance. Mention any landmarks
      you used to judge distance. If lighting was poor, say so
      honestly — your honesty strengthens the rest of your testimony.]

2. Q: [Defense will ask why you didn't immediately report to police]
   A: [Explain any reason (fear, injury, was at hospital). If none,
      acknowledge the delay. Explain when you DID report.]

3. Q: [Defense will suggest you are lying because of police pressure]
   A: [Be calm. State that you are stating what you saw. Mention any
      detail only you would know (e.g., victim's clothing, the
      accused's position, a specific sound).]

4. Q: [Defense will ask about prior relationship with accused]
   A: [Be honest. If you know the accused, say so — it doesn't
      invalidate your testimony. If you have a history of disputes,
      disclose it; courts weigh this but don't reject.]

5. Q: [Defense will ask why you identify accused in dock]
   A: [Confirm lighting, distance, time you observed. If TIP was
      conducted, mention it. If no TIP, be prepared to explain.]

6. Q: [Defense will ask about inconsistencies in 161 statement]
   A: [Be prepared to explain. Minor inconsistencies are normal; major
      ones are damaging. If you forgot a detail in 161, admit it
      honestly now.]

7. Q: [Defense will try to impeach you under Section 145 BSA]
   A: [Stay calm. The court will read your 161 statement. If there
      are minor differences, explain them. Do not invent explanations.]

KEY TACTICS:
- Speak slowly and clearly
- Answer only what is asked — do not volunteer
- If you don't know, say "I don't know" — do not guess
- If you don't remember, say "I don't remember" — do not make up
- Stay in the facts. The lawyer's job is to confuse; yours is clarity.

[Note: This brief is DRAFT. IO/PP must review and customize for
the specific case and witness.]"""
    ),
    (
        # Investigation recommendations
        re.compile(r"investigation recommendations|RECOMMENDED ACTIONS|investigation gaps|missing evidence", re.IGNORECASE),
        """INVESTIGATION RECOMMENDATIONS
=====================================
Case ID: {case_id}
Current Lapse Profile:
{lapses}

RECOMMENDED ACTIONS (priority order):
{recommendations}

PROCEDURAL DEADLINES TO WATCH:
{deadlines}

[Note: DRAFT for IO consideration. Final decisions remain with IO/PP.]"""
    ),
    (
        # Acquittal-risk score (must come before FIR so "risk score" doesn't match FIR)
        re.compile(r"acquittal.?risk|risk score|RISK ASSESSMENT|Risk Band", re.IGNORECASE),
        """ACQUITTAL-RISK ASSESSMENT (ADVISORY ONLY)
=====================================
Case ID: {case_id}
Risk Score: {risk_score:.2f} / 1.00
Risk Band: {risk_band}

CONTRIBUTING FACTORS (by weight):
{factors}

SUGGESTED CURES (top 3):
{cures}

[Note: This is an ADVISORY score. IO/PP/SP make the final call.
No decision is automated based on this score.]"""
    ),
    (
        # Complaint intake (distinct from FIR — uses "complaint intake" specifically)
        re.compile(r"complaint intake|COMPLAINT INTAKE|structured record of the complaint|register the complaint", re.IGNORECASE),
        """COMPLAINT INTAKE — STRUCTURED RECORD
=====================================
Complainant: {complainant_name}
Contact: {complainant_contact}
Date/Time of incident: {incident_time}
Location: {location}
Alleged offence(s): {offences}

Complainant's statement (transcribed/structured):
{statement}

Likely sections (BNS): {sections}
Likely FIR registerable: {registerable}

NEXT STEPS:
1. Verify complainant's identity (Aadhaar if available)
2. Record the complaint in CCTNS
3. Generate FIR draft via /ai/fir-draft endpoint
4. Initiate eSakshya AV recording
5. Forward to IO for investigation

[Note: DRAFT. IO must review and approve before FIR registration.]"""
    ),
    (
        # FIR (last among the structured docs so the more specific ones above win)
        re.compile(r"FIR|First Information Report|154 BNSS \(FIR", re.IGNORECASE),
        """FIR (First Information Report)
=====================================
FIR No.: [AUTO]/{YEAR}
Date and Time: {date}
Police Station: {ps}
District: {district}
Sections: {sections}
Act: Bharatiya Nagarik Suraksha Sanhita (BNSS) 2023

Complainant:
Name: {complainant_name}
Contact: {complainant_contact}

Allegations:
{facts}

Witnesses Present:
1. [Witness name, contact]
2. [Witness name, contact]

Investigation Officer: IO [{io_name}], {rank}

This FIR has been registered under sections cited above. Investigation
to commence as per BNSS §173. Audio-visual recording of the registration
process is required per eSakshya rules.

[Note: This is a DRAFT generated by Aranmanai. IO must review and approve.]"""
    ),
]


class MockLLMClient(LLMClient):
    """Mock LLM client that returns canned responses based on prompt keywords.

    Deterministic: same prompt + same config = same response.
    """

    def __init__(self, model_name: str = "mock-aranmanai-v1") -> None:
        self._model_name = model_name

    @property
    def model_name(self) -> str:
        return self._model_name

    def health(self) -> bool:
        return True

    def _route(self, messages: list[LLMMessage]) -> re.Pattern[str] | None:
        """Find the best matching template. Returns None if no match.

        Routing preference: the system message is the most specific
        identifier of which service is asking. Use it first; fall back
        to the full prompt only if no system match.
        """
        system_msgs = [m.content for m in messages if m.role == "system"]
        if system_msgs:
            system_text = "\n".join(system_msgs)
            for pattern, _ in _MOCK_TEMPLATES:
                if pattern.search(system_text):
                    return pattern
        # Fallback: full prompt
        prompt = "\n".join(m.content for m in messages)
        for pattern, _ in _MOCK_TEMPLATES:
            if pattern.search(prompt):
                return pattern
        return None

    def _substitute(self, template: str, messages: list[LLMMessage]) -> str:
        """Substitute known placeholders from prompt context if present.

        Strategy:
        1. Parse the prompt into a flat key->value context using
           "Key: Value" and "Key = Value" line formats.
        2. For unresolved placeholders, do a substring search of
           the full prompt — if a line has e.g. "BNS sections: BNS 308",
           and the value is on the next line, capture it.
        3. Build a synonym map for common placeholder names.
        4. Resolve each template placeholder via exact match, synonym
           match, or suffix match.
        """
        prompt = "\n".join(m.content for m in messages)
        ctx: dict[str, str] = {}

        # Pass 1: line-by-line "Key: Value" parsing
        for line in prompt.splitlines():
            if ":" not in line:
                continue
            key, _, value = line.partition(":")
            key = key.strip().lower().replace(" ", "_").replace("/", "_")
            value = value.strip()
            if key and value and key not in ctx:
                ctx[key] = value

        # Pass 1b: "Key = Value"
        for line in prompt.splitlines():
            if "=" not in line:
                continue
            key, _, value = line.partition("=")
            key = key.strip().lower().replace(" ", "_")
            value = value.strip()
            if key and value and key not in ctx:
                ctx[key] = value

        # Pass 2: multi-line blocks. If a "Key:" line has empty value,
        # the next non-empty line is its value.
        lines = prompt.splitlines()
        for i, line in enumerate(lines):
            if ":" not in line:
                continue
            key, _, value = line.partition(":")
            key = key.strip().lower().replace(" ", "_").replace("/", "_")
            value = value.strip()
            if not value and i + 1 < len(lines):
                # Look at next non-empty line(s) until the next "Key:" header
                nxt = lines[i + 1].strip()
                if nxt and not (":" in nxt and nxt.split(":", 1)[0].strip().replace(" ", "_").isalpha()):
                    ctx[key] = nxt
                    # Also extract synonyms from inside parentheses
                    # e.g. "OFFENCES (BNS sections):" -> also create "bns_sections"
                    if "(" in key and ")" in key:
                        paren = key[key.index("(") + 1 : key.index(")")].strip()
                        paren = paren.replace(" ", "_").replace("/", "_")
                        if paren and paren not in ctx:
                            ctx[paren] = nxt
                    # Extract last word as a possible synonym
                    last_word = key.split("_")[-1] if "_" in key else key
                    if last_word and last_word not in ctx and len(last_word) > 2:
                        ctx[last_word] = nxt

        # Synonyms: template placeholder -> possible prompt keys
        synonyms: dict[str, list[str]] = {
            "ps": ["police_station", "ps", "station"],
            "io_name": ["io_name", "investigation_officer", "io"],
            "complainant_name": ["complainant_name", "name", "complainant"],
            "complainant_contact": ["complainant_contact", "contact", "phone"],
            "district": ["district", "dist"],
            "court": ["court", "court_where_chargesheet_will_be_filed"],
            "accused_name": ["accused_name", "accused", "name"],
            "accused_address": ["accused_address", "address"],
            "arrest_date": ["arrest_date", "date_of_arrest", "arrest_date"],
            "facts": ["facts", "facts_of_the_case", "allegations", "case_facts", "facts_as_stated_by_complainant"],
            "evidence": ["evidence", "evidence_summary"],
            "witnesses": ["witnesses", "witness_summary", "witnesses_present"],
            "sections": ["sections", "bns_sections", "bnss_sections", "offences"],
            "case_id": ["case_id", "case_no", "case_id_(aranmanai)", "fir_no"],
            "witness_id": ["witness_id"],
            "witness_type": ["witness_type"],
            "witness_category": ["witness_category", "current_category"],
            "case_facts": ["case_facts", "facts"],
            "hostile_reason": ["hostile_reason", "reason"],
            "lapses": ["lapses", "current_lapse_profile"],
            "recommendations": ["recommendations", "recommended_actions"],
            "deadlines": ["deadlines", "procedural_deadlines"],
            "risk_score": ["risk_score"],
            "risk_band": ["risk_band"],
            "factors": ["factors", "contributing_factors"],
            "cures": ["cures", "suggested_cures"],
            "statement": ["statement", "complainant_s_statement"],
            "offences": ["offences", "alleged_offences"],
            "registerable": ["registerable", "likely_fir_registerable"],
            "year": ["year", "YEAR"],
            "date": ["date", "incident_time", "date_time", "date/time"],
            "rank": ["rank", "io_rank"],
        }

        # Build a normalized ctx
        normalized_ctx: dict[str, str] = {}
        for k, v in ctx.items():
            k2 = k.lower().replace(" ", "_").replace("/", "_")
            normalized_ctx.setdefault(k2, v)

        def _resolve(key: str) -> str | None:
            kl = key.lower()
            if kl in normalized_ctx:
                return normalized_ctx[kl]
            if kl in synonyms:
                for cand in synonyms[kl]:
                    if cand in normalized_ctx:
                        return normalized_ctx[cand]
            for ck, cv in normalized_ctx.items():
                if ck == kl or ck.endswith("_" + kl) or ck.endswith(kl):
                    return cv
            return None

        def _sub(m: re.Match[str]) -> str:
            return _resolve(m.group(1)) or m.group(0)

        return re.sub(r"\{([a-zA-Z_][a-zA-Z0-9_]*)\}", _sub, template)

    def complete(
        self,
        messages: list[LLMMessage],
        *,
        temperature: float | None = None,
        max_tokens: int | None = None,
        stop: list[str] | None = None,
        json_mode: bool = False,
    ) -> LLMResponse:
        pattern = self._route(messages)
        if pattern is None:
            content = (
                "Mock LLM: no template matched this prompt. "
                "Refine the prompt to mention one of: FIR, chargesheet, "
                "cross-exam, investigation, complaint, risk."
            )
        else:
            template = next(t for p, t in _MOCK_TEMPLATES if p is pattern)
            content = self._substitute(template, messages)

        if json_mode:
            # Wrap in a JSON envelope so callers that expect JSON don't crash
            try:
                json.loads(content)
            except (json.JSONDecodeError, TypeError):
                content = json.dumps({"draft": content, "model": self._model_name})

        prompt_tokens = sum(len(m.content.split()) for m in messages)
        completion_tokens = len(content.split())
        log.debug("mock.llm.complete", tokens_in=prompt_tokens, tokens_out=completion_tokens)
        return LLMResponse(
            content=content,
            model=self._model_name,
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            total_tokens=prompt_tokens + completion_tokens,
        )
