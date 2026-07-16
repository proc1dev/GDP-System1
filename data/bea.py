"""
BEA REST API provider.

Free access — no authentication required for most NIPA tables.
An API key unlocks higher rate limits; set it via BEA_API_KEY env var
or pass it to the constructor.

BEA NIPA GetData endpoint:
    https://apps.bea.gov/api/data/?method=GetData
        &datasetname=NIPA
        &TableName=T10105       ← BEA table ID (T + digits)
        &Frequency=Q
        &Year=ALL
        &ResultFormat=JSON
        [&UserID=YOUR_KEY]

Note: The BEA API returns data by table, not by individual series code.
This provider fetches the whole table and returns the requested codes.
"""
from __future__ import annotations

import os
from typing import Optional, Sequence

import pandas as pd
import requests
import truststore

truststore.inject_into_ssl()

from .base import DataProvider

_BEA_ENDPOINT = "https://apps.bea.gov/api/data/"
_DEFAULT_KEY = ""  # register free at https://apps.bea.gov/API/signup/

# BEA series code → table name (needed because BEA API is table-centric)
# Add entries here as more series are needed.
_CODE_TO_TABLE: dict[str, str] = {
    # Table 1.1.5 — Nominal GDP
    "A191RC": "T10105", "DPCERC": "T10105", "DGDSRC": "T10105",
    "DDURRC": "T10105", "DNDGRC": "T10105", "DSERRC": "T10105",
    "A006RC": "T10105", "A007RC": "T10105", "A008RC": "T10105",
    "A009RC": "T10105", "Y033RC": "T10105", "Y001RC": "T10105",
    "Y002RC": "T10105", "Y010RC": "T10105", "A014RC": "T10105",
    "A011RC": "T10105", "A019RC": "T10105", "A020RC": "T10105",
    "A021RC": "T10105", "A022RC": "T10105", "A023RC": "T10105",
    "A024RC": "T10105", "A025RC": "T10105", "A026RC": "T10105",
    "A822RC": "T10105", "A823RC": "T10105", "B823RC": "T10105",
    "B826RC": "T10105", "B827RC": "T10105", "B828RC": "T10105",
    "B831RC": "T10105", "B832RC": "T10105", "A829RC": "T10105",
    "A832RC": "T10105", "A833RC": "T10105",
    # Table 1.1.6 — Real GDP
    "A191RX": "T10106", "DPCERX": "T10106", "DGDSRX": "T10106",
    "DDURRX": "T10106", "DNDGRX": "T10106", "DSERRX": "T10106",
    "A006RX": "T10106", "A007RX": "T10106", "A008RX": "T10106",
    "A009RX": "T10106", "Y033RX": "T10106", "Y001RX": "T10106",
    "Y002RX": "T10106", "Y010RX": "T10106", "A014RX": "T10106",
    "A011RX": "T10106", "A019RD": "T10106", "A020RX": "T10106",
    "A021RX": "T10106", "A022RX": "T10106", "A023RX": "T10106",
    "A024RX": "T10106", "A025RX": "T10106", "A026RX": "T10106",
    "A822RX": "T10106", "A823RX": "T10106", "B823RX": "T10106",
    "B826RX": "T10106", "B827RX": "T10106", "B828RX": "T10106",
    "B831RX": "T10106", "B832RX": "T10106", "A829RX": "T10106",
    "A832RX": "T10106", "A833RX": "T10106",
    # Table 1.7.5 — Income bridge
    "A017RC": "T10705", "B015RC": "T10705", "A032RC": "T10705",
    "A065RC": "T10705", "A067RC": "T10705", "A071RC": "T10705",
    "A072RC": "T10705", "A073RC": "T10705",
    # Table 2.1 — Personal Income
    "A033RC": "T20100", "A576RC": "T20100", "A038RC": "T20100",
    "A041RC": "T20100", "A045RC": "T20100", "A048RC": "T20100",
    "A048RC1": "T20100", "A064RCB": "T20100", "B054RC": "T20100",
    "A064RC": "T20100", "A063RCB": "T20100", "A063RC1": "T20100",
    "A063RC2": "T20100", "A063RC3": "T20100", "W825RC": "T20100",
    "A061RC1": "T20100",
}

_FREQ_MAP = {"Q": "Q", "A": "A", "M": "M"}


class BEAProvider(DataProvider):
    """Fetches NIPA data from the BEA's public REST API."""

    def __init__(
        self,
        api_key: Optional[str] = None,
        verify_ssl: bool = True,
    ) -> None:
        self._key = api_key or os.getenv("BEA_API_KEY", _DEFAULT_KEY)
        self._verify_ssl = verify_ssl
        self._cache: dict[tuple, pd.DataFrame] = {}
        self._catalog: Optional[dict[str, tuple[str, str]]] = None

    @property
    def name(self) -> str:
        return "BEA"

    def available(self) -> bool:
        try:
            r = requests.get(
                _BEA_ENDPOINT,
                params={"method": "GetDataSetList", "ResultFormat": "JSON"},
                timeout=5,
                verify=self._verify_ssl,
            )
            return r.status_code == 200
        except Exception:
            return False

    # ------------------------------------------------------------------ #
    # Public interface
    # ------------------------------------------------------------------ #

    def fetch(
        self,
        series_codes: Sequence[str],
        start: Optional[str] = None,
        end: Optional[str] = None,
        frequency: str = "Q",
    ) -> pd.DataFrame:
        """Fetch series by BEA series code. Groups requests by table."""
        bea_freq = _FREQ_MAP.get(frequency, "Q")

        # Group requested codes by table
        by_table: dict[str, list[str]] = {}
        for code in series_codes:
            table = _CODE_TO_TABLE.get(code)
            if table is None:
                print(f"[BEA] Unknown table for series {code!r} — skipping.")
                continue
            by_table.setdefault(table, []).append(code)

        frames: list[pd.DataFrame] = []
        for table_id, codes in by_table.items():
            df_table = self._fetch_table(table_id, bea_freq)
            if df_table.empty:
                continue
            # Keep only the requested codes that exist in this table
            keep = [c for c in codes if c in df_table.columns]
            frames.append(df_table[keep])

        if not frames:
            return pd.DataFrame()

        result = pd.concat(frames, axis=1)
        result.sort_index(inplace=True)

        if start:
            result = result.loc[result.index >= pd.Timestamp(start)]
        if end:
            result = result.loc[result.index <= pd.Timestamp(end)]

        return result

    # ------------------------------------------------------------------ #
    # Table catalog + line-level structure (SeriesCode/LineNumber/LineDescription)
    # ------------------------------------------------------------------ #

    def table_catalog(self) -> dict[str, tuple[str, str]]:
        """
        Authoritative BEA table-number -> (TableName id, full description) map,
        e.g. "1.1.5" -> ("T10105", "Table 1.1.5. Gross Domestic Product (A) (Q)").

        Built from GetParameterValues rather than a guessed padding formula --
        some table numbers don't follow the naive "pad each segment to 2
        digits" rule (e.g. "1.10" -> T11000, not T10100).
        """
        if self._catalog is not None:
            return self._catalog

        import re

        params = {
            "UserID": self._key,
            "method": "GetParameterValues",
            "datasetname": "NIPA",
            "ParameterName": "TableName",
            "ResultFormat": "JSON",
        }
        resp = requests.get(_BEA_ENDPOINT, params=params, timeout=30, verify=self._verify_ssl)
        resp.raise_for_status()
        vals = resp.json()["BEAAPI"]["Results"]["ParamValue"]

        catalog: dict[str, tuple[str, str]] = {}
        for v in vals:
            m = re.match(r"Table ([\d.]+)\.", v["Description"])
            if m:
                catalog[m.group(1)] = (v["TableName"], v["Description"])

        self._catalog = catalog
        return catalog

    def table_id_for_number(self, table_number: str) -> Optional[str]:
        """Look up a BEA TableName id from a table number like '1.1.5'. None if unknown."""
        entry = self.table_catalog().get(table_number)
        return entry[0] if entry else None

    def get_line_metadata(self, table_id: str, frequency: str = "Q") -> list[dict]:
        """
        Return the ordered, deduplicated line structure for a BEA table:
        [{"line_number": int, "series_code": str, "description": str, "is_subtraction": bool}, ...]

        Uses a single recent year (line structure doesn't vary by period within
        a vintage) rather than the full history used by _fetch_table.
        """
        params = {
            "UserID": self._key,
            "method": "GetData",
            "datasetname": "NIPA",
            "TableName": table_id,
            "Frequency": frequency,
            "Year": "2023",
            "ResultFormat": "JSON",
        }
        resp = requests.get(_BEA_ENDPOINT, params=params, timeout=30, verify=self._verify_ssl)
        resp.raise_for_status()
        payload = resp.json()

        try:
            rows = payload["BEAAPI"]["Results"]["Data"]
        except (KeyError, TypeError):
            return []

        seen: dict[str, dict] = {}
        for row in rows:
            code = row.get("SeriesCode")
            if code and code not in seen:
                desc = row["LineDescription"]
                seen[code] = {
                    "line_number": int(row["LineNumber"]),
                    "series_code": code,
                    "description": desc,
                    "is_subtraction": desc.strip().lower().startswith("less:"),
                }

        return sorted(seen.values(), key=lambda r: r["line_number"])

    # ------------------------------------------------------------------ #
    # Internal: fetch a whole table and parse it
    # ------------------------------------------------------------------ #

    def _fetch_table(self, table_id: str, frequency: str) -> pd.DataFrame:
        cache_key = (table_id, frequency)
        if cache_key in self._cache:
            return self._cache[cache_key]

        params = {
            "UserID": self._key,
            "method": "GetData",
            "datasetname": "NIPA",
            "TableName": table_id,
            "Frequency": frequency,
            "Year": "ALL",
            "ResultFormat": "JSON",
        }
        try:
            resp = requests.get(_BEA_ENDPOINT, params=params, timeout=30,
                                verify=self._verify_ssl)
            resp.raise_for_status()
            payload = resp.json()
        except Exception as exc:
            print(f"[BEA] API error for {table_id}: {exc}")
            return pd.DataFrame()

        df = self._parse_response(payload)
        self._cache[cache_key] = df
        return df

    def _parse_response(self, payload: dict) -> pd.DataFrame:
        """Parse the BEA JSON response into a wide DataFrame."""
        try:
            rows = payload["BEAAPI"]["Results"]["Data"]
        except (KeyError, TypeError):
            err_block = payload.get("BEAAPI", {}).get("Results", {}).get("Error", {})
            code = err_block.get("APIErrorCode", "?")
            desc = err_block.get("APIErrorDescription", "unknown error")
            if code == "1" and "UserId" in desc:
                print(
                    "[BEA] API key required. Register free at "
                    "https://apps.bea.gov/API/signup/ then pass "
                    "BEAProvider(api_key='YOUR_KEY') or set BEA_API_KEY env var."
                )
            else:
                print(f"[BEA] API error {code}: {desc}")
            return pd.DataFrame()

        records = []
        for row in rows:
            try:
                date_str = row["TimePeriod"]         # e.g. "2023Q3"
                code     = row["SeriesCode"]
                value    = row["DataValue"].replace(",", "")
                records.append((date_str, code, float(value)))
            except (KeyError, ValueError):
                continue

        if not records:
            return pd.DataFrame()

        raw = pd.DataFrame(records, columns=["period", "code", "value"])
        raw["date"] = raw["period"].apply(self._parse_period)
        wide = raw.pivot_table(index="date", columns="code", values="value",
                               aggfunc="last")
        wide.columns.name = None
        wide.sort_index(inplace=True)
        return wide

    @staticmethod
    def _parse_period(period_str: str) -> pd.Timestamp:
        """Convert BEA period strings like '2023Q3', '2023', '2023M03'."""
        s = period_str.strip()
        if "Q" in s:
            year, q = s.split("Q")
            month = int(q) * 3
            return pd.Timestamp(year=int(year), month=month, day=1)
        if "M" in s:
            year, m = s.split("M")
            return pd.Timestamp(year=int(year), month=int(m), day=1)
        return pd.Timestamp(year=int(s), month=12, day=31)

    def get_release_dates(self, table_id: str = "T10105") -> list[str]:
        """Return a list of available vintage dates for a table (if supported)."""
        params = {
            "UserID": self._key,
            "method": "GetData",
            "datasetname": "NIUnderlyingDetail",
            "TableName": table_id,
            "Frequency": "Q",
            "Year": "ALL",
            "ResultFormat": "JSON",
        }
        # BEA vintage data is in a different dataset; return placeholder
        return []
