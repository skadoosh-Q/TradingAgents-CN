from unittest.mock import Mock

import pandas as pd
import pytest

from core.data_sources.free_china_market import FreeChinaMarketData


@pytest.mark.asyncio
async def test_index_daily_is_normalized(monkeypatch):
    adapter = FreeChinaMarketData(retries=1)
    monkeypatch.setattr(adapter, "_mongo_collection", lambda: None)
    fake_ak = Mock()
    fake_ak.stock_zh_index_daily_em.return_value = pd.DataFrame(
        {
            "date": ["2026-08-10", "2026-08-11"],
            "open": [3900, 3910],
            "close": [3910, 3930],
            "high": [3920, 3940],
            "low": [3890, 3900],
            "volume": [100, 120],
            "amount": [1000, 1200],
        }
    )
    monkeypatch.setattr(adapter, "_ak", lambda: fake_ak)

    result = await adapter.get_index_daily("000001.SH", "20260801", "20260811")

    assert list(result["trade_date"]) == ["20260810", "20260811"]
    assert result.iloc[-1]["pct_chg"] == pytest.approx((3930 / 3910 - 1) * 100)
    fake_ak.stock_zh_index_daily_em.assert_called_once_with(
        symbol="sh000001", start_date="20260801", end_date="20260811"
    )


@pytest.mark.asyncio
async def test_market_activity_is_normalized(monkeypatch):
    adapter = FreeChinaMarketData(retries=1)
    monkeypatch.setattr(adapter, "_mongo_collection", lambda: None)
    fake_ak = Mock()
    fake_ak.stock_market_activity_legu.return_value = pd.DataFrame(
        {
            "item": ["上涨", "下跌", "平盘", "真实涨停", "真实跌停", "活跃度", "统计日期"],
            "value": [2500, 2000, 100, 80, 5, "54.35%", "2026-08-11 15:00:00"],
        }
    )
    monkeypatch.setattr(adapter, "_ak", lambda: fake_ak)

    result = await adapter.get_market_activity()

    assert result["up_count"] == 2500
    assert result["limit_up_count"] == 80
    assert result["activity_rate"] == pytest.approx(54.35)


def test_remote_failure_uses_stale_persistent_cache(monkeypatch):
    adapter = FreeChinaMarketData(retries=1)
    stale = pd.DataFrame({"value": [42]})
    monkeypatch.setattr(
        adapter,
        "_read_persistent",
        lambda key, max_age: pd.DataFrame() if max_age == 1 else stale,
    )

    def fail():
        raise ConnectionError("upstream disconnected")

    result = adapter._fetch_frame(
        "test:key", fail, ttl=1, stale_ttl=3600, source="test"
    )

    assert result.iloc[0]["value"] == 42
    assert result.attrs["stale"] is True
