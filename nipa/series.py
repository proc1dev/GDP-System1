"""
Core NIPA series descriptor — metadata for a single BEA data series.
"""
from dataclasses import dataclass
from typing import Optional


@dataclass(frozen=True)
class NIPASeries:
    """Immutable descriptor for a single NIPA data series."""

    code: str               # BEA series code, e.g. "A191RC"
    name: str               # Full name as published by BEA
    table: str              # NIPA table number, e.g. "1.1.5"
    line: int               # Line number within the table
    units: str = "Billions of dollars"
    frequency: str = "Q"    # Q=quarterly, A=annual, M=monthly
    seasonal_adj: str = "SAAR"
    is_nominal: bool = True  # False for chained-dollar (real) series
    bbl_ticker: Optional[str] = None  # Bloomberg ticker; None = not yet mapped

    def __str__(self) -> str:
        return f"{self.code}  [{self.table} L{self.line}]  {self.name}"

    @property
    def real_counterpart_code(self) -> Optional[str]:
        """
        Nominal BEA codes end in 'RC'; their real counterparts end in 'RX'.
        Returns None for series that don't follow this convention.
        """
        if self.code.endswith("RC"):
            return self.code[:-2] + "RX"
        return None
