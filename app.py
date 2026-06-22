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
st.set_page_config(page_title="GDP System", layout="wide")

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
    forecast_label: str,
    forecast_overrides: dict | None = None,
) -> pd.DataFrame:
    rows: list[dict] = []
    last_period = periods[-1]
    overrides = forecast_overrides or {}

    def _walk(node: NIPANode, depth: int, parent_sign: float):
        code = node.series.code
        indent = " " * (4 * depth)
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
            "_clicked_col": "",
            "Component": indent + prefix + node.series.name,
        }
        for p in periods:
            val = data.loc[p, code] if code in data.columns else None
            row[_qlabel(p)] = round(float(val), 1) if val is not None else None
        # Forecast: use user override if present, else last actual value
        last_val = data.loc[last_period, code] if code in data.columns else None
        fcst_val = overrides.get(code, last_val)
        row[forecast_label] = round(float(fcst_val), 1) if fcst_val is not None else None
        rows.append(row)
        for child, child_sign in node.children:
            _walk(child, depth + 1, child_sign)

    _walk(root, 0, 1.0)
    return pd.DataFrame(rows)


def _add_period_highlight(fig: go.Figure, period: str | None) -> None:
    if period:
        fig.add_vline(x=period, line_width=2, line_color="orange",
                      line_dash="dash", annotation_text=period,
                      annotation_position="top right")


def build_level_chart(
    code: str, name: str, data: pd.DataFrame, units_label: str,
    selected_period: pd.Timestamp, forecast_label: str,
    forecast_value: float | None = None,
    highlight_period: str | None = None,
) -> go.Figure:
    if code not in data.columns:
        return go.Figure()
    series = data[code].dropna().sort_index()
    series = series[series.index <= selected_period]
    labels = [_qlabel(ts) for ts in series.index]
    last_val = float(series.iloc[-1])
    fcst_val = forecast_value if forecast_value is not None else last_val

    fig = go.Figure()
    fig.add_trace(go.Scatter(
        x=labels, y=series.values,
        mode="lines+markers", name="Actual",
        line=dict(color="#1f77b4", width=2), marker=dict(size=4),
        hovertemplate="%{x}: $%{y:,.1f}B<extra></extra>",
    ))
    fig.add_trace(go.Scatter(
        x=[labels[-1], forecast_label], y=[last_val, fcst_val],
        mode="lines+markers", name="Forecast",
        line=dict(color="#ff7f0e", width=2, dash="dash"),
        marker=dict(size=8, symbol="diamond"),
        hovertemplate="%{x}: $%{y:,.1f}B<extra></extra>",
    ))
    fig.update_layout(
        title=dict(text=name, font_size=13),
        xaxis=dict(tickangle=-45, nticks=12),
        yaxis=dict(title=units_label),
        legend=dict(orientation="h", y=1.08, x=0),
        margin=dict(t=50, l=60, r=20, b=80),
        height=560,
    )
    _add_period_highlight(fig, highlight_period)
    return fig


def build_growth_chart(
    code: str, name: str, data: pd.DataFrame,
    selected_period: pd.Timestamp, forecast_label: str,
    forecast_value: float | None = None,
    highlight_period: str | None = None,
) -> go.Figure:
    if code not in data.columns:
        return go.Figure()
    series = data[code].dropna().sort_index()
    series = series[series.index <= selected_period]
    growth = (series.pct_change() * 4 * 100).dropna()
    labels = [_qlabel(ts) for ts in growth.index]
    bar_colors = ["#d62728" if v < 0 else "#1f77b4" for v in growth.values]
    last_val = float(series.iloc[-1])
    if forecast_value is not None and last_val != 0:
        fcst_growth = ((forecast_value / last_val) - 1) * 4 * 100
    else:
        fcst_growth = 0.0

    fig = go.Figure()
    fig.add_trace(go.Bar(
        x=labels, y=growth.values,
        marker_color=bar_colors, name="Actual",
        hovertemplate="%{x}: %{y:+.2f}%<extra></extra>",
    ))
    fig.add_trace(go.Bar(
        x=[forecast_label], y=[fcst_growth],
        marker_color="#ff7f0e", name="Forecast",
        hovertemplate="%{x}: %{y:+.2f}% (F)<extra></extra>",
    ))
    fig.add_hline(y=0, line_width=1, line_color="black")
    fig.update_layout(
        title=dict(text=f"{name} — QoQ growth (ann. %)", font_size=13),
        xaxis=dict(tickangle=-45, nticks=12),
        yaxis=dict(title="% ann."),
        legend=dict(orientation="h", y=1.08, x=0),
        margin=dict(t=50, l=60, r=20, b=80),
        height=560,
        barmode="overlay",
    )
    _add_period_highlight(fig, highlight_period)
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
            f"<b>{node.series.name}</b><br>Code: {code}<br>Level: ${val_raw:,.1f}B SAAR"
            + ("<br>(subtracted from GDP)" if sign < 0 else "")
        )
        for child, child_sign in node.children:
            _walk(child, code, child_sign)

    _walk(root, "", 1.0)
    fig = go.Figure(go.Treemap(
        ids=ids, labels=labels, parents=parents, values=values,
        marker=dict(colors=[c if c else "#1f77b4" for c in colors], line=dict(width=1.5, color="white")),
        hovertemplate="%{customdata}<extra></extra>", customdata=hover,
        textinfo="label+percent parent", maxdepth=3,
    ))
    fig.update_layout(margin=dict(t=10, l=0, r=0, b=0), height=460)
    return fig


def build_identity_table(root: NIPANode) -> pd.DataFrame:
    rows = []
    for node in root.all_nodes():
        if not node.is_leaf:
            rows.append({"Parent": node.series.code, "Name": node.series.name, "Identity": node.identity_str()})
    return pd.DataFrame(rows)


# ── Session state defaults ───────────────────────────────────────────────── #
if "chart_code" not in st.session_state:
    st.session_state["chart_code"] = None
    st.session_state["chart_name"] = None
    st.session_state["highlight_period"] = None
if "forecast_overrides" not in st.session_state:
    st.session_state["forecast_overrides"] = {}
    st.session_state["_last_forecast_label"] = None

# ── Controls (compact top bar) ───────────────────────────────────────────── #
c1, c2, c3, _ = st.columns([2, 1, 1, 3])
with c1:
    table_choice = st.radio("Table", ["Nominal GDP", "Real GDP (2017 $)"],
                            horizontal=True, label_visibility="collapsed")
table_id = "T10105" if "Nominal" in table_choice else "T10106"
units_label = "Nominal $B SAAR" if table_id == "T10105" else "Real $B SAAR (2017)"

data = load_data(table_id)
root = get_table(table_id)
quarters = data.index.sort_values()
quarter_labels = [_qlabel(q) for q in quarters]

with c2:
    n_periods = st.selectbox("Qtrs", list(range(2, 13)), index=4, label_visibility="visible")
with c3:
    selected_label = st.selectbox("As of", quarter_labels[::-1], index=0, label_visibility="visible")

selected_period = quarters[quarter_labels.index(selected_label)]
sel_idx = quarters.get_loc(selected_period)
hist_periods = list(quarters[max(0, sel_idx - n_periods + 1): sel_idx + 1])
period_cols = [_qlabel(p) for p in hist_periods]
forecast_period = selected_period + pd.DateOffset(months=3)
forecast_label = _qlabel(forecast_period) + " (F)"

# Clear edits when the forecast period changes
if st.session_state["_last_forecast_label"] != forecast_label:
    st.session_state["forecast_overrides"] = {}
    st.session_state["_last_forecast_label"] = forecast_label

# Default chart code once data is loaded
if st.session_state["chart_code"] is None:
    st.session_state["chart_code"] = root.series.code
    st.session_state["chart_name"] = root.series.name

# ── Build tree df ────────────────────────────────────────────────────────── #
tree_df = build_tree_table(root, data, hist_periods, forecast_label,
                            st.session_state["forecast_overrides"])

# ── AgGrid config ────────────────────────────────────────────────────────── #
row_style = JsCode("""
function(params) {
    if (params.data._is_id)      return { fontWeight: 'bold', background: '#f5f5f5' };
    if (params.data._subtracted) return { color: '#c0392b' };
    return {};
}
""")

num_fmt = JsCode("""
function(p) {
    return p.value != null
        ? p.value.toLocaleString('en-US', {minimumFractionDigits:1, maximumFractionDigits:1})
        : '—';
}
""")


scroll_to_last = JsCode(f"""
function(params) {{ params.api.ensureColumnVisible('{forecast_label}'); }}
""")

gb = GridOptionsBuilder.from_dataframe(tree_df[["Component"] + period_cols])
gb.configure_default_column(resizable=True, sortable=False, filter=False, suppressSizeToFit=True)
gb.configure_column("Component", pinned="left", width=260)
for col in period_cols:
    gb.configure_column(col, type=["numericColumn"], valueFormatter=num_fmt, width=110)
forecast_style = JsCode("function(p){ return { background: '#fff8e1', fontStyle: 'italic' }; }")
gb.configure_column(forecast_label, type=["numericColumn"], valueFormatter=num_fmt,
                    width=120, cellStyle=forecast_style, editable=True)
gb.configure_selection("single", use_checkbox=False, suppressRowDeselection=False)
cell_clicked_js = JsCode("""
function(params) {
    var field = params.colDef ? params.colDef.field : '';
    if (!field.startsWith('_')) {
        params.node.setDataValue('_clicked_col', field);
    }
}
""")

gb.configure_grid_options(
    getRowStyle=row_style,
    onCellClicked=cell_clicked_js,
    suppressRowClickSelection=False,
    suppressHorizontalScroll=False,
    alwaysShowHorizontalScroll=True,
    rowHeight=24,
    headerHeight=32,
    onGridReady=scroll_to_last,
)
grid_opts = gb.build()

custom_css = {
    ".ag-cell": {"font-size": "12px !important", "line-height": "24px !important"},
    ".ag-header-cell-text": {"font-size": "12px !important"},
    ".ag-root-wrapper": {"border": "none"},
}

# ── Layout: hierarchy (left) + chart (right) ─────────────────────────────── #
col_table, col_chart = st.columns([1, 1])

with col_table:
    st.caption("= identity  ·  - subtracted  ·  click a row to chart it")
    resp = AgGrid(
        tree_df,
        gridOptions=grid_opts,
        update_mode=GridUpdateMode.VALUE_CHANGED,
        allow_unsafe_jscode=True,
        height=600,
        theme="alpine",
        custom_css=custom_css,
    )

# Pick up selection and clicked column from returned data
selected = resp.selected_rows
if selected is not None and len(selected) > 0:
    sel_row = selected[0] if isinstance(selected, list) else selected.iloc[0]
    st.session_state["chart_code"] = sel_row["_code"]
    st.session_state["chart_name"] = str(sel_row["Component"]).lstrip().lstrip("=- ").strip()

try:
    ret_df = resp.data if isinstance(resp.data, pd.DataFrame) else pd.DataFrame(resp.data)
    # Capture any edited forecast values and persist them
    if forecast_label in ret_df.columns and "_code" in ret_df.columns:
        for _, row in ret_df.iterrows():
            code_key = row.get("_code")
            fcst_val = row.get(forecast_label)
            if code_key and fcst_val is not None and not pd.isna(fcst_val):
                st.session_state["forecast_overrides"][code_key] = float(fcst_val)
    # Detect clicked column for period highlight
    clicked = ret_df[ret_df["_clicked_col"].astype(str) != ""]
    if not clicked.empty:
        col_clicked = str(clicked.iloc[0]["_clicked_col"])
        st.session_state["highlight_period"] = col_clicked if col_clicked in period_cols else None
except Exception:
    pass

with col_chart:
    code = st.session_state["chart_code"]
    name = st.session_state["chart_name"]
    hp   = st.session_state["highlight_period"]
    default_fcst = float(data.loc[selected_period, code]) if code in data.columns else None
    fcst_val = st.session_state["forecast_overrides"].get(code, default_fcst)
    view = st.segmented_control("View", ["Level ($B)", "QoQ Growth (%)"], default="Level ($B)", label_visibility="collapsed")
    if view == "QoQ Growth (%)":
        fig = build_growth_chart(code, name, data, selected_period, forecast_label,
                                 forecast_value=fcst_val, highlight_period=hp)
    else:
        fig = build_level_chart(code, name, data, units_label, selected_period, forecast_label,
                                forecast_value=fcst_val, highlight_period=hp)
    st.plotly_chart(fig, width="stretch")

st.markdown("---")

# ── Composition treemap ──────────────────────────────────────────────────── #
st.subheader("Composition")
st.caption(f"Box size = share of GDP  ·  red = subtracted  ·  {selected_label}")
st.plotly_chart(build_treemap(root, data, selected_period), width="stretch")

st.markdown("---")

# ── Accounting identities ────────────────────────────────────────────────── #
with st.expander("Accounting Identities", expanded=False):
    st.dataframe(build_identity_table(root), width="stretch", hide_index=True)
