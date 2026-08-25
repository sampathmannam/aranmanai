"""Unit tests for the LLM clients (mock + factory)."""
from __future__ import annotations


def test_mock_llm_routes_fir_prompt(tmp_env):
    from aranmanai.ai.mock_client import MockLLMClient
    from aranmanai.ai.prompts.fir import build_fir_prompt
    client = MockLLMClient()
    msgs = build_fir_prompt(
        complainant_name="Ravi Kumar",
        complainant_contact="+91-9876543210",
        incident_time="2026-08-15 14:30",
        location="Bus stand, Tambaram",
        facts="Accused pulled a knife and demanded wallet.",
        sections_bns=["BNS 308"],
        sections_bnss=["154 BNSS"],
        police_station="Tambaram PS",
        district="Chengalpattu",
        io_name="Inspector S. Krishnan",
    )
    r = client.complete(msgs)
    assert "FIR" in r.content
    assert "Tambaram" in r.content or "Chengalpattu" in r.content
    assert r.model == "mock-aranmanai-v1"


def test_mock_llm_routes_chargesheet_prompt(tmp_env):
    from aranmanai.ai.mock_client import MockLLMClient
    from aranmanai.ai.prompts.chargesheet import build_chargesheet_prompt
    client = MockLLMClient()
    msgs = build_chargesheet_prompt(
        case_id="case-1",
        fir_no="123/2026",
        court="Sessions Court, Chengalpattu",
        accused_name="Suresh",
        accused_address="12 Gandhi St",
        arrest_date="2026-08-16",
        sections_bns=["BNS 308"],
        facts="Knife attack at bus stand.",
        evidence_summary="Knife recovered, CCTV available",
        witness_summary="Two eyewitnesses",
        io_name="IO S. Krishnan",
    )
    r = client.complete(msgs)
    assert "CHARGE SHEET" in r.content or "Chargesheet" in r.content.lower() or "charge sheet" in r.content.lower()
    assert "BNS 308" in r.content or "308" in r.content


def test_mock_llm_routes_cross_exam(tmp_env):
    from aranmanai.ai.mock_client import MockLLMClient
    from aranmanai.ai.prompts.cross_exam import build_cross_exam_prompt
    client = MockLLMClient()
    msgs = build_cross_exam_prompt(
        case_id="c-1",
        witness_id="w-1",
        witness_type="eyewitness",
        witness_category="hostile",
        witness_statement="I saw the accused at the bus stand at 14:30.",
        case_facts="Knife attack at bus stand on 2026-08-15.",
        hostile_reason="Inducement by accused family",
    )
    r = client.complete(msgs)
    assert "CROSS" in r.content.upper() or "PREP" in r.content.upper()
    assert "hostile" in r.content.lower() or "Hostile" in r.content


def test_mock_llm_json_mode(tmp_env):
    import json

    from aranmanai.ai.llm_client import LLMMessage
    from aranmanai.ai.mock_client import MockLLMClient
    client = MockLLMClient()
    msgs = [
        LLMMessage(role="system", content="Output JSON"),
        LLMMessage(role="user", content="FIR section BNS 308"),
    ]
    r = client.complete(msgs, json_mode=True)
    parsed = json.loads(r.content)
    assert "draft" in parsed


def test_mock_llm_deterministic(tmp_env):
    from aranmanai.ai.llm_client import LLMMessage
    from aranmanai.ai.mock_client import MockLLMClient
    client = MockLLMClient()
    msgs = [LLMMessage(role="user", content="FIR section BNS 308")]
    r1 = client.complete(msgs)
    r2 = client.complete(msgs)
    assert r1.content == r2.content


def test_factory_returns_mock_by_default(tmp_env):
    from aranmanai.ai.factory import get_llm_client
    from aranmanai.ai.mock_client import MockLLMClient
    get_llm_client.cache_clear()
    client = get_llm_client()
    assert isinstance(client, MockLLMClient)


def test_health_check(tmp_env):
    from aranmanai.ai.mock_client import MockLLMClient
    client = MockLLMClient()
    assert client.health() is True
    assert client.model_name == "mock-aranmanai-v1"
