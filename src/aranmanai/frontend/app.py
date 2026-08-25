"""Aranmanai Streamlit app — main entrypoint.

Run with: streamlit run src/aranmanai/frontend/app.py

Frontend QA fixes applied (2026-08-25). See docs/FRONTEND_QA_AUDIT_2026-08.md.
"""
from __future__ import annotations

import base64
import json as _json
import sys
import time
from pathlib import Path

# Add project root to sys.path so `from aranmanai...` works under streamlit
_ROOT = Path(__file__).resolve().parents[3]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

import requests
import streamlit as st

from aranmanai.config import get_settings

# Always-wide layout. Login also uses wide so the visual transition is
# not jarring. (Fix U-1)
#
# U-8: `_sidebar_state` (session_state) drives `initial_sidebar_state` below.
# Streamlit's sidebar only re-evaluates its collapsed/expanded state when
# this value actually *changes* between reruns (it does not track a
# persisted "user manually collapsed" flag) — so toggling this value is a
# real way to force it back open, not just a placebo. See "Show Menu"
# button in main_page().
st.set_page_config(
    page_title="Aranmanai",
    page_icon="🏛️",
    layout="wide",
    initial_sidebar_state=st.session_state.get("_sidebar_state", "auto"),
)

API_BASE = f"http://{get_settings().host}:{get_settings().port}"


# ──────────────────────────────────────────────────────────────
# F-7 / S-7: Guard — require token for any tab that calls the API
# ──────────────────────────────────────────────────────────────
def _require_auth() -> str:
    token = st.session_state.get("token")
    if not token:
        st.warning("Please log in to use this view.")
        st.stop()
    return token


# ──────────────────────────────────────────────────────────────
# S-8: JWT expiry detection — auto-logout when token expires
# ──────────────────────────────────────────────────────────────
def _jwt_exp(token: str) -> int | None:
    """Return the JWT 'exp' claim (unix timestamp), or None if unparseable."""
    try:
        payload = token.split(".")[1]
        payload += "=" * ((4 - len(payload) % 4) % 4)
        return int(_json.loads(base64.urlsafe_b64decode(payload)).get("exp", 0))
    except Exception:
        return None


def _check_token_validity() -> None:
    """If the stored token is expired, clear session and rerun."""
    token = st.session_state.get("token")
    if token and _jwt_exp(token):
        exp = _jwt_exp(token)
        if exp and exp < time.time():
            st.session_state.clear()
            st.rerun()


# ──────────────────────────────────────────────────────────────
# F-12: Whitespace-trim + non-empty validation helper
# ──────────────────────────────────────────────────────────────
def _nonempty(label: str, value: str) -> str:
    """Strip and require non-empty. Returns the cleaned value."""
    v = (value or "").strip()
    if not v:
        st.error(f"{label} cannot be empty.")
        st.stop()
    return v


# ──────────────────────────────────────────────────────────────
# S-6: HTTP error handler — redirects 401 to login, retries on others
# ──────────────────────────────────────────────────────────────
def _api_call(method: str, path: str, *, token: str | None = None, **kwargs) -> dict:
    """Centralized API call with auth header + 401 auto-logout + retry affordance.

    method: 'get' | 'post' | 'patch' | 'delete'
    path: API path beginning with /
    """
    headers = kwargs.pop("headers", {})
    if token:
        headers["Authorization"] = f"Bearer {token}"
    try:
        r = requests.request(method, f"{API_BASE}{path}", headers=headers, timeout=kwargs.pop("timeout", 30), **kwargs)
    except requests.exceptions.ConnectionError:
        st.error("Cannot reach the API. Is the server running?")
        st.stop()
    if r.status_code == 401:
        st.error("Your session has expired. Please log in again.")
        st.session_state.clear()
        st.rerun()
    if r.status_code >= 400:
        # S-6: offer retry
        body = r.text[:300] if r.text else "(empty)"
        st.error(f"API error {r.status_code}: {body}")
        if st.button("Retry", key=f"retry_{path}_{r.status_code}"):
            st.rerun()
        st.stop()
    r.raise_for_status()
    return r.json() if r.content else {}


def api_get(path: str, token: str | None = None) -> dict:
    return _api_call("get", path, token=token, timeout=30)


def api_post(path: str, body: dict, token: str | None = None) -> dict:
    return _api_call("post", path, token=token, json=body, timeout=60)


def api_patch(path: str, body: dict, token: str | None = None) -> dict:
    return _api_call("patch", path, token=token, json=body, timeout=60)


def api_post_multipart(path: str, *, files: dict, data: dict | None = None, token: str | None = None, timeout: int = 120) -> dict:
    """For file uploads. Goes through the same 401/error pipeline."""
    headers = {}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    try:
        r = requests.post(
            f"{API_BASE}{path}", headers=headers, files=files, data=data or {}, timeout=timeout
        )
    except requests.exceptions.ConnectionError:
        st.error("Cannot reach the API. Is the server running?")
        st.stop()
    if r.status_code == 401:
        st.error("Your session has expired. Please log in again.")
        st.session_state.clear()
        st.rerun()
    if r.status_code >= 400:
        st.error(f"API error {r.status_code}: {r.text[:300]}")
        st.stop()
    r.raise_for_status()
    return r.json() if r.content else {}


# ──────────────────────────────────────────────────────────────
# U-2: Truncate long strings with ellipsis
# ──────────────────────────────────────────────────────────────
def _short(s: str | None, n: int = 40) -> str:
    s = s or "—"
    return s if len(s) <= n else s[: n - 1] + "…"


# ──────────────────────────────────────────────────────────────
# U-7: Custom CSS — focus indicators + improved button contrast
# ──────────────────────────────────────────────────────────────
st.markdown(
    """
<style>
button:focus, [role="button"]:focus, [data-testid="baseButton"]:focus {
    outline: 2px solid #ffaa00 !important;
    outline-offset: 2px !important;
}
</style>
""",
    unsafe_allow_html=True,
)


# ──────────────────────────────────────────────────────────────
# Login
# ──────────────────────────────────────────────────────────────
def login_page() -> None:
    st.title("Aranmanai (அரண்மனை)")
    st.subheader("Conviction-Rate Management")
    st.caption("District-scoped · IPS SP-of-district lens · Lean solo v1")
    with st.form("login"):
        # F-12: trim username
        username = st.text_input("Username").strip()
        password = st.text_input("Password", type="password")
        submitted = st.form_submit_button("Sign in")
    if submitted:
        if not username:
            st.error("Username cannot be empty or whitespace.")
            st.stop()
        # S-3: spinner during submit
        with st.spinner("Signing in..."):
            try:
                r = api_post("/api/v1/auth/login", {"username": username, "password": password})
            except Exception as e:
                st.error(f"Login failed: {e}")
                st.stop()
        st.session_state["token"] = r["access_token"]
        st.session_state["user"] = r
        st.rerun()


# ──────────────────────────────────────────────────────────────
# U-8: persistent breadcrumb at top of every page
# ──────────────────────────────────────────────────────────────
def _breadcrumb(page_name: str) -> None:
    st.caption(f"Aranmanai › **{page_name}**")  # noqa: RUF001 -- intentional breadcrumb separator


# ──────────────────────────────────────────────────────────────
# U-8: sidebar recovery — a visible, working way back in after the user
# collapses Streamlit's native sidebar.
#
# Streamlit has no public "force sidebar open" API. But it is not a
# placebo either: verified against the installed streamlit==1.40.0
# frontend bundle that `Sidebar.componentDidUpdate` recomputes
# `collapsedSidebar` (open/closed) from the `initialSidebarState` prop
# *whenever that prop's value changes* between reruns — there is no
# separate persisted "user manually collapsed" flag that would fight
# this, so a genuine value change reliably re-expands it.
#
# `initial_sidebar_state` only accepts "auto" / "expanded" / "collapsed"
# (anything else raises StreamlitInvalidSidebarStateError), so re-sending
# the same "expanded" string twice in a row is a no-op the *second* time
# (no value change => no recompute). We therefore flip-flop between
# "expanded" and "auto" on every click, which guarantees the value
# genuinely changes on every click. Since this app always renders with
# layout="wide" on a single-workstation desktop deployment, "auto"
# resolves to expanded in practice (Streamlit only auto-collapses under
# a ~768px width) — the flip-flop lands on an open sidebar on every
# click in the deployment this product targets.
# ──────────────────────────────────────────────────────────────
def _show_menu_button() -> None:
    if st.button(
        "Show Menu",
        key="_show_menu_btn",
        help="Opens the navigation panel (Cases, CMC, Witnesses, AI Assist) if it has been closed.",
    ):
        current = st.session_state.get("_sidebar_state", "auto")
        st.session_state["_sidebar_state"] = "auto" if current == "expanded" else "expanded"
        st.rerun()


# ──────────────────────────────────────────────────────────────
# Main page
# ──────────────────────────────────────────────────────────────
def main_page() -> None:
    _check_token_validity()
    token = st.session_state.get("token")
    user = st.session_state.get("user")
    if not token or not user:
        login_page()
        return
    _show_menu_button()
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


# ──────────────────────────────────────────────────────────────
# Today
# ──────────────────────────────────────────────────────────────
def render_today() -> None:
    _breadcrumb("Today")
    token = _require_auth()
    st.header("Today")
    try:
        with st.spinner("Loading hearings..."):
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
        # U-2: truncate FIR number
        fir = _short(h.get("fir_no", ""), 50)
        with st.expander(f"{color} {fir} — {h.get('case_stage', '?')} — {priority.upper()}"):
            cols = st.columns(4)
            cols[0].metric("Witnesses", h.get("total_witnesses", 0))
            cols[1].metric("Hostile", h.get("hostile_witnesses", 0))
            cols[2].metric("Prepared", h.get("prepared_witnesses", 0))
            cols[3].metric("Risk", f"{h['risk_score']:.2f}" if h.get("risk_score") else "—")
            st.write(f"Judge: {h.get('judge') or '—'}")
            st.write(f"Docket: {h.get('docket_label') or '—'}")
            if h.get("pp_confirmed") is not None:
                st.write(
                    f"PP: {h['pp_confirmed']} | "
                    f"Defense: {h['defense_confirmed']} | "
                    f"Accused: {h['accused_confirmed']}"
                )


# ──────────────────────────────────────────────────────────────
# Cases
# ──────────────────────────────────────────────────────────────
def render_cases() -> None:
    _breadcrumb("Cases")
    token = _require_auth()
    st.header("Cases")

    # F4 fix: pagination, search, status filter, stage filter, pilot_only
    if "cases_page" not in st.session_state:
        st.session_state.cases_page = 1
    if "cases_search" not in st.session_state:
        st.session_state.cases_search = ""

    col_search, col_status, col_stage, col_pilot = st.columns([3, 2, 2, 1])
    with col_search:
        search = st.text_input(
            "Search FIR or facts",
            value=st.session_state.cases_search,
            key="cases_search_input",
        )
        if search != st.session_state.cases_search:
            st.session_state.cases_search = search
            st.session_state.cases_page = 1
    with col_status:
        status_filter = st.selectbox(
            "Status", ["", "open", "charge_sheeted", "trial", "judgment",
                        "appeal", "closed_acquitted", "closed_convicted"],
            index=0, key="cases_status_select",
        )
    with col_stage:
        stage_filter = st.selectbox(
            "Stage", ["", "investigation", "charge_sheet", "argument",
                        "evidence", "judgment"],
            index=0, key="cases_stage_select",
        )
    with col_pilot:
        pilot_only = st.checkbox("Pilot only", value=False, key="cases_pilot_only")

    qs = {
        "page": st.session_state.cases_page,
        "page_size": 10,
        "search": st.session_state.cases_search or None,
        "status": status_filter or None,
        "stage": stage_filter or None,
        "pilot_only": pilot_only,
    }
    qs = {k: v for k, v in qs.items() if v is not None}
    qs_str = "&".join(f"{k}={v}" for k, v in qs.items())
    try:
        with st.spinner("Loading cases..."):
            data = api_get(f"/api/v1/kishore/cases?{qs_str}", token=token)
    except Exception as e:
        st.error(f"Failed: {e}")
        return

    cases = data.get("cases", [])
    total = data.get("total", 0)
    has_more = data.get("has_more", False)
    page = data.get("page", 1)

    col_prev, col_info, col_next = st.columns([1, 3, 1])
    with col_prev:
        if st.button("Prev", disabled=page <= 1, key="cases_prev") and page > 1:
            st.session_state.cases_page = page - 1
            st.rerun()
    with col_info:
        st.write(f"Page {page} — showing {len(cases)} of {total} cases")
    with col_next:
        if st.button("Next", disabled=not has_more, key="cases_next") and has_more:
            st.session_state.cases_page = page + 1
            st.rerun()

    if not cases:
        st.info("No cases match your filters.")
        return

    for c in cases:
        fir = _short(c.get("fir_no", ""), 40)
        status = c.get("status", "?")
        stage = c.get("stage", "?")
        with st.expander(f"{fir} — {status} / {stage}"):
            cols = st.columns(4)
            cols[0].metric("Status", status)
            cols[1].metric("Stage", stage)
            cols[2].metric("Next hearing", str(c.get("next_hearing") or "—")[:10])
            cols[3].metric("Risk", f"{c['risk_score']:.2f}" if c.get("risk_score") else "—")
            st.write(f"**Court:** {c.get('court') or '—'}")
            st.write(f"**Judge:** {c.get('judge') or '—'}")
            st.write(f"**IO:** {c.get('io_username') or '—'}")
            st.write(f"**PP:** {c.get('pp_username') or '—'}")
            st.write(f"**District:** {c.get('district', '—')}")
            if c.get("bns_sections"):
                with st.expander("BNS Sections"):
                    st.write(", ".join(c["bns_sections"]))


# ──────────────────────────────────────────────────────────────
# Witnesses
# ──────────────────────────────────────────────────────────────
def render_witnesses() -> None:
    _breadcrumb("Witnesses")
    token = _require_auth()
    st.header("Witnesses")
    try:
        with st.spinner("Loading witnesses..."):
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
        # U-2: truncate witness name
        wname = _short(w.get("name", "?"), 40)
        with st.expander(f"{color} {wname} ({w['type']}) — {cat}"):
            st.write(f"Prep: {w['prep_status']}")
            if w.get("hostile_reason"):
                st.warning(f"Hostile reason: {w['hostile_reason']}")


# ──────────────────────────────────────────────────────────────
# SP Dashboard
# ──────────────────────────────────────────────────────────────
def render_sp_dashboard() -> None:
    _breadcrumb("SP Dashboard")
    token = _require_auth()
    st.header("SP Daily Review")
    district = st.session_state["user"]["district"]
    try:
        with st.spinner("Loading dashboard..."):
            data = api_get(f"/api/v1/cms/sp-dashboard?district={district}", token=token)
    except Exception as e:
        st.error(f"Failed: {e}")
        return
    # U-3/F-6: single-workstation v1 — always wide-desktop layout (no fake
    # responsiveness; see README "Known Limitations").
    cols = st.columns(4)
    cols[0].metric("Today hearings", data["today_hearings"])
    cols[1].metric("Critical hearings", data["critical_hearings"])
    cols[2].metric("Cases stuck", data["cases_stuck"])
    cols[3].metric("Hostile need prep", data["hostile_witnesses_needing_prep"])
    if data.get("conviction_rate_30d") is not None:
        st.metric(
            "Conviction rate (30 days)",
            f"{data['conviction_rate_30d']:.0%}",
            delta=f"{data['trend_delta']:+.0%}" if data.get("trend_delta") is not None else None,
        )
    st.subheader("Top actions")
    for a in data.get("top_actions", []):
        st.write(f"- {a}")


# ──────────────────────────────────────────────────────────────
# CMC Morning
# ──────────────────────────────────────────────────────────────
def render_cmc_morning() -> None:
    """CMC morning view — Kishore's accountability loop, in the UI.

    The SP sees this at 10am. Their job:
    1. Review escalations (overdue actions)
    2. Review pending actions
    3. Open today's meeting (if not already)
    4. Sign off on every case
    """
    _breadcrumb("CMC Morning — 10am Review")
    token = _require_auth()
    st.header("CMC Morning — 10am Review")
    st.caption("Kishore's accountability loop. SP reviews every case daily.")

    try:
        with st.spinner("Loading CMC view..."):
            view = api_get("/api/v1/cmc/daily-view", token=token)
    except Exception as e:
        st.error(f"Failed to load CMC view: {e}")
        return

    # U-3/F-6: single-workstation v1 — always wide-desktop layout (no fake
    # responsiveness; see README "Known Limitations").
    cols = st.columns(5)
    cols[0].metric("Today's hearings", view["n_hearings"])
    cols[1].metric("Pending actions", view["n_actions_pending"])
    cols[2].metric("Overdue actions", view["n_actions_overdue"], delta_color="inverse")
    cols[3].metric("Open escalations", view["n_escalations_open"], delta_color="inverse")
    cols[4].metric("Cases unreviewed", view["n_cases_unreviewed"], delta_color="inverse")

    # Open meeting (W-5/S-2: rerun after success)
    st.subheader("1. Open morning meeting")
    if st.button("Open today's CMC meeting", key="open_meeting_btn"):
        # F-1 / F-2: guard against double-click via session_state flag
        if st.session_state.get("opening_meeting"):
            st.info("Already opening…")
        else:
            st.session_state["opening_meeting"] = True
            try:
                with st.spinner("Opening meeting..."):
                    r = api_post(
                        "/api/v1/cmc/meeting",
                        {"minutes": "Daily CMC — 10am"},
                        token=token,
                    )
                st.success(f"Meeting opened: {_short(r['meeting_id'], 12)}…")
                # W-5 / S-2: rerun to refresh the rest of the page
                st.rerun()
            except Exception as e:
                st.error(f"Failed: {e}")
            finally:
                st.session_state["opening_meeting"] = False

    # Today's hearings
    st.subheader("2. Today's hearings")
    if not view["hearings"]:
        st.info("No hearings today.")
    for h in view["hearings"]:
        reviewed = h.get("sp_reviewed", "pending")
        icon = {"reviewed": "OK", "escalated": "ESC", "cleared": "CLR", "pending": "..."}.get(reviewed, "?")
        # U-2: truncate FIR number
        fir = _short(h.get("fir_no", ""), 40)
        with st.expander(f"[{icon}] {fir} — {h.get('stage', '?')}"):
            st.write(f"Hearing: {h.get('date', '?')}")
            st.write(f"PP present: {h.get('pp_present')}, Accused: {h.get('accused_present')}")
            # W-5 / S-1 / F-1: disable button during in-flight, then rerun
            btn_key = f"sp_rev_{h['hearing_id']}"
            if st.session_state.get(f"reviewing_{h['hearing_id']}"):
                st.info("Marking reviewed…")
            elif st.button("Mark reviewed", key=btn_key):
                st.session_state[f"reviewing_{h['hearing_id']}"] = True
                try:
                    with st.spinner("Marking reviewed..."):
                        api_post(
                            "/api/v1/cmc/sp-review",
                            {"case_id": h["case_id"], "status": "reviewed"},
                            token=token,
                        )
                    st.success("Marked reviewed.")
                    # W-5 / S-1: rerun to refresh
                    st.rerun()
                except Exception as e:
                    st.error(f"Failed: {e}")
                finally:
                    st.session_state[f"reviewing_{h['hearing_id']}"] = False

    # Overdue actions
    st.subheader("3. Overdue actions (raised escalations)")
    if not view["overdue_actions"]:
        st.success("No overdue actions.")
    for a in view["overdue_actions"]:
        # U-2: truncate description
        desc = _short(a.get("description", ""), 60)
        # U-2: truncate FIR number
        fir = _short(a.get("fir_no", ""), 40)
        with st.expander(f"[{a.get('priority', '?')}] {desc} (FIR: {fir})"):
            st.write(f"Assigned to: {a.get('assigned_role', '?')}")
            st.write(f"Due: {a.get('due_date', '?')}")

    # Open escalations
    st.subheader("4. Open escalations")
    if not view["open_escalations"]:
        st.success("No open escalations.")
    for e in view["open_escalations"]:
        sev = {"critical": "🔴", "warning": "🟠", "info": "⚪"}.get(e.get("severity"), "⚪")
        reason = _short(e.get("reason", ""), 60)
        fir = _short(e.get("fir_no", ""), 40)
        with st.expander(f"{sev} {reason} (FIR: {fir})"):
            st.write(f"Detail: {e.get('detail') or '—'}")
            st.write(f"Raised: {e.get('created_at', '?')}")

    # Top priority actions
    st.subheader("5. Top priority actions")
    if not view["top_priority"]:
        st.info("Nothing pending.")
    for a in view["top_priority"]:
        desc = _short(a.get("description", ""), 80)
        fir = _short(a.get("fir_no", ""), 40)
        st.write(
            f"- [{a.get('priority', '?')}] {desc} "
            f"(FIR: {fir}, status: {a.get('status', '?')})"
        )


# ──────────────────────────────────────────────────────────────
# AI Assist — W-1, W-2, S-5, F-3, F-5
# ──────────────────────────────────────────────────────────────
def render_ai_assist() -> None:
    _breadcrumb("AI Assist")
    token = _require_auth()
    st.header("AI Assist")
    tab = st.selectbox(
        "Service",
        [
            "Complaint Intake",
            "FIR Draft",
            "Chargesheet Draft",
            "Investigation Recommendations",
            "Cross-Exam Prep",
            "Risk Score",
        ],
    )

    # F-5: Persist last result per tab in session_state
    last_key = f"_last_result_{tab}"
    if hasattr(st.session_state, last_key):
        st.info("Showing your last result for this tab (re-run to refresh).")
        last = getattr(st.session_state, last_key)
        st.json(last)

    if tab == "Complaint Intake":
        with st.form("intake"):
            raw = st.text_area("Raw complaint (voice transcript or text)")
            name = st.text_input("Complainant name (optional)")
            contact = st.text_input("Complainant contact (optional)")
            submitted = st.form_submit_button("Generate structured complaint")
        if submitted:
            # F-3: whitespace check
            try:
                raw_clean = _nonempty("Raw complaint", raw)
            except SystemExit:
                return
            with st.spinner("Generating complaint..."):
                try:
                    r = api_post(
                        "/api/v1/ai/complaint-intake",
                        {
                            "raw_complaint": raw_clean,
                            "complainant_name": name.strip() or None,
                            "complainant_contact": contact.strip() or None,
                            "language": "en",
                        },
                        token=token,
                    )
                except Exception as e:
                    st.error(f"Failed: {e}")
                    return
            setattr(st.session_state, last_key, r)
            st.text_area("Structured complaint", r.get("structured", ""), height=400)
            st.write(f"**Registerable:** {r.get('registerable', '?')}")
            st.write(f"**Likely BNS sections:** {r.get('likely_sections_bns', [])}")

    elif tab == "FIR Draft":
        # F8 fix: case_id auto-fills 8 of 9 fields from the existing Case record
        token_fir = _require_auth()
        st.write(
            "Enter a case_id to auto-fill from the existing Case record. "
            "Only `facts` (the unique part of this case) needs IO input."
        )
        with st.form("fir_autofill"):
            auto_case_id = st.text_input("Case ID (for autofill)")
            auto_btn = st.form_submit_button("Autofill from case")
        if auto_btn and auto_case_id:
            with st.spinner("Fetching case record..."):
                try:
                    autofill = api_get(
                        f"/api/v1/kishore/cases/{auto_case_id}/fir-autofill", token=token_fir
                    )
                    st.session_state["fir_autofill"] = autofill
                    st.success(
                        f"Auto-filled from {autofill.get('fir_no')}. "
                        f"Auto-populated: {', '.join(autofill.get('auto_filled_fields', []))}"
                    )
                except Exception as e:
                    st.error(f"Autofill failed: {e}")

        # F7 fix: case entry in Tamil, auto-translated to English
        with st.expander("F7: enter case notes in Tamil (auto-translate)"):
            f7_text = st.text_area("Tamil/Hindi text", height=120, key="f7_text")
            f7_case_id = st.text_input("Case ID (optional, to persist)", key="f7_case_id")
            f7_lang = st.selectbox("Source language", ["ta", "hi", "te", "kn", "ml", "mr", "bn", "en"], index=0, key="f7_lang")
            if st.button("Translate", key="f7_translate") and f7_text:
                with st.spinner("Translating..."):
                    try:
                        r_f7 = api_post(
                            "/api/v1/kishore/cases/translate-entry",
                            {"case_id": f7_case_id or "case-scst-019",
                             "text": f7_text, "source_language": f7_lang},
                            token=token_fir,
                        )
                        st.session_state["f7_translated"] = r_f7
                        st.success(f"Translated ({r_f7.get('model')}):")
                        st.text_area("English", r_f7.get("translated_text", ""), height=120, key="f7_out")
                    except Exception as e:
                        st.error(f"Translate failed: {e}")

        # F8 wiring: full form, pre-populated from autofill if available
        autofill = st.session_state.get("fir_autofill", {})
        with st.form("fir"):
            fir_no = st.text_input("FIR No.", value=autofill.get("fir_no", ""))
            ps = st.text_input("Police Station")
            district = st.text_input("District", value=st.session_state["user"].get("district", ""))
            complainant_name = st.text_input("Complainant name")
            complainant_contact = st.text_input("Complainant contact")
            incident_dt = st.text_input("Incident date/time", value=(autofill.get("incident_datetime") or "")[:10] if autofill.get("incident_datetime") else "")
            location = st.text_input("Location")
            facts = st.text_area("Facts", value=autofill.get("facts_summary", ""))
            io_name = st.text_input("IO name")
            bns_default = ", ".join(autofill.get("bns_sections_suggested", []))
            bns = st.text_input("BNS sections (comma-separated)", value=bns_default)
            submitted = st.form_submit_button("Draft FIR")
        if submitted:
            # F-3: facts is required
            try:
                facts_clean = _nonempty("Facts", facts)
            except SystemExit:
                return
            with st.spinner("Drafting FIR..."):
                try:
                    r = api_post(
                        "/api/v1/ai/fir-draft",
                        {
                            "fir_no": fir_no.strip() or None,
                            "police_station": ps.strip() or None,
                            "district": district.strip() or None,
                            "complainant_name": complainant_name.strip() or None,
                            "complainant_contact": complainant_contact.strip() or None,
                            "incident_datetime": incident_dt.strip() or None,
                            "location": location.strip() or None,
                            "facts": facts_clean,
                            "io_name": io_name.strip() or None,
                            "bns_sections": [s.strip() for s in bns.split(",") if s.strip()] or None,
                        },
                        token=token,
                    )
                except Exception as e:
                    st.error(f"Failed: {e}")
                    return
            setattr(st.session_state, last_key, r)
            st.text_area("Drafted FIR", r.get("drafted_fir", ""), height=400)
            st.write(f"**FIR No:** {r.get('fir_no', '?')}")
            st.write(f"**Sections applied:** {r.get('sections_applied', [])}")

    elif tab == "Chargesheet Draft":
        # W-2: wire up
        with st.form("chargesheet"):
            case_id = st.text_input("Case ID")
            charges = st.text_area("Charges (one per line, e.g. 'BNS 302 murder')")
            evidence_summary = st.text_area("Evidence summary")
            witnesses = st.text_area("Witnesses (one per line, name + role)")
            submitted = st.form_submit_button("Draft chargesheet")
        if submitted:
            try:
                _nonempty("Case ID", case_id)
                _nonempty("Charges", charges)
            except SystemExit:
                return
            with st.spinner("Drafting chargesheet..."):
                try:
                    r = api_post(
                        "/api/v1/ai/chargesheet-draft",
                        {
                            "case_id": case_id.strip(),
                            "charges": [c.strip() for c in charges.split("\n") if c.strip()],
                            "evidence_summary": evidence_summary.strip() or None,
                            "witnesses": [
                                w.strip() for w in witnesses.split("\n") if w.strip()
                            ] or None,
                        },
                        token=token,
                    )
                except Exception as e:
                    st.error(f"Failed: {e}")
                    return
            setattr(st.session_state, last_key, r)
            st.text_area("Drafted chargesheet", r.get("drafted_chargesheet", ""), height=400)
            st.write(f"**Charges applied:** {r.get('charges_applied', [])}")

    elif tab == "Investigation Recommendations":
        # W-2: wire up
        with st.form("inv_recs"):
            case_id = st.text_input("Case ID")
            case_facts = st.text_area("Case facts (known so far)")
            focus = st.selectbox(
                "Focus area",
                ["witnesses", "evidence", "forensic", "all"],
            )
            submitted = st.form_submit_button("Get recommendations")
        if submitted:
            try:
                _nonempty("Case ID", case_id)
                _nonempty("Case facts", case_facts)
            except SystemExit:
                return
            with st.spinner("Generating recommendations..."):
                try:
                    r = api_post(
                        "/api/v1/ai/investigation-recommendations",
                        {
                            "case_id": case_id.strip(),
                            "case_facts": case_facts.strip(),
                            "focus": focus,
                        },
                        token=token,
                    )
                except Exception as e:
                    st.error(f"Failed: {e}")
                    return
            setattr(st.session_state, last_key, r)
            for rec in r.get("recommendations", []):
                st.write(f"- {rec}")

    elif tab == "Cross-Exam Prep":
        # W-2: wire up
        with st.form("cross_exam"):
            witness_id = st.text_input("Witness ID")
            case_facts = st.text_area("Case facts (what the prosecution will rely on)")
            witness_statement = st.text_area("Witness statement (their own version)")
            language = st.selectbox("Language", ["en", "ta", "hi"], index=0)
            submitted = st.form_submit_button("Generate cross-exam questions")
        if submitted:
            try:
                _nonempty("Witness ID", witness_id)
                _nonempty("Case facts", case_facts)
            except SystemExit:
                return
            with st.spinner("Generating cross-exam questions..."):
                try:
                    r = api_post(
                        "/api/v1/witnesses/cross-exam-prep",
                        {
                            "witness_id": witness_id.strip(),
                            "case_facts": case_facts.strip(),
                            "witness_statement": witness_statement.strip() or None,
                            "language": language,
                        },
                        token=token,
                    )
                except Exception as e:
                    st.error(f"Failed: {e}")
                    return
            setattr(st.session_state, last_key, r)
            st.text_area(
                "Cross-exam questions",
                r.get("questions", ""),
                height=400,
            )
            st.write(f"**Strategy notes:** {r.get('strategy_notes', '—')}")

    elif tab == "Risk Score":
        with st.form("risk"):
            case_id = st.text_input("Case ID")
            facts = st.text_area("Case facts")
            evidence_strength = st.selectbox("Evidence strength", ["STRONG", "MEDIUM", "WEAK"])
            witness_count = st.number_input("Witness count", min_value=0, value=3)
            hostile_count = st.number_input("Hostile witness count", min_value=0, value=0)
            fsl = st.selectbox(
                "FSL status",
                ["returned", "in_queue", "sent", "not_sent", "overdue"],
            )
            bnss173 = st.checkbox("BNSS §173 AV recording done", value=False)
            submitted = st.form_submit_button("Score")
        if submitted:
            # F-3: facts required
            try:
                facts_clean = _nonempty("Case facts", facts)
            except SystemExit:
                return
            with st.spinner("Computing risk score..."):
                try:
                    r = api_post(
                        "/api/v1/risk/score",
                        {
                            "case_id": case_id.strip(),
                            "case_facts": facts_clean,
                            "evidence_strength": evidence_strength,
                            "witness_count": int(witness_count),
                            "hostile_witness_count": int(hostile_count),
                            "fsl_status": fsl,
                            "bnss_173_compliant": bnss173,
                            "lapses": [],
                            "language": "en",
                        },
                        token=token,
                    )
                except Exception as e:
                    st.error(f"Failed: {e}")
                    return
            setattr(st.session_state, last_key, r)
            st.metric(
                "Acquittal risk",
                f"{r.get('score', 0):.0%}",
                delta=r.get("band", "?").upper(),
            )
            st.text_area("Narrative", r.get("narrative", ""), height=300)
            st.write("Contributing factors:", r.get("contributing_factors", []))


if __name__ == "__main__":
    main_page()
