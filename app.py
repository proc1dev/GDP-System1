"""
GDP System — Streamlit application.

Run with:  streamlit run app.py
"""
import sys
import os

sys.path.insert(0, os.path.dirname(__file__))

import streamlit as st
import plotly.graph_objects as go
import pandas as pd
from st_aggrid import AgGrid, GridOptionsBuilder, GridUpdateMode, JsCode

from nipa import get_table, NIPANode
from data import MockProvider

# ── Page config ─────────────────────────────────────────────────────────── #
st.set_page_config(
    page_title="GDP System",
    page_icon=None,
    layout="wide",
)

# ── Helpers ──────────────────────────────────────────────────────────────── #

@st.cache_data(ttl=3600)
def load_data(table_id: str, n_quarters: int = 40) -> pd.DataFrame:
    provider = MockProvider(n_quarters=n_quarters, seed=42)
    root = get_table(table_id)
    codes = [n.series.code for n in root.all_nodes()]
    return provider.fetch(codes)


def _qlabel(ts: pd.Timestamp) -> str:
    return f"{ts.year} Q{(ts.month - 1) // 3 + 1}"


def build_tree_table(
    root: NIPANode,
    data: pd.DataFrame,
    periods: list[pd.Timestamp],
) -> pd.DataFrame:
    """
    Flatten the NIPANode tree into a display DataFrame.
    _code, _is_id, _subtracted are used by AgGrid for styling/lookup.
    """
    rows: list[dict] = []

    def _walk(node: NIPANode, depth: int, parent_sign: float):
        code = node.series.code
        indent = " " * (4 * depth)
        if depth == 0:
            prefix = ""
        elif not node.is_leaf:
            prefix = "= "
        elif parent_sign < 0:
            prefix = "- "
        else:
            prefix = "  "
        row: dict = {
            "_code": code,
            "_is_id": not node.is_leaf,
            "_subtracted": parent_sign < 0,
            "Component": indent + prefix + node.series.name,
        }
        for p in periods:
            val = data.loc[p, code] if code in data.columns else None
            row[_qlabel(p)] = round(float(val), 1) if val is not None else None
        rows.append(row)
        for child, child_sign in node.children:
            _walk(child, depth + 1, child_sign)

    _walk(root, 0, 1.0)
    return pd.DataFrame(rows)


def build_series_chart(
    code: str,
    name: str,
    data: pd.DataFrame,
    units_label: str,
) -> go.Figure:
    if code not in data.columns:
        return go.Figure()
    series = data[code].dropna().sort_index()
    labels = [_qlabel(ts) for ts in series.index]
    fig = go.Figure(go.Scatter(
        x=labels,
        y=series.values,
        mode="lines+markers",
        line=dict(color="#1f77b4", width=2),
        marker=dict(size=4),
        hovertemplate="%{x}: $%{y:,.1f}B<extra></extra>",
    ))
    fig.update_layout(
        title=dict(text=name, font_size=13),
        xaxis=dict(tickangle=-45, nticks=12),
        yaxis=dict(title=units_label),
        margin=dict(t=40, l=60, r=20, b=80),
        height=560,
    )
    return fig


def build_treemap(root: NIPANode, data: pd.DataFrame, period: pd.Timestamp) -> go.Figure:
    ids, labels, parents, values, colors, hover = [], [], [], [], [], []

    def _walk(node: NIPANode, parent_code: str, sign: float):
        code = node.series.code
        val_raw = float(data.loc[period, code]) if code in data.columns else 0.0
        val = abs(val_raw)
        ids.append(code)
        labels.append(node.series.name)
        parents.append(parent_code)
        values.append(val)
        colors.append("#d62728" if sign < 0 else None)
        hover.append(
            f"<b>{node.series.name}</b><br>"
            f"Code: {code}<br>"
            f"Level: ${val_raw:,.1f}B SAAR"
            + ("<br>(subtracted from GDP)" if sign < 0 else "")
        )
        for child, child_sign in node.children:
            _walk(child, code, child_sign)

    _walk(root, "", 1.0)

    fig = go.Figure(go.Treemap(
        ids=ids,
        labels=labels,
        parents=parents,
        values=values,
        marker=dict(
            colors=[c if c else "#1f77b4" for c in colors],
            line=dict(width=1.5, color="white"),
        ),
        hovertemplate="%{customdata}<extra></extra>",
        customdata=hover,
        textinfo="label+percent parent",
        maxdepth=3,
    ))
    fig.update_layout(margin=dict(t=10, l=0, r=0, b=0), height=460)
    return fig


def build_identity_table(root: NIPANode) -> pd.DataFrame:
    rows = []
    for node in root.all_nodes():
        if not node.is_leaf:
            rows.append({
                "Parent": node.series.code,
                "Name": node.series.name,
                "Identity": node.identity_str(),
            })
    return pd.DataFrame(rows)


# ── Controls (top bar, no sidebar) ──────────────────────────────────────── #
c1, c2, c3, c4 = st.columns([2, 1, 1, 3])

with c1:
    table_choice = st.radio(
        "Table",
        options=["Nominal GDP", "Real GDP (2017 $)"],
        index=0,
        horizontal=True,
        label_visibility="collapsed",
    )
table_id = "T10105" if "Nominal" in table_choice else "T10106"
units_label = "Nominal $B SAAR" if table_id == "T10105" else "Real $B SAAR (2017)"

# ── Load data ────────────────────────────────────────────────────────────── #
data = load_data(table_id)
root = get_table(table_id)

quarters = data.index.sort_values()
quarter_labels = [_qlabel(q) for q in quarters]

with c2:
    n_periods = st.selectbox("Qtrs", options=list(range(2, 13)), index=4, label_visibility="visible")

with c3:
    selected_label = st.selectbox("As of", options=quarter_labels[::-1], index=0, label_visibility="visible")

selected_period = quarters[quarter_labels.index(selected_label)]
sel_idx = quarters.get_loc(selected_period)
hist_periods = list(quarters[max(0, sel_idx - n_periods + 1): sel_idx + 1])
period_cols = [_qlabel(p) for p in hist_periods]

# ── Build tree df once ───────────────────────────────────────────────────── #
tree_df = build_tree_table(root, data, hist_periods)

# ── Component Hierarchy (left) + Series Chart (right) ───────────────────── #
col_table, col_chart = st.columns([1, 1])

row_style = JsCode("""
function(params) {
    if (params.data._is_id)        return { fontWeight: 'bold', background: '#f5f5f5' };
    if (params.data._subtracted)   return { color: '#c0392b' };
    return {};
}
""")

num_fmt = JsCode("function(p){ return p.value != null ? p.value.toLocaleString('en-US',{minimumFractionDigits:1,maximumFractionDigits:1}) : '—'; }")

gb = GridOptionsBuilder.from_dataframe(tree_df[["Component"] + period_cols])
gb.configure_default_column(resizable=True, sortable=False, filter=False, suppressSizeToFit=True)
gb.configure_column("Component", pinned="left", width=260, suppressSizeToFit=True)
for col in period_cols:
    gb.configure_column(col, type=["numericColumn"], valueFormatter=num_fmt, width=110)
gb.configure_selection("single", use_checkbox=False, suppressRowDeselection=False)
gb.configure_grid_options(
    getRowStyle=row_style,
    suppressRowClickSelection=False,
    suppressHorizontalScroll=False,
    alwaysShowHorizontalScroll=True,
    rowHeight=24,
    headerHeight=32,
)
grid_opts = gb.build()

custom_css = {
    ".ag-cell": {"font-size": "12px !important", "line-height": "24px !important"},
    ".ag-header-cell-text": {"font-size": "12px !important"},
    ".ag-root-wrapper": {"border": "none"},
}

with col_table:
    st.subheader("Component Hierarchy")
    st.caption("= identity row  ·  - subtracted (imports)  ·  click a row to chart it")
    resp = AgGrid(
        tree_df,
        gridOptions=grid_opts,
        update_mode=GridUpdateMode.SELECTION_CHANGED,
        allow_unsafe_jscode=True,
        height=580,
        theme="alpine",
        custom_css=custom_css,
    )

with col_chart:
    st.subheader("Series History")
    selected = resp.selected_rows
    if selected is not None and len(selected) > 0:
        row = selected[0] if isinstance(selected, list) else selected.iloc[0]
        chart_code = row["_code"]
        chart_name = str(row["Component"]).lstrip().lstrip("=- ").strip()
    else:
        chart_code = root.series.code
        chart_name = root.series.name
    st.plotly_chart(
        build_series_chart(chart_code, chart_name, data, units_label),
        width="stretch",
    )

st.markdown("---")

# ── Composition treemap ──────────────────────────────────────────────────── #
st.subheader("Composition")
st.caption(f"Box size = share of GDP  ·  red = subtracted  ·  {selected_label}")
st.plotly_chart(build_treemap(root, data, selected_period), width="stretch")

st.markdown("---")

# ── Accounting identities ────────────────────────────────────────────────── #
with st.expander("Accounting Identities", expanded=False):
    st.dataframe(build_identity_table(root), width="stretch", hide_index=True)
