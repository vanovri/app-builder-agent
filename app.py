import json

import streamlit as st

from builder.llm import make_llm
from builder.orchestrator import AppBuilder

st.set_page_config(page_title="App Builder Agent", layout="wide")
st.title("AI Agent for App Development")
provider = st.sidebar.selectbox("LLM provider", ["grok-cli", "openai"])
max_debug = st.sidebar.slider("Max debugger rounds", 0, 5, 3)
prompt = st.text_input("Describe the app", "a todo app with tags")
ICONS = {"planner": "🧭", "backend": "🛠️", "frontend": "🎨", "tester": "🧪", "verify": "✔️", "debugger": "🐞", "orchestrator": "📦"}
if st.button("Build") and prompt:
    log = st.container()
    with st.spinner("Agents working (Grok CLI ~1 min per agent call)..."):
        b = AppBuilder(make_llm(provider), max_debug=max_debug,
                       on_event=lambda ev: log.write(f"{ICONS.get(ev['agent'], '')} **{ev['agent']}** "
                                                     f"{ev.get('output') or ev.get('pytest_summary') or ev.get('files') or ''}")).build(prompt)
    (st.success if b.passed else st.error)(f"{'PASS' if b.passed else 'FAIL'} — workspace: {b.workspace}")
    st.code(f"cd {b.workspace} && ~/projects/app-builder-agent/.venv/bin/uvicorn app.main:app --port 8000", language="bash")
    st.subheader("Orchestration trace")
    for ev in b.trace:
        with st.expander(f"{ICONS.get(ev['agent'], '')} {ev['agent']}" + (f" round {ev['round']}" if "round" in ev else "")
                         + (f" — {'PASS' if ev['passed'] else 'FAIL'}" if "passed" in ev else "")):
            if ev["agent"] == "planner":
                st.json(ev["spec"])
            elif ev["agent"] == "verify":
                st.write("pytest:", ev["pytest_summary"], "| sandbox:", ev["sandbox"])
                st.code(ev["pytest_output"][-3000:], language="text")
                st.json(ev["smoke"]["checks"])
            else:
                st.json({k: v for k, v in ev.items() if k != "t"})
    st.subheader("Generated files")
    for k, v in b.files.items():
        with st.expander(k):
            st.code(v, language="python" if k.endswith(".py") else "html" if k.endswith(".html") else "text")
