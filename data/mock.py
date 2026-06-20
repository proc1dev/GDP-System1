"""
Mock data provider — generates synthetic NIPA data that satisfies all
accounting identities exactly.  Useful for testing the tree structure and
validator without any API keys.

Data is constructed bottom-up: random leaf values are generated, then
parent values are computed from the identities so every residual is zero.
"""
from __future__ import annotations

import random
from typing import Optional, Sequence

import numpy as np
import pandas as pd

from .base import DataProvider
from nipa.node import NIPANode
from nipa.tables import build_T10105, build_T10106


# Rough baseline levels (billions $, 2024 Q4 nominal SAAR)
_LEAF_BASELINES: dict[str, float] = {
    # PCE
    "DDURRC": 2_450.0,   "DNDGRC": 3_750.0,   "DSERRC": 11_600.0,
    # Investment leaves
    "A009RC": 1_050.0,   "Y033RC": 1_650.0,
    "Y002RC": 600.0,     "Y010RC": 760.0,   "A014RC": 90.0,
    "A011RC": 950.0,     "A019RC": 80.0,
    # Net exports leaves
    "A022RC": 1_800.0,   "A023RC": 1_100.0,
    "A025RC": 3_300.0,   "A026RC": 800.0,
    # Government leaves
    "B826RC": 680.0,     "B827RC": 280.0,
    "B831RC": 450.0,     "B832RC": 110.0,
    "A832RC": 2_300.0,   "A833RC": 600.0,
}

# Real series baselines (chained 2017 $, approximately)
_LEAF_BASELINES_REAL: dict[str, float] = {
    "DDURRX": 1_950.0,   "DNDGRX": 3_150.0,   "DSERRX": 10_500.0,
    "A009RX": 920.0,     "Y033RX": 1_540.0,
    "Y002RX": 580.0,     "Y010RX": 710.0,   "A014RX": 80.0,
    "A011RX": 870.0,     "A019RD": 60.0,
    "A022RX": 1_750.0,   "A023RX": 1_000.0,
    "A025RX": 3_100.0,   "A026RX": 770.0,
    "B826RX": 650.0,     "B827RX": 260.0,
    "B831RX": 430.0,     "B832RX": 100.0,
    "A832RX": 2_200.0,   "A833RX": 570.0,
}


class MockProvider(DataProvider):
    """
    Generates synthetic NIPA data obeying all accounting identities.

    Parameters
    ----------
    n_quarters : int  — number of quarterly observations to generate.
    growth_rate : float — mean quarterly growth rate for leaf series (e.g. 0.006).
    noise_std   : float — std dev of idiosyncratic noise added to each leaf.
    seed        : int | None — random seed for reproducibility.
    """

    def __init__(
        self,
        n_quarters: int = 40,
        growth_rate: float = 0.006,
        noise_std: float = 0.008,
        seed: Optional[int] = 42,
    ) -> None:
        self._n = n_quarters
        self._mu = growth_rate
        self._sigma = noise_std
        self._rng = random.Random(seed)
        self._np_rng = np.random.default_rng(seed)

    @property
    def name(self) -> str:
        return "Mock"

    def available(self) -> bool:
        return True

    def fetch(
        self,
        series_codes: Sequence[str],
        start: Optional[str] = None,
        end: Optional[str] = None,
        frequency: str = "Q",
    ) -> pd.DataFrame:
        # Determine date range
        end_ts   = pd.Timestamp(end) if end else (pd.Timestamp.now().to_period("Q") - 1).to_timestamp("Q")
        start_ts = (
            pd.Timestamp(start)
            if start
            else end_ts - pd.DateOffset(months=3 * (self._n - 1))
        )
        dates = pd.date_range(start_ts, end_ts, freq="QE")

        nominal_tree = build_T10105()
        real_tree    = build_T10106()

        data = pd.DataFrame(index=dates)

        # Generate nominal series
        nom_data = self._build_tree_data(nominal_tree, _LEAF_BASELINES, dates)
        for code, series in nom_data.items():
            if code in series_codes:
                data[code] = series

        # Generate real series
        real_data = self._build_tree_data(real_tree, _LEAF_BASELINES_REAL, dates)
        for code, series in real_data.items():
            if code in series_codes:
                data[code] = series

        return data.dropna(axis=1, how="all")

    def _build_tree_data(
        self,
        root: NIPANode,
        leaf_baselines: dict[str, float],
        dates: pd.DatetimeIndex,
    ) -> dict[str, pd.Series]:
        n = len(dates)

        # Generate leaf series with random walk
        leaf_data: dict[str, pd.Series] = {}
        for node in root.leaves():
            code = node.series.code
            baseline = leaf_baselines.get(code, 100.0)
            # Random walk: level_t = level_{t-1} * (1 + mu + eps_t)
            growth = self._np_rng.normal(self._mu, self._sigma, size=n)
            level = np.empty(n)
            level[0] = baseline
            for t in range(1, n):
                level[t] = level[t - 1] * (1.0 + growth[t])
            leaf_data[code] = pd.Series(level, index=dates, name=code)

        # Compute parent values bottom-up so identities hold exactly
        all_data: dict[str, pd.Series] = dict(leaf_data)

        def _fill(node: NIPANode) -> pd.Series:
            if node.series.code in all_data:
                return all_data[node.series.code]
            total = None
            for child, sign in node.children:
                child_series = _fill(child)
                total = sign * child_series if total is None else total + sign * child_series
            all_data[node.series.code] = total
            return total

        _fill(root)
        return all_data
