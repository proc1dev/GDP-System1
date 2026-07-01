"""
GDP System — Streamlit application.

Run with:  python -m streamlit run app.py
"""
import sys
import os

sys.path.insert(0, os.path.dirname(__file__))

import streamlit as st
import plotly.graph_objects as go
import pandas as pd
from st_aggrid import AgGrid, GridOptionsBuilder, GridUpdateMode, JsCode

from db import load_table, list_tables

# ── Page config ─────────────────────────────────────────────────────────── #
st.set_page_config(page_title="GDP System", layout="wide")

# ── Helpers ──────────────────────────────────────────────────────────────── #

def _qlabel(ts: pd.Timestamp) -> str:
    return f"{ts.year} Q{(ts.month - 1) // 3 + 1}"


@st.cache_data(ttl=3600)
def get_all_tables() -> list[str]:
    return list_tables()


@st.cache_data(ttl=300, show_spinner="Checking Bloomberg data...")
def fetch_table(table_name: str) -> tuple[list[dict], pd.DataFrame]:
    """Thin cache wrapper around load_table (lazy-loads from Bloomberg if stale)."""
    return load_table(table_name)


def _units_label(table_name: str) -> str:
    """Heuristic units label from table name."""
    suffixes = table_name.split(".")
    last = suffixes[-1] if suffixes else ""
    if last in ("5", "1"):
        return "Nominal $B SAAR"
    if last == "6":
        return "Real $B SAAR (Chained 2017)"
    if last in ("2", "8", "9", "10", "11"):
        return "% Change"
    if last in ("3", "4"):
        return "Index / Price"
    return "Value"


def build_tree_table(
    series: list[dict],
    data: pd.DataFrame,
    periods: list[pd.Timestamp],
    forecast_label: str,
    forecast_overrides: dict | None = None,
) -> pd.DataFrame:
    rows: list[dict] = []
    last_period = periods[-1]
    overrides = forecast_overrides or {}

    for s in series:
        ticker = s["ticker"]
        indent = " " * (4 * s["indent_level"])
        prefix = "= " if s["is_aggregate"] else "  "
        row: dict = {
            "_ticker": ticker,
            "_is_id": s["is_aggregate"],
            "_clicked_col": "",
            "Component": indent + prefix + s["series_name"],
        }
        for p in periods:
            val = data.loc[p, ticker] if ticker in data.columns and p in data.index else None
            row[_qlabel(p)] = round(float(val), 1) if val is not None and not pd.isna(val) else None
        last_val = data.loc[last_period, ticker] if ticker in data.columns and last_period in data.index else None
        fcst_val = overrides.get(ticker, last_val)
        row[forecast_label] = round(float(fcst_val), 1) if fcst_val is not None and not pd.isna(fcst_val) else None
        rows.append(row)

    return pd.DataFrame(rows)


def _add_period_highlight(fig: go.Figure, period: str | None) -> None:
    if period:
        fig.add_vline(x=period, line_width=2, line_color="orange",
                      line_dash="dash", annotation_text=period,
                      annotation_position="top right")


def build_level_chart(
    ticker: str, name: str, data: pd.DataFrame, units_label: str,
    selected_period: pd.Timestamp, forecast_label: str,
    forecast_value: float | None = None,
    highlight_period: str | None = None,
) -> go.Figure:
    if ticker not in data.columns:
        return go.Figure()
    series = data[ticker].dropna().sort_index()
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
    ticker: str, name: str, data: pd.DataFrame,
    selected_period: pd.Timestamp, forecast_label: str,
    forecast_value: float | None = None,
    highlight_period: str | None = None,
) -> go.Figure:
    if ticker not in data.columns:
        return go.Figure()
    series = data[ticker].dropna().sort_index()
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


def build_treemap(series: list[dict], data: pd.DataFrame, period: pd.Timestamp) -> go.Figure:
    ids, labels, parents, values, hover = [], [], [], [], []
    stack: list[str] = []  # track parent tickers by indent depth

    for s in series:
        ticker = s["ticker"]
        depth = s["indent_level"]
        val_raw = float(data.loc[period, ticker]) if ticker in data.columns and period in data.index else 0.0
        val = abs(val_raw)

        # Determine parent from stack
        while len(stack) > depth:
            stack.pop()
        parent = stack[-1] if stack else ""

        ids.append(ticker)
        labels.append(s["series_name"])
        parents.append(parent)
        values.append(val)
        hover.append(f"<b>{s['series_name']}</b><br>{ticker}<br>Level: ${val_raw:,.1f}B")

        if s["is_aggregate"]:
            stack.append(ticker)

    fig = go.Figure(go.Treemap(
        ids=ids, labels=labels, parents=parents, values=values,
        marker=dict(line=dict(width=1.5, color="white")),
        hovertemplate="%{customdata}<extra></extra>", customdata=hover,
        textinfo="label+percent parent", maxdepth=3,
    ))
    fig.update_layout(margin=dict(t=10, l=0, r=0, b=0), height=460)
    return fig


# ── Bloomberg diagnostics (sidebar) ─────────────────────────────────────── #
with st.sidebar:
    st.caption("Bloomberg diagnostics")
    if st.button("Test connection"):
        import subprocess, sys
        result = subprocess.run(
            [sys.executable, "-c",
             "import sys; sys.path.insert(0, r'C:\\claude\\GDP_System1');"
             "from data.bloomberg import BloombergProvider;"
             "p = BloombergProvider();"
             "print('available:', p.available())"],
            capture_output=True, text=True, timeout=15,
        )
        st.code(result.stdout or result.stderr or "(no output)")

# ── Session state defaults ───────────────────────────────────────────────── #
if "chart_ticker" not in st.session_state:
    st.session_state["chart_ticker"] = None
    st.session_state["chart_name"] = None
    st.session_state["highlight_period"] = None
if "forecast_overrides" not in st.session_state:
    st.session_state["forecast_overrides"] = {}
    st.session_state["_last_forecast_label"] = None

# ── Controls ─────────────────────────────────────────────────────────────── #
all_tables = get_all_tables()
default_idx = all_tables.index("Table 1.1.6") if "Table 1.1.6" in all_tables else 0

c1, c2, c3, _ = st.columns([3, 1, 1, 2])
with c1:
    table_name = st.selectbox("Table", all_tables, index=default_idx, label_visibility="collapsed")
units_label = _units_label(table_name)

# Reset chart + forecast state when table changes
if st.session_state.get("_current_table") != table_name:
    st.session_state["chart_ticker"] = None
    st.session_state["chart_name"] = None
    st.session_state["forecast_overrides"] = {}
    st.session_state["_last_forecast_label"] = None
    st.session_state["_current_table"] = table_name

import warnings as _warnings

series_meta, data, load_warning = None, None, None
with _warnings.catch_warnings(record=True) as caught:
    _warnings.simplefilter("always")
    try:
        series_meta, data = fetch_table(table_name)
    except Exception as e:
        st.error(f"Failed to load {table_name}: {e}")
        st.stop()
    if caught:
        load_warning = str(caught[-1].message)

if load_warning:
    st.warning(f"Bloomberg offline — showing cached data. ({load_warning})")

if data is None or data.empty:
    st.warning("No data in archive and Bloomberg Terminal is not running. Open Bloomberg and reload.")
    st.stop()

quarters = data.index.sort_values()
quarter_labels = [_qlabel(q) for q in quarters]

with c2:
    n_periods = st.selectbox("Qtrs", list(range(2, 13)), index=4)
with c3:
    selected_label = st.selectbox("As of", quarter_labels[::-1], index=0)

selected_period = quarters[quarter_labels.index(selected_label)]
sel_idx = quarters.get_loc(selected_period)
hist_periods = list(quarters[max(0, sel_idx - n_periods + 1): sel_idx + 1])
period_cols = [_qlabel(p) for p in hist_periods]
forecast_period = selected_period + pd.DateOffset(months=3)
forecast_label = _qlabel(forecast_period) + " (F)"

if st.session_state["_last_forecast_label"] != forecast_label:
    st.session_state["forecast_overrides"] = {}
    st.session_state["_last_forecast_label"] = forecast_label

if st.session_state["chart_ticker"] is None and series_meta:
    st.session_state["chart_ticker"] = series_meta[0]["ticker"]
    st.session_state["chart_name"] = series_meta[0]["series_name"]

# ── Build tree df ────────────────────────────────────────────────────────── #
tree_df = build_tree_table(series_meta, data, hist_periods, forecast_label,
                           st.session_state["forecast_overrides"])

# ── AgGrid config ────────────────────────────────────────────────────────── #
row_style = JsCode("""
function(params) {
    if (params.data._is_id) return { fontWeight: 'bold', background: '#f5f5f5' };
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

gb = GridOptionsBuilder.from_dataframe(tree_df[["Component"] + period_cols + [forecast_label]])
gb.configure_default_column(resizable=True, sortable=False, filter=False, suppressSizeToFit=True)
gb.configure_column("Component", pinned="left", width=280)
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

# ── Layout ───────────────────────────────────────────────────────────────── #
col_table, col_chart = st.columns([1, 1])

with col_table:
    st.caption("= aggregate  ·  click a row to chart it")
    resp = AgGrid(
        tree_df,
        gridOptions=grid_opts,
        update_mode=GridUpdateMode.VALUE_CHANGED,
        allow_unsafe_jscode=True,
        height=600,
        theme="alpine",
        custom_css=custom_css,
    )

selected = resp.selected_rows
if selected is not None and len(selected) > 0:
    sel_row = selected[0] if isinstance(selected, list) else selected.iloc[0]
    st.session_state["chart_ticker"] = sel_row["_ticker"]
    st.session_state["chart_name"] = str(sel_row["Component"]).lstrip(" ").lstrip("= ").strip()

try:
    ret_df = resp.data if isinstance(resp.data, pd.DataFrame) else pd.DataFrame(resp.data)
    if forecast_label in ret_df.columns and "_ticker" in ret_df.columns:
        for _, row in ret_df.iterrows():
            t = row.get("_ticker")
            fcst_val = row.get(forecast_label)
            if t and fcst_val is not None and not pd.isna(fcst_val):
                st.session_state["forecast_overrides"][t] = float(fcst_val)
    clicked = ret_df[ret_df["_clicked_col"].astype(str) != ""]
    if not clicked.empty:
        col_clicked = str(clicked.iloc[0]["_clicked_col"])
        st.session_state["highlight_period"] = col_clicked if col_clicked in period_cols else None
except Exception:
    pass

with col_chart:
    ticker = st.session_state["chart_ticker"]
    name = st.session_state["chart_name"]
    hp = st.session_state["highlight_period"]
    default_fcst = float(data.loc[selected_period, ticker]) if ticker in data.columns and selected_period in data.index else None
    fcst_val = st.session_state["forecast_overrides"].get(ticker, default_fcst)
    view = st.segmented_control("View", ["Level ($B)", "QoQ Growth (%)"], default="Level ($B)", label_visibility="collapsed")
    if view == "QoQ Growth (%)":
        fig = build_growth_chart(ticker, name, data, selected_period, forecast_label,
                                 forecast_value=fcst_val, highlight_period=hp)
    else:
        fig = build_level_chart(ticker, name, data, units_label, selected_period, forecast_label,
                                forecast_value=fcst_val, highlight_period=hp)
    st.plotly_chart(fig, width="stretch")

st.markdown("---")

# ── Composition treemap ──────────────────────────────────────────────────── #
st.subheader("Composition")
st.caption(f"Box size = share of total  ·  {selected_label}")
st.plotly_chart(build_treemap(series_meta, data, selected_period), width="stretch")
