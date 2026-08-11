"""
统一股票新闻工具

自动识别股票类型（A股、港股、美股）并调用相应的新闻数据源

数据源优先级：
1. MongoDB 数据库（包括 local、akshare、tushare 等数据源）
2. 外部 API（AKShare、Google News、Finnhub）
"""

import asyncio
import logging
from concurrent.futures import ThreadPoolExecutor
from typing import Annotated, List, Dict, Any
from langchain_core.tools import tool
from datetime import datetime, timedelta

from core.tools.base import register_tool

logger = logging.getLogger(__name__)


def _query_news_from_database(symbol: str, start_date: datetime, end_date: datetime, limit: int = 20) -> List[Dict[str, Any]]:
    """
    从 MongoDB 数据库查询新闻（按数据源优先级）

    Args:
        symbol: 股票代码（6位代码，如 000001）
        start_date: 开始日期
        end_date: 结束日期
        limit: 返回数量限制

    Returns:
        新闻数据列表，如果没有数据则返回空列表
    """
    try:
        from app.core.database import get_mongo_db_sync
        db = get_mongo_db_sync()
        collection = db.stock_news

        # end_date 是排他上界，确保分析日当天的新闻也能被查到。
        query = {
            "$and": [
                {
                    "$or": [
                        {"symbol": symbol},
                        {"symbols": symbol},
                    ]
                },
                {
                    "publish_time": {
                        "$gte": start_date,
                        "$lt": end_date,
                    }
                },
            ]
        }
        cursor = collection.find(query).sort("publish_time", -1).limit(limit * 4)

        # 合并所有数据源，只对完全相同的 URL/标题/时间去重。
        merged = []
        seen = set()
        for news in cursor:
            publish_time = news.get("publish_time")
            key = (
                str(news.get("url") or "").strip(),
                str(news.get("title") or "").strip(),
                publish_time.isoformat() if isinstance(publish_time, datetime) else str(publish_time),
            )
            if key in seen:
                continue
            seen.add(key)
            merged.append(news)
            if len(merged) >= limit:
                break

        logger.info(
            f"📊 [新闻数据库查询] {start_date:%Y-%m-%d} 至 "
            f"{(end_date - timedelta(days=1)):%Y-%m-%d} 合并获取 {len(merged)} 条"
        )
        return merged

    except Exception as e:
        logger.error(f"❌ [新闻数据库查询] 查询失败: {e}")
        return []


def _format_database_news(news_list: List[Dict[str, Any]], data_source_name: str = "数据库") -> str:
    """
    格式化数据库新闻为 Markdown 格式

    Args:
        news_list: 新闻数据列表
        data_source_name: 数据源名称

    Returns:
        格式化的 Markdown 文本
    """
    if not news_list:
        return ""

    news_items = []
    for news in news_list:
        title = news.get('title', '无标题')
        publish_time = news.get('publish_time', '')
        url = news.get('url', '')
        source = news.get('source', '')
        content = news.get('content', '') or news.get('summary', '')

        # 格式化时间
        if isinstance(publish_time, datetime):
            time_str = publish_time.strftime('%Y-%m-%d %H:%M')
        else:
            time_str = str(publish_time)

        # 构建新闻条目
        if url:
            news_item = f"- **{title}** [{time_str}]({url})"
        else:
            news_item = f"- **{title}** [{time_str}]"

        if source:
            news_item += f" - 来源: {source}"
        if content:
            news_item += f"\n  {str(content).strip()[:800]}"

        news_items.append(news_item)

    news_text = "\n".join(news_items)
    return f"## {data_source_name}\n{news_text}"


def _primary_window_start(analysis_date: datetime) -> datetime:
    """返回分析日所在周的上一个周一。"""
    current_week_monday = analysis_date - timedelta(days=analysis_date.weekday())
    return current_week_monday - timedelta(days=7)


def _run_coroutine_sync(coro):
    """在同步 LangGraph 工具节点中安全执行异步数据源。"""
    with ThreadPoolExecutor(max_workers=1) as executor:
        return executor.submit(asyncio.run, coro).result(timeout=45)


def _refresh_a_share_news(symbol: str, limit: int = 20) -> List[Dict[str, Any]]:
    """刷新 AKShare/东方财富新闻并合并写入数据库。"""
    try:
        from tradingagents.dataflows.providers.china.akshare import AKShareProvider
        from app.services.news_data_service import NewsDataService

        provider = AKShareProvider()
        news_list = _run_coroutine_sync(
            provider.get_stock_news(symbol=symbol, limit=limit)
        ) or []
        valid_news = [item for item in news_list if item.get("publish_time")]
        if valid_news:
            NewsDataService().save_news_data_sync(
                valid_news, data_source="akshare", market="CN"
            )
        logger.info(f"✅ [统一新闻工具] 实时刷新完成: {len(valid_news)} 条")
        return valid_news
    except Exception as exc:
        logger.warning(f"⚠️ [统一新闻工具] 实时刷新失败，继续使用缓存: {exc}")
        return []


def _filter_news_by_window(
    news_list: List[Dict[str, Any]], start_date: datetime, end_date: datetime
) -> List[Dict[str, Any]]:
    result = []
    for news in news_list:
        publish_time = news.get("publish_time")
        if isinstance(publish_time, datetime) and start_date <= publish_time < end_date:
            result.append(news)
    return sorted(result, key=lambda item: item["publish_time"], reverse=True)


@tool
@register_tool(
    tool_id="get_stock_news_unified",
    name="统一股票新闻",
    description="获取股票相关新闻，支持A股、港股、美股",
    category="news",
    is_online=True,
    auto_register=True
)
def get_stock_news_unified(
    ticker: Annotated[str, "股票代码（支持A股、港股、美股）"],
    curr_date: Annotated[str, "当前日期，格式：YYYY-MM-DD"]
) -> str:
    """
    统一的股票新闻工具
    自动识别股票类型（A股、港股、美股）并调用相应的新闻数据源

    Args:
        ticker: 股票代码（如：000001、0700.HK、AAPL）
        curr_date: 当前日期（格式：YYYY-MM-DD）

    Returns:
        str: 新闻分析报告
    """
    logger.info(f"📰 [统一新闻工具] 分析股票: {ticker}")

    try:
        from tradingagents.utils.stock_utils import StockUtils

        # 自动识别股票类型
        market_info = StockUtils.get_market_info(ticker)
        is_china = market_info['is_china']
        is_hk = market_info['is_hk']
        is_us = market_info['is_us']

        logger.info(f"📰 [统一新闻工具] 股票类型: {market_info['market_name']}")

        # 计算新闻查询的日期范围
        # 处理可能包含时间的日期字符串（如 "2026-01-14 00:00:00"）
        curr_date_clean = curr_date.split()[0] if ' ' in curr_date else curr_date
        analysis_date = datetime.strptime(curr_date_clean, '%Y-%m-%d')
        end_date = analysis_date + timedelta(days=1)
        start_date = analysis_date - timedelta(days=7)
        start_date_str = start_date.strftime('%Y-%m-%d')

        result_data = []

        if is_china:
            # 中国A股：当前日分析先刷新，再读取合并后的数据库新闻。
            logger.info(f"🇨🇳 [统一新闻工具] 处理A股新闻...")

            clean_ticker = ticker.replace('.SH', '').replace('.SZ', '').replace('.SS', '')\
                           .replace('.XSHE', '').replace('.XSHG', '')

            refreshed_news = []
            is_current_analysis = abs((datetime.now().date() - analysis_date.date()).days) <= 1
            if is_current_analysis:
                refreshed_news = _refresh_a_share_news(clean_ticker, limit=20)
            else:
                logger.info(f"📅 历史分析 {curr_date_clean} 跳过实时新闻刷新")

            primary_start = _primary_window_start(analysis_date)
            primary_news = _query_news_from_database(
                symbol=clean_ticker,
                start_date=primary_start,
                end_date=end_date,
                limit=20,
            )
            if not primary_news and refreshed_news:
                primary_news = _filter_news_by_window(
                    refreshed_news, primary_start, end_date
                )[:20]

            if primary_news:
                result_data.append(
                    _format_database_news(primary_news, "核心新闻窗口（刷新后合并）")
                )
                start_date = primary_start
                start_date_str = primary_start.strftime('%Y-%m-%d')
            else:
                context_start = analysis_date - timedelta(days=30)
                context_news = _query_news_from_database(
                    symbol=clean_ticker,
                    start_date=context_start,
                    end_date=end_date,
                    limit=20,
                )
                if context_news:
                    result_data.append(
                        _format_database_news(
                            context_news,
                            "30天内历史背景（不得作为当前催化剂）",
                        )
                    )
                    start_date = context_start
                    start_date_str = context_start.strftime('%Y-%m-%d')
                else:
                    result_data.append("## 新闻时效性\n未获取到核心窗口有效新闻。")
                    start_date = primary_start
                    start_date_str = primary_start.strftime('%Y-%m-%d')

        elif is_hk:
            # 港股：使用Google新闻
            logger.info(f"🇭🇰 [统一新闻工具] 处理港股新闻...")

            try:
                search_query = f"{ticker} 港股"

                from tradingagents.dataflows.interface import get_google_news
                from concurrent.futures import ThreadPoolExecutor, TimeoutError as FutureTimeoutError
                
                # 🔥 使用 ThreadPoolExecutor 实现超时控制，避免 Google 新闻获取阻塞整个流程
                # 设置 30 秒超时，如果超时则跳过 Google 新闻，不阻塞其他节点的执行
                with ThreadPoolExecutor(max_workers=1) as executor:
                    future = executor.submit(get_google_news, search_query, curr_date_clean)
                    try:
                        news_data = future.result(timeout=30.0)  # 最多等待30秒
                        if news_data:
                            result_data.append(f"## Google新闻\n{news_data}")
                            logger.info(f"✅ 成功获取Google新闻")
                        else:
                            logger.warning(f"⚠️ Google新闻返回空结果")
                    except FutureTimeoutError:
                        logger.warning(f"⚠️ Google新闻获取超时（30秒），跳过Google新闻以避免阻塞流程")
                        # 不添加到结果中，让流程继续
                    except Exception as e:
                        logger.error(f"❌ Google新闻获取失败: {e}")
                        # 不添加到结果中，避免显示错误信息，让流程继续
                        
            except Exception as google_e:
                logger.error(f"❌ Google新闻获取异常: {google_e}")
                # 不添加到结果中，避免显示错误信息，让流程继续

        elif is_us:
            # 美股：使用Finnhub新闻和Google新闻
            logger.info(f"🇺🇸 [统一新闻工具] 处理美股新闻...")

            # 1. 获取Finnhub新闻
            try:
                from tradingagents.dataflows.interface import get_finnhub_news
                news_data = get_finnhub_news(ticker, start_date_str, curr_date)
                if news_data:
                    result_data.append(f"## 美股新闻\n{news_data}")
            except Exception as e:
                logger.error(f"❌ Finnhub新闻获取失败: {e}")
                result_data.append(f"## 美股新闻\n获取失败: {e}")

            # 2. 获取Google新闻作为补充（带超时保护，避免阻塞整个流程）
            try:
                search_query = f"{ticker} stock news"

                from tradingagents.dataflows.interface import get_google_news
                from concurrent.futures import ThreadPoolExecutor, TimeoutError as FutureTimeoutError
                
                # 🔥 使用 ThreadPoolExecutor 实现超时控制，避免 Google 新闻获取阻塞整个流程
                # 设置 30 秒超时，如果超时则跳过 Google 新闻，不阻塞其他节点的执行
                with ThreadPoolExecutor(max_workers=1) as executor:
                    future = executor.submit(get_google_news, search_query, curr_date_clean)
                    try:
                        news_data = future.result(timeout=30.0)  # 最多等待30秒
                        if news_data:
                            result_data.append(f"## Google新闻\n{news_data}")
                            logger.info(f"✅ 成功获取Google新闻")
                        else:
                            logger.warning(f"⚠️ Google新闻返回空结果")
                    except FutureTimeoutError:
                        logger.warning(f"⚠️ Google新闻获取超时（30秒），跳过Google新闻以避免阻塞流程")
                        # 不添加到结果中，让流程继续
                    except Exception as e:
                        logger.error(f"❌ Google新闻获取失败: {e}")
                        # 不添加到结果中，避免显示错误信息，让流程继续
                        
            except Exception as google_e:
                logger.error(f"❌ Google新闻获取异常: {google_e}")
                # 不添加到结果中，避免显示错误信息，让流程继续

        # 组合所有数据
        combined_result = f"""# {ticker} 新闻分析

**股票类型**: {market_info['market_name']}
**分析日期**: {curr_date}
**新闻时间范围**: {start_date_str} 至 {curr_date}

{chr(10).join(result_data)}

---
*数据来源: 当前分析先刷新，再合并数据库中的多数据源新闻*
"""

        logger.info(f"📰 [统一新闻工具] 数据获取完成，总长度: {len(combined_result)}")
        return combined_result

    except Exception as e:
        error_msg = f"统一新闻工具执行失败: {str(e)}"
        logger.error(f"❌ [统一新闻工具] {error_msg}")
        return error_msg
