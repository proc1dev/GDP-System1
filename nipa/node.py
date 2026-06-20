"""
NIPANode — a tree node encoding one level of a NIPA accounting identity.

Each non-leaf node carries an identity of the form:
    parent.value = Σ (sign_i × child_i.value)

Signs are +1 for additive children and -1 for subtractive ones (imports).
For real (chain-weighted) series the identity holds only approximately; the
`is_nominal` flag controls whether strict equality is expected.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import List, Optional, Tuple

import pandas as pd

from .series import NIPASeries


@dataclass
class NIPANode:
    series: NIPASeries
    # (child_node, sign) — sign is +1 or -1
    children: List[Tuple[NIPANode, float]] = field(default_factory=list)

    # ------------------------------------------------------------------ #
    # Tree construction helpers
    # ------------------------------------------------------------------ #

    def add(self, child: NIPANode, sign: float = 1.0) -> NIPANode:
        """Append a child and return self for chaining."""
        self.children.append((child, sign))
        return self

    @property
    def is_leaf(self) -> bool:
        return len(self.children) == 0

    # ------------------------------------------------------------------ #
    # Traversal
    # ------------------------------------------------------------------ #

    def all_nodes(self) -> List[NIPANode]:
        """Pre-order depth-first list of every node in the subtree."""
        result: List[NIPANode] = [self]
        for child, _ in self.children:
            result.extend(child.all_nodes())
        return result

    def leaves(self) -> List[NIPANode]:
        return [n for n in self.all_nodes() if n.is_leaf]

    def find(self, code: str) -> Optional[NIPANode]:
        """Find a node by BEA series code."""
        for node in self.all_nodes():
            if node.series.code == code:
                return node
        return None

    # ------------------------------------------------------------------ #
    # Display
    # ------------------------------------------------------------------ #

    def identity_str(self) -> str:
        """Human-readable accounting identity for this node."""
        if self.is_leaf:
            return self.series.code
        parts: List[str] = []
        for i, (child, sign) in enumerate(self.children):
            prefix = ("- " if sign < 0 else "+ ") if i > 0 else ("  " if sign > 0 else "-")
            parts.append(f"{prefix}{child.series.code}")
        rhs = "  " + "  ".join(parts)
        return f"{self.series.code}  =  {rhs.strip()}"

    def display(self, indent: int = 0, sign: float = 1.0) -> str:
        """Indented tree view with sign and series metadata."""
        sign_str = "+" if sign > 0 else "-"
        line = (
            f"{'  ' * indent}{sign_str} [{self.series.line:>2}] "
            f"{self.series.code:<10}  {self.series.name}"
        )
        lines = [line]
        for child, child_sign in self.children:
            lines.append(child.display(indent + 1, child_sign))
        return "\n".join(lines)

    def __repr__(self) -> str:
        return f"NIPANode({self.series.code})"

    # ------------------------------------------------------------------ #
    # Accounting validation
    # ------------------------------------------------------------------ #

    def validate(
        self,
        data: pd.DataFrame,
        tolerance: float = 0.6,
    ) -> pd.DataFrame:
        """
        Check that  parent = Σ sign_i × child_i  holds within tolerance.

        Parameters
        ----------
        data : DataFrame with BEA series codes as columns, dates as index.
        tolerance : Acceptable absolute residual in billions of dollars.
                    BEA rounds published data to 1 decimal, so residuals of
                    up to ~0.5 × n_children are expected for nominal series.

        Returns
        -------
        DataFrame with columns [parent, computed_sum, residual, ok].
        Empty DataFrame if this node is a leaf or data is missing.
        """
        if self.is_leaf:
            return pd.DataFrame()

        missing = [
            c.series.code
            for c, _ in [(self, 1)] + self.children
            if c.series.code not in data.columns
        ]
        if missing:
            return pd.DataFrame(
                {"missing_series": [missing]},
                index=["validation_error"],
            )

        computed = sum(
            sign * data[child.series.code] for child, sign in self.children
        )
        residual = data[self.series.code] - computed
        return pd.DataFrame(
            {
                "parent": data[self.series.code],
                "computed_sum": computed,
                "residual": residual,
                "ok": residual.abs() <= tolerance,
            }
        )

    def validate_all(
        self,
        data: pd.DataFrame,
        tolerance: float = 0.6,
    ) -> dict[str, pd.DataFrame]:
        """
        Recursively validate every non-leaf identity in the subtree.

        Returns a dict keyed by parent series code.
        """
        results: dict[str, pd.DataFrame] = {}
        if not self.is_leaf:
            results[self.series.code] = self.validate(data, tolerance)
            for child, _ in self.children:
                results.update(child.validate_all(data, tolerance))
        return results

    # ------------------------------------------------------------------ #
    # Contribution analysis
    # ------------------------------------------------------------------ #

    def contributions(
        self, data: pd.DataFrame, annualize: bool = True
    ) -> pd.DataFrame:
        """
        Compute each direct child's contribution to the change in this node.

        Contribution of child i in period t:
            contrib_i(t) = sign_i × Δchild_i(t) / parent(t-1)
        Multiplied by 4 when annualizing quarterly data.

        Parameters
        ----------
        data        : DataFrame indexed by date, columns = BEA series codes.
        annualize   : Multiply by 4 for quarterly SAAR (default True).

        Returns
        -------
        DataFrame indexed like data, one column per direct child.
        """
        if self.is_leaf or self.series.code not in data.columns:
            return pd.DataFrame()

        scale = 4.0 if (annualize and self.series.frequency == "Q") else 1.0
        parent = data[self.series.code]
        lag_parent = parent.shift(1)

        cols: dict[str, pd.Series] = {}
        for child, sign in self.children:
            if child.series.code in data.columns:
                delta = data[child.series.code].diff()
                # ×100 converts fraction → percentage points, matching GDP % growth
                cols[child.series.code] = sign * delta / lag_parent * scale * 100

        return pd.DataFrame(cols, index=data.index)
