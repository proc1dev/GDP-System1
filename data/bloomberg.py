"""
Bloomberg blpapi provider for NIPA data.

Requires a running Bloomberg Terminal or B-PIPE connection and the
`blpapi` Python package (pip install blpapi --index-url
https://blp.bintray.com/pip/simple/).

The provider maps BEA series codes → Bloomberg tickers using the
`bbl_ticker` field stored on each NIPASeries, supplemented by the
catalog below.  When a code has no ticker mapping it is silently skipped
(the BEA provider handles it as fallback).

Bloomberg reference fields used:
    PX_LAST      — latest value (for spot/current reads)
    LAST_UPDATE  — date of latest value
For time-series bulk pulls we use the BDH (historical data) call:
    fields: ["PX_LAST"]
    overrides: PERIODICITY_SELECTION = Q / M / A
"""
from __future__ import annotations

from typing import Optional, Sequence

import pandas as pd

from .base import DataProvider

# ── Optional import — graceful degradation if blpapi not installed ──────── #
try:
    import blpapi  # type: ignore
    _BLPAPI_AVAILABLE = True
except ImportError:
    _BLPAPI_AVAILABLE = False

# --------------------------------------------------------------------------- #
# Ticker catalog
# BEA series code → Bloomberg ticker
# Values come from the bbl_ticker field in NIPASeries definitions in tables.py
# and are extended here for coverage.  Verify against your Bloomberg instance.
# --------------------------------------------------------------------------- #
BBL_TICKER_MAP: dict[str, str] = {
    # ── Headline GDP ─────────────────────────────────────────────────────── #
    "A191RC": "GDP CUR$ Index",      # Nominal GDP level (BEA, $B SAAR)
    "A191RX": "GDP CHNG Index",      # Real GDP QoQ change (BEA, chained $)
    # ── PCE ──────────────────────────────────────────────────────────────── #
    "DPCERC": "PCE CUR$ Index",      # Nominal PCE level
    "DPCERX": "PCE CHNG Index",      # Real PCE change
    "DDURRC": "PCE DUR$ Index",      # Nominal durable goods PCE
    "DNDGRC": "PCE NDG$ Index",      # Nominal nondurable goods PCE
    "DSERRC": "PCE SVC$ Index",      # Nominal services PCE
    # ── Investment ───────────────────────────────────────────────────────── #
    "A006RC": "GPDI CUR$ Index",     # Gross private domestic investment
    "A007RC": "GFDI CUR$ Index",     # Gross fixed domestic investment
    "A008RC": "GNRI CUR$ Index",     # Nonresidential fixed investment
    "A011RC": "GRRI CUR$ Index",     # Residential fixed investment
    # ── Net Exports ──────────────────────────────────────────────────────── #
    "A020RC": "NETX CUR$ Index",     # Net exports
    "A021RC": "GEXP CUR$ Index",     # Exports
    "A024RC": "GIMP CUR$ Index",     # Imports
    # ── Government ───────────────────────────────────────────────────────── #
    "A822RC": "GGCE CUR$ Index",     # Government consumption & investment
    "A823RC": "GFCE CUR$ Index",     # Federal government
    "A829RC": "GSLCE CUR$ Index",    # State and local government
    # ── Income / PI ──────────────────────────────────────────────────────── #
    "A065RC": "PERS INC$ Index",     # Personal income
    "A067RC": "DPI CUR$ Index",      # Disposable personal income
    "A071RC": "PERS SAV$ Index",     # Personal saving
}


class BloombergProvider(DataProvider):
    """
    Fetches NIPA data from Bloomberg Terminal via blpapi.

    Usage
    -----
    provider = BloombergProvider()
    df = provider.fetch(["A191RC", "DPCERC"], start="2000-01-01")
    """

    _FREQ_OVERRIDE = {"Q": "QUARTERLY", "A": "ANNUAL", "M": "MONTHLY"}

    def __init__(
        self,
        host: str = "localhost",
        port: int = 8194,
        ticker_map: Optional[dict[str, str]] = None,
    ) -> None:
        self._host = host
        self._port = port
        self._ticker_map: dict[str, str] = {**BBL_TICKER_MAP, **(ticker_map or {})}
        self._session: Optional[object] = None

    @property
    def name(self) -> str:
        return "Bloomberg"

    def available(self) -> bool:
        if not _BLPAPI_AVAILABLE:
            print("[Bloomberg] blpapi not installed or import failed.")
            return False
        try:
            session = self._get_session()
            return session is not None
        except Exception as e:
            print(f"[Bloomberg] available() failed: {type(e).__name__}: {e}")
            return False

    def close(self) -> None:
        """Cleanly stop the Bloomberg session."""
        if self._session is not None:
            try:
                self._session.stop()
            except Exception:
                pass
            self._session = None

    def add_ticker(self, bea_code: str, bbl_ticker: str) -> None:
        """Register an additional BEA code → Bloomberg ticker mapping."""
        self._ticker_map[bea_code] = bbl_ticker

    # ------------------------------------------------------------------ #
    # Public interface
    # ------------------------------------------------------------------ #

    def fetch_by_ticker(
        self,
        tickers: Sequence[str],
        field: str = "PX_LAST",
        start: Optional[str] = None,
        end: Optional[str] = None,
        frequency: str = "Q",
    ) -> pd.DataFrame:
        """Fetch historical data using Bloomberg tickers directly (no BEA mapping)."""
        if not _BLPAPI_AVAILABLE:
            raise RuntimeError("blpapi not installed.")
        session = self._get_session()
        return self._bdh(
            tickers=list(tickers),
            field=field,
            start=start or "1947-01-01",
            end=end,
            frequency=frequency,
            session=session,
        )

    def fetch_metadata(self, tickers: Sequence[str]) -> dict[str, dict[str, str]]:
        """BDP call — returns reference data for series_info auto-population.

        Returns {ticker: {"NAME": ..., "CRNCY": ..., ...}}
        """
        if not _BLPAPI_AVAILABLE:
            raise RuntimeError("blpapi not installed.")
        fields = ["NAME", "CRNCY", "MARKET_SECTOR_DES", "PERIODICITY_SELECTION", "UNIT_OF_MEASURE", "DATA_SOURCE"]
        session = self._get_session()
        return self._bdp(list(tickers), fields, session)

    def fetch(
        self,
        series_codes: Sequence[str],
        start: Optional[str] = None,
        end: Optional[str] = None,
        frequency: str = "Q",
    ) -> pd.DataFrame:
        if not _BLPAPI_AVAILABLE:
            raise RuntimeError(
                "blpapi not installed. Run: pip install blpapi "
                "--index-url https://blp.bintray.com/pip/simple/"
            )

        # Map BEA codes → Bloomberg tickers; skip unmapped
        ticker_to_code: dict[str, str] = {}
        skipped = []
        for code in series_codes:
            ticker = self._ticker_map.get(code)
            if ticker:
                ticker_to_code[ticker] = code
            else:
                skipped.append(code)
        if skipped:
            print(f"[Bloomberg] No ticker mapping for: {skipped}. "
                  "Use provider.add_ticker() to register them.")

        if not ticker_to_code:
            return pd.DataFrame()

        session = self._get_session()
        raw = self._bdh(
            tickers=list(ticker_to_code.keys()),
            field="PX_LAST",
            start=start or "1947-01-01",
            end=end,
            frequency=frequency,
            session=session,
        )
        # Rename columns from Bloomberg ticker → BEA code
        raw.rename(columns=ticker_to_code, inplace=True)
        return raw

    # ------------------------------------------------------------------ #
    # blpapi internals
    # ------------------------------------------------------------------ #

    def _get_session(self):
        if self._session is not None:
            return self._session
        options = blpapi.SessionOptions()
        options.setServerHost(self._host)
        options.setServerPort(self._port)
        session = blpapi.Session(options)
        if not session.start():
            raise ConnectionError(
                f"Cannot connect to Bloomberg at {self._host}:{self._port}. "
                "Ensure Bloomberg Terminal is running."
            )
        session.openService("//blp/refdata")
        self._session = session
        return session

    def _bdh(
        self,
        tickers: list[str],
        field: str,
        start: str,
        end: Optional[str],
        frequency: str,
        session,
    ) -> pd.DataFrame:
        """Bloomberg BDH (historical data) request."""
        refDataService = session.getService("//blp/refdata")
        request = refDataService.createRequest("HistoricalDataRequest")

        for ticker in tickers:
            request.getElement("securities").appendValue(ticker)
        request.getElement("fields").appendValue(field)

        request.set("startDate", pd.Timestamp(start).strftime("%Y%m%d"))
        if end:
            request.set("endDate", pd.Timestamp(end).strftime("%Y%m%d"))
        request.set(
            "periodicitySelection",
            self._FREQ_OVERRIDE.get(frequency, "QUARTERLY"),
        )
        request.set("adjustmentNormal", True)

        session.sendRequest(request)

        records: list[dict] = []
        while True:
            ev = session.nextEvent(500)
            for msg in ev:
                if msg.hasElement("securityData"):
                    sec_data = msg.getElement("securityData")
                    ticker = sec_data.getElementAsString("security")
                    field_data = sec_data.getElement("fieldData")
                    for i in range(field_data.numValues()):
                        fv = field_data.getValue(i)
                        date = fv.getElementAsDatetime("date")
                        val  = fv.getElementAsFloat(field)
                        records.append({
                            "date": pd.Timestamp(date.year, date.month, date.day),
                            "ticker": ticker,
                            "value": val,
                        })
            if ev.eventType() == blpapi.Event.RESPONSE:
                break

        if not records:
            return pd.DataFrame()

        df = pd.DataFrame(records)
        wide = df.pivot(index="date", columns="ticker", values="value")
        wide.columns.name = None
        wide.sort_index(inplace=True)
        return wide

    def _bdp(
        self,
        tickers: list[str],
        fields: list[str],
        session,
    ) -> dict[str, dict[str, str]]:
        """Bloomberg BDP (reference data) request."""
        refDataService = session.getService("//blp/refdata")
        request = refDataService.createRequest("ReferenceDataRequest")

        for ticker in tickers:
            request.getElement("securities").appendValue(ticker)
        for field in fields:
            request.getElement("fields").appendValue(field)

        session.sendRequest(request)

        result: dict[str, dict[str, str]] = {t: {} for t in tickers}
        while True:
            ev = session.nextEvent(500)
            for msg in ev:
                if msg.hasElement("securityData"):
                    sec_array = msg.getElement("securityData")
                    for i in range(sec_array.numValues()):
                        sec = sec_array.getValue(i)
                        ticker = sec.getElementAsString("security")
                        field_data = sec.getElement("fieldData")
                        for field in fields:
                            if field_data.hasElement(field):
                                result[ticker][field] = field_data.getElementAsString(field)
            if ev.eventType() == blpapi.Event.RESPONSE:
                break

        return result
