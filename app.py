import time, requests
import pandas as pd
import streamlit as st
import streamlit.components.v1 as components
from pyvis.network import Network

API = "https://api.semanticscholar.org/graph/v1/paper/"
NAVY, RED, BROWN, SAGE, CREAM = "#244855", "#E64833", "#874F41", "#90AEAD", "#FBE9D0"
SEED, CIT, REF, BOTH = RED, SAGE, CREAM, BROWN

def get(url, **kw):
    for i in range(5):
        r = requests.get(url, timeout=30, **kw)
        if r.status_code != 429: return r.json()
        time.sleep(2 ** i * 2)  # rate limited: wait 2, 4, 8, 16, 32s
    r.raise_for_status()

@st.cache_data(show_spinner=False)
def fetch(title):
    m = get(API + "search/match", params={"query": title, "fields": "venue"})["data"][0]
    pid, out = m["paperId"], {"venue": m.get("venue") or ""}
    for kind, key in [("citations", "citingPaper"), ("references", "citedPaper")]:
        time.sleep(1)
        data = get(f"{API}{pid}/{kind}", params={"fields": "title,venue"}).get("data") or []
        out[kind] = [(d[key]["title"].strip(), d[key].get("venue") or "") for d in data if d[key].get("title")]
    return out

@st.cache_data(show_spinner=False)
def build(titles):
    edges, kind, deg, failed, venue = [], {t: "seed" for t in titles}, {}, [], {}
    for t in titles:
        try: d = fetch(t)
        except Exception: failed.append(t); continue
        venue[t] = d["venue"]
        venue.update(d["citations"] + d["references"])
        for c, _ in d["citations"]:
            edges.append((c, t, CIT)); kind[c] = "both" if kind.get(c) == "reference" else kind.get(c, "citation")
        for r, _ in d["references"]:
            edges.append((t, r, REF)); kind[r] = "both" if kind.get(r) == "citation" else kind.get(r, "reference")
    for u, v, _ in edges:
        deg[u] = deg.get(u, 0) + 1; deg[v] = deg.get(v, 0) + 1
    return edges, kind, deg, failed, venue

st.set_page_config(layout="wide", page_title="Connected Papers But Free", page_icon="🕸️")
st.markdown("""<style>
.block-container {padding-top: 2rem;}
.chip {display:inline-block; padding:3px 12px; margin:0 6px 6px 0; border-radius:999px;
       font-size:0.85rem; color:white; font-weight:500;}
</style>""", unsafe_allow_html=True)

st.sidebar.title("🕸️ Connected Papers But Free")
up = st.sidebar.file_uploader("Titles file (.txt)", type="txt")
text = st.sidebar.text_area("Or paste titles (one per line)", up.getvalue().decode() if up else "", height=200)
min_deg = st.sidebar.slider("Min degree", 1, 10, 1)
titles = [t.strip() for t in text.splitlines() if t.strip()]
if not titles:
    st.title("Connected Papers But Free"); st.info("👈 Add titles in the sidebar."); st.stop()

with st.spinner("Fetching papers…"):
    edges, kind, deg, failed, venue = build(tuple(titles))
for t in failed:
    st.sidebar.warning(f"Failed: {t[:50]}")
if failed and st.sidebar.button("Retry failed"):
    build.clear(); st.rerun()

keep = {n for n, k in deg.items() if k >= min_deg or kind[n] == "seed"}
color = {"seed": SEED, "citation": CIT, "reference": REF, "both": BOTH}
label = {"seed": "Yours", "citation": "Cites yours", "reference": "Cited by yours", "both": "Both"}
rev = {v: k for k, v in label.items()}

st.title("Connected Papers But Free")
st.markdown("".join(f"<span class='chip' style='background:{color[k]};color:{NAVY if k in ('citation', 'reference') else CREAM}'>{label[k]}</span>" for k in color), unsafe_allow_html=True)
left, right = st.columns([3, 2], gap="large")

with right:
    st.subheader("Papers by degree")
    df = pd.DataFrame([(n, kind[n], deg[n]) for n in keep], columns=["Title", "Type", "Degree"])
    t = st.radio("Show", ["all", "seed", "citation", "reference", "both"], horizontal=True, label_visibility="collapsed",
                 format_func=lambda x: "All" if x == "all" else label[x])
    if t != "all": df = df[df.Type == t]
    q = st.text_input("Search", placeholder="🔍 Search titles…", label_visibility="collapsed").lower().split()
    df = df[df.Title.str.lower().apply(lambda x: all(w in x for w in q))]
    df = df.sort_values("Degree", ascending=False).reset_index(drop=True)
    df["Type"] = df.Type.map(label)
    ev = st.dataframe(df.style.map(lambda x: f"color:{color[rev[x]]};font-weight:600", subset=["Type"]), height=400, hide_index=True, use_container_width=True, on_select="rerun", selection_mode="single-row",
                      column_config={"Degree": st.column_config.ProgressColumn(format="%d", min_value=0, max_value=int(df.Degree.max() or 1))})
    sel = df.Title[ev.selection.rows[0]] if ev.selection.rows else None

    st.subheader("Top venues")
    v = pd.Series([venue.get(n) for n in keep]).replace("", None).dropna().value_counts().head(10)
    st.dataframe(v.rename_axis("Venue").reset_index(name="Papers"), hide_index=True, use_container_width=True,
                 column_config={"Papers": st.column_config.ProgressColumn(format="%d", min_value=0, max_value=int(v.max() if len(v) else 1))})

with left:
    net = Network(height="760px", width="100%", directed=True, cdn_resources="in_line", bgcolor=NAVY, font_color=CREAM)
    net.set_options("""{"layout": {"randomSeed": 1},
      "physics": {"solver": "forceAtlas2Based"},
      "nodes": {"shape": "dot", "font": {"size": 14, "face": "sans-serif", "color": "#FBE9D0"}, "borderWidth": 0},
      "edges": {"smooth": {"type": "continuous"}, "arrows": {"to": {"scaleFactor": 0.4}}},
      "interaction": {"hover": true, "tooltipDelay": 100}}""")  # same layout every time
    for n in sorted(keep):
        hi = n == sel
        net.add_node(n, label=n[:60] if kind[n] == "seed" or hi else " ", title=f"{n}\n{venue.get(n) or ''}".replace("<", "").replace(">", ""),  # no HTML in tooltips
                     color={"background": NAVY, "border": RED} if hi else color[kind[n]], borderWidth=6 if hi else 0,
                     size=(25 if hi else 8) + 4 * deg[n] ** 0.5)
    for u, v_, c in edges:
        if u in keep and v_ in keep:
            on = sel in (u, v_)
            net.add_edge(u, v_, color={"color": c, "opacity": 1 if on else 0.45}, width=3 if on else 0.8)
    with st.container(border=True):
        components.html(net.generate_html(), height=775)