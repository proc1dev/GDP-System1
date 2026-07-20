"""
Auto-generate NIPANode accounting trees for the Bloomberg ECST tables in
macro.db, instead of hand-typing each one in tables.py.

macro.db gives us the tree *shape* for free (row_order + indent_level from
the ECST export). It does NOT give us the +/- sign on each child (series
names are plain, e.g. "Imports", not "Less: Imports") -- so sign is inferred
by brute-forcing +1/-1 for every child of a parent and keeping whichever
combination makes  parent = Sigma sign_i * child_i  fit the archived history
best. Nodes where no combination fits well are flagged rather than forced
into a tree (e.g. ratios, price indexes, per-capita lines that ride along
in an ECST export without being part of a summation).

Usage:
    python -m nipa.build_from_macro_db                    # report over all tables
    python -m nipa.build_from_macro_db --table "Table 1.1.5"
"""
from __future__ import annotations

import argparse
import itertools
import time
from dataclasses import dataclass
from typing import Optional

import pandas as pd

from .compare_bea import _align, macro_table_number
from .node import NIPANode
from .series import NIPASeries
from data.bea import BEAProvider
from db.macro_bridge import list_tables, get_table_series
from db.reader import _query_archive

# Relative-residual thresholds for classifying a fitted identity.
ADDITIVE_THRESHOLD = 0.01          # nominal $ tables should match almost exactly
CHAIN_WEIGHTED_THRESHOLD = 0.05    # real/chained tables drift from strict additivity
MIN_OVERLAPPING_PERIODS = 8        # too little history to trust a fit


@dataclass
class SignFit:
    child_codes: list[str]
    signs: list[float]
    median_abs_residual: float
    relative_residual: Optional[float]  # None if parent scale is ~0
    classification: str  # "additive" | "chain_weighted" | "unresolved" | "insufficient_data"
    bea_hinted: bool = False  # True if >=1 child sign came from BEA line metadata, not brute force


def _build_forest(table_name: str, series: list[dict]) -> list[NIPANode]:
    """Parse row_order/indent_level into a forest of NIPANode trees, signs unset (+1 placeholder)."""
    nodes = [
        NIPANode(
            NIPASeries(
                code=s["ticker"],
                name=s["series_name"],
                table=table_name,
                line=s["row_order"],
                bbl_ticker=s["ticker"],
            )
        )
        for s in series
    ]

    roots: list[NIPANode] = []
    stack: list[tuple[int, NIPANode]] = []
    for s, node in zip(series, nodes):
        level = s["indent_level"]
        while stack and stack[-1][0] >= level:
            stack.pop()
        if stack:
            stack[-1][1].add(node, 1.0)
        else:
            roots.append(node)
        stack.append((level, node))
    return roots


def _bea_sign_hints(
    table_name: str,
    series: list[dict],
    provider: Optional[BEAProvider],
) -> dict[str, float]:
    """
    Authoritative ticker -> sign (+1.0 / -1.0), read off BEA's own line
    descriptions ("Less: ...") via the same text-anchored alignment
    compare_bea.py uses to cross-check Bloomberg rows against BEA.

    Empty (falls back to pure brute force in _fit_signs) if the table has no
    standard BEA table number, BEA has no matching table, or provider is None.
    """
    if provider is None:
        return {}

    table_number = macro_table_number(table_name)
    if table_number is None:
        return {}

    bea_table_id = provider.table_id_for_number(table_number)
    if bea_table_id is None:
        return {}

    bea_rows = provider.get_line_metadata(bea_table_id)
    if not bea_rows:
        return {}

    aligned = _align(series, bea_rows)
    return {
        r.bbg_ticker: (-1.0 if r.is_subtraction else 1.0)
        for r in aligned
        if r.anchored
    }


def _fit_signs(
    parent_code: str,
    child_codes: list[str],
    data: pd.DataFrame,
    sign_hints: Optional[dict[str, float]] = None,
) -> SignFit:
    cols = [parent_code] + child_codes
    present = [c for c in cols if c in data.columns]
    if len(present) < len(cols):
        return SignFit(child_codes, [1.0] * len(child_codes), float("nan"), None, "insufficient_data")

    sub = data[cols].dropna()
    if len(sub) < MIN_OVERLAPPING_PERIODS:
        return SignFit(child_codes, [1.0] * len(child_codes), float("nan"), None, "insufficient_data")

    parent = sub[parent_code]
    children = [sub[c] for c in child_codes]

    sign_hints = sign_hints or {}
    fixed: list[Optional[float]] = [sign_hints.get(c) for c in child_codes]
    free_idx = [i for i, s in enumerate(fixed) if s is None]

    best_signs: Optional[list[float]] = None
    best_score = float("inf")
    for combo in itertools.product((1.0, -1.0), repeat=len(free_idx)):
        candidate = list(fixed)
        for idx, sign in zip(free_idx, combo):
            candidate[idx] = sign
        computed = sum(sign * c for sign, c in zip(candidate, children))
        score = (parent - computed).abs().median()
        if score < best_score:
            best_score = score
            best_signs = candidate

    scale = parent.abs().median()
    rel = (best_score / scale) if scale > 0 else None

    if rel is None:
        classification = "unresolved"
    elif rel < ADDITIVE_THRESHOLD:
        classification = "additive"
    elif rel < CHAIN_WEIGHTED_THRESHOLD:
        classification = "chain_weighted"
    else:
        classification = "unresolved"

    return SignFit(
        child_codes, best_signs, best_score, rel, classification,
        bea_hinted=len(free_idx) < len(child_codes),
    )


def build_table(
    table_name: str,
    data: Optional[pd.DataFrame] = None,
    provider: Optional[BEAProvider] = None,
) -> tuple[list[NIPANode], dict[str, SignFit]]:
    """
    Build the forest for one table and fit signs for every parent that has children.

    If `provider` is given, child signs are seeded from BEA's authoritative
    line descriptions where a reliable text anchor exists, instead of relying
    solely on the brute-force fit (see _bea_sign_hints).

    Returns (roots, fits) where fits is keyed by parent series code.
    """
    series = get_table_series(table_name)
    roots = _build_forest(table_name, series)
    if data is None:
        all_tickers = [n.series.code for r in roots for n in r.all_nodes()]
        data = _query_archive(all_tickers)

    hints = _bea_sign_hints(table_name, series, provider)

    fits: dict[str, SignFit] = {}
    for root in roots:
        for node in root.all_nodes():
            if node.is_leaf:
                continue
            child_codes = [c.series.code for c, _ in node.children]
            fit = _fit_signs(node.series.code, child_codes, data, sign_hints=hints)
            fits[node.series.code] = fit
            # Apply inferred signs back onto the tree so callers get a usable NIPANode.
            node.children = list(zip([c for c, _ in node.children], fit.signs))

    return roots, fits


def report(tables: Optional[list[str]] = None, use_bea: bool = True) -> None:
    tables = tables or list_tables()
    provider: Optional[BEAProvider] = None
    if use_bea:
        provider = BEAProvider()
        if provider.available():
            provider.table_catalog()  # prime cache once up front
        else:
            print("BEA API not reachable -- falling back to pure brute-force sign fitting.")
            provider = None

    totals = {"additive": 0, "chain_weighted": 0, "unresolved": 0, "insufficient_data": 0}
    total_hinted = 0

    for table_name in tables:
        try:
            _, fits = build_table(table_name, provider=provider)
        except Exception as e:
            print(f"{table_name}: FAILED ({e})")
            continue

        if provider is not None:
            time.sleep(0.15)  # be polite to the BEA API across ~80 tables

        if not fits:
            print(f"{table_name}: no parent/child identities (flat list)")
            continue

        counts = {"additive": 0, "chain_weighted": 0, "unresolved": 0, "insufficient_data": 0}
        hinted = 0
        for fit in fits.values():
            counts[fit.classification] += 1
            totals[fit.classification] += 1
            if fit.bea_hinted:
                hinted += 1
                total_hinted += 1

        print(
            f"{table_name}: {len(fits)} identities -- "
            f"additive={counts['additive']} chain_weighted={counts['chain_weighted']} "
            f"unresolved={counts['unresolved']} insufficient_data={counts['insufficient_data']}  "
            f"bea_hinted={hinted}"
        )

    print()
    print(
        f"TOTAL across {len(tables)} tables: "
        f"additive={totals['additive']} chain_weighted={totals['chain_weighted']} "
        f"unresolved={totals['unresolved']} insufficient_data={totals['insufficient_data']}  "
        f"bea_hinted={total_hinted}"
    )


def _cli() -> None:
    parser = argparse.ArgumentParser(description="Auto-build NIPA accounting trees from macro.db.")
    parser.add_argument("--table", default=None, help="Single table name, e.g. 'Table 1.1.5'")
    parser.add_argument("--no-bea", action="store_true", help="Skip BEA sign hints; pure brute-force fit only.")
    args = parser.parse_args()

    if args.table:
        provider = None if args.no_bea else BEAProvider()
        roots, fits = build_table(args.table, provider=provider)
        for root in roots:
            print(root.display())
        print()
        for code, fit in fits.items():
            print(
                f"{code}: {fit.classification} (signs={fit.signs}, "
                f"rel_residual={fit.relative_residual}, bea_hinted={fit.bea_hinted})"
            )
    else:
        report(use_bea=not args.no_bea)


if __name__ == "__main__":
    _cli()
