"""Integration tests for mock state-platform integrations."""
from __future__ import annotations


def test_mock_cctns_write_read(tmp_env):
    from aranmanai.integrations.mock_cctns import MockCctnsAdapter
    adapter = MockCctnsAdapter()
    rec = {
        "district": "test-district",
        "ps": "Test PS",
        "fir_date": "2026-08-15T14:30:00",
        "sections": ["BNS 308"],
        "complainant": {"name": "Ravi", "contact": "+91-9876543210"},
        "allegations": "Accused threatened with knife.",
    }
    p = adapter.write("MOCK-001/2026", rec)
    assert p.endswith("MOCK-001_2026.json")
    fetched = adapter.read("MOCK-001/2026")
    assert fetched["fir_no"] == "MOCK-001/2026"
    assert fetched["sections"] == ["BNS 308"]


def test_mock_cctns_import_to_aranmanai(tmp_env):
    from aranmanai.integrations.mock_cctns import MockCctnsAdapter
    adapter = MockCctnsAdapter()
    rec = {
        "district": "test-district",
        "ps": "Test PS",
        "fir_date": "2026-08-15T14:30:00",
        "sections": ["BNS 308"],
        "complainant": {"name": "Ravi", "contact": "+91-9876543210"},
        "allegations": "Accused threatened with knife.",
    }
    adapter.write("MOCK-002/2026", rec)
    imported = adapter.import_fir("MOCK-002/2026")
    assert imported["fir_no"] == "MOCK-002/2026"
    assert imported["bns_sections"] == ["BNS 308"]
    assert "cctns_metadata" in imported


def test_mock_cctns_list_firs(tmp_env):
    from aranmanai.integrations.mock_cctns import MockCctnsAdapter
    adapter = MockCctnsAdapter()
    for i in range(3):
        adapter.write(f"MOCK-{i:03d}/2026", {"district": "test-district", "sections": ["BNS 308"]})
    firs = adapter.list_firs(district="test-district")
    assert len(firs) == 3
    assert "MOCK-000/2026" in firs


def test_mock_esakshya_create_sid_packet(tmp_env):
    from aranmanai.integrations.mock_esakshya import MockEsakshyaAdapter
    adapter = MockEsakshyaAdapter()
    packet = adapter.create_packet(
        fir_no="ESAK-001/2026",
        evidence_type="video",
        captured_by="IO S. Krishnan",
        content_bytes=b"video content here",
        metadata={"geo": [12.92, 80.23], "duration_s": 45},
    )
    assert packet["sid"] is not None
    assert len(packet["sid"]) == 16
    assert packet["fir_no"] == "ESAK-001/2026"
    assert packet["content_hash"] is not None
    assert len(packet["content_hash"]) == 64  # SHA-256 hex
    assert packet["content_size_bytes"] == len(b"video content here")


def test_mock_esakshya_read_by_sid(tmp_env):
    from aranmanai.integrations.mock_esakshya import MockEsakshyaAdapter
    adapter = MockEsakshyaAdapter()
    p = adapter.create_packet("F1/2026", "photo", "IO", b"data", {"camera": "Canon"})
    fetched = adapter.read(p["sid"])
    assert fetched["sid"] == p["sid"]
    assert fetched["metadata"]["camera"] == "Canon"


def test_mock_esakshya_list_for_fir(tmp_env):
    from aranmanai.integrations.mock_esakshya import MockEsakshyaAdapter
    adapter = MockEsakshyaAdapter()
    adapter.create_packet("F1/2026", "video", "IO1", b"v1")
    adapter.create_packet("F1/2026", "photo", "IO1", b"p1")
    adapter.create_packet("F2/2026", "video", "IO2", b"v2")
    f1_packets = adapter.list_for_fir("F1/2026")
    assert len(f1_packets) == 2


def test_mock_icjs_link_and_lookup(tmp_env):
    from aranmanai.integrations.mock_icjs import MockIcjsAdapter
    adapter = MockIcjsAdapter()
    adapter.link_case("aranmanai-case-1", "CNR001/2026", "Sessions Court, Chengalpattu")
    link = adapter.lookup("aranmanai-case-1")
    assert link["cnr"] == "CNR001/2026"
    assert link["court"] == "Sessions Court, Chengalpattu"


def test_generate_sid_is_16_digits():
    from aranmanai.integrations.mock_esakshya import generate_sid
    sid = generate_sid()
    assert len(sid) == 16
    assert sid.isdigit()


def test_content_hash_deterministic():
    from aranmanai.integrations.mock_esakshya import compute_content_hash
    h1 = compute_content_hash(b"hello")
    h2 = compute_content_hash(b"hello")
    h3 = compute_content_hash(b"world")
    assert h1 == h2
    assert h1 != h3
    assert len(h1) == 64
