from datetime import datetime
from unittest.mock import Mock, patch

import pandas as pd

from tradingagents.dataflows.news.realtime_news import RealtimeNewsAggregator
from tradingagents.tools.unified_news_tool import UnifiedNewsAnalyzer


class _EmptyCursor:
    def sort(self, *_args):
        return self

    def limit(self, *_args):
        return self

    def __iter__(self):
        return iter(())


def test_database_query_is_bounded_by_analysis_date():
    collection = Mock()
    collection.find.return_value = _EmptyCursor()
    database = Mock()
    database.stock_news = collection
    client = Mock()
    client.get_database.return_value = database

    analyzer = UnifiedNewsAnalyzer(Mock())
    with patch(
        "tradingagents.dataflows.cache.app_adapter.get_mongodb_client",
        return_value=client,
    ):
        result = analyzer._get_news_from_database(
            "000661", analysis_date="2026-07-30", max_age_days=7
        )

    assert result == ""
    time_filter = collection.find.call_args.args[0]["$and"][1]["publish_time"]
    assert time_filter["$gte"] == datetime(2026, 7, 23)
    assert time_filter["$lt"] == datetime(2026, 7, 31)


def test_historical_analysis_does_not_refresh_or_call_live_sources():
    toolkit = Mock(spec=[])
    analyzer = UnifiedNewsAnalyzer(toolkit)
    analyzer._get_news_from_database = Mock(side_effect=["", "背景新闻"])
    analyzer._sync_news_from_akshare = Mock()

    result = analyzer._get_a_share_news(
        "000661", 10, analysis_date="2025-01-15"
    )

    analyzer._sync_news_from_akshare.assert_not_called()
    assert "仅限历史背景" in result
    assert "背景新闻" in result


def test_eastmoney_dataframe_fields_are_mapped_to_news_items():
    current_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    news_df = pd.DataFrame(
        [
            {
                "新闻标题": "<em>长春高新</em>最新公告",
                "新闻内容": "公司披露最新临床进展",
                "发布时间": current_time,
                "新闻链接": "https://example.com/news/1",
                "新闻来源": "东方财富网",
            }
        ]
    )
    provider = Mock()
    provider.get_stock_news_sync.return_value = news_df
    aggregator = RealtimeNewsAggregator()
    aggregator._parse_rss_feed = Mock(return_value=[])

    with patch(
        "tradingagents.dataflows.providers.china.akshare.AKShareProvider",
        return_value=provider,
    ):
        result = aggregator._get_chinese_finance_news("000661", hours_back=72)

    assert len(result) == 1
    assert result[0].title == "长春高新最新公告"
    assert result[0].content == "公司披露最新临床进展"
    assert result[0].source == "东方财富网"
    assert result[0].url == "https://example.com/news/1"


def test_invalid_publish_time_is_not_replaced_with_current_time():
    news_df = pd.DataFrame(
        [{"新闻标题": "有效标题但没有时间", "新闻内容": "内容", "发布时间": ""}]
    )
    provider = Mock()
    provider.get_stock_news_sync.return_value = news_df
    aggregator = RealtimeNewsAggregator()
    aggregator._parse_rss_feed = Mock(return_value=[])

    with patch(
        "tradingagents.dataflows.providers.china.akshare.AKShareProvider",
        return_value=provider,
    ):
        result = aggregator._get_chinese_finance_news("000661", hours_back=72)

    assert result == []
