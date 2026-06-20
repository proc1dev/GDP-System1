from .base import DataProvider, FallbackProvider
from .bea import BEAProvider
from .bloomberg import BloombergProvider, BBL_TICKER_MAP
from .fred import FREDProvider, FRED_ID_MAP
from .mock import MockProvider


def default_provider(
    bea_api_key: str | None = None,
    fred_api_key: str | None = None,
    verify_ssl: bool = True,
) -> FallbackProvider:
    """
    Return the standard three-tier provider:
      1. Bloomberg (if blpapi installed and Terminal running)
      2. BEA REST API (if api_key provided via arg or BEA_API_KEY env var)
      3. FRED (no key required for basic access)

    Pass verify_ssl=False to bypass SSL cert verification (Windows dev machines).
    """
    fred = FREDProvider(api_key=fred_api_key, verify_ssl=verify_ssl)
    bea  = BEAProvider(api_key=bea_api_key, verify_ssl=verify_ssl)
    bea_with_fred_fallback = FallbackProvider(primary=bea, secondary=fred)
    return FallbackProvider(
        primary=BloombergProvider(),
        secondary=bea_with_fred_fallback,
    )


__all__ = [
    "DataProvider",
    "FallbackProvider",
    "BEAProvider",
    "BloombergProvider",
    "FREDProvider",
    "MockProvider",
    "BBL_TICKER_MAP",
    "FRED_ID_MAP",
    "default_provider",
]
