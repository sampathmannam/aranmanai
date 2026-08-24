"""Aranmanai Streamlit app — main entrypoint.

Run with: streamlit run src/aranmanai/frontend/app.py
"""
from __future__ import annotations

import sys
from pathlib import Path

# Add project root to sys.path so `from aranmanai...` works under streamlit
_ROOT = Path(__file__).resolve().parents[3]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

import requests
import streamlit as st

from aranmanai.config import get_settings

API_BASE = f"http://{get_settings().host}:{get_settings().port}"


def api_get(path: str, token: str | None = None) -> dict:
    headers = {"Authorization": f"Bearer {token}"} if token else {}
    r = requests.get(f"{API_BASE}{path}", headers=headers, timeout=30)
    r.raise_for_status()
    return r.json() if r.content else {}


def api_post(path: str, body: dict, token: str | None = None) -> dict:
    headers = {"Authorization": f"Bearer {token}"} if token else {}
    r = requests.post(f"{API_BASE}{path}", json=body, headers=headers, timeout=60)
    r.raise_for_status()
    return r.json() if r.content else {}


def api_patch(path: str, body: dict, token: str | None = None) -> dict:
    headers = {"Authorization": f"Bearer {token}"} if token else {}
    r = requests.patch(f"{API_BASE}{path}", json=body, headers=headers, timeout=60)
    r.raise_for_status()
    return r.json() if r.content else {}


def login_page() -> None:
    st.set_page_config(page_title="Aranmanai", page_icon="🏛️", layout="centered")
    st.title("Aranmanai (அரண்மனை)")
    st.subheader("Conviction-Rate Management")
    st.caption("District-scoped · IPS SP-of-district lens · Lean solo v1")
    with st.form("login"):
        username = st.text_input("Username")
        password = st.text_input("Password", type="password")
        submitted = st.form_submit_button("Sign in")
    if submitted:
        try:
            r = api_post("/api/v1/auth/login", {"username": username, "password": password})
            st.session_state["token"] = r["access_token"]
            st.session_state["user"] = r
            st.success(f"Signed in as {r['username']} ({r['role']})")
            st.rerun()
        except Exception as e:
            st.error(f"Login failed: {e}")


def main_page() -> None:
    st.set_page_config(page_title="Aranmanai", page_icon="🏛️", layout="wide")
    token = st.session_state.get("token")
    user = st.session_state.get("user")
    if not token or not user:
        login_page()
        return
    st.sidebar.title("Aranmanai")
    st.sidebar.write(f"**{user['username']}** ({user['role']})")
    st.sidebar.write(f"District: {user['district']}")
    if st.sidebar.button("Sign out"):
        st.session_state.clear()
        st.rerun()
    page = st.sidebar.radio(
        "Navigate",
        ["Today", "CMC Morning", "Cases", "Witnesses", "SP Dashboard", "AI Assist", "Voice", "Tamil"],
        index=0,
    )
    if page == "Today":
        render_today()
    elif page == "CMC Morning":
        render_cmc_morning()
    elif page == "Cases":
        render_cases()
    elif page == "Witnesses":
        render_witnesses()
    elif page == "SP Dashboard":
        render_sp_dashboard()
    elif page == "AI Assist":
        render_ai_assist()
    elif page == "Voice":
        from aranmanai.frontend.voice_tab import render_voice_tab
        render_voice_tab()
    elif page == "Tamil":
        from aranmanai.frontend.tamil_tab import render_tamil_tab
        render_tamil_tab()


def render_today() -> None:
    st.header("Today")
    token = st.session_state["token"]
    try:
        data = api_get("/api/v1/cms/calendar/today", token=token)
    except Exception as e:
        st.error(f"Failed to load: {e}")
        return
    if not data:
        st.info("No hearings today.")
        return
    st.write(f"{len(data)} hearings today")
    for h in data:
        priority = h.get("priority", "normal")
        color = {"critical": "🔴", "high": "🟠", "normal": "🟢", "low": "⚪"}.get(priority, "⚪")
        with st.expander(f"{color} {h['fir_no']} — {h['case_stage']} — {priority.upper()}"):
            cols = st.columns(4)
            cols[0].metric("Witnesses", h["total_witnesses"])
            cols[1].metric("Hostile", h["hostile_witnesses"])
            cols[2].metric("Prepared", h["prepared_witnesses"])
            cols[3].metric("Risk", f"{h['risk_score']:.2f}" if h.get("risk_score") else "—")
            st.write(f"Judge: {h.get('judge') or '—'}")
            st.write(f"Docket: {h.get('docket_label') or '—'}")
            if h.get("pp_confirmed") is not None:
                st.write(f"PP: {h['pp_confirmed']} | Defense: {h['defense_confirmed']} | Accused: {h['accused_confirmed']}")


def render_cases() -> None:
    st.header("Cases")
    token = st.session_state["token"]
    district = st.session_state["user"]["district"]
    try:
        data = api_get(f"/api/v1/cases?district={district}&limit=100", token=token)
    except Exception as e:
        st.error(f"Failed: {e}")
        return
    if not data:
        st.info("No cases.")
        return
    for c in data:
        with st.expander(f"{c['fir_no']} — {c['status']} / {c['stage']}"):
            st.json(c)


def render_witnesses() -> None:
    st.header("Witnesses")
    token = st.session_state["token"]
    try:
        data = api_get("/api/v1/witnesses", token=token)
    except Exception as e:
        st.error(f"Failed: {e}")
        return
    if not data:
        st.info("No witnesses.")
        return
    for w in data:
        cat = w["category"]
        color = {"supportive": "🟢", "neutral": "⚪", "hostile": "🔴"}.get(cat, "⚪")
        with st.expander(f"{color} {w['name']} ({w['type']}) — {cat}"):
            st.write(f"Prep: {w['prep_status']}")
            if w.get("hostile_reason"):
                st.warning(f"Hostile reason: {w['hostile_reason']}")


def render_sp_dashboard() -> None:
    st.header("SP Daily Review")
    token = st.session_state["token"]
    district = st.session_state["user"]["district"]
    try:
        data = api_get(f"/api/v1/cms/sp-dashboard?district={district}", token=token)
    except Exception as e:
        st.error(f"Failed: {e}")
        return
    cols = st.columns(4)
    cols[0].metric("Today hearings", data["today_hearings"])
    cols[1].metric("Critical hearings", data["critical_hearings"])
    cols[2].metric("Cases stuck", data["cases_stuck"])
    cols[3].metric("Hostile need prep", data["hostile_witnesses_needing_prep"])
    if data.get("conviction_rate_30d") is not None:
        st.metric("Conviction rate (30 days)", f"{data['conviction_rate_30d']:.0%}",
                  delta=f"{data['trend_delta']:+.0%}" if data.get("trend_delta") is not None else None)
    st.subheader("Top actions")
    for a in data.get("top_actions", []):
        st.write(f"- {a}")


def render_cmc_morning() -> None:
    """CMC morning view — Kishore's accountability loop, in the UI.

    The SP sees this at 10am. Their job:
    1. Review escalations (overdue actions)
    2. Review pending actions
    3. Open today's meeting (if not already)
    4. Sign off on every case
    """
    st.header("CMC Morning — 10am Review")
    st.caption("Kishore's accountability loop. SP reviews every case daily.")
    token = st.session_state["token"]

    # Top row: KPIs
    try:
        view = api_get("/api/v1/cmc/daily-view", token=token)
    except Exception as e:
        st.error(f"Failed to load CMC view: {e}")
        return

    cols = st.columns(5)
    cols[0].metric("Today's hearings", view["n_hearings"])
    cols[1].metric("Pending actions", view["n_actions_pending"])
    cols[2].metric("Overdue actions", view["n_actions_overdue"], delta_color="inverse")
    cols[3].metric("Open escalations", view["n_escalations_open"], delta_color="inverse")
    cols[4].metric("Cases unreviewed", view["n_cases_unreviewed"], delta_color="inverse")

    # Open meeting
    st.subheader("1. Open morning meeting")
    if st.button("Open today's CMC meeting"):
        try:
            r = api_post("/api/v1/cmc/meeting", {"minutes": "Daily CMC — 10am"}, token=token)
            st.success(f"Meeting opened: {r['meeting_id'][:8]}...")
            st.session_state["last_meeting_id"] = r["meeting_id"]
        except Exception as e:
            st.error(f"Failed: {e}")

    # Today's hearings
    st.subheader("2. Today's hearings")
    if not view["hearings"]:
        st.info("No hearings today.")
    for h in view["hearings"]:
        reviewed = h.get("sp_reviewed", "pending")
        icon = {"reviewed": "OK", "escalated": "ESC", "cleared": "CLR", "pending": "..."}.get(reviewed, "?")
        with st.expander(f"[{icon}] {h['fir_no']} — {h['stage']}"):
            st.write(f"Hearing: {h['date']}")
            st.write(f"PP present: {h['pp_present']}, Accused: {h['accused_present']}")
            if st.button(f"Mark reviewed", key=f"sp_rev_{h['hearing_id']}"):
                try:
                    api_post("/api/v1/cmc/sp-review",
                             {"case_id": h["case_id"], "status": "reviewed"}, token=token)
                    st.success("Marked reviewed. Refresh to see update.")
                except Exception as e:
                    st.error(f"Failed: {e}")

    # Overdue actions
    st.subheader("3. Overdue actions (raised escalations)")
    if not view["overdue_actions"]:
        st.success("No overdue actions.")
    for a in view["overdue_actions"]:
        with st.expander(f"[{a['priority']}] {a['description']} (FIR: {a['fir_no']})"):
            st.write(f"Assigned to: {a['assigned_role']}")
            st.write(f"Due: {a['due_date']}")

    # Open escalations
    st.subheader("4. Open escalations")
    if not view["open_escalations"]:
        st.success("No open escalations.")
    for e in view["open_escalations"]:
        sev = {"critical": "🔴", "warning": "🟠", "info": "⚪"}.get(e["severity"], "⚪")
        with st.expander(f"{sev} {e['reason']} (FIR: {e['fir_no']})"):
            st.write(f"Detail: {e.get('detail') or '—'}")
            st.write(f"Raised: {e['created_at']}")

    # Top priority actions
    st.subheader("5. Top priority actions")
    if not view["top_priority"]:
        st.info("Nothing pending.")
    for a in view["top_priority"]:
        st.write(f"- [{a['priority']}] {a['description'][:80]} (FIR: {a['fir_no']}, status: {a['status']})")


def render_ai_assist() -> None:
    st.header("AI Assist")
    tab = st.selectbox("Service", ["Complaint Intake", "FIR Draft", "Chargesheet Draft", "Investigation Recommendations", "Cross-Exam Prep", "Risk Score"])
    token = st.session_state["token"]
    if tab == "Complaint Intake":
        with st.form("intake"):
            raw = st.text_area("Raw complaint (voice transcript or text)")
            name = st.text_input("Complainant name (optional)")
            contact = st.text_input("Complainant contact (optional)")
            if st.form_submit_button("Generate structured complaint"):
                try:
                    r = api_post("/api/v1/ai/complaint-intake",
                                 {"raw_complaint": raw, "complainant_name": name or None,
                                  "complainant_contact": contact or None, "language": "en"}, token=token)
                    st.text_area("Structured complaint", r["structured"], height=400)
                    st.write(f"Registerable: {r['registerable']}")
                    st.write(f"Likely BNS sections: {r['likely_sections_bns']}")
                except Exception as e:
                    st.error(f"Failed: {e}")
    elif tab == "FIR Draft":
        with st.form("fir"):
            st.text_input("FIR No.")
            st.text_input("Police Station")
            st.text_input("District")
            st.text_input("Complainant name")
            st.text_input("Complainant contact")
            st.text_input("Incident date/time")
            st.text_input("Location")
            st.text_area("Facts")
            st.text_input("IO name")
            st.text_input("BNS sections (comma-separated)")
            if st.form_submit_button("Draft FIR"):
                st.info("Fill the form and click Draft FIR. Full form handling TBD.")
    elif tab == "Risk Score":
        with st.form("risk"):
            case_id = st.text_input("Case ID")
            facts = st.text_area("Case facts")
            evidence_strength = st.selectbox("Evidence strength", ["STRONG", "MEDIUM", "WEAK"])
            witness_count = st.number_input("Witness count", min_value=0, value=3)
            hostile_count = st.number_input("Hostile witness count", min_value=0, value=0)
            fsl = st.selectbox("FSL status", ["returned", "in_queue", "sent", "not_sent", "overdue"])
            bnss173 = st.checkbox("BNSS §173 AV recording done", value=False)
            if st.form_submit_button("Score"):
                try:
                    r = api_post("/api/v1/risk/score",
                                 {"case_id": case_id, "case_facts": facts,
                                  "evidence_strength": evidence_strength,
                                  "witness_count": int(witness_count),
                                  "hostile_witness_count": int(hostile_count),
                                  "fsl_status": fsl, "bnss_173_compliant": bnss173,
                                  "lapses": [], "language": "en"}, token=token)
                    st.metric("Acquittal risk", f"{r['score']:.0%}", delta=r["band"].upper())
                    st.text_area("Narrative", r["narrative"], height=300)
                    st.write("Contributing factors:", r["contributing_factors"])
                except Exception as e:
                    st.error(f"Failed: {e}")
    else:
        st.info(f"{tab}: form coming. Use the API directly for now.")


if __name__ == "__main__":
    main_page()
