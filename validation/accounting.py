"""
AccountingValidator — checks that every identity in a NIPA tree holds.

Usage
-----
from nipa import get_table
from validation.accounting import AccountingValidator

tree = get_table("T10105")
validator = AccountingValidator(tree)
report = validator.run(data_df)
print(report)
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

import pandas as pd

from nipa.node import NIPANode


@dataclass
class IdentityCheck:
    parent_code: str
    parent_name: str
    n_periods: int
    n_violations: int
    max_residual: float
    mean_residual: float
    tolerance: float

    @property
    def passed(self) -> bool:
        return self.n_violations == 0

    def __str__(self) -> str:
        status = "PASS" if self.passed else f"FAIL ({self.n_violations}/{self.n_periods} periods)"
        return (
            f"  {status:30s}  {self.parent_code:<12}  "
            f"max_resid={self.max_residual:+.2f}  mean_resid={self.mean_residual:+.2f}  "
            f"({self.parent_name})"
        )


class AccountingValidator:
    """
    Validates all NIPA accounting identities for a given dataset.

    Parameters
    ----------
    root : NIPANode — root of the accounting tree (e.g. from get_table()).
    tolerance : float — acceptable residual in billions of dollars.
                Nominal series: 0.6 (BEA rounds to 1 decimal).
                Real (chain-weighted): 15.0 (chain-weighting residuals).
    """

    def __init__(
        self,
        root: NIPANode,
        tolerance: float = 0.6,
        real_tolerance: float = 15.0,
    ) -> None:
        self._root = root
        self._tolerance = tolerance
        self._real_tolerance = real_tolerance

    def run(self, data: pd.DataFrame) -> "ValidationReport":
        """
        Validate all identities in the tree against `data`.

        Parameters
        ----------
        data : DataFrame with BEA series codes as columns, dates as index.
               Values should be in billions of dollars (SAAR).

        Returns
        -------
        ValidationReport with per-identity results.
        """
        checks: list[IdentityCheck] = []
        for node in self._root.all_nodes():
            if node.is_leaf or len(node.children) == 0:
                continue

            tol = (
                self._real_tolerance
                if not node.series.is_nominal
                else self._tolerance
            )
            result_df = node.validate(data, tolerance=tol)

            if result_df.empty or "missing_series" in result_df.columns:
                continue

            residual = result_df["residual"]
            checks.append(
                IdentityCheck(
                    parent_code=node.series.code,
                    parent_name=node.series.name,
                    n_periods=len(residual),
                    n_violations=(~result_df["ok"]).sum(),
                    max_residual=float(residual.abs().max()),
                    mean_residual=float(residual.mean()),
                    tolerance=tol,
                )
            )

        return ValidationReport(
            table=self._root.series.table,
            checks=checks,
            data_start=str(data.index.min()) if not data.empty else "n/a",
            data_end=str(data.index.max()) if not data.empty else "n/a",
        )

    def missing_series(self, data: pd.DataFrame) -> list[str]:
        """List all BEA codes referenced by the tree but absent from data."""
        all_codes = {n.series.code for n in self._root.all_nodes()}
        return sorted(all_codes - set(data.columns))


@dataclass
class ValidationReport:
    table: str
    checks: list[IdentityCheck]
    data_start: str
    data_end: str

    @property
    def n_passed(self) -> int:
        return sum(1 for c in self.checks if c.passed)

    @property
    def n_failed(self) -> int:
        return sum(1 for c in self.checks if not c.passed)

    @property
    def all_passed(self) -> bool:
        return self.n_failed == 0

    def failed_checks(self) -> list[IdentityCheck]:
        return [c for c in self.checks if not c.passed]

    def summary(self) -> str:
        lines = [
            f"\nNIPA Accounting Validation — Table {self.table}",
            f"  Data range : {self.data_start}  to  {self.data_end}",
            f"  Identities : {len(self.checks)} checked  |  "
            f"{self.n_passed} passed  |  {self.n_failed} failed",
            "",
            "  Identity-level results:",
        ]
        for check in self.checks:
            lines.append(str(check))
        if self.all_passed:
            lines.append("\n  [OK] All accounting identities hold within tolerance.")
        else:
            lines.append(
                f"\n  [FAIL] {self.n_failed} identities have residuals exceeding tolerance."
            )
        return "\n".join(lines)

    def __str__(self) -> str:
        return self.summary()

    def to_dataframe(self) -> pd.DataFrame:
        """Return all check results as a tidy DataFrame."""
        return pd.DataFrame(
            [
                {
                    "parent_code": c.parent_code,
                    "parent_name": c.parent_name,
                    "n_periods": c.n_periods,
                    "n_violations": c.n_violations,
                    "max_residual": c.max_residual,
                    "mean_residual": c.mean_residual,
                    "tolerance": c.tolerance,
                    "passed": c.passed,
                }
                for c in self.checks
            ]
        )
