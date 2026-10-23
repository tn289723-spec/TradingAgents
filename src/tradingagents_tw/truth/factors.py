"""Point-in-time factor contract; unknown terms and unsupported events block.

Exchange reference formula (unrounded, multiplicative research basis):
https://www.twse.com.tw/zh/announcement/ex-right/twt49u.html
https://www.tpex.org.tw/zh-tw/about/company/faq.html
This is not a tick-rounded executable order price or a total-return series.
"""
from datetime import date, datetime
from decimal import Decimal, InvalidOperation, localcontext
import re
from typing import Literal

from tradingagents_tw.contracts import CorporateAction, CorporateActionType, Evidence, EvidenceStatus, StrictModel
from tradingagents_tw.providers.registry import ACTION_SOURCES, HISTORICAL_SOURCES, Market
from .calendar import TradingCalendar, PostMarketPolicy
from .corporate_actions import BACK_ADJUSTMENT_METHOD
from .point_in_time import assert_point_in_time

FACTOR_VERSION = "official-reference-factor-v1"


class ActionCoverage(StrictModel):
    version: Literal["historical-action-coverage-v1"] = "historical-action-coverage-v1"
    market: Market
    start_date: date
    end_date: date
    announcement_ids: tuple[str, ...]


class DerivedFactor(StrictModel):
    version: Literal["official-reference-factor-v1"] = FACTOR_VERSION
    action: CorporateAction
    reference_price: Decimal
    announcement_id: str
    announcement_revision: str
    announcement_hash: str
    previous_close_id: str
    previous_close_revision: str
    previous_close_hash: str


def _verified(evidence: Evidence, cutoff: datetime):
    if evidence.status is not EvidenceStatus.VERIFIED or evidence.schema_version != "1.0":
        raise ValueError("factor derivation requires verified evidence with a supported schema")
    if not re.fullmatch(r"[0-9a-f]{64}", evidence.content_hash):
        raise ValueError("factor evidence content hash must be SHA-256")
    assert_point_in_time(evidence, cutoff)


def validate_action_coverage(coverage: Evidence, announcements: tuple[Evidence, ...], *,
                             market: Market, symbol: str, start: date, end: date,
                             cutoff: datetime) -> None:
    _verified(coverage, cutoff)
    if (coverage.evidence_type != "CORPORATE_ACTION_COVERAGE" or coverage.symbol != symbol
            or coverage.source != f"{market.value}_ARCHIVE"):
        raise ValueError("historical action coverage requires a board-specific archive manifest")
    window = ActionCoverage.model_validate(coverage.payload)
    if window.market is not market or not window.start_date <= start <= end <= window.end_date:
        raise ValueError("corporate action coverage does not cover the price window")
    ids = tuple(sorted(a.evidence_id for a in announcements))
    if window.announcement_ids != tuple(sorted(set(window.announcement_ids))) or ids != window.announcement_ids:
        raise ValueError("corporate action manifest is incomplete or duplicated")
    event_dates = set()
    for announcement in announcements:
        _verified(announcement, cutoff)
        if (announcement.symbol != symbol or announcement.evidence_type != "CORPORATE_ACTION"
                or announcement.source not in ACTION_SOURCES[market]):
            raise ValueError("corporate action source/symbol mismatch")
        event = date.fromisoformat(announcement.payload["event_date"])
        if not start < event <= end or event in event_dates:
            raise ValueError("corporate action outside window or ambiguous same-day actions")
        event_dates.add(event)


def _decimal(value) -> Decimal:
    if value is None or isinstance(value, bool):
        raise ValueError("pending corporate action terms cannot be treated as zero")
    try:
        result = Decimal(str(value))
    except InvalidOperation as exc:
        raise ValueError("invalid corporate action number") from exc
    if not result.is_finite() or result < 0:
        raise ValueError("corporate action values must be finite and nonnegative")
    return result


def derive_adjustment_factor(announcement: Evidence, previous_close: Evidence, *,
                             calendar: TradingCalendar, cutoff: datetime,
                             as_of: date) -> DerivedFactor:
    for e in (announcement, previous_close):
        _verified(e, cutoff)
    market = calendar.market
    PostMarketPolicy().require_finalized(calendar, as_of, cutoff)
    if (announcement.evidence_type != "CORPORATE_ACTION" or announcement.source not in ACTION_SOURCES[market]
            or previous_close.evidence_type != "OHLCV" or previous_close.source != HISTORICAL_SOURCES[market].source
            or announcement.symbol != previous_close.symbol or not announcement.symbol):
        raise ValueError("factor input source/symbol/type mismatch")
    terms, price = announcement.payload, previous_close.payload
    event = date.fromisoformat(terms["event_date"])
    if event > as_of or not calendar.is_session(event, cutoff=cutoff):
        raise ValueError("action is not effective on a covered trading session")
    preceding = calendar.previous_session(event, cutoff=cutoff)
    if (price.get("price_basis") != "RAW" or price.get("market") != market.value
            or date.fromisoformat(price["trade_date"]) != preceding):
        raise ValueError("factor requires the immediately preceding session's RAW close")
    expected_kind = {
        "息": CorporateActionType.DIVIDEND, "除息": CorporateActionType.DIVIDEND,
        "權": CorporateActionType.STOCK_DIVIDEND, "除權": CorporateActionType.STOCK_DIVIDEND,
        "權息": CorporateActionType.STOCK_DIVIDEND, "除權息": CorporateActionType.STOCK_DIVIDEND,
    }
    if terms.get("event_kind") not in expected_kind or terms.get("adjustment_factor") is not None:
        raise ValueError("unsupported event or untrusted precomputed adjustment factor")
    close = _decimal(price["close"])
    cash = _decimal(terms.get("cash_dividend"))
    stock = _decimal(terms.get("stock_dividend_ratio"))
    rights = _decimal(terms.get("subscription_ratio"))
    subscription = _decimal(terms.get("subscription_price_per_share"))
    ratio_unit = terms.get("ratio_unit")
    if ratio_unit not in (None, "PERCENT", "PER_SHARE"):
        raise ValueError("unsupported corporate action ratio unit")
    if (stock or rights) and ratio_unit is None:
        raise ValueError("nonzero allocation ratios require explicit units")
    if close <= 0 or cash >= close:
        raise ValueError("invalid pre-event close or cash distribution")
    with localcontext() as ctx:
        ctx.prec = 34
        if ratio_unit == "PERCENT":
            stock, rights = stock / 100, rights / 100
        if not (cash or stock or rights) or (not rights and subscription):
            raise ValueError("empty or inconsistent action terms")
        if terms["event_kind"] in ("息", "除息") and (stock or rights):
            raise ValueError("cash-only announcement contains allocation terms")
        reference = (close - cash + subscription * rights) / (1 + stock + rights)
        factor = reference / close
    return DerivedFactor(
        action=CorporateAction(
            action_id=announcement.evidence_id, symbol=announcement.symbol,
            action_type=CorporateActionType.RIGHTS_ISSUE if rights else expected_kind[terms["event_kind"]],
            event_date=event, adjustment_factor=float(factor), adjustment_method=BACK_ADJUSTMENT_METHOD,
            source=announcement.source, published_at=max(announcement.published_at, previous_close.published_at),
            observed_at=max(announcement.observed_at, previous_close.observed_at),
        ),
        reference_price=reference, announcement_id=announcement.evidence_id,
        announcement_revision=announcement.revision_id, announcement_hash=announcement.content_hash,
        previous_close_id=previous_close.evidence_id, previous_close_revision=previous_close.revision_id,
        previous_close_hash=previous_close.content_hash,
    )
