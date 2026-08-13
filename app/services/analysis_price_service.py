"""Build one auditable A-share price snapshot for an analysis task."""

from __future__ import annotations

import asyncio
import json
import logging
import queue
import threading
from dataclasses import dataclass
from datetime import datetime, time, timezone
from typing import Any, Dict, Optional
from zoneinfo import ZoneInfo

from app.core.config import settings
from app.core.database import get_mongo_db_sync, get_redis_sync_client

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class MarketPhase:
    name: str
    is_trade_day: bool
    should_refresh: bool
    freshness_minutes: Optional[int]
    calendar_reliable: bool
    last_trade_date: Optional[str]


def _normalize_date(value: Any) -> Optional[str]:
    if value in (None, ""):
        return None
    text = str(value).strip().replace("-", "")[:8]
    if len(text) == 8 and text.isdigit():
        return f"{text[:4]}-{text[4:6]}-{text[6:]}"
    return None


def _as_local_datetime(value: Any, tz: ZoneInfo) -> Optional[datetime]:
    if not value:
        return None
    try:
        parsed = value if isinstance(value, datetime) else datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        return parsed.astimezone(tz)
    except (TypeError, ValueError):
        return None


def classify_market_phase(now: datetime, calendar: Optional[Dict[str, Any]]) -> MarketPhase:
    """Classify the A-share session using the cached exchange calendar.

    A failed calendar lookup never authorizes a quote to be called realtime. This
    avoids treating a weekend/holiday quote stamped with today's fetch date as a
    live market price.
    """
    today = now.strftime("%Y-%m-%d")
    calendar = calendar or {}
    reliable = (
        calendar.get("fetched_at") == today
        and calendar.get("source") not in (None, "", "fallback")
        and bool(calendar.get("last_trade_date"))
    )
    last_trade_date = _normalize_date(calendar.get("last_trade_date"))
    is_trade_day = reliable and last_trade_date == today and bool(calendar.get("is_today_trade_day"))

    if not reliable:
        return MarketPhase("calendar_unknown", False, False, None, False, last_trade_date)
    if not is_trade_day:
        return MarketPhase("closed_day", False, False, None, True, last_trade_date)

    current = now.time()
    if current < time(9, 30):
        return MarketPhase("pre_open", True, False, None, True, last_trade_date)
    if time(9, 30) <= current <= time(11, 30):
        return MarketPhase("morning_session", True, True, 10, True, last_trade_date)
    if time(11, 30) < current < time(13, 0):
        return MarketPhase("lunch_break", True, True, None, True, last_trade_date)
    if time(13, 0) <= current <= time(15, 0):
        return MarketPhase("afternoon_session", True, True, 10, True, last_trade_date)
    if time(15, 0) < current <= time(15, 30):
        return MarketPhase("close_buffer", True, True, 10, True, last_trade_date)
    return MarketPhase("after_close", True, False, None, True, last_trade_date)


class AnalysisPriceService:
    """Resolve and freeze the price context used by one workflow execution."""

    def __init__(self, now: Optional[datetime] = None, refresh_timeout: float = 15.0):
        self.tz = ZoneInfo(settings.TIMEZONE)
        self.now = (now or datetime.now(self.tz)).astimezone(self.tz)
        self.refresh_timeout = refresh_timeout

    def _read_calendar(self) -> Optional[Dict[str, Any]]:
        try:
            redis_client = get_redis_sync_client()
            raw = redis_client.get("trading_calendar:last_trade_date")
            calendar = json.loads(raw) if raw else None
            if calendar and calendar.get("fetched_at") == self.now.strftime("%Y-%m-%d"):
                return calendar

            # 长期运行的服务在次日开盘前可能仍保留昨日缓存，按需刷新一次。
            result_queue: queue.Queue = queue.Queue(maxsize=1)

            def runner() -> None:
                try:
                    from app.services.trading_calendar_service import get_trading_calendar_service

                    last_trade_date, source = asyncio.run(
                        get_trading_calendar_service()._fetch_last_trade_date()
                    )
                    result_queue.put({
                        "last_trade_date": last_trade_date,
                        "is_today_trade_day": last_trade_date == self.now.strftime("%Y-%m-%d"),
                        "fetched_at": self.now.strftime("%Y-%m-%d"),
                        "source": source,
                    })
                except Exception as exc:  # pragma: no cover - external providers
                    logger.warning("[价格快照] 按需刷新交易日历失败: %s", exc)
                    result_queue.put(None)

            threading.Thread(target=runner, daemon=True, name="calendar-refresh").start()
            try:
                refreshed_calendar = result_queue.get(timeout=min(self.refresh_timeout, 12.0))
                if refreshed_calendar:
                    redis_client.setex(
                        "trading_calendar:last_trade_date",
                        25 * 3600,
                        json.dumps(refreshed_calendar, ensure_ascii=False),
                    )
                    return refreshed_calendar
            except queue.Empty:
                logger.warning("[价格快照] 按需刷新交易日历超时，按非实时行情降级")

            raw = redis_client.get("trading_calendar:last_trade_date")
            return json.loads(raw) if raw else calendar
        except Exception as exc:
            logger.warning("[价格快照] 无法读取交易日历，按非实时行情降级: %s", exc)
            return None

    def _read_quote(self, code: str) -> Optional[Dict[str, Any]]:
        try:
            return get_mongo_db_sync().market_quotes.find_one(
                {"$or": [{"code": code}, {"symbol": code}]},
                {"_id": 0},
            )
        except Exception as exc:
            logger.warning("[价格快照] 读取 %s 行情缓存失败: %s", code, exc)
            return None

    def _needs_refresh(self, quote: Optional[Dict[str, Any]], phase: MarketPhase) -> bool:
        if not phase.should_refresh:
            return False
        if not quote or not quote.get("close"):
            return True

        quote_date = _normalize_date(quote.get("trade_date"))
        today = self.now.strftime("%Y-%m-%d")
        if quote_date != today:
            return True

        updated_at = _as_local_datetime(quote.get("updated_at"), self.tz)
        if not updated_at:
            return True

        if phase.name == "lunch_break":
            # 午休没有新成交；仅接受足够接近上午收盘的快照。
            return updated_at.time() < time(11, 25)

        if phase.freshness_minutes is None:
            return False
        age_seconds = max(0.0, (self.now - updated_at).total_seconds())
        return age_seconds > phase.freshness_minutes * 60

    def _refresh_single_quote(self, code: str) -> Optional[Dict[str, Any]]:
        """Call the existing AKShare single-stock adapter without blocking forever."""
        result_queue: queue.Queue = queue.Queue(maxsize=1)

        def runner() -> None:
            try:
                from tradingagents.dataflows.providers.china.akshare import get_akshare_provider

                quote = asyncio.run(
                    get_akshare_provider().get_stock_quotes(code, fallback_to_batch=False)
                )
                result_queue.put((quote, None))
            except Exception as exc:  # pragma: no cover - provider/network dependent
                result_queue.put((None, exc))

        thread = threading.Thread(target=runner, daemon=True, name=f"quote-refresh-{code}")
        thread.start()
        try:
            quote, error = result_queue.get(timeout=self.refresh_timeout)
        except queue.Empty:
            logger.warning("[价格快照] %s 单股行情刷新超过 %.0f 秒，使用数据库快照", code, self.refresh_timeout)
            return None
        if error:
            logger.warning("[价格快照] %s 单股行情刷新失败: %s", code, error)
            return None
        if not quote or not quote.get("close") or float(quote.get("close", 0)) <= 0:
            return None

        normalized = {
            key: quote.get(key)
            for key in ("close", "pct_chg", "amount", "volume", "open", "high", "low", "pre_close")
        }
        normalized.update({
            "code": code,
            "symbol": code,
            "trade_date": self.now.strftime("%Y%m%d"),
            "updated_at": self.now,
            "source": quote.get("data_source") or "akshare_single",
        })
        try:
            get_mongo_db_sync().market_quotes.update_one(
                {"code": code}, {"$set": normalized}, upsert=True
            )
        except Exception as exc:
            logger.warning("[价格快照] 实时行情已获取但写入缓存失败: %s", exc)
        return normalized

    def _latest_completed_close(self, code: str, phase: MarketPhase) -> tuple[Optional[Any], Optional[str]]:
        try:
            db = get_mongo_db_sync()
            today = self.now.strftime("%Y-%m-%d")
            docs = db.stock_daily_quotes.find(
                {"$or": [{"symbol": code}, {"code": code}]},
                {"_id": 0, "close": 1, "trade_date": 1},
            ).sort("trade_date", -1).limit(10)
            for doc in docs:
                trade_date = _normalize_date(doc.get("trade_date"))
                if not trade_date or doc.get("close") in (None, ""):
                    continue
                # 盘中和午休不把尚未完成的当日日线当作技术指标收盘价。
                if phase.name in {"morning_session", "lunch_break", "afternoon_session"} and trade_date >= today:
                    continue
                return doc.get("close"), trade_date
        except Exception as exc:
            logger.warning("[价格快照] 读取 %s 完整日线收盘价失败: %s", code, exc)
        return None, None

    def get_snapshot(self, code: str) -> Dict[str, Any]:
        calendar = self._read_calendar()
        phase = classify_market_phase(self.now, calendar)
        quote = self._read_quote(code)
        refreshed = False
        refresh_attempted = self._needs_refresh(quote, phase)

        if refresh_attempted:
            fresh_quote = self._refresh_single_quote(code)
            if fresh_quote:
                quote = fresh_quote
                refreshed = True

        price = quote.get("close") if quote else None
        quote_date = _normalize_date(quote.get("trade_date")) if quote else None
        updated_at = _as_local_datetime(quote.get("updated_at"), self.tz) if quote else None
        today = self.now.strftime("%Y-%m-%d")

        remains_stale = self._needs_refresh(quote, phase)
        is_intraday = (
            phase.calendar_reliable
            and phase.is_trade_day
            and phase.name in {"morning_session", "lunch_break", "afternoon_session"}
            and quote_date == today
            and updated_at is not None
            and not remains_stale
        )
        if is_intraday:
            price_type = "intraday_snapshot"
            price_label = "盘中参考价" if phase.name != "lunch_break" else "午间休市快照"
        elif (
            quote_date == today
            and phase.name in {"close_buffer", "after_close"}
            and updated_at is not None
            and updated_at.time() >= time(14, 50)
        ):
            price_type = "closing_snapshot"
            price_label = "当日收盘快照"
        elif quote_date == today and phase.is_trade_day:
            price_type = "stale_intraday_snapshot"
            price_label = "过期盘中快照"
        else:
            price_type = "latest_close"
            price_label = "最近可用收盘价"

        completed_close, completed_date = self._latest_completed_close(code, phase)
        if quote_date == today and phase.name in {"morning_session", "lunch_break", "afternoon_session"}:
            if quote and quote.get("pre_close") not in (None, "", 0):
                completed_close = quote.get("pre_close")
                completed_date = "上一交易日（行情昨收）"
        elif price_type == "closing_snapshot":
            completed_close, completed_date = price, today
        if completed_close is None and price_type == "latest_close":
            completed_close, completed_date = price, quote_date

        as_of = updated_at.strftime("%Y-%m-%d %H:%M:%S") if updated_at else quote_date or "未知"
        source = (quote or {}).get("source") or (quote or {}).get("data_source") or "database"
        note = (
            f"{price_label} {price if price is not None else '未知'}，时点 {as_of}，来源 {source}。"
            f"技术指标使用最近完整交易日收盘价 {completed_close if completed_close is not None else '未知'}"
            f"（{completed_date or '日期未知'}）。"
        )
        if not phase.calendar_reliable:
            note += "交易日历不可确认，本次价格不得表述为实时价。"
        elif phase.name == "closed_day":
            note += "当前为周末或节假日，不要求按分钟刷新。"
        elif phase.name == "lunch_break" and not remains_stale:
            note += "当前为午间休市，上午收盘快照在下午开盘前持续有效。"
        elif phase.name == "lunch_break":
            note += "当前为午间休市，但缓存并非足够接近上午收盘的快照。"
        if refresh_attempted and not refreshed:
            note += "实时刷新失败，当前快照可能已经过期，结论应降低价格时效性权重。"

        logger.info(
            "[价格快照] code=%s phase=%s price=%s type=%s as_of=%s refreshed=%s",
            code, phase.name, price, price_type, as_of, refreshed,
        )
        return {
            "current_price": str(price) if price is not None else "未知",
            "price_as_of": as_of,
            "price_trade_date": quote_date or "未知",
            "price_type": price_type,
            "price_label": price_label,
            "price_source": source,
            "price_market_phase": phase.name,
            "price_context": note,
            "latest_completed_close": str(completed_close) if completed_close is not None else "未知",
            "latest_completed_close_date": completed_date or "未知",
        }
