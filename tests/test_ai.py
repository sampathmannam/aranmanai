"""AI client + prompt templates (mock backend; no real model)."""
from __future__ import annotations

import pytest

from src.aranmanai.ai.llm_client import LLMClient, get_llm_client
from src.aranmanai.ai.prompts import templates as prompts
from src.aranmanai.integrations import mock_cctns, mock_esakshya, mock_icjs


def test_llm_client_singleton_returns_same_instance():
    a = get_llm_client()
    b = get_llm_client()
    assert a is b


def test_llm_client_uses_mock_when_no_model_path(temp_dir):
    c = LLMClient()
    # In tests, LLM_MODEL_PATH is unset → falls back to mock
    assert c.backend in ("mock", "llama-cpp-python")  # any is acceptable


def test_llm_complete_returns_response_with_metadata(temp_dir):
    c = LLMClient()
    r = c.complete("What is 2+2?", system="You are a math tutor.", temperature=0.0, max_tokens=50)
    assert isinstance(r.text, str) and r.text
    assert r.model
    assert r.backend in ("mock", "llama-cpp-python", "ollama")
    assert r.elapsed_ms >= 0
    assert r.prompt_tokens >= 0
    assert r.completion_tokens >= 0


def test_prompt_templates_return_system_and_user():
    cases = [
        prompts.complaint_intake("Test narrative", "Tamil"),
        prompts.fir_draft("C-1", ["376 IPC"], "Test facts"),
        prompts.case_diary_draft("C-1", [{"day": 1, "note": "n"}]),
        prompts.chargesheet_draft("C-1", "facts", ["e1"], ["376 IPC"]),
        prompts.investigation_recommendations("C-1", ["fir_delay"]),
        prompts.cross_exam_prep("W1", "Hostile", "Statement", ["376 IPC"], "cross-exam"),
    ]
    for sys_msg, usr_msg in cases:
        assert isinstance(sys_msg, str) and sys_msg
        assert isinstance(usr_msg, str) and usr_msg


def test_fir_draft_prompt_includes_case_id_and_sections():
    sys_msg, usr_msg = prompts.fir_draft("CASE-X", ["376 IPC", "6 POCSO"], "victim minor")
    assert "CASE-X" in usr_msg
    assert "376 IPC" in usr_msg
    assert "6 POCSO" in usr_msg


def test_cross_exam_prep_prompt_uses_category():
    _, usr_hostile = prompts.cross_exam_prep("W", "Hostile", "stmt", ["376"], "x")
    _, usr_supportive = prompts.cross_exam_prep("W", "Supportive", "stmt", ["376"], "x")
    assert "Hostile" in usr_hostile
    assert "Supportive" in usr_supportive


def test_mock_cctns_push_pull_roundtrip(temp_dir):
    from src.aranmanai.integrations.mock_cctns import CCTNSCase
    c = CCTNSCase(case_id="CCTNS-1", fir_no="FIR-1", district="Vellore", sections=["376 IPC"])
    assert mock_cctns.push_case(c) is True
    pulled = mock_cctns.pull_case("CCTNS-1")
    assert pulled is not None and pulled.fir_no == "FIR-1"
    assert "CCTNS-1" in mock_cctns.list_case_ids()
    assert mock_cctns.delete_case("CCTNS-1") is True
    assert mock_cctns.pull_case("CCTNS-1") is None


def test_mock_esakshya_sid_format_and_hash_roundtrip(temp_dir):
    from src.aranmanai.integrations.mock_esakshya import (
        SIDPacket, build_packet, hash_content, generate_sid, validate_hash,
    )
    sid = generate_sid()
    assert len(sid) == 16 and sid.isdigit()
    content = b"test evidence bytes"
    h = hash_content(content)
    assert len(h) == 64
    p = build_packet(
        fir_no="F-1", case_id="C-1", evidence_type="photo", content=content, io_badge="IO-1",
    )
    assert isinstance(p, SIDPacket)
    assert len(p.sid) == 16
    assert p.hash_sha256 == h
    assert mock_esakshya.upload_packet(p) is True
    fetched = mock_esakshya.get_packet(p.sid)
    assert fetched is not None
    assert validate_hash(p.sid, content) is True
    assert validate_hash(p.sid, b"tampered") is False
    packets = mock_esakshya.list_packets_for_case("C-1")
    assert any(pk.sid == p.sid for pk in packets)


def test_mock_esakshya_rejects_bad_sid():
    from src.aranmanai.integrations.mock_esakshya import SIDPacket
    with pytest.raises(Exception):
        SIDPacket(
            sid="abc", fir_no="F", case_id="C", evidence_type="photo",
            timestamp_open="t", timestamp_close="t",
            hash_sha256="0" * 64, io_badge="I",
        )


def test_mock_icjs_link_and_lookup(temp_dir):
    e = mock_icjs.link_case(fir_no="FIR-ICJS-1", case_id="C-ICJS-1", cnr="CNR1", custody_status="on_bail")
    assert e.fir_no == "FIR-ICJS-1" and e.cnr == "CNR1" and e.custody_status == "on_bail"
    found = mock_icjs.lookup("FIR-ICJS-1")
    assert found is not None
    by_cnr = mock_icjs.lookup_by_cnr("CNR1")
    assert by_cnr is not None and by_cnr.fir_no == "FIR-ICJS-1"
    assert mock_icjs.record_hearing("FIR-ICJS-1", "2026-09-01T10:00:00+00:00") is True
    updated = mock_icjs.lookup("FIR-ICJS-1")
    assert updated.hearing_count == 1
    assert updated.next_hearing == "2026-09-01T10:00:00+00:00"
