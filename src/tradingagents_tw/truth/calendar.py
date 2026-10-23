"""Official annual calendars plus explicit, observed emergency amendments.

18:00 Taipei is our conservative ingestion policy, NOT an exchange publication
guarantee. Annual schedules do not prove that no typhoon closure occurred:
missing OHLCV sessions remain blocking until an official amendment is supplied.
"""
from datetime import date, datetime, time, timedelta
from html.parser import HTMLParser
import hashlib
import json
import re
from typing import Literal
from urllib.parse import urlparse
from zoneinfo import ZoneInfo

from pydantic import model_validator

from tradingagents_tw.contracts import StrictModel
from tradingagents_tw.providers.registry import Market, CALENDAR_SOURCES

TAIPEI = ZoneInfo("Asia/Taipei")


def require_available(observed_at: datetime, cutoff: datetime) -> None:
    if observed_at.utcoffset() is None or cutoff.utcoffset() is None:
        raise ValueError("calendar timestamps must be timezone-aware")
    if observed_at > cutoff:
        raise ValueError("calendar information is unavailable at cutoff")


class SessionAmendment(StrictModel):
    trade_date: date
    is_open: bool
    source_url: str
    reason: str
    observed_at: datetime


class TradingCalendar(StrictModel):
    version: Literal["official-taiwan-calendar-v1"] = "official-taiwan-calendar-v1"
    market: Market
    year: int
    source_url: str
    source_hash: str
    observed_at: datetime
    closed_dates: tuple[date, ...]
    open_dates: tuple[date, ...] = ()
    amendments: tuple[SessionAmendment, ...] = ()

    @model_validator(mode="after")
    def valid_calendar(self):
        if self.source_url != CALENDAR_SOURCES[self.market]:
            raise ValueError("calendar source does not match market")
        if not re.fullmatch(r"[0-9a-f]{64}", self.source_hash):
            raise ValueError("calendar source hash must be SHA-256")
        require_available(self.observed_at, self.observed_at)
        for dates in (self.closed_dates, self.open_dates):
            if dates != tuple(sorted(set(dates))) or any(d.year != self.year for d in dates):
                raise ValueError("calendar dates must be unique, sorted and in coverage year")
        if set(self.closed_dates) & set(self.open_dates):
            raise ValueError("conflicting calendar sessions")
        amended = [a.trade_date for a in self.amendments]
        if amended != sorted(set(amended)):
            raise ValueError("amendments must be unique and sorted")
        host = "www.twse.com.tw" if self.market is Market.TWSE else "www.tpex.org.tw"
        for a in self.amendments:
            u = urlparse(a.source_url)
            if a.trade_date.year != self.year or u.scheme != "https" or u.hostname != host:
                raise ValueError("amendment must cite the official board and covered year")
            if not a.reason.strip():
                raise ValueError("amendment reason is required")
            require_available(a.observed_at, a.observed_at)
        return self

    def is_session(self, day: date, *, cutoff: datetime) -> bool:
        require_available(self.observed_at, cutoff)
        if day.year != self.year:
            raise ValueError("date outside official calendar coverage")
        for amendment in self.amendments:
            require_available(amendment.observed_at, cutoff)
            if amendment.trade_date == day:
                return amendment.is_open
        if day in self.closed_dates:
            return False
        return day in self.open_dates or day.weekday() < 5

    def sessions(self, start: date, end: date, *, cutoff: datetime) -> tuple[date, ...]:
        if end < start:
            raise ValueError("invalid calendar interval")
        days = (start + timedelta(days=n) for n in range((end - start).days + 1))
        return tuple(d for d in days if self.is_session(d, cutoff=cutoff))

    def previous_session(self, day: date, *, cutoff: datetime) -> date:
        candidate = day - timedelta(days=1)
        while not self.is_session(candidate, cutoff=cutoff):
            candidate -= timedelta(days=1)
        return candidate


class PostMarketPolicy(StrictModel):
    version: Literal["taipei-post-market-1800-v1"] = "taipei-post-market-1800-v1"

    def ready_at(self, day: date) -> datetime:
        return datetime.combine(day, time(18), TAIPEI)

    def require_finalized(self, calendar: TradingCalendar, day: date, cutoff: datetime) -> None:
        if not calendar.is_session(day, cutoff=cutoff):
            raise ValueError("requested date is not an official trading session")
        if cutoff < self.ready_at(day):
            raise ValueError("post-market cutoff has not been reached")


_HOLIDAYS = ("紀念日", "春節", "除夕", "和平", "兒童", "掃墓", "勞動", "端午", "中秋", "國慶", "教師")


def _classify(name: str, note: str) -> bool:
    if "開始交易" in name or "最後交易" in name:
        return True
    if "無交易" in name or "休市" in name or any(k in name for k in _HOLIDAYS):
        return False
    raise ValueError(f"unrecognized official calendar event: {name}")


def _calendar(market, year, payload, observed_at, rows):
    closed, opened = set(), set()
    for day, name, note in rows:
        (opened if _classify(name, note) else closed).add(day)
    if not rows or not closed or not opened:
        raise ValueError("incomplete annual calendar")
    return TradingCalendar(
        market=market, year=year, source_url=CALENDAR_SOURCES[market],
        source_hash=hashlib.sha256(json.dumps(payload, ensure_ascii=False, sort_keys=True,
                                            separators=(",", ":")).encode()).hexdigest(),
        observed_at=observed_at, closed_dates=tuple(sorted(closed)), open_dates=tuple(sorted(opened)),
    )


def parse_twse_calendar(payload: dict, *, year: int, observed_at: datetime) -> TradingCalendar:
    if (payload.get("stat", "").lower() != "ok" or payload.get("queryYear") != year
            or payload.get("fields") != ["日期", "名稱", "說明"]):
        raise ValueError("unsupported TWSE calendar schema/year")
    rows = []
    for row in payload.get("data", []):
        if len(row) != 3:
            raise ValueError("malformed TWSE calendar row")
        rows.append((date.fromisoformat(row[0]), row[1], row[2]))
    return _calendar(Market.TWSE, year, payload, observed_at, rows)


class _TableParser(HTMLParser):
    """Expand official table rowspans before interpreting any date column."""
    def __init__(self):
        super().__init__()
        self.rows, self.cells, self.pending = [], [], {}
        self.text, self.span = None, 1

    def handle_starttag(self, tag, attrs):
        if tag == "tr":
            self.cells = []
        if tag in ("td", "th"):
            attrs = dict(attrs)
            if int(attrs.get("colspan", "1")) != 1:
                raise ValueError("unsupported calendar colspan")
            self.text, self.span = [], int(attrs.get("rowspan", "1"))

    def handle_data(self, data):
        if self.text is not None:
            self.text.append(data)

    def handle_endtag(self, tag):
        if tag in ("td", "th") and self.text is not None:
            self.cells.append(("".join(self.text).strip(), self.span))
            self.text = None
        if tag == "tr":
            row, index, remaining = [], 0, list(self.cells)
            while remaining or index in self.pending:
                if index in self.pending:
                    value, count = self.pending.pop(index)
                else:
                    value, count = remaining.pop(0)
                row.append(value)
                if count > 1:
                    self.pending[index] = (value, count - 1)
                index += 1
            self.rows.append(row)


def parse_tpex_calendar(payload: dict, *, year: int, observed_at: datetime) -> TradingCalendar:
    if payload.get("stat", "").lower() != "ok" or payload.get("endDate") != f"{year}0101":
        raise ValueError("unsupported TPEx calendar schema/year")
    parser = _TableParser()
    parser.feed(payload["data"]["html"])
    if not parser.rows or f"{year - 1911}年" not in parser.rows[0][0]:
        raise ValueError("TPEx calendar title year mismatch")
    rows = []
    for row in parser.rows[2:]:
        if len(row) != 4:
            raise ValueError("malformed TPEx calendar row")
        name, days, weekday, note = row
        if "債券" in name:  # The table also describes different bond-market closures.
            continue
        dates = re.findall(r"(\d{1,2})月(\d{1,2})日", days)
        remainder = re.sub(r"\d{1,2}月\d{1,2}日|\\[rnt]|\s", "", days)
        if not dates or remainder:
            raise ValueError("unsupported TPEx calendar date expression")
        rows.extend((date(year, int(m), int(d)), name, note) for m, d in dates)
        if "最後交易" in name and "無交易" in note:
            closures = re.findall(r"(\d{1,2})月(\d{1,2})日", note)
            if not closures or "至" in note:
                raise ValueError("unsupported settlement-only date expression")
            rows.extend((date(year, int(m), int(d)), "市場無交易", note) for m, d in closures)
    return _calendar(Market.TPEX, year, payload, observed_at, rows)
