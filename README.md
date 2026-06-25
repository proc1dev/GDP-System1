# GDP_System1

A Python framework for NIPA accounting tree analysis. Defines the BEA table structure, accounting identities, and data-provider interfaces. Intended to be used as a **reference/library** by the bloomberg-scraper project, which handles all actual data collection.

---

## What this project contains

### NIPA accounting trees (`nipa/`)

The core of the project. Each BEA table is represented as a tree of `NIPANode` objects where every non-leaf node encodes an accounting identity:

```
parent = Σ (sign_i × child_i)
```

Signs are `+1` for additive components and `-1` for subtractive ones (e.g. Imports under Net Exports).

**Four tables are implemented in `nipa/tables.py`:**

| Key | BEA Table | Description |
|-----|-----------|-------------|
| `T10105` | 1.1.5 | GDP — Nominal, current dollars, SAAR |
| `T10106` | 1.1.6 | GDP — Real, chained 2017 dollars, SAAR |
| `T10705` | 1.7.5 | GDP → GNP → NNP → NI → PI → DPI → PCE bridge |
| `T20100` | 2.1   | Personal Income and its Disposition |

**T10105 tree (GDP Nominal) — 35 nodes:**
```
+ GDP  (A191RC)
    + PCE         (DPCERC)    → Goods (DGDSRC): Durables, Nondurables
                              → Services (DSERRC)
    + GPDI        (A006RC)    → Fixed Inv (A007RC): Nonresidential, Residential
                              → Change in Inventories (A019RC)
    + Net Exports (A020RC)    + Exports (A021RC): Goods, Services
                              - Imports (A024RC): Goods, Services   ← sign = -1
    + Government  (A822RC)    → Federal (A823RC): Defense, Nondefense
                              → State & Local (A829RC)
```

**Key classes:**

`NIPASeries` (frozen dataclass) — metadata for one BEA series:
- `code` — BEA series code, e.g. `"A191RC"`
- `name` — full BEA name
- `table` — BEA table number, e.g. `"1.1.5"`
- `line` — line number within the table
- `is_nominal` — `False` for chained-dollar (real) series
- `bbl_ticker` — Bloomberg ticker if mapped, e.g. `"GDP CQOQ Index"`; `None` for most series

`NIPANode` — tree node wrapping a `NIPASeries`:
- `.add(child, sign=1.0)` — attach a child, returns self for chaining
- `.all_nodes()` — pre-order list of every node in subtree
- `.leaves()` — only leaf nodes
- `.find(code)` — find a node by BEA code
- `.validate(data, tolerance)` — check identity holds against a DataFrame
- `.validate_all(data)` — recursive validation of entire subtree
- `.contributions(data, annualize=True)` — each child's contribution to parent change (ppts)
- `.display()` — indented text tree with signs and line numbers
- `.identity_str()` — e.g. `"A191RC = DPCERC + A006RC + A020RC + A822RC"`

```python
from nipa.tables import build_T10105
root = build_T10105()
print(root.display())          # full tree
root.find("A024RC")            # Imports node
root.validate_all(data_df)     # dict of identity check DataFrames
root.contributions(data_df)    # ppt contributions to GDP growth
```

---

### Data providers (`data/`)

**These are placeholder/toy implementations.** Real data should come from the bloomberg-scraper project's macro.db (populated via ECST export) or directly via blpapi.

| File | Class | Status |
|------|-------|--------|
| `data/bloomberg.py` | `BloombergProvider` | Wraps `blpapi` BDH calls; requires Bloomberg Terminal + blpapi package |
| `data/bea.py` | `BEAProvider` | BEA REST API; needs free API key |
| `data/fred.py` | `FREDProvider` | FRED API; needs free API key |
| `data/mock.py` | `MockProvider` | Generates synthetic data satisfying identities exactly; used for UI demos |
| `data/base.py` | `DataProvider` (ABC), `FallbackProvider` | Interface all providers implement |

`BloombergProvider` in `data/bloomberg.py` also maintains `BBL_TICKER_MAP` — a dict of `BEA code → Bloomberg ticker` for ~20 key series. This is the most complete ticker mapping in the project.

---

### Accounting validation (`validation/`)

`AccountingValidator` — checks every non-leaf identity in a tree against a DataFrame:
- Nominal series tolerance: `0.6` ($B) — BEA rounds to 1 decimal
- Real (chain-weighted) tolerance: `15.0` ($B) — chain-weighting residuals are expected
- Returns a `ValidationReport` with per-identity pass/fail and max residuals

---

### Streamlit app (`app.py`)

A working interactive UI (uses `MockProvider` — no live data):
- Left panel: NIPA hierarchy table with editable forecast column; identity rows bold, subtracted rows red
- Right panel: level chart or QoQ growth bar chart for selected row
- Bottom: treemap of GDP composition by component share
- Accounting identities tab

Run with: `streamlit run app.py`

**The app currently uses `MockProvider` (fake data).** To use real data, replace `MockProvider` with a provider that reads from the bloomberg-scraper macro.db.

---

### Entry point (`gdp_system.py`)

CLI demo that prints the accounting structure, fetches data (MockProvider by default), validates all identities, and prints contribution-to-growth breakdowns.

```
python gdp_system.py           # full demo with mock data
python gdp_system.py --no-fetch  # structure/tree only, no data
```

---

## What this project does NOT have

- Any live data — all data comes from `MockProvider` unless you wire up blpapi/BEA/FRED
- Historical series storage — no database
- A way to pull ECST-section data from Bloomberg Terminal UI
- Bloomberg ticker mappings for most NIPA series (only ~6 nodes have `bbl_ticker` set in the tree; `BBL_TICKER_MAP` in `data/bloomberg.py` covers ~20 more)

These gaps are filled by the bloomberg-scraper project.

---

## Relationship to bloomberg-scraper

The two projects have complementary roles:

**bloomberg-scraper** was the discovery tool. By automating Bloomberg ECST exports across dozens of sections and tables, it produced `macro.db` — a map of which series exist, how they are named, how they are organized hierarchically within each table, and what tickers Bloomberg uses for them. That structure is now known.

**This project (GDP_System1)** is the analysis interface built on top of that discovered structure. Now that we know what Bloomberg has and how it is organized, this project is responsible for:

- Defining the accounting relationships (which series add up to which, with what signs)
- Pulling the actual time-series data from Bloomberg via blpapi
- Validating that accounting identities hold in the live data
- Computing contributions to growth and other derived quantities
- Presenting the data through the Streamlit UI

| Concern | This project | bloomberg-scraper |
|---------|-------------|-------------------|
| Discover series structure via ECST exports | ✗ | ✓ (macro.db) |
| Bloomberg Terminal automation | ✗ | ✓ |
| Bloomberg API (blpapi BDH pulls) | **✓ lives here** | ✗ |
| NIPA tree definitions & accounting identities | ✓ | imports from here |
| Validation & contribution analysis | ✓ | ✗ |
| Interactive UI | ✓ Streamlit | ✗ |

The `nipa/` package defines what to ask for. The `data/bloomberg.py` provider is where to implement how to ask for it. The bloomberg-scraper project's `macro.db` and its ECST ticker/name mappings are the reference for filling in the remaining `bbl_ticker` gaps in the NIPA tree.
