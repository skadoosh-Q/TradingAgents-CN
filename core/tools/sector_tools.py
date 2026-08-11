"""
板块分析工具函数

提供板块表现分析、轮动识别、同业对比等功能
"""

import asyncio
import logging
from datetime import datetime, timedelta
from typing import Optional, Dict, Any, List, Tuple

import pandas as pd

logger = logging.getLogger(__name__)


def _get_market_data_provider():
    """获取独立的免费 A 股市场数据接口。"""
    from core.data_sources import get_free_china_market_data

    return get_free_china_market_data()


def _clean_date_string(date_str: str) -> str:
    """清理日期字符串，去掉可能的时间部分"""
    if not date_str:
        return date_str
    return date_str.split()[0] if ' ' in date_str else date_str


async def _get_latest_trade_date(trade_date: str) -> str:
    """
    获取最新可用的交易日期

    一次性获取最近8天的数据，取最后一条有效交易日

    Args:
        trade_date: 原始交易日期 (YYYY-MM-DD 或 YYYYMMDD)

    Returns:
        最新可用的交易日期 (YYYYMMDD格式)
    """
    provider = _get_market_data_provider()
    # 清理日期字符串，去掉可能的时间部分
    trade_date_clean = _clean_date_string(trade_date).replace('-', '')

    try:
        # 计算8天前的日期
        end_date = datetime.strptime(trade_date_clean, '%Y%m%d')
        start_date = end_date - timedelta(days=8)
        start_date_str = start_date.strftime('%Y%m%d')

        # 一次性获取最近8天的上证指数数据
        df = await provider.get_index_daily(
            ts_code='000001.SH',
            start_date=start_date_str,
            end_date=trade_date_clean,
            use_cache=False  # 不使用缓存，确保获取最新数据
        )

        if df is not None and not df.empty:
            # 按日期排序，取最后一条（最新的交易日）
            df = df.sort_values('trade_date', ascending=False)
            latest_trade_date = str(df.iloc[0]['trade_date'])

            if latest_trade_date != trade_date_clean:
                logger.info(f"📅 {trade_date} 无数据，使用最近交易日 {latest_trade_date}")

            return latest_trade_date

        # 如果都没有找到，返回原始日期
        logger.warning(f"⚠️ 无法找到有效交易日，使用原始日期 {trade_date_clean}")
        return trade_date_clean

    except Exception as e:
        logger.error(f"❌ 获取最新交易日失败: {e}")
        return trade_date_clean


async def get_stock_sector_info(ticker: str) -> Dict[str, Any]:
    """
    获取股票所属的板块信息
    
    Args:
        ticker: 股票代码（如 000001 或 000001.SZ）
    
    Returns:
        包含行业和所属板块列表的字典
    """
    provider = _get_market_data_provider()
    
    result = {
        "ticker": ticker,
        "industry": None,
        "sectors": [],
        "error": None
    }
    
    try:
        # 1. 获取行业分类
        industry = await provider.get_stock_industry(ticker)
        result["industry"] = industry
        
        if industry:
            result["sectors"] = [{"name": industry, "type": "industry"}]
        
        return result
        
    except Exception as e:
        logger.error(f"获取股票板块信息失败: {e}")
        result["error"] = str(e)
        return result


async def get_sector_performance(
    ticker: str, 
    trade_date: str,
    lookback_days: int = 20
) -> str:
    """
    分析目标股票所属行业的整体表现
    
    Args:
        ticker: 股票代码
        trade_date: 交易日期 (YYYY-MM-DD 或 YYYYMMDD)
        lookback_days: 回看天数
    
    Returns:
        板块表现分析报告（字符串）
    """
    provider = _get_market_data_provider()
    
    try:
        # 1. 获取股票所属行业
        industry = await provider.get_stock_industry(ticker)
        if not industry:
            return f"⚠️ 无法获取股票 {ticker} 的行业信息"
        
        trade_date_clean = _clean_date_string(trade_date).replace('-', '')
        end_date = datetime.strptime(trade_date_clean, '%Y%m%d')
        start_date = end_date - timedelta(days=lookback_days + 10)
        start_date_str = start_date.strftime('%Y%m%d')
        end_date_str = trade_date_clean
        
        report_lines = [
            f"📊 板块表现分析报告",
            f"{'='*50}",
            f"🎯 目标股票: {ticker}",
            f"🏭 所属行业: {industry}",
            f"📅 分析日期: {trade_date}",
            f"📆 回看周期: {lookback_days} 交易日",
            "",
        ]
        
        daily_df = await provider.get_sector_daily(
            industry=industry,
            start_date=start_date_str,
            end_date=end_date_str,
        )
        if daily_df is None or daily_df.empty:
            report_lines.append("⚠️ 暂无该行业板块行情（免费数据源暂时不可用或行业口径不匹配）")
            return "\n".join(report_lines)

        daily_df = daily_df.sort_values('trade_date')
        first_close = float(daily_df.iloc[0]['close'])
        last_close = float(daily_df.iloc[-1]['close'])
        period_pct = ((last_close - first_close) / first_close) * 100 if first_close else 0
        today_pct = float(daily_df.iloc[-1].get('pct_change', 0) or 0)
        latest_date = str(daily_df.iloc[-1].get('trade_date', end_date_str))
        report_lines.extend(
            [
                "【行业板块走势】",
                f"  • 区间涨跌幅: {period_pct:+.2f}%",
                f"  • 最新交易日（{latest_date}）涨跌幅: {today_pct:+.2f}%",
                f"  • 最新收盘点位: {last_close:.2f}",
                f"  • 有效数据日: {len(daily_df)} 天",
                "  • 行业口径: 东方财富行业板块",
            ]
        )
        
        return "\n".join(report_lines)

    except Exception as e:
        logger.error(f"板块表现分析失败: {e}")
        return f"❌ 板块表现分析失败: {e}"


async def get_sector_rotation(trade_date: str, top_n: int = 10) -> str:
    """
    识别板块轮动趋势

    分析近期热门板块和资金流向，识别轮动方向

    Args:
        trade_date: 交易日期
        top_n: 返回前N个板块

    Returns:
        板块轮动分析报告
    """
    provider = _get_market_data_provider()

    try:
        # 获取最新可用的交易日
        moneyflow_df = await provider.get_sector_fund_flow(indicator="今日")
        data_date = (
            str(moneyflow_df.iloc[0].get("data_date", ""))
            if moneyflow_df is not None and not moneyflow_df.empty else ""
        )
        trade_date_formatted = (
            f"{data_date[:4]}-{data_date[4:6]}-{data_date[6:8]}"
            if len(data_date) >= 8 else _clean_date_string(trade_date)
        )

        report_lines = [
            f"🔄 板块轮动趋势分析",
            f"{'='*50}",
            f"📅 分析日期: {trade_date_formatted}",
            "",
        ]

        if moneyflow_df is None or moneyflow_df.empty:
            report_lines.append("⚠️ 暂无板块资金流向数据")
            return "\n".join(report_lines)

        # 按净流入金额排序
        moneyflow_df = moneyflow_df.sort_values('net_amount', ascending=False)

        # 资金流入TOP板块
        report_lines.append("【💰 资金净流入TOP板块】")
        inflow_df = moneyflow_df.head(top_n)
        for i, row in enumerate(inflow_df.itertuples(), 1):
            ts_code = getattr(row, 'ts_code', '')
            name = getattr(row, 'name', ts_code)
            net_amount = getattr(row, 'net_amount', 0)
            net_rate = getattr(row, 'net_amount_rate', 0)

            net_amount_yi = net_amount / 100000000 if net_amount else 0
            trend = "🔴" if net_amount > 0 else "🟢"

            report_lines.append(
                f"  {i}. {name}: {trend} {net_amount_yi:+.2f}亿 "
                f"(占比: {net_rate:.2f}%)"
            )

        report_lines.append("")

        # 资金流出TOP板块
        report_lines.append("【💸 资金净流出TOP板块】")
        outflow_df = moneyflow_df.tail(top_n).iloc[::-1]
        for i, row in enumerate(outflow_df.itertuples(), 1):
            ts_code = getattr(row, 'ts_code', '')
            name = getattr(row, 'name', ts_code)
            net_amount = getattr(row, 'net_amount', 0)
            net_rate = getattr(row, 'net_amount_rate', 0)

            net_amount_yi = net_amount / 100000000 if net_amount else 0

            report_lines.append(
                f"  {i}. {name}: 🟢 {net_amount_yi:+.2f}亿 "
                f"(占比: {net_rate:.2f}%)"
            )

        # 轮动判断
        report_lines.append("")
        report_lines.append("【🎯 轮动判断】")

        total_inflow = inflow_df['net_amount'].sum() / 100000000
        total_outflow = abs(outflow_df['net_amount'].sum()) / 100000000

        if total_inflow > total_outflow * 1.5:
            report_lines.append("  • 市场整体资金流入，偏多头氛围")
        elif total_outflow > total_inflow * 1.5:
            report_lines.append("  • 市场整体资金流出，偏空头氛围")
        else:
            report_lines.append("  • 市场资金进出均衡，板块轮动明显")

        return "\n".join(report_lines)

    except Exception as e:
        logger.error(f"板块轮动分析失败: {e}")
        return f"❌ 板块轮动分析失败: {e}"


async def get_peer_comparison(
    ticker: str,
    trade_date: str,
    top_n: int = 10
) -> str:
    """
    同业竞争对手对比分析

    对比目标股票与同行业其他股票的表现

    Args:
        ticker: 目标股票代码
        trade_date: 交易日期
        top_n: 对比的同业公司数量

    Returns:
        同业对比分析报告
    """
    provider = _get_market_data_provider()

    try:
        # 1. 获取股票所属行业
        industry = await provider.get_stock_industry(ticker)
        if not industry:
            return f"⚠️ 无法获取股票 {ticker} 的行业信息"

        # 2. 获取最新可用的交易日
        industry_df = await provider.get_sector_constituents(industry=industry)
        data_date = (
            str(industry_df.iloc[0].get("data_date", ""))
            if industry_df is not None and not industry_df.empty else ""
        )
        trade_date_formatted = (
            f"{data_date[:4]}-{data_date[4:6]}-{data_date[6:8]}"
            if len(data_date) >= 8 else _clean_date_string(trade_date)
        )

        report_lines = [
            f"📊 同业对比分析报告",
            f"{'='*50}",
            f"🎯 目标股票: {ticker}",
            f"🏭 所属行业: {industry}",
            f"📅 分析日期: {trade_date_formatted}",
            "",
        ]

        if industry_df is None or industry_df.empty:
            report_lines.append(f"⚠️ 暂无行业 {industry} 的对比数据")
            return "\n".join(report_lines)

        ranking_column = 'total_mv' if 'total_mv' in industry_df.columns else 'pct_chg'
        industry_df = industry_df.sort_values(ranking_column, ascending=False)
        total_count = len(industry_df)
        report_lines.append(f"📌 行业内上市公司: {total_count} 家")
        report_lines.append("")

        # 4. 找到目标股票的数据
        ts_code = ticker.split('.')[0].zfill(6)
        target_row = industry_df[industry_df['ts_code'] == ts_code]

        if not target_row.empty:
            target = target_row.iloc[0]
            target_rank = (industry_df['ts_code'] == ts_code).idxmax()
            target_rank_num = industry_df.index.get_loc(target_rank) + 1

            report_lines.append("【🎯 目标股票指标】")
            report_lines.append(f"  • 股票名称: {target.get('name', ticker)}")
            rank_label = "市值排名" if ranking_column == 'total_mv' else "当日涨幅排名"
            report_lines.append(f"  • {rank_label}: {target_rank_num}/{total_count}")
            if 'total_mv' in industry_df.columns and pd.notna(target.get('total_mv')):
                report_lines.append(f"  • 总市值: {target.get('total_mv', 0)/100000000:.2f}亿")
            report_lines.append(f"  • PE(TTM): {target.get('pe_ttm', 'N/A')}")
            report_lines.append(f"  • PB: {target.get('pb', 'N/A')}")
            report_lines.append(f"  • 换手率: {target.get('turnover_rate', 'N/A')}%")
            report_lines.append("")

        # 5. 行业龙头对比
        ranking_name = "市值" if ranking_column == 'total_mv' else "当日涨幅"
        report_lines.append(f"【🏆 同业{ranking_name}TOP{min(top_n, total_count)}】")
        for i, row in enumerate(industry_df.head(top_n).itertuples(), 1):
            name = getattr(row, 'name', getattr(row, 'ts_code', ''))
            pe_ttm = getattr(row, 'pe_ttm', 'N/A')
            pb = getattr(row, 'pb', 'N/A')

            marker = "⭐" if getattr(row, 'ts_code', '') == ts_code else "  "
            if ranking_column == 'total_mv':
                rank_value = f"市值{getattr(row, 'total_mv', 0) / 100000000:.0f}亿"
            else:
                rank_value = f"涨跌幅{getattr(row, 'pct_chg', 0):+.2f}%"
            report_lines.append(f"{marker}{i}. {name}: {rank_value} | PE: {pe_ttm} | PB: {pb}")

        # 6. 计算行业统计（过滤掉 NaN 值）
        import pandas as pd
        report_lines.append("")
        report_lines.append("【📈 行业统计】")

        valid_pe = industry_df['pe_ttm'].dropna()
        valid_pe = valid_pe[valid_pe > 0]
        valid_pb = industry_df['pb'].dropna()
        valid_pb = valid_pb[valid_pb > 0]
        pe_median = valid_pe.median()
        pb_median = valid_pb.median()
        pe_mean = valid_pe.mean()
        pb_mean = valid_pb.mean()

        if pd.notna(pe_median):
            report_lines.append(f"  • PE中位数: {pe_median:.2f} | PE均值: {pe_mean:.2f}")
        else:
            report_lines.append(f"  • PE数据: 暂无有效数据")

        if pd.notna(pb_median):
            report_lines.append(f"  • PB中位数: {pb_median:.2f} | PB均值: {pb_mean:.2f}")
        else:
            report_lines.append(f"  • PB数据: 暂无有效数据")

        # 7. 目标股票在行业中的估值位置
        if not target_row.empty:
            target_pe = target.get('pe_ttm')
            target_pb = target.get('pb')

            report_lines.append("")
            report_lines.append("【📊 估值评价】")

            # 处理 PE 估值（检查是否为 None 或 NaN）
            if pd.notna(target_pe) and pd.notna(pe_median):
                if target_pe < pe_median * 0.8:
                    report_lines.append(f"  • PE估值: {target_pe:.2f}，低于行业中位数({pe_median:.1f})，估值偏低")
                elif target_pe > pe_median * 1.2:
                    report_lines.append(f"  • PE估值: {target_pe:.2f}，高于行业中位数({pe_median:.1f})，估值偏高")
                else:
                    report_lines.append(f"  • PE估值: {target_pe:.2f}，接近行业中位数({pe_median:.1f})，估值合理")
            else:
                report_lines.append(f"  • PE估值: 数据缺失（可能亏损或数据未更新）")

            # 处理 PB 估值（检查是否为 None 或 NaN）
            if pd.notna(target_pb) and pd.notna(pb_median):
                if target_pb < pb_median * 0.8:
                    report_lines.append(f"  • PB估值: {target_pb:.2f}，低于行业中位数({pb_median:.1f})，估值偏低")
                elif target_pb > pb_median * 1.2:
                    report_lines.append(f"  • PB估值: {target_pb:.2f}，高于行业中位数({pb_median:.1f})，估值偏高")
                else:
                    report_lines.append(f"  • PB估值: {target_pb:.2f}，接近行业中位数({pb_median:.1f})，估值合理")
            else:
                report_lines.append(f"  • PB估值: 数据缺失")

        return "\n".join(report_lines)

    except Exception as e:
        logger.error(f"同业对比分析失败: {e}")
        return f"❌ 同业对比分析失败: {e}"


async def analyze_sector(ticker: str, trade_date: str) -> str:
    """
    综合板块分析（SectorAnalyst 主入口）

    整合板块表现、轮动趋势、同业对比三个维度的分析

    Args:
        ticker: 目标股票代码（如果是 "MARKET" 则分析整体板块情况）
        trade_date: 交易日期

    Returns:
        综合板块分析报告
    """
    try:
        # 判断是整体板块分析还是个股板块分析
        is_market_analysis = (ticker == "MARKET" or not ticker)

        if is_market_analysis:
            # 整体板块分析：只分析板块轮动
            rotation_report = await get_sector_rotation(trade_date)

            # 组合报告
            full_report = [
                "=" * 60,
                "🏭 板块分析师综合报告",
                "=" * 60,
                "",
                rotation_report,
                "",
                "=" * 60,
                "📋 分析结论",
                "=" * 60,
            ]

            full_report.append("请根据以上数据综合判断：")
            full_report.append("1. 当前市场热点板块和资金流向")
            full_report.append("2. 板块轮动的方向和强度")
            full_report.append("3. 市场整体的风险偏好")

        else:
            # 个股板块分析：分析目标股票所属板块
            performance_task = get_sector_performance(ticker, trade_date)
            rotation_task = get_sector_rotation(trade_date)
            peer_task = get_peer_comparison(ticker, trade_date)

            performance_report, rotation_report, peer_report = await asyncio.gather(
                performance_task, rotation_task, peer_task
            )

            # 组合报告
            full_report = [
                "=" * 60,
                "🏭 板块分析师综合报告",
                "=" * 60,
                "",
                performance_report,
                "",
                rotation_report,
                "",
                peer_report,
                "",
                "=" * 60,
                "📋 分析结论",
                "=" * 60,
            ]

            full_report.append("请根据以上数据综合判断：")
            full_report.append("1. 目标股票所属板块是否处于热点轮动中")
            full_report.append("2. 个股在行业中的地位和估值水平")
            full_report.append("3. 板块资金流向是否支持当前投资方向")

        return "\n".join(full_report)

    except Exception as e:
        logger.error(f"综合板块分析失败: {e}")
        return f"❌ 综合板块分析失败: {e}"


# ==================== 同步包装函数 ====================
# 为 LangGraph 工具提供同步接口

def analyze_sector_sync(ticker: str, trade_date: str) -> str:
    """analyze_sector 的同步版本"""
    return asyncio.run(analyze_sector(ticker, trade_date))


def get_sector_performance_sync(ticker: str, trade_date: str, lookback_days: int = 20) -> str:
    """get_sector_performance 的同步版本"""
    return asyncio.run(get_sector_performance(ticker, trade_date, lookback_days))


def get_sector_rotation_sync(trade_date: str, top_n: int = 10) -> str:
    """get_sector_rotation 的同步版本"""
    return asyncio.run(get_sector_rotation(trade_date, top_n))


def get_peer_comparison_sync(ticker: str, trade_date: str, top_n: int = 10) -> str:
    """get_peer_comparison 的同步版本"""
    return asyncio.run(get_peer_comparison(ticker, trade_date, top_n))
