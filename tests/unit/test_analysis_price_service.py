from datetime import datetime
from zoneinfo import ZoneInfo

from app.services.analysis_price_service import AnalysisPriceService, classify_market_phase


TZ = ZoneInfo("Asia/Shanghai")


def _calendar(today: str, is_trade_day: bool = True):
    return {
        "last_trade_date": today if is_trade_day else "2026-08-07",
        "is_today_trade_day": is_trade_day,
        "fetched_at": today,
        "source": "akshare",
    }


def test_market_phase_does_not_treat_unknown_calendar_as_live():
    now = datetime(2026, 8, 10, 10, 0, tzinfo=TZ)
    phase = classify_market_phase(now, None)
    assert phase.name == "calendar_unknown"
    assert phase.should_refresh is False


def test_lunch_break_accepts_morning_close_snapshot():
    now = datetime(2026, 8, 10, 12, 45, tzinfo=TZ)
    service = AnalysisPriceService(now=now)
    phase = classify_market_phase(now, _calendar("2026-08-10"))
    quote = {
        "close": 87.36,
        "trade_date": "20260810",
        "updated_at": datetime(2026, 8, 10, 11, 28, tzinfo=TZ),
    }
    assert phase.name == "lunch_break"
    assert service._needs_refresh(quote, phase) is False


def test_lunch_break_refreshes_snapshot_older_than_session_close():
    now = datetime(2026, 8, 10, 12, 45, tzinfo=TZ)
    service = AnalysisPriceService(now=now)
    phase = classify_market_phase(now, _calendar("2026-08-10"))
    quote = {
        "close": 86.18,
        "trade_date": "20260810",
        "updated_at": datetime(2026, 8, 10, 10, 50, tzinfo=TZ),
    }
    assert service._needs_refresh(quote, phase) is True


def test_lunch_break_refreshes_snapshot_nine_minutes_before_close():
    now = datetime(2026, 8, 10, 12, 45, tzinfo=TZ)
    service = AnalysisPriceService(now=now)
    phase = classify_market_phase(now, _calendar("2026-08-10"))
    quote = {
        "close": 86.98,
        "trade_date": "20260810",
        "updated_at": datetime(2026, 8, 10, 11, 21, tzinfo=TZ),
    }
    assert service._needs_refresh(quote, phase) is True


def test_holiday_never_uses_minute_freshness_rule():
    now = datetime(2026, 8, 10, 10, 0, tzinfo=TZ)
    phase = classify_market_phase(now, _calendar("2026-08-10", is_trade_day=False))
    assert phase.name == "closed_day"
    assert phase.should_refresh is False


def test_active_session_refreshes_quote_older_than_ten_minutes():
    now = datetime(2026, 8, 10, 10, 30, tzinfo=TZ)
    service = AnalysisPriceService(now=now)
    phase = classify_market_phase(now, _calendar("2026-08-10"))
    quote = {
        "close": 86.18,
        "trade_date": "20260810",
        "updated_at": datetime(2026, 8, 10, 10, 19, tzinfo=TZ),
    }
    assert service._needs_refresh(quote, phase) is True


def test_after_close_requires_a_near_close_snapshot():
    now = datetime(2026, 8, 10, 16, 0, tzinfo=TZ)
    service = AnalysisPriceService(now=now)
    service._read_calendar = lambda: _calendar("2026-08-10")
    service._read_quote = lambda code: {
        "close": 86.18,
        "trade_date": "20260810",
        "updated_at": datetime(2026, 8, 10, 11, 28, tzinfo=TZ),
        "source": "test",
    }
    service._latest_completed_close = lambda code, phase: (85.50, "2026-08-07")
    snapshot = service.get_snapshot("000661")
    assert snapshot["price_type"] == "stale_intraday_snapshot"
    assert snapshot["price_label"] == "过期盘中快照"


def test_close_buffer_uses_fresh_quote_as_closing_snapshot():
    now = datetime(2026, 8, 10, 15, 8, tzinfo=TZ)
    service = AnalysisPriceService(now=now)
    service._read_calendar = lambda: _calendar("2026-08-10")
    service._read_quote = lambda code: {
        "close": 87.50,
        "trade_date": "20260810",
        "updated_at": datetime(2026, 8, 10, 15, 2, tzinfo=TZ),
        "source": "test",
    }
    service._latest_completed_close = lambda code, phase: (87.50, "2026-08-10")
    snapshot = service.get_snapshot("000661")
    assert snapshot["price_type"] == "closing_snapshot"
    assert snapshot["price_label"] == "当日收盘快照"
