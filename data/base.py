"""
Abstract DataProvider interface.

All concrete providers (Bloomberg, BEA, FRED, etc.) implement this protocol
so the rest of the system never touches provider-specific APIs directly.
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Optional, Sequence

import pandas as pd


class DataProvider(ABC):
    """Fetch NIPA time-series data into a tidy DataFrame."""

    @abstractmethod
    def fetch(
        self,
        series_codes: Sequence[str],
        start: Optional[str] = None,
        end: Optional[str] = None,
        frequency: str = "Q",
    ) -> pd.DataFrame:
        """
        Retrieve one or more series.

        Parameters
        ----------
        series_codes : BEA series codes, e.g. ["A191RC", "DPCERC"].
        start        : ISO date string, e.g. "2000-01-01". None = all history.
        end          : ISO date string. None = latest available.
        frequency    : "Q" quarterly | "A" annual | "M" monthly.

        Returns
        -------
        DataFrame indexed by period-end date (pd.Period or pd.Timestamp),
        columns = series codes, values in billions of dollars SAAR.
        Missing series columns are NaN.
        """

    @abstractmethod
    def available(self) -> bool:
        """Return True if the provider can be reached right now."""

    @property
    @abstractmethod
    def name(self) -> str:
        """Short label for logging, e.g. 'Bloomberg' or 'BEA'."""


class FallbackProvider(DataProvider):
    """
    Try a primary provider; fall back to secondary on failure.

    This is the main entry point used by the rest of the system.
    """

    def __init__(self, primary: DataProvider, secondary: DataProvider) -> None:
        self._primary = primary
        self._secondary = secondary

    @property
    def name(self) -> str:
        return f"{self._primary.name} → {self._secondary.name}"

    def available(self) -> bool:
        return self._primary.available() or self._secondary.available()

    def fetch(
        self,
        series_codes: Sequence[str],
        start: Optional[str] = None,
        end: Optional[str] = None,
        frequency: str = "Q",
    ) -> pd.DataFrame:
        if self._primary.available():
            try:
                return self._primary.fetch(series_codes, start, end, frequency)
            except Exception as exc:
                print(f"[{self._primary.name}] fetch failed: {exc}. Trying {self._secondary.name}.")
        return self._secondary.fetch(series_codes, start, end, frequency)
