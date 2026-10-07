import time, requests
import pandas as pd
import streamlit as st
import streamlit.components.v1 as components
from pyvis.network import Network

API = "https://api.semanticscholar.org/graph/v1/paper/"
SEED, CIT, REF, BOTH = "#d55e00", "#009e73", "#0072b2", "#cc79a7"

def get(url, **kw):
    for i in range(5):
        r = requests.get(url, **kw)
        if r.status_code != 429: return r.json()
        time.sleep(2 ** i * 2)  # rate limited: wait 2, 4, 8, 16, 32s
    r.raise_for_status()

@st.cache_data(show_spinner=False)
def fetch(title):
    pid = get(API + "search/match", params={"query": title})["data"][0]["paperId"]
    out = {}
    for kind, key in [("citations", "citingPaper"), ("references", "citedPaper")]:
        time.sleep(1)
        data = get(f"{API}{pid}/{kind}").get("data") or []
        out[kind] = [d[key]["title"].strip() for d in data if d[key].get("title")]
    return out

@st.cache_data(show_spinner=False)
def build(titles):
    edges, kind, deg, failed = [], {t: "seed" for t in titles}, {}, []
    for t in titles:
        try: d = fetch(t)
        except Exception: failed.append(t); continue
        for c in d["citations"]:
            edges.append((c, t, CIT)); kind[c] = "both" if kind.get(c) == "reference" else kind.get(c, "citation")
        for r in d["references"]:
            edges.append((t, r, REF)); kind[r] = "both" if kind.get(r) == "citation" else kind.get(r, "reference")
    for u, v, _ in edges:
        deg[u] = deg.get(u, 0) + 1; deg[v] = deg.get(v, 0) + 1
    return edges, kind, deg, failed

st.set_page_config(layout="wide", page_title="Paper graph")
st.sidebar.title("Papers")
up = st.sidebar.file_uploader("Titles file (.txt)", type="txt")
text = st.sidebar.text_area("Or paste titles (one per line)", up.getvalue().decode() if up else "", height=200)
min_deg = st.sidebar.slider("Min degree", 1, 10, 1)
titles = [t.strip() for t in text.splitlines() if t.strip()]
if not titles:
    st.info("Add titles in the sidebar."); st.stop()

with st.spinner("Fetching papers…"):
    edges, kind, deg, failed = build(tuple(titles))
for t in failed:
    st.sidebar.warning(f"Failed: {t[:50]}")
if failed and st.sidebar.button("Retry failed"):
    build.clear(); st.rerun()

keep = {n for n, k in deg.items() if k >= min_deg or kind[n] == "seed"}
color = {"seed": SEED, "citation": CIT, "reference": REF, "both": BOTH}

st.markdown(f"<span style='color:{SEED}'>● Your papers</span> &nbsp; <span style='color:{CIT}'>● Cites your papers</span> &nbsp; "
            f"<span style='color:{REF}'>● Cited by your papers</span> &nbsp; <span style='color:{BOTH}'>● Both</span>", unsafe_allow_html=True)
left, right = st.columns([3, 2])

with left:
    net = Network(height="750px", width="100%", directed=True, cdn_resources="in_line")
    net.force_atlas_2based()
    for n in keep:
        net.add_node(n, label=n if kind[n] == "seed" else " ", title=n, color=color[kind[n]], size=10 + 4 * deg[n] ** 0.5)
    for u, v, c in edges:
        if u in keep and v in keep:
            net.add_edge(u, v, color=c)
    components.html(net.generate_html(), height=770)

with right:
    df = pd.DataFrame([(n, kind[n], deg[n]) for n in keep], columns=["Title", "Type", "Degree"])
    t = st.radio("Show", ["all", "seed", "citation", "reference", "both"], horizontal=True)
    if t != "all": df = df[df.Type == t]
    st.dataframe(df.sort_values("Degree", ascending=False), height=700, hide_index=True, use_container_width=True)