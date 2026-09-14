"""Demo UI. The only thing it has to do well is show WHY an answer is trusted:
each claim coloured by its verdict, with the source it was checked against,
and the trace of what the pipeline did to get there.

    streamlit run app/streamlit_demo.py
"""

from __future__ import annotations

import httpx
import streamlit as st

API = st.sidebar.text_input("API", "http://localhost:8000")
CONFIG = st.sidebar.selectbox("Configuration", ["full", "agentic", "threshold", "baseline"])
AS_OF = st.sidebar.date_input("Read the law as of (empty = today)", value=None)

COLORS = {
    "supported": "#1b5e20",
    "unsupported": "#b71c1c",
    "uncited": "#e65100",
    None: "#616161",            # guard disabled: reported, never verified
}

st.title("grounded-rag")
st.caption("Every claim is checked against the passage it cites before you see it.")

question = st.text_input("Câu hỏi", "Nghỉ việc phải báo trước bao nhiêu ngày?")

if st.button("Hỏi", type="primary"):
    payload = {"question": question, "config": CONFIG}
    if AS_OF:
        payload["as_of"] = AS_OF.isoformat()
    with st.spinner("retrieve → generate → verify"):
        r = httpx.post(f"{API}/chat", json=payload, timeout=120)
    if r.status_code != 200:
        st.error(f"{r.status_code}: {r.json().get('detail', r.text)}")
        st.stop()
    res = r.json()
    meta = res["meta"]

    reason = f" · {meta['abstain_reason']}" if meta.get("abstain_reason") else ""
    st.subheader(f"Status: `{res['status']}`{reason}")
    st.write(res["answer"])

    st.divider()
    st.subheader("Claim verification")
    for claim in res["claims"]:
        verdict = claim["verdict"]
        st.markdown(
            f"<div style='border-left:4px solid {COLORS.get(verdict, '#616161')};"
            f"padding-left:10px;margin-bottom:8px'>{claim['text']}<br>"
            f"<small>{verdict or 'unverified'} · entailment={claim['entailment']} · "
            f"{', '.join(claim['citations']) or 'no citation'}</small></div>",
            unsafe_allow_html=True,
        )

    with st.expander("Retrieved sources"):
        for s in res["sources"]:
            st.markdown(f"**[{s['label']}]** `{s['chunk']['ref']}` · score={s['score']}")
            st.text(s["chunk"]["text"][:600])

    with st.expander(
        f"Pipeline trace · {meta['latency_ms']} ms · {meta['llm_calls']} LLM calls · "
        f"{meta['tokens']} tokens"
    ):
        for step in meta["steps"]:
            st.markdown(f"`{step['name']}` · {step['ms']} ms · {step['detail']}")
