"""Tamil (and other Indian language) tab for the Streamlit app.

Language detection, translation, semantic search via embeddings.
Uses the /api/v1/tamil/* endpoints.
"""
from __future__ import annotations

import requests
import streamlit as st

from aranmanai.config import get_settings

API_BASE = f"http://{get_settings().host}:{get_settings().port}"


def _auth_headers() -> dict:
    token = st.session_state.get("token")
    return {"Authorization": f"Bearer {token}"} if token else {}


def render_tamil_tab() -> None:
    """Render the Tamil/Indian-language tab inside the Streamlit app."""
    st.header("Tamil / Indian languages")
    st.caption("Language detect, translation (Tamil <-> English <-> Hindi), and semantic search.")

    tab = st.selectbox("Tool", ["Detect language", "Translate", "Embed (semantic search)"])

    if tab == "Detect language":
        text = st.text_area("Text to detect", height=120, placeholder="Vanakkam! Naan case ezhuthuren.")
        if st.button("Detect", type="primary") and text:
            try:
                r = requests.post(
                    f"{API_BASE}/api/v1/tamil/detect",
                    json={"text": text},
                    headers=_auth_headers(),
                    timeout=15,
                )
                if r.status_code == 200:
                    result = r.json()
                    cols = st.columns(3)
                    cols[0].metric("Language", f"{result.get('language_name', '?')} ({result.get('language', '?')})")
                    cols[1].metric("Confidence", f"{result.get('confidence', 0):.0%}")
                    cols[2].metric("Script", result.get("script", "?"))
                else:
                    st.error(f"HTTP {r.status_code}: {r.text[:200]}")
            except Exception as e:
                st.error(f"Error: {e}")

    elif tab == "Translate":
        col1, col2 = st.columns(2)
        source = col1.selectbox("From", ["en", "ta", "hi", "te", "kn", "ml", "mr", "bn"], index=0)
        target = col2.selectbox("To", ["en", "ta", "hi", "te", "kn", "ml", "mr", "bn"], index=1)
        text = st.text_area("Text to translate", height=120)
        if st.button("Translate", type="primary") and text:
            try:
                r = requests.post(
                    f"{API_BASE}/api/v1/tamil/translate",
                    json={"text": text, "source": source, "target": target},
                    headers=_auth_headers(),
                    timeout=30,
                )
                if r.status_code == 200:
                    result = r.json()
                    st.text_area("Translated text", result.get("translated_text", ""), height=120)
                    if result.get("routed"):
                        st.caption(f"Routed through: {result.get('via', '?')}")
                    st.code(
                        f"model: {result.get('model', '?')}\n"
                        f"source_sha256: {result.get('source_sha256', '?')[:24]}...",
                        language="text",
                    )
                else:
                    st.error(f"HTTP {r.status_code}: {r.text[:200]}")
            except Exception as e:
                st.error(f"Error: {e}")

    elif tab == "Embed (semantic search)":
        st.caption("Compute a 384-dim multilingual vector for the text. Use for semantic search over cases / witnesses / judgments.")
        text = st.text_area("Text to embed", height=120)
        if st.button("Embed", type="primary") and text:
            try:
                r = requests.post(
                    f"{API_BASE}/api/v1/tamil/embed",
                    json={"text": text},
                    headers=_auth_headers(),
                    timeout=30,
                )
                if r.status_code == 200:
                    result = r.json()
                    cols = st.columns(2)
                    cols[0].metric("Vector dim", result.get("vector_dim", "?"))
                    cols[1].metric("Model", result.get("model", "?"))
                    vec = result.get("vector", [])
                    if vec:
                        # Show as bar chart of first 50 dims (rough visualization)
                        st.bar_chart({"value": vec[:50]})
                        st.caption(f"Showing first 50 of {len(vec)} dimensions.")
                else:
                    st.error(f"HTTP {r.status_code}: {r.text[:200]}")
            except Exception as e:
                st.error(f"Error: {e}")
