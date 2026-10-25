"""Versioned, explicit board routing. Never infer a board from a ticker suffix."""
from enum import Enum
from types import MappingProxyType

from .base import ProviderMetadata
from .twse import TWSEStockDayAllAdapter
from .tpex import TPEXDailyCloseAdapter


class Market(str, Enum):
    TWSE = "TWSE"
    TPEX = "TPEX"


REGISTRY_VERSION = "taiwan-market-sources-v1"
TWSE_HISTORY_URL = "https://www.twse.com.tw/rwd/zh/afterTrading/STOCK_DAY"
TPEX_HISTORY_URL = "https://www.tpex.org.tw/www/zh-tw/afterTrading/tradingStock"
TWSE_CALENDAR_URL = "https://www.twse.com.tw/rwd/zh/holidaySchedule/holidaySchedule"
TPEX_CALENDAR_URL = "https://www.tpex.org.tw/www/zh-tw/bulletin/tradingDate"

HISTORICAL_SOURCES = MappingProxyType({
    Market.TWSE: ProviderMetadata(
        provider_id="twse-stock-day-history", source="TWSE_HISTORY",
        schema_version="1.0", evidence_types=("OHLCV",), source_priority=1,
        history_mode="HISTORICAL", endpoint=TWSE_HISTORY_URL,
    ),
    Market.TPEX: ProviderMetadata(
        provider_id="tpex-trading-stock-history", source="TPEX_HISTORY",
        schema_version="1.0", evidence_types=("OHLCV",), source_priority=1,
        history_mode="HISTORICAL", endpoint=TPEX_HISTORY_URL,
    ),
})
LATEST_SOURCES = MappingProxyType({
    Market.TWSE: TWSEStockDayAllAdapter.metadata,
    Market.TPEX: TPEXDailyCloseAdapter.metadata,
})
CALENDAR_SOURCES = MappingProxyType({
    Market.TWSE: TWSE_CALENDAR_URL, Market.TPEX: TPEX_CALENDAR_URL,
})
ACTION_SOURCES = MappingProxyType({
    Market.TWSE: ("TWSE_OPENAPI", "TWSE_ARCHIVE"),
    Market.TPEX: ("TPEX_OPENAPI", "TPEX_ARCHIVE"),
})


def resolve_ohlcv_source(market: Market, *, history_mode: str) -> ProviderMetadata:
    market = Market(market)  # Unknown boards fail instead of falling back to TWSE.
    if history_mode == "HISTORICAL":
        return HISTORICAL_SOURCES[market]
    if history_mode == "LATEST_ONLY":
        return LATEST_SOURCES[market]
    raise ValueError("unknown history mode")


def require_historical_source(market: Market, metadata: ProviderMetadata) -> None:
    if metadata != resolve_ohlcv_source(market, history_mode="HISTORICAL"):
        raise ValueError("historical bootstrap requires the registered board-specific source")


def official_latest_fallback_for(metadata: ProviderMetadata):
    """Return the same-board official daily source for a one-session fallback."""
    from .tpex import TPEXDailyCloseAdapter
    from .twse import TWSEStockDayAllAdapter

    if metadata == HISTORICAL_SOURCES[Market.TWSE]:
        return TWSEStockDayAllAdapter()
    if metadata == HISTORICAL_SOURCES[Market.TPEX]:
        return TPEXDailyCloseAdapter()
    return None
