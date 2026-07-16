"""
Compare Bloomberg-ECST-derived table structure (macro.db, via db.macro_bridge)
against BEA's authoritative line structure (data.bea.BEAProvider).

What BEA's GetData API gives us that macro.db can't:
  - Authoritative row order and naming (no OCR/scrape artifacts).
  - Explicit "Less: ..." text on subtractive lines (real sign ground truth
    for the lines that carry it -- not every table uses the convention).

What it does NOT give us: an explicit indentation/depth field. BEA's
LineNumber is a flat ordered list, same as macro.db's row_order -- so tree
*shape* still has to come from data-driven residual fitting
(nipa.build_from_macro_db), not from BEA alone.

Two layers of validation, because either alone can mislead:

  1. Structural alignment. Naive positional alignment (BEA LineNumber N <->
     macro.db row_order N-1) breaks as soon as one source has an extra or
     missing row -- everything after the gap shifts out of alignment and
     produces garbage matches. So instead this aligns the two lists like a
     diff: rows with matching normalized text are anchors
     (difflib.SequenceMatcher over the normalized-name sequences), and only
     a Bloomberg<->BEA pairing backed by an anchor is trusted. Rows in an
     insert/delete/replace gap are left unaligned rather than guessed at by
     position.

  2. Numeric confirmation. A text anchor only proves the *labels* line up
     ("Goods" can anchor to the wrong "Goods" in a table with repeated
     labels, and a stale/mis-scraped ticker can still carry the right name).
     So for every anchored pair this also pulls BEA's actual value series
     and Bloomberg's archived value series and checks they actually
     correlate. Real matches should correlate ~1.0 (constant unit-scale
     differences, e.g. millions vs billions, don't affect correlation).

Reports, per table:
  - how many Bloomberg rows found a reliable BEA anchor (name-level)
  - of those, how many are numerically confirmed vs suspect
  - "Less:" subtraction cues on numerically-confirmed rows

Usage:
    python -m nipa.compare_bea                    # report over all tables
    python -m nipa.compare_bea --table "Table 2.1"
"""
from __future__ import annotations

import argparse
import difflib
import re
import time
from dataclasses import dataclass
from typing import Optional

import pandas as pd

from data.bea import BEAProvider
from db.macro_bridge import list_tables, get_table_series
from db.reader import _query_archive

CORR_CONFIRMED = 0.999
CORR_WEAK = 0.9
MIN_OVERLAPPING_PERIODS = 8


@dataclass
class AlignedRow:
    position: int
    bbg_ticker: str
    bbg_name: str
    bea_code: Optional[str]
    bea_desc: Optional[str]
    is_subtraction: bool
    anchored: bool
    numeric_status: str = "not_checked"  # confirmed | weak | suspect | insufficient_data | not_checked
    correlation: Optional[float] = None


def macro_table_number(table_name: str) -> Optional[str]:
    """'Table 1.1.5' -> '1.1.5'. Returns None for non-standard names (can't map to BEA)."""
    m = re.match(r"^Table ([\d.]+)$", table_name.strip())
    return m.group(1) if m else None


def _normalize(text: str) -> str:
    return re.sub(r"[^a-z0-9 ]", "", text.lower()).strip()


def _align(bbg_rows: list[dict], bea_rows: list[dict]) -> list[AlignedRow]:
    """Diff-based alignment: only trust pairings backed by a matching-text anchor."""
    bbg_keys = [_normalize(r["series_name"]) for r in bbg_rows]
    bea_keys = [_normalize(r["description"]) for r in bea_rows]

    matcher = difflib.SequenceMatcher(None, bbg_keys, bea_keys, autojunk=False)
    aligned: list[AlignedRow] = []

    for tag, i1, i2, j1, j2 in matcher.get_opcodes():
        if tag == "equal":
            for k in range(i2 - i1):
                b, e = bbg_rows[i1 + k], bea_rows[j1 + k]
                aligned.append(AlignedRow(
                    position=i1 + k, bbg_ticker=b["ticker"], bbg_name=b["series_name"],
                    bea_code=e["series_code"], bea_desc=e["description"],
                    is_subtraction=e["is_subtraction"], anchored=True,
                ))
        else:
            for k in range(i1, i2):
                b = bbg_rows[k]
                aligned.append(AlignedRow(
                    position=k, bbg_ticker=b["ticker"], bbg_name=b["series_name"],
                    bea_code=None, bea_desc=None, is_subtraction=False, anchored=False,
                ))

    aligned.sort(key=lambda r: r.position)
    return aligned


def _numeric_confirm(provider: BEAProvider, bea_table_id: str, aligned: list[AlignedRow]) -> None:
    """Mutate aligned rows in place with a numeric_status based on real archived data."""
    anchored = [r for r in aligned if r.anchored]
    if not anchored:
        return

    bea_df = provider._fetch_table(bea_table_id, "Q")
    bbg_df = _query_archive([r.bbg_ticker for r in anchored])

    for r in anchored:
        if r.bea_code not in bea_df.columns or r.bbg_ticker not in bbg_df.columns:
            r.numeric_status = "insufficient_data"
            continue
        # BEA reports quarter-start dates, Bloomberg archive uses quarter-end --
        # align on quarter period, not raw timestamp, or nothing ever overlaps.
        bea_s = bea_df[r.bea_code].copy()
        bea_s.index = bea_s.index.to_period("Q")
        bbg_s = bbg_df[r.bbg_ticker].copy()
        bbg_s.index = bbg_s.index.to_period("Q")
        sub = pd.concat([bea_s, bbg_s], axis=1, keys=["bea", "bbg"], sort=True).dropna()
        if len(sub) < MIN_OVERLAPPING_PERIODS:
            r.numeric_status = "insufficient_data"
            continue
        corr = sub["bea"].corr(sub["bbg"])
        r.correlation = corr
        if corr >= CORR_CONFIRMED:
            r.numeric_status = "confirmed"
        elif corr >= CORR_WEAK:
            r.numeric_status = "weak"
        else:
            r.numeric_status = "suspect"


def compare_table(provider: BEAProvider, table_name: str) -> Optional[dict]:
    table_number = macro_table_number(table_name)
    if table_number is None:
        return None

    bea_table_id = provider.table_id_for_number(table_number)
    if bea_table_id is None:
        return None

    bbg_rows = sorted(get_table_series(table_name), key=lambda r: r["row_order"])
    bea_rows = provider.get_line_metadata(bea_table_id)

    aligned = _align(bbg_rows, bea_rows)
    _numeric_confirm(provider, bea_table_id, aligned)

    confirmed = [r for r in aligned if r.numeric_status == "confirmed"]
    return {
        "table_number": table_number,
        "bea_table_id": bea_table_id,
        "n_bloomberg_rows": len(bbg_rows),
        "n_bea_rows": len(bea_rows),
        "aligned": aligned,
        "n_anchored": sum(1 for r in aligned if r.anchored),
        "n_confirmed": len(confirmed),
        "n_weak": sum(1 for r in aligned if r.numeric_status == "weak"),
        "n_suspect": sum(1 for r in aligned if r.numeric_status == "suspect"),
        "subtraction_cues": [r for r in confirmed if r.is_subtraction],
    }


def report(tables: Optional[list[str]] = None) -> None:
    provider = BEAProvider()
    if not provider.available():
        print("BEA API not reachable -- check BEA_API_KEY / connectivity.")
        return
    provider.table_catalog()  # prime cache once up front

    tables = tables or list_tables()
    n_mappable = 0
    total_rows = 0
    total_anchored = 0
    total_confirmed = 0
    total_weak = 0
    total_suspect = 0
    total_subtraction_cues = 0
    unmappable: list[str] = []

    for table_name in tables:
        try:
            result = compare_table(provider, table_name)
        except Exception as e:
            print(f"{table_name}: ERROR ({e})")
            continue

        if result is None:
            unmappable.append(table_name)
            continue

        n_mappable += 1
        total_rows += result["n_bloomberg_rows"]
        total_anchored += result["n_anchored"]
        total_confirmed += result["n_confirmed"]
        total_weak += result["n_weak"]
        total_suspect += result["n_suspect"]
        total_subtraction_cues += len(result["subtraction_cues"])

        print(
            f"{table_name} -> {result['bea_table_id']}: "
            f"rows={result['n_bloomberg_rows']} anchored={result['n_anchored']} "
            f"confirmed={result['n_confirmed']} weak={result['n_weak']} suspect={result['n_suspect']}  "
            f"less_cues={len(result['subtraction_cues'])}"
        )
        time.sleep(0.15)  # be polite to the API across ~80 requests

    print()
    print(f"Mappable to a BEA table: {n_mappable}/{len(tables)}  ({len(unmappable)} unmapped)")
    print(f"Rows with a text anchor: {total_anchored}/{total_rows}")
    print(f"Numerically confirmed:   {total_confirmed}/{total_anchored}")
    print(f"Weak correlation:        {total_weak}/{total_anchored}")
    print(f"Suspect (likely wrong):  {total_suspect}/{total_anchored}")
    print(f"'Less:' cues on confirmed rows: {total_subtraction_cues}")
    if unmappable:
        print()
        print("Unmapped tables (non-standard name, need manual handling):")
        for t in unmappable:
            print(f"  - {t}")


def _cli() -> None:
    parser = argparse.ArgumentParser(description="Compare Bloomberg ECST tables against BEA's authoritative structure.")
    parser.add_argument("--table", default=None)
    args = parser.parse_args()

    if args.table:
        provider = BEAProvider()
        result = compare_table(provider, args.table)
        if result is None:
            print(f"{args.table}: not mappable to a BEA table.")
            return
        print(f"{args.table} -> {result['bea_table_id']}  "
              f"(bbg={result['n_bloomberg_rows']} bea={result['n_bea_rows']})")
        print()
        for r in result["aligned"]:
            flag = "LESS:" if r.is_subtraction else "     "
            corr_str = f"{r.correlation:.4f}" if r.correlation is not None else "  --  "
            print(
                f"[{r.position:>2}] {flag} {r.bbg_ticker:<14} {r.bbg_name:<40} | "
                f"{r.bea_code or '':<10} {r.bea_desc or '':<40} "
                f"corr={corr_str} [{r.numeric_status}]"
            )
    else:
        report()


if __name__ == "__main__":
    _cli()
