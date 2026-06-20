"""
FRED (Federal Reserve Economic Data) provider — St. Louis Fed.

No API key required for basic access; a free key unlocks higher limits.
Register at https://fred.stlouisfed.org/docs/api/api_key.html

FRED hosts the BEA NIPA series under their own identifiers.  The mapping
below covers the main Table 1.1.5 and 1.1.6 series.  FRED data is
vintaged to the latest BEA release; for real-time vintages use BEA directly.
"""
from __future__ import annotations

import os
from typing import Optional, Sequence

import pandas as pd
import requests

from .base import DataProvider

_FRED_ENDPOINT = "https://api.stlouisfed.org/fred/series/observations"
_DEFAULT_KEY = "annualrevisionkey"   # FRED's public demo key (rate-limited)

# BEA series code → FRED series ID
# fmt: off
FRED_ID_MAP: dict[str, str] = {
    # ── Nominal GDP (Table 1.1.5, billions SAAR) ──────────────────────── #
    "A191RC":  "GDP",          # Gross Domestic Product
    "DPCERC":  "PCE",          # Personal Consumption Expenditures
    "DGDSRC":  "PCND",         # PCE: Goods (durable+nondurable combined in FRED)
    "DDURRC":  "PCDG",         # PCE: Durable Goods
    "DNDGRC":  "PCND",         # PCE: Nondurable Goods
    "DSERRC":  "PCESV",        # PCE: Services
    "A006RC":  "GPDI",         # Gross Private Domestic Investment
    "A007RC":  "FPI",          # Fixed Private Investment
    "A008RC":  "PNFI",         # Nonresidential Fixed Investment
    "A009RC":  "PNFIS",        # Nonres Structures
    "Y033RC":  "PNFIE",        # Nonres Equipment
    "Y001RC":  "PNFII",        # Nonres Intellectual Property
    "A011RC":  "PRFI",         # Residential Fixed Investment
    "A019RC":  "CBI",          # Change in Private Inventories
    "A020RC":  "NETEXP",       # Net Exports
    "A021RC":  "EXPGS",        # Exports of Goods & Services
    "A024RC":  "IMPGS",        # Imports of Goods & Services
    "A822RC":  "GCE",          # Government Consumption & Investment
    "A823RC":  "FGCE",         # Federal Government
    "A829RC":  "SLCE",         # State and Local Government
    # ── Real GDP (Table 1.1.6, billions chained 2017 $) ──────────────── #
    "A191RX":  "GDPC1",        # Real GDP
    "DPCERX":  "PCECC96",      # Real PCE
    "DDURRX":  "PCDGCC96",     # Real PCE Durables
    "DNDGRX":  "PCNDGC96",     # Real PCE Nondurables
    "DSERRX":  "PCESVC96",     # Real PCE Services
    "A006RX":  "GPDIC1",       # Real GPDI
    "A007RX":  "FPIC1",        # Real Fixed Private Investment
    "A008RX":  "PNFIC1",       # Real Nonresidential Fixed Investment
    "A009RX":  "PNFISC1",      # Real Nonres Structures
    "Y033RX":  "PNFIEC1",      # Real Nonres Equipment
    "Y001RX":  "PNFIIC1",      # Real Nonres IP
    "A011RX":  "PRFIC1",       # Real Residential Fixed Investment
    "A019RD":  "CBIC1",        # Real Change in Inventories
    "A020RX":  "NETEXC",       # Real Net Exports
    "A021RX":  "EXPGSC96",     # Real Exports
    "A024RX":  "IMPGSC96",     # Real Imports
    "A822RX":  "GCEC1",        # Real Government Expenditures
    "A823RX":  "FGCEC1",       # Real Federal
    "A829RX":  "SLCEC1",       # Real State & Local
    # ── Personal Income / Disposition (Table 2.1) ─────────────────────── #
    "A065RC":  "PI",           # Personal Income
    "A033RC":  "WASCUR",       # Compensation of Employees
    "A576RC":  "WASEMP",       # Wages and Salaries
    "A067RC":  "DPI",          # Disposable Personal Income
    "A071RC":  "PSAVE",        # Personal Saving
}
# fmt: on

_FREQ_MAP = {"Q": "q", "A": "a", "M": "m"}


class FREDProvider(DataProvider):
    """Fetches NIPA-equivalent data from the St. Louis FRED API."""

    def __init__(
        self,
        api_key: Optional[str] = None,
        verify_ssl: bool = True,
    ) -> None:
        self._key = api_key or os.getenv("FRED_API_KEY", _DEFAULT_KEY)
        self._verify_ssl = verify_ssl
        self._cache: dict[str, pd.Series] = {}

    @property
    def name(self) -> str:
        return "FRED"

    def available(self) -> bool:
        try:
            r = requests.get(
                "https://fred.stlouisfed.org",
                timeout=5,
                verify=self._verify_ssl,
            )
            return r.status_code < 500
        except Exception:
            return False

    def fetch(
        self,
        series_codes: Sequence[str],
        start: Optional[str] = None,
        end: Optional[str] = None,
        frequency: str = "Q",
    ) -> pd.DataFrame:
        freq = _FREQ_MAP.get(frequency, "q")
        cols: dict[str, pd.Series] = {}
        skipped = []

        for code in series_codes:
            fred_id = FRED_ID_MAP.get(code)
            if fred_id is None:
                skipped.append(code)
                continue
            series = self._fetch_series(fred_id, start, end, freq)
            if series is not None:
                cols[code] = series

        if skipped:
            print(f"[FRED] No mapping for: {skipped}")

        if not cols:
            return pd.DataFrame()

        df = pd.DataFrame(cols)
        df.sort_index(inplace=True)
        return df

    def _fetch_series(
        self,
        fred_id: str,
        start: Optional[str],
        end: Optional[str],
        freq: str,
    ) -> Optional[pd.Series]:
        cache_key = f"{fred_id}:{freq}:{start}:{end}"
        if cache_key in self._cache:
            return self._cache[cache_key]

        params: dict[str, str] = {
            "series_id": fred_id,
            "api_key": self._key,
            "file_type": "json",
            "frequency": freq,
            "aggregation_method": "eop",  # end of period
        }
        if start:
            params["observation_start"] = pd.Timestamp(start).strftime("%Y-%m-%d")
        if end:
            params["observation_end"] = pd.Timestamp(end).strftime("%Y-%m-%d")

        try:
            resp = requests.get(
                _FRED_ENDPOINT, params=params, timeout=20, verify=self._verify_ssl
            )
            resp.raise_for_status()
            data = resp.json()
        except Exception as exc:
            print(f"[FRED] Error fetching {fred_id}: {exc}")
            return None

        obs = data.get("observations", [])
        if not obs:
            return None

        records = []
        for o in obs:
            if o["value"] == ".":
                continue
            records.append((pd.Timestamp(o["date"]), float(o["value"])))

        if not records:
            return None

        s = pd.Series(dict(records), name=fred_id)
        s.sort_index(inplace=True)
        self._cache[cache_key] = s
        return s
