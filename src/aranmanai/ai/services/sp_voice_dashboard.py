"""SP voice dashboard service.

Allows the SP to query the daily review / bottlenecks / case status via voice or
text. Designed for push-to-talk on a mobile device.

Workflow:
1. SP speaks / types a command in Tamil, English, or Hindi
2. This service parses the intent (get_daily_review, get_case_status, etc.)
3. It queries the CMS services and returns a structured response
4. The response is TTS-synthesised and played back

DPDP: No audio is stored. Audio is transcribed to text, text is processed,
and the audio SHA-256 is logged for audit.
"""
from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from typing import Any

from aranmanai.ai.factory import get_llm_client
from aranmanai.ai.llm_client import LLMClient
from aranmanai.core.cms.bottleneck import BottleneckDetector
from aranmanai.core.cms.daily_calendar import DailyCalendarService
from aranmanai.core.cms.sp_dashboard import SpDashboardService
from aranmanai.db.session import SessionLocal
from aranmanai.observability import get_logger

log = get_logger(__name__)

_SP_PROMPT = """You are Aranmanai, the SP's AI command surface.
You parse natural-language commands from the Superintendent of Police (SP)
and return a structured JSON intent.

The SP speaks in Tamil, English, or Hindi. Parse the intent and respond ONLY
with this JSON format:

{
  "intent": "daily_review | case_status | bottlenecks | risk_alerts | general",
  "target_date": "YYYY-MM-DD or today",
  "case_id": "FIR number or null",
  "filters": ["list of relevant filters or empty array"],
  "language": "en | ta | hi",
  "urgency": "critical | normal"
}

Intent definitions:
- daily_review: "show today's hearings", "what cases are there today", "today's calendar"
- case_status: "show FIR number XYZ", "what is the status of case ABC", "update on case XYZ"
- bottlenecks: "what is stuck", "which cases need attention", "bottlenecks"
- risk_alerts: "show risk alerts", "which cases are high risk", "acquittal risk"
- general: anything that doesn't fit above — return the general dashboard

Keep filters as lowercase strings.
Return ONLY the JSON object. No markdown, no explanation.
"""


@dataclass
class SpVoiceCommand:
    intent: str = "general"
    target_date: str = ""
    case_id: str | None = None
    filters: list[str] = field(default_factory=list)
    language: str = "en"
    urgency: str = "normal"
    raw_text: str = ""


@dataclass
class SpDashboardResult:
    """Structured result of the SP voice command."""
    command_id: str
    intent: str
    parsed_command: str      # what was understood
    dashboard_text: str     # human-readable dashboard summary
    actions: list[str]      # recommended actions for the SP
    raw_text: str           # original input
    language: str
    model: str = "unknown"

    def to_dict(self) -> dict[str, Any]:
        return {
            "command_id": self.command_id,
            "intent": self.intent,
            "parsed_command": self.parsed_command,
            "dashboard_text": self.dashboard_text,
            "actions": self.actions,
            "raw_text": self.raw_text,
            "language": self.language,
            "model": self.model,
        }


class SpVoiceDashboardService:
    """Process SP voice/text commands and return structured dashboard results."""

    def __init__(self, llm: LLMClient | None = None) -> None:
        self.llm = llm or get_llm_client()

    def _parse_command(self, text: str, language: str = "en") -> SpVoiceCommand:
        """Use LLM to parse the natural-language command into structured intent."""
        from aranmanai.ai.llm_client import LLMMessage
        prompt = [
            LLMMessage(role="system", content=_SP_PROMPT),
            LLMMessage(role="user", content=text),
        ]
        response = self.llm.complete(prompt, temperature=0.1, max_tokens=256)
        import json
        content = response.content.strip()
        # Strip markdown code fences if present
        if content.startswith("```"):
            content = content.split("```")[1]
            if content.startswith("json"):
                content = content[4:]
        try:
            parsed = json.loads(content)
            return SpVoiceCommand(
                intent=parsed.get("intent", "general"),
                target_date=parsed.get("target_date", ""),
                case_id=parsed.get("case_id"),
                filters=parsed.get("filters", []),
                language=parsed.get("language", language),
                urgency=parsed.get("urgency", "normal"),
                raw_text=text,
            )
        except (json.JSONDecodeError, KeyError):
            log.warning("sp_voice.parse_failed raw=%s", text)
            return SpVoiceCommand(intent="general", raw_text=text, language=language)

    def _build_daily_review(self, target_date: str | None, district: str) -> tuple[str, list[str]]:
        """Query the daily calendar and return summary + actions."""
        db = SessionLocal()
        try:
            from datetime import date
            target = date.today() if not target_date or target_date == "today" else date.fromisoformat(target_date)
            svc = DailyCalendarService(db)
            entries = svc.for_date(target, district=district)

            if not entries:
                return f"No hearings scheduled for {target.isoformat()}.", []

            lines = [f"Today's hearings — {target.isoformat()} — {len(entries)} case(s):\n"]
            actions: list[str] = []

            for e in entries:
                priority_icon = {"critical": "CRITICAL", "high": "HIGH", "medium": "MEDIUM", "low": "LOW"}.get(
                    e.priority, "MEDIUM"
                )
                lines.append(f"- {e.fir_no} [{priority_icon}] at {e.time}: {e.court or 'court TBC'}")
                if e.hostile_witnesses > 0:
                    lines.append(f"  {e.hostile_witnesses} hostile witness(es), {e.ready_witnesses} ready")
                    actions.append(f"SP: call IO — {e.fir_no} has {e.hostile_witnesses} hostile witness(es)")
                if e.case_stuck:
                    lines.append(f"  STUCK — last hearing {e.days_since_last} days ago")
                    actions.append(f"SP: escalate {e.fir_no} — stuck {e.days_since_last} days")

            summary = "\n".join(lines)
            return summary, actions[:5]
        finally:
            db.close()

    def _build_bottlenecks(self, district: str) -> tuple[str, list[str]]:
        """Query bottlenecks and return summary."""
        db = SessionLocal()
        try:
            svc = BottleneckDetector(db)
            bottlenecks = svc.detect(district=district)

            if not bottlenecks:
                return "No bottlenecks detected. All cases are moving normally.", []

            lines = [f"Bottlenecks — {len(bottlenecks)} case(s) need attention:\n"]
            actions: list[str] = []

            for b in bottlenecks[:10]:
                lines.append(f"- {b.fir_no}: {b.reason} [{b.severity.upper()}]")
                if b.severity == "critical":
                    actions.append(f"SP: immediate action — {b.fir_no}: {b.reason}")

            return "\n".join(lines), actions[:5]
        finally:
            db.close()

    def _build_sp_dashboard(self, district: str) -> tuple[str, list[str]]:
        """Query the full SP dashboard and return summary."""
        db = SessionLocal()
        try:
            svc = SpDashboardService(db)
            snap = svc.snapshot(district=district)
            lines = [f"SP Dashboard — {snap.as_of.strftime('%Y-%m-%d %H:%M')}:\n"]
            lines.append(f"- Today's hearings: {snap.today_hearings}")
            lines.append(f"- Critical: {snap.critical_hearings}")
            lines.append(f"- Hostile witnesses needing prep: {snap.hostile_witnesses_needing_prep}")
            lines.append(f"- Cases stuck: {snap.cases_stuck} ({snap.cases_stuck_critical} critical)")
            if snap.conviction_rate_30d is not None:
                lines.append(f"- 30-day conviction rate: {snap.conviction_rate_30d:.1%}")
            if snap.trend_delta is not None:
                delta_str = f"+{snap.trend_delta:.1%}" if snap.trend_delta > 0 else f"{snap.trend_delta:.1%}"
                lines.append(f"- Trend vs baseline: {delta_str}")
            actions = list(snap.top_actions[:5])
            return "\n".join(lines), actions
        finally:
            db.close()

    def process(self, text: str, district: str, language: str = "en") -> SpDashboardResult:
        """Main entry: parse command + query CMS + return structured result."""
        cmd_id = str(uuid.uuid4())
        log.info("sp_voice.command id=%s text=%s", cmd_id, text[:100])

        parsed = self._parse_command(text, language)
        log.info("sp_voice.parsed id=%s intent=%s", cmd_id, parsed.intent)

        if parsed.intent == "daily_review":
            summary, actions = self._build_daily_review(parsed.target_date or "today", district)
        elif parsed.intent == "bottlenecks":
            summary, actions = self._build_bottlenecks(district)
        elif parsed.intent == "case_status":
            summary, actions = self._build_sp_dashboard(district)
        elif parsed.intent == "risk_alerts":
            summary, actions = self._build_bottlenecks(district)
        else:
            summary, actions = self._build_sp_dashboard(district)

        parsed_text = f"Intent: {parsed.intent} | Date: {parsed.target_date or 'today'} | Case: {parsed.case_id or 'all'}"

        log.info("sp_voice.result id=%s intent=%s actions=%d", cmd_id, parsed.intent, len(actions))

        return SpDashboardResult(
            command_id=cmd_id,
            intent=parsed.intent,
            parsed_command=parsed_text,
            dashboard_text=summary,
            actions=actions,
            raw_text=text,
            language=language,
            model=getattr(self.llm, "model", "mock"),
        )
