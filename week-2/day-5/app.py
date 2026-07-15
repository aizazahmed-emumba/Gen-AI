"""
app.py — Streamlit UI for the Preference-Aware Travel RAG Assistant.

Shows the pipeline the assignment asks for, stage by stage:
    query  ->  preferences  ->  retrieval + reasoning  ->  grounded answer
with a debug panel (extracted preferences, URLs used, top retrieved chunks).

Run:  streamlit run app.py
"""

import os
# Cap torch threads BEFORE sentence-transformers/torch import (avoids OOM on macOS).
os.environ.setdefault("OMP_NUM_THREADS", "2")

import streamlit as st

import config
import preferences
import retriever
import generator
import store

st.set_page_config(page_title="Travel RAG Assistant", page_icon="🧭", layout="wide")


# Warm the vector store once per session (cross-encoder/embedder lazy-load on first query).
@st.cache_resource
def _warm():
    store.load()
    return True


_warm()

st.title("🧭 Preference-Aware Travel RAG Assistant")
st.caption("Grounded travel answers from Wikivoyage · "
           f"cities: {', '.join(config.CITIES)} · embeddings: {config.EMBED_MODEL}")

query = st.text_input("Ask a travel question",
                      value="3-day Berlin trip with cheap food and art")
go = st.button("Plan my trip", type="primary")

if go and query.strip():
    main, debug = st.columns([3, 2])

    # ── Stage 1: preferences ──
    with st.spinner("Understanding your preferences…"):
        prefs = preferences.extract(query)

    # ── Input guard: unsupported cities are caught HERE, before we waste a
    #    retrieve/rerank/judge cycle. We refuse ONLY when the user named cities and
    #    NONE are supported. If at least one is supported (e.g. "Paris and Rome", or
    #    "Berlin and Tokyo"), we proceed with the supported ones and note the rest.
    supported = prefs.get("cities") or []
    unsupported = prefs.get("unsupported_cities") or []
    if unsupported and not supported:
        with main:
            st.subheader("Answer")
            st.warning(
                f"I don't have travel sources for **{', '.join(unsupported)}**. "
                f"I currently cover only: **{', '.join(config.CITIES)}**. "
                "Ask about one of those cities and I'll plan it for you.")
        with debug:
            st.subheader("🔍 Debug panel")
            with st.expander("① Extracted preferences", expanded=True):
                st.json({k: v for k, v in prefs.items() if k != "_raw"})
            st.caption("Short-circuited at input validation — retrieval was not run.")
        st.stop()
    skipped = unsupported if (unsupported and supported) else []

    # ── Stage 2+3: retrieve + reason ──
    with st.spinner("Retrieving and reasoning over sources…"):
        hits, trace = retriever.retrieve(query, prefs)
    # ── Stage 4: answer ──
    with st.spinner("Writing a grounded answer…"):
        answer = generator.generate(query, prefs, hits, trace["verdict"])

    with main:
        st.subheader("Answer")
        if skipped:
            st.info(f"Note: I don't have sources for **{', '.join(skipped)}**, "
                    f"so I focused on **{', '.join(supported)}**.")
        verdict = trace["verdict"]
        badge = "✅ context_good" if verdict == "context_good" else "⚠️ context_insufficient"
        st.markdown(f"**Context check:** {badge}"
                    + (f"  ·  filters relaxed ×{trace['final_relax_level']}" if trace["final_relax_level"] else ""))
        st.markdown(answer)

    with debug:
        st.subheader("🔍 Debug panel")

        with st.expander("① Extracted preferences", expanded=True):
            st.json({k: v for k, v in prefs.items() if k != "_raw"})

        with st.expander("② Retrieval & reasoning trace", expanded=True):
            for a in trace["attempts"]:
                icon = "✅" if a["verdict"] == "context_good" else "⚠️"
                st.markdown(f"{icon} **relax level {a['relax_level']}** — "
                            f"{a['n_candidates']} candidates → *{a['verdict']}*")
                st.caption(f"filters: {a['filters'] or 'none'} · {a['reason']}")

        with st.expander(f"③ Top {len(hits)} retrieved chunks", expanded=True):
            for i, h in enumerate(hits, 1):
                st.markdown(f"**[{i}]** `{h['city']} · {h['category']} · {h['price_level']}` "
                            f"— rerank {h.get('rerank_score', 0):.2f}")
                st.caption(h["text"][:280] + "…")

        with st.expander("④ Source URLs used", expanded=False):
            for u in sorted({h["url"] for h in hits}):
                st.markdown(f"- [{u}]({u})")

elif go:
    st.warning("Please enter a question.")
