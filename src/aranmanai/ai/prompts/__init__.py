"""Prompt templates for AI assist services. Centralized for easy iteration."""
from aranmanai.ai.prompts.case_diary import build_case_diary_prompt
from aranmanai.ai.prompts.chargesheet import build_chargesheet_prompt
from aranmanai.ai.prompts.complaint_intake import build_complaint_intake_prompt
from aranmanai.ai.prompts.cross_exam import build_cross_exam_prompt
from aranmanai.ai.prompts.fir import build_fir_prompt
from aranmanai.ai.prompts.investigation import build_investigation_prompt
from aranmanai.ai.prompts.risk_score import build_risk_prompt

__all__ = [
    "build_fir_prompt",
    "build_chargesheet_prompt",
    "build_case_diary_prompt",
    "build_complaint_intake_prompt",
    "build_cross_exam_prompt",
    "build_investigation_prompt",
    "build_risk_prompt",
]
