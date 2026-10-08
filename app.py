import re, time, unicodedata, requests, bibtexparser
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

# ---------- reference checker ----------
REQUIRED = {"article": ["author", "title", "journal", "year"], "inproceedings": ["author", "title", "booktitle", "year"],
            "incollection": ["author", "title", "booktitle", "publisher", "year"], "book": ["title", "publisher", "year"],
            "phdthesis": ["author", "title", "school", "year"], "mastersthesis": ["author", "title", "school", "year"],
            "techreport": ["author", "title", "institution", "year"], "misc": ["title"]}

def norm(s):  # ö -> o, drop case, spaces, punctuation
    return re.sub(r"[^a-z0-9]", "", unicodedata.normalize("NFKD", s).encode("ascii", "ignore").decode().lower())

def last_names(authors):
    names = [n.strip() for n in re.sub(r"[{}]", "", authors).split(" and ")]
    return [n.split(",")[0] if "," in n else n.split()[-1] for n in names if n and n.lower() != "others"]

def style_issues(e):
    t, title = e["ENTRYTYPE"].lower(), e.get("title", "")
    out = [f"missing {k}" for k in REQUIRED.get(t, ["title", "year"]) if not e.get(k, "").strip()]
    if t == "book" and not (e.get("author") or e.get("editor")): out.append("missing author/editor")
    if e.get("year") and not re.fullmatch(r"\d{4}", e["year"].strip()): out.append(f"bad year '{e['year']}'")
    if re.search(r"\d\s*[-–—]\s*\d", e.get("pages", "")) and "--" not in e["pages"]: out.append("pages should use '--'")
    if "et al" in e.get("author", "").lower(): out.append("use 'and others', not 'et al'")
    if title.count("{") != title.count("}"): out.append("unbalanced braces in title")
    if e.get("doi", "").startswith("http"): out.append("doi should not be a URL")
    return out

@st.cache_data(show_spinner=False)
def lookup(title):
    time.sleep(1)
    r = get(API + "search/match", params={"query": title, "fields": "title,year,authors,publicationTypes"})
    return (r.get("data") or [None])[0]

def refs_page():
    st.title("Reference checker")
    up = st.file_uploader("Upload .bib file", type="bib")
    if not up: st.info("Upload a .bib file to check it."); return
    entries = bibtexparser.loads(up.getvalue().decode()).entries
    rows, seen, bar = [], {}, st.progress(0.0)
    for i, e in enumerate(entries):
        bar.progress((i + 1) / len(entries), f"Checking {i + 1}/{len(entries)}")
        title, issues, found, status = re.sub(r"[{}\\]", "", e.get("title", "")).strip(), style_issues(e), "", ""
        if norm(title) in seen: issues.append(f"duplicate of {seen[norm(title)]}")
        seen.setdefault(norm(title), e["ID"])
        if not title: status = "❌ No title"
        else:
            try: m = lookup(title)
            except Exception: m, status = None, "⚠️ Lookup failed"
            if not m: status = status or "❌ Not found"
            else:
                found, a, b = m["title"], norm(title), norm(m["title"])
                if a != b and a not in b and b not in a: status = "❌ Title mismatch"
                ss = norm(" ".join(x["name"] for x in m.get("authors") or []))
                miss = [l for l in last_names(e.get("author", "")) if norm(l) not in ss]
                if miss: issues.append("authors not found: " + ", ".join(miss))
                if m.get("year") and e.get("year") and e["year"].strip() != str(m["year"]): issues.append(f"year {e.get('year')} vs {m['year']}")
                types, t = m.get("publicationTypes") or [], e["ENTRYTYPE"].lower()
                if "Conference" in types and t != "inproceedings": issues.append("looks like @inproceedings")
                elif "JournalArticle" in types and t not in ("article", "misc"): issues.append("looks like @article")
        rows.append({"Status": status or ("⚠️ Issues" if issues else "✅ OK"), "Key": e["ID"], "Type": e["ENTRYTYPE"],
                     "Your title": title, "Found title": found, "Issues": "; ".join(issues)})
    bar.empty()
    df = pd.DataFrame(rows)
    st.caption(" · ".join(f"{k}: {v}" for k, v in df.Status.value_counts().items()))
    if st.toggle("Only problems", True): df = df[df.Status != "✅ OK"]
    st.dataframe(df, hide_index=True, use_container_width=True, height=600)
    safe = df.replace(r"^([=+\-@])", r"'\1", regex=True)  # stop Excel running text as formulas
    st.download_button("Download CSV", safe.to_csv(index=False), "ref_check.csv")

st.set_page_config(layout="wide", page_title="Connected Papers But Free", page_icon="🕸️")
st.markdown("""<style>
.block-container {padding-top: 2rem;}
html, body, h1, h2, h3, p, label, li, input, textarea, button, .chip {font-family: Calibri, sans-serif !important;}
.chip {display:inline-block; padding:3px 12px; margin:0 6px 6px 0; border-radius:999px;
       font-size:0.85rem; color:white; font-weight:500;}
</style>""", unsafe_allow_html=True)

if "refs" not in st.session_state: st.session_state.refs = False
def flip(): st.session_state.refs = not st.session_state.refs
st.button("🕸️ Back to main panel" if st.session_state.refs else "📚 Check references", on_click=flip)
if st.session_state.refs: refs_page(); st.stop()

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
      "nodes": {"shape": "dot", "font": {"size": 14, "face": "Calibri, sans-serif", "color": "#FBE9D0"}, "borderWidth": 0},
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