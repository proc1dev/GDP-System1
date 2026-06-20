"""
GDP System — main entry point and demonstration.

Quick start
-----------
    python gdp_system.py

This will:
  1. Build the NIPA accounting trees for Tables 1.1.5 and 1.1.6
  2. Print the full accounting structure (tree + identities)
  3. Fetch data from BEA (Bloomberg if available, BEA REST API as fallback)
  4. Validate all accounting identities against the fetched data
  5. Print contribution-to-growth breakdown for the last 8 quarters
"""
import sys
import pandas as pd

from nipa import get_table, build_T10105, build_T10106, build_T10705, build_T20100
from data import default_provider, BEAProvider, FREDProvider, MockProvider
from validation import AccountingValidator


# =========================================================================== #
# 1.  Describe the accounting structure (no data needed)
# =========================================================================== #

def print_structure(table_id: str = "T10105") -> None:
    print(f"\n{'='*70}")
    print(f"  NIPA Table {table_id}  - Accounting Structure")
    print(f"{'='*70}")

    root = get_table(table_id)
    print(root.display())

    print(f"\n{'-'*70}")
    print("  Accounting Identities:")
    for node in root.all_nodes():
        if not node.is_leaf:
            print(f"    {node.identity_str()}")


# =========================================================================== #
# 2.  Fetch data and validate
# =========================================================================== #

def fetch_and_validate(
    table_id: str = "T10105",
    start: str = "2000-01-01",
    provider=None,
) -> tuple[pd.DataFrame, object]:
    root = get_table(table_id)
    all_codes = [n.series.code for n in root.all_nodes()]

    if provider is None:
        # MockProvider generates synthetic data that satisfies all identities exactly.
        # Replace with FREDProvider(api_key=...) or BEAProvider(api_key=...) for
        # real data once you have registered for a free API key.
        provider = MockProvider(n_quarters=40)

    print(f"\n[{provider.name}] Fetching {len(all_codes)} series for Table {table_id}…")
    data = provider.fetch(all_codes, start=start)

    if data.empty:
        print("  No data returned. Check your connection or API key.")
        return data, None

    print(f"  Retrieved {len(data.columns)} series, "
          f"{len(data)} periods ({data.index.min()} – {data.index.max()})")

    validator = AccountingValidator(
        root,
        tolerance=0.6 if root.series.is_nominal else 15.0,
    )
    missing = validator.missing_series(data)
    if missing:
        print(f"  Missing series (not in response): {missing}")

    report = validator.run(data)
    print(report)

    return data, report


# =========================================================================== #
# 3.  Contribution-to-growth breakdown
# =========================================================================== #

def print_contributions(
    data: pd.DataFrame,
    table_id: str = "T10106",
    n_quarters: int = 8,
) -> None:
    root = get_table(table_id)
    recent = data.tail(n_quarters + 1)      # +1 for diff()

    contrib = root.contributions(recent, annualize=True)
    if contrib.empty:
        print("  Cannot compute contributions — GDP data missing.")
        return

    # Map codes → short labels
    code_to_name = {n.series.code: n.series.name for n in root.all_nodes()}

    print(f"\n{'='*70}")
    print("  Contributions to Real GDP Growth  (QoQ, SAAR, ppts)")
    print(f"{'='*70}")
    contrib.rename(columns=code_to_name, inplace=True)

    # Compute actual GDP growth as well
    gdp_code = root.series.code
    if gdp_code in data.columns:
        gdp = data[gdp_code]
        actual_growth = (gdp / gdp.shift(1) - 1) * 4 * 100
        contrib.insert(0, "Real GDP (actual %)", actual_growth.reindex(contrib.index))

    # Drop the lagged row used for diff
    contrib = contrib.iloc[1:]

    with pd.option_context("display.float_format", "{:+.2f}".format,
                           "display.max_columns", 10,
                           "display.width", 120):
        print(contrib.to_string())


# =========================================================================== #
# 4.  Quick sanity-check on the tree structure alone (no network)
# =========================================================================== #

def check_tree_structure() -> None:
    print("\n  Checking tree structure integrity...")
    issues = []
    for tid in ["T10105", "T10106", "T10705", "T20100"]:
        root = get_table(tid)
        nodes = root.all_nodes()
        codes = [n.series.code for n in nodes]
        # Detect duplicate codes within a tree
        dupes = [c for c in set(codes) if codes.count(c) > 1]
        if dupes:
            issues.append(f"  {tid}: duplicate codes {dupes}")
        print(f"    {tid}: {len(nodes):>3} nodes, "
              f"{sum(1 for n in nodes if n.is_leaf):>3} leaves, "
              f"{sum(1 for n in nodes if not n.is_leaf):>3} identities"
              + (f"  ← DUPES: {dupes}" if dupes else ""))

    if not issues:
        print("  All trees structurally valid.")


# =========================================================================== #
# Entry point
# =========================================================================== #

if __name__ == "__main__":
    # ── Structure only (always works offline) ───────────────────────────── #
    print_structure("T10105")
    check_tree_structure()

    # ── Live data fetch + validation (requires internet) ────────────────── #
    fetch_live = "--no-fetch" not in sys.argv
    if fetch_live:
        data_nominal, _ = fetch_and_validate("T10105", start="2015-01-01")
        data_real,    _ = fetch_and_validate("T10106", start="2015-01-01")

        if not data_real.empty:
            # Merge real and nominal for contribution analysis
            combined = pd.concat([data_real, data_nominal], axis=1)
            combined = combined.loc[:, ~combined.columns.duplicated()]
            print_contributions(combined, table_id="T10106", n_quarters=8)
    else:
        print("\n  [--no-fetch] Skipping live data pull.")
