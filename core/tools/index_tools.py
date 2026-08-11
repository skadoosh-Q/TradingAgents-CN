"""
大盘/指数分析工具函数

提供指数走势分析、市场宽度分析、市场环境评估等功能
"""

import asyncio
import logging
from datetime import datetime, timedelta
from typing import Optional, Dict, Any, List

import pandas as pd

logger = logging.getLogger(__name__)


def _clean_date_string(date_str: str) -> str:
    """清理日期字符串，去掉可能的时间部分"""
    if not date_str:
        return date_str
    return date_str.split()[0] if ' ' in date_str else date_str

# 缓存管理器
_cache = None

def _get_cache():
    """获取缓存管理器实例"""
    global _cache
    if _cache is None:
        try:
            from tradingagents.dataflows.cache import get_cache
            _cache = get_cache()
            logger.info("✅ 指数分析工具已启用缓存")
        except Exception as e:
            logger.warning(f"⚠️ 缓存系统不可用: {e}")
    return _cache

# 主要指数代码
MAIN_INDICES = {
    '000001.SH': '上证指数',
    '399001.SZ': '深证成指',
    '399006.SZ': '创业板指',
    '000300.SH': '沪深300',
    '000905.SH': '中证500',
}


def _get_market_data_provider():
    """获取独立的免费 A 股市场数据接口。"""
    from core.data_sources import get_free_china_market_data

    return get_free_china_market_data()


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

            logger.debug(f"🔍 获取到 {len(df)} 个交易日，最新: {latest_trade_date}, 请求: {trade_date_clean}")

            if latest_trade_date != trade_date_clean:
                logger.info(f"📅 {trade_date} 无数据，使用最近交易日 {latest_trade_date}")
            else:
                logger.debug(f"✅ {trade_date} 是有效交易日")

            return latest_trade_date

        # 如果都没有找到，返回原始日期
        logger.warning(f"⚠️ 无法找到有效交易日，使用原始日期 {trade_date_clean}")
        return trade_date_clean

    except Exception as e:
        logger.error(f"❌ 获取最新交易日失败: {e}")
        return trade_date_clean


async def get_index_trend(
    trade_date: str,
    lookback_days: int = 60
) -> str:
    """
    分析主要指数走势
    
    Args:
        trade_date: 交易日期
        lookback_days: 回看天数
    
    Returns:
        指数走势分析报告
    """
    provider = _get_market_data_provider()
    
    try:
        # 计算日期范围
        # 清理日期字符串，去掉可能的时间部分
        trade_date_clean = _clean_date_string(trade_date).replace('-', '')
        end_date = datetime.strptime(trade_date_clean, '%Y%m%d')
        start_date = end_date - timedelta(days=lookback_days + 30)
        start_date_str = start_date.strftime('%Y%m%d')
        end_date_str = trade_date_clean
        
        report_lines = [
            "📈 主要指数走势分析",
            "=" * 50,
            f"📅 分析日期: {trade_date}",
            f"📆 回看周期: {lookback_days} 交易日",
            "",
            "【主要指数表现】",
        ]
        
        for index_code, index_name in MAIN_INDICES.items():
            daily_df = await provider.get_index_daily(
                ts_code=index_code,
                start_date=start_date_str,
                end_date=end_date_str
            )
            
            if daily_df is None or daily_df.empty:
                report_lines.append(f"  {index_name}: 暂无数据")
                continue
            
            # 按日期排序
            daily_df = daily_df.sort_values('trade_date')
            
            if len(daily_df) < 5:
                report_lines.append(f"  {index_name}: 数据不足")
                continue
            
            # 计算指标
            latest = daily_df.iloc[-1]
            today_pct = latest.get('pct_chg', 0)
            close_price = latest.get('close', 0)
            latest_date = str(latest.get('trade_date', end_date_str))
            latest_date_display = (
                f"{latest_date[:4]}-{latest_date[4:6]}-{latest_date[6:8]}"
                if len(latest_date) >= 8 else latest_date
            )
            
            # 5日/20日/60日涨跌幅
            pct_5d = ((close_price / daily_df.iloc[-5]['close']) - 1) * 100 if len(daily_df) >= 5 else 0
            pct_20d = ((close_price / daily_df.iloc[-20]['close']) - 1) * 100 if len(daily_df) >= 20 else 0
            
            # 均线位置
            ma5 = daily_df['close'].tail(5).mean()
            ma20 = daily_df['close'].tail(20).mean() if len(daily_df) >= 20 else ma5
            ma60 = daily_df['close'].tail(60).mean() if len(daily_df) >= 60 else ma20
            
            # 趋势判断
            if close_price > ma5 > ma20 > ma60:
                trend = "📈 多头排列"
            elif close_price < ma5 < ma20 < ma60:
                trend = "📉 空头排列"
            else:
                trend = "📊 震荡整理"
            
            trend_icon = "🔴" if today_pct > 0 else "🟢" if today_pct < 0 else "⚪"
            
            report_lines.append(
                f"  {trend_icon} {index_name}({index_code}): {close_price:.2f}"
            )
            report_lines.append(
                f"      {latest_date_display}: {today_pct:+.2f}% | 5日: {pct_5d:+.2f}% | "
                f"20日: {pct_20d:+.2f}% | {trend}"
            )
        
        return "\n".join(report_lines)
        
    except Exception as e:
        logger.error(f"指数走势分析失败: {e}")
        return f"❌ 指数走势分析失败: {e}"


async def get_market_breadth(trade_date: str) -> str:
    """
    分析市场宽度（涨跌家数、涨停跌停等）

    Args:
        trade_date: 交易日期

    Returns:
        市场宽度分析报告
    """
    provider = _get_market_data_provider()

    try:
        activity = await provider.get_market_activity()
        report_lines = [
            "",
            "📊 市场宽度分析",
            "=" * 50,
            f"📅 分析日期: {_clean_date_string(trade_date)}",
            "",
        ]
        if not activity:
            report_lines.append("⚠️ 暂无市场宽度数据（免费数据源暂时不可用）")
            return "\n".join(report_lines)

        requested_date = _clean_date_string(trade_date).replace("-", "")
        activity_date = str(activity.get("data_time", ""))[:10].replace("-", "")
        if activity_date and activity_date != requested_date:
            report_lines.append(
                f"⚠️ 暂无 {trade_date} 的历史市场宽度，未使用 {activity_date} 的当前快照替代"
            )
            return "\n".join(report_lines)

        up_count = activity["up_count"]
        down_count = activity["down_count"]
        flat_count = activity["flat_count"]
        total_count = up_count + down_count + flat_count
        up_ratio = up_count / total_count * 100 if total_count else 0
        down_ratio = down_count / total_count * 100 if total_count else 0
        breadth = up_count - down_count

        report_lines.extend(
            [
                "【涨跌分布】",
                f"  • 上涨: {up_count} 家 ({up_ratio:.1f}%)",
                f"  • 下跌: {down_count} 家 ({down_ratio:.1f}%)",
                f"  • 平盘: {flat_count} 家",
                f"  • 涨跌家数差: {breadth:+d}",
                "",
                "【极端波动】",
                f"  • 涨停: {activity['limit_up_count']} 家",
                f"  • 跌停: {activity['limit_down_count']} 家",
                f"  • 市场活跃度: {activity['activity_rate']:.2f}%",
            ]
        )
        if activity.get("data_time"):
            report_lines.append(f"  • 数据时间: {activity['data_time']}")
        return "\n".join(report_lines)

    except Exception as e:
        logger.error(f"市场宽度分析失败: {e}")
        return f"❌ 市场宽度分析失败: {e}"


async def get_market_environment(trade_date: str) -> str:
    """
    评估市场环境（估值、风险等）

    Args:
        trade_date: 交易日期

    Returns:
        市场环境评估报告
    """
    provider = _get_market_data_provider()

    try:
        # 清理日期字符串（移除可能的时间部分）
        trade_date_display = _clean_date_string(trade_date)
        trade_date_clean = trade_date_display.replace('-', '')

        report_lines = [
            "",
            "🌐 市场环境评估",
            "=" * 50,
            f"📅 日期: {trade_date_display}",
            "",
            "【A股整体估值水平】",
        ]
        valuation = await provider.get_market_valuation()
        if valuation is not None and not valuation.empty:
            available = valuation[valuation["trade_date"] <= trade_date_clean]
            row = (available if not available.empty else valuation).iloc[-1]
            report_lines.extend(
                [
                    f"  • 全A滚动PE中位数: {row.get('pe_ttm_median', 'N/A')}",
                    f"  • 全A滚动PE均值: {row.get('pe_ttm_mean', 'N/A')}",
                    f"  • 静态PE中位数: {row.get('pe_lyr_median', 'N/A')}",
                    f"  • 估值数据日期: {row.get('trade_date', 'N/A')}",
                ]
            )
        else:
            report_lines.append("  ⚠️ 暂无可靠的免费估值数据")

        # 风险评估
        report_lines.append("")
        report_lines.append("【风险评估】")

        # 获取上证指数近期数据计算波动率
        daily_df = await provider.get_index_daily(
            ts_code='000001.SH',
            start_date=(datetime.strptime(trade_date_clean, '%Y%m%d') - timedelta(days=30)).strftime('%Y%m%d'),
            end_date=trade_date_clean
        )

        if daily_df is not None and len(daily_df) >= 20:
            # 计算20日波动率
            returns = daily_df['pct_chg'].dropna()
            volatility = returns.std() * (252 ** 0.5)  # 年化波动率

            if volatility > 30:
                risk_level = "高风险 🔴"
            elif volatility > 20:
                risk_level = "中等风险 🟡"
            else:
                risk_level = "低风险 🟢"

            report_lines.append(f"  • 20日年化波动率: {volatility:.2f}% ({risk_level})")

        return "\n".join(report_lines)

    except Exception as e:
        logger.error(f"市场环境评估失败: {e}")
        return f"❌ 市场环境评估失败: {e}"


async def identify_market_cycle(trade_date: str) -> str:
    """
    识别市场周期（牛市/熊市/震荡市）

    Args:
        trade_date: 交易日期

    Returns:
        市场周期判断报告
    """
    provider = _get_market_data_provider()

    try:
        # 清理日期字符串，去掉可能的时间部分
        trade_date_clean = _clean_date_string(trade_date).replace('-', '')
        end_date = datetime.strptime(trade_date_clean, '%Y%m%d')
        start_date = end_date - timedelta(days=365)  # 一年数据

        # 获取上证指数数据
        daily_df = await provider.get_index_daily(
            ts_code='000001.SH',
            start_date=start_date.strftime('%Y%m%d'),
            end_date=trade_date_clean
        )

        report_lines = [
            "",
            "🔄 市场周期判断",
            "=" * 50,
        ]

        if daily_df is None or len(daily_df) < 60:
            report_lines.append("⚠️ 数据不足，无法判断市场周期")
            return "\n".join(report_lines)

        daily_df = daily_df.sort_values('trade_date')

        current_close = daily_df.iloc[-1]['close']
        ma60 = daily_df['close'].tail(60).mean()
        ma120 = daily_df['close'].tail(120).mean() if len(daily_df) >= 120 else ma60
        ma250 = daily_df['close'].tail(250).mean() if len(daily_df) >= 250 else ma120

        # 计算年内高低点
        year_high = daily_df['high'].max()
        year_low = daily_df['low'].min()
        position = (current_close - year_low) / (year_high - year_low) * 100 if year_high != year_low else 50

        # 周期判断
        if current_close > ma60 > ma120 > ma250:
            cycle = "牛市阶段 🐂"
            advice = "趋势向上，可适度积极"
        elif current_close < ma60 < ma120 < ma250:
            cycle = "熊市阶段 🐻"
            advice = "趋势向下，建议防守"
        elif current_close > ma60 and current_close > ma120:
            cycle = "反弹阶段 📈"
            advice = "短期走强，关注持续性"
        elif current_close < ma60 and current_close < ma120:
            cycle = "调整阶段 📉"
            advice = "短期走弱，等待企稳"
        else:
            cycle = "震荡阶段 📊"
            advice = "方向不明，轻仓观望"

        report_lines.append(f"  🎯 市场周期: {cycle}")
        report_lines.append(f"  📍 年内位置: {position:.1f}% (0%=年内低点, 100%=年内高点)")
        report_lines.append(f"  💡 操作建议: {advice}")
        report_lines.append("")
        report_lines.append("【均线系统】")
        report_lines.append(f"  • 当前价格: {current_close:.2f}")
        report_lines.append(f"  • MA60: {ma60:.2f} ({'↑' if current_close > ma60 else '↓'})")
        report_lines.append(f"  • MA120: {ma120:.2f} ({'↑' if current_close > ma120 else '↓'})")
        report_lines.append(f"  • MA250: {ma250:.2f} ({'↑' if current_close > ma250 else '↓'})")

        return "\n".join(report_lines)

    except Exception as e:
        logger.error(f"市场周期判断失败: {e}")
        return f"❌ 市场周期判断失败: {e}"


async def analyze_index(trade_date: str) -> str:
    """
    综合大盘分析（IndexAnalyst 主入口）

    整合指数走势、市场宽度、市场环境、市场周期四个维度的分析

    Args:
        trade_date: 交易日期

    Returns:
        综合大盘分析报告
    """
    try:
        # 首先获取最新可用的交易日
        actual_trade_date = await _get_latest_trade_date(trade_date)
        actual_trade_date_formatted = f"{actual_trade_date[:4]}-{actual_trade_date[4:6]}-{actual_trade_date[6:8]}"

        logger.info(f"📊 大盘分析使用交易日: {actual_trade_date_formatted}")

        # 并行获取四个分析结果
        trend_task = get_index_trend(actual_trade_date_formatted)
        breadth_task = get_market_breadth(actual_trade_date_formatted)
        env_task = get_market_environment(actual_trade_date_formatted)
        cycle_task = identify_market_cycle(actual_trade_date_formatted)

        trend_report, breadth_report, env_report, cycle_report = await asyncio.gather(
            trend_task, breadth_task, env_task, cycle_task
        )

        # 组合报告
        full_report = [
            "=" * 60,
            "🌐 大盘分析师综合报告",
            f"📅 分析日期: {actual_trade_date_formatted}",
            "=" * 60,
            "",
            trend_report,
            breadth_report,
            env_report,
            cycle_report,
            "",
            "=" * 60,
        ]

        return "\n".join(full_report)

    except Exception as e:
        logger.error(f"综合大盘分析失败: {e}")
        return f"❌ 综合大盘分析失败: {e}"


# ==================== 同步包装函数 ====================

def analyze_index_sync(trade_date: str) -> str:
    """analyze_index 的同步版本"""
    return asyncio.run(analyze_index(trade_date))


def get_index_trend_sync(trade_date: str, lookback_days: int = 60) -> str:
    """get_index_trend 的同步版本"""
    return asyncio.run(get_index_trend(trade_date, lookback_days))


def get_market_breadth_sync(trade_date: str) -> str:
    """get_market_breadth 的同步版本"""
    return asyncio.run(get_market_breadth(trade_date))


def get_market_environment_sync(trade_date: str) -> str:
    """get_market_environment 的同步版本"""
    return asyncio.run(get_market_environment(trade_date))


def identify_market_cycle_sync(trade_date: str) -> str:
    """identify_market_cycle 的同步版本"""
    return asyncio.run(identify_market_cycle(trade_date))


# ==================== 新增大盘分析工具 ====================

async def get_north_flow(trade_date: str, lookback_days: int = 10) -> str:
    """
    获取北向资金流向分析

    Args:
        trade_date: 交易日期 (YYYY-MM-DD)
        lookback_days: 回看天数

    Returns:
        北向资金流向分析报告
    """
    provider = _get_market_data_provider()

    try:
        df = await provider.get_northbound_summary()
        report_lines = [
            "",
            "💰 沪深股通公开信息",
            "=" * 50,
            f"📅 日期: {_clean_date_string(trade_date)}",
            "",
            "【披露口径说明】",
            "  • 2024-08-19起，交易所不再披露北向每日买入、卖出及净买入额",
            "  • 免费接口中的净流入零值不代表真实资金为零，本报告不会据此判断外资方向",
        ]
        if df is None or df.empty:
            report_lines.append("  ⚠️ 暂未获取到沪深股通交易状态")
            return "\n".join(report_lines)

        report_lines.extend(["", "【当日通道状态】"])
        for _, row in df.iterrows():
            status = "交易中/已开通" if str(row.get("status", "")) == "1" else str(row.get("status", "未知"))
            report_lines.append(
                f"  • {row.get('channel', '北向通道')}: {status} | "
                f"相关指数 {row.get('related_index', 'N/A')} "
                f"{float(row.get('index_pct_chg', 0) or 0):+.2f}%"
            )
        report_lines.extend(
            [
                "",
                "【分析约束】",
                "  • 不生成近5日/10日净流入趋势，也不据此判断外资加仓或撤离",
                "  • 可结合收盘后成交总额、活跃证券及季度持仓变化进行辅助观察",
            ]
        )
        return "\n".join(report_lines)

    except Exception as e:
        logger.error(f"北向资金分析失败: {e}")
        return f"❌ 北向资金分析失败: {e}"


async def get_margin_trading(trade_date: str, lookback_days: int = 10) -> str:
    """
    获取两融余额分析

    Args:
        trade_date: 交易日期 (YYYY-MM-DD)
        lookback_days: 回看天数

    Returns:
        两融余额分析报告
    """
    provider = _get_market_data_provider()

    try:
        df = await provider.get_margin_summary(_clean_date_string(trade_date), lookback_days)

        report_lines = [
            "",
            "📊 两融余额分析",
            "=" * 50,
            f"📅 日期: {trade_date}",
            "",
        ]

        if df is None or df.empty:
            report_lines.append("⚠️ 暂无两融数据（交易所免费接口暂时不可用）")
            return "\n".join(report_lines)

        df = df.sort_values('trade_date', ascending=False)
        latest = df.iloc[0]
        latest_date = str(latest['trade_date'])
        rzye = float(latest['financing_balance']) / 100000000
        rqye = float(latest['securities_balance']) / 100000000
        rzrqye = float(latest['margin_balance']) / 100000000

        report_lines.append(f"【最新两融余额（{latest_date}）】")
        report_lines.append(f"  • 融资余额: {rzye:.2f} 亿元")
        report_lines.append(f"  • 融券余额: {rqye:.2f} 亿元")
        report_lines.append(f"  • 两融余额: {rzrqye:.2f} 亿元")

        # 计算变化
        if len(df) >= 2:
            prev_rzye = float(df.iloc[1]['financing_balance']) / 100000000
            change = rzye - prev_rzye
            change_icon = "🔴" if change > 0 else "🟢"
            change_text = "增加" if change > 0 else "减少"
            report_lines.append(f"  • 融资变化: {change_icon} {abs(change):.2f} 亿元 ({change_text})")

        # 近期趋势
        if len(df) >= 5:
            report_lines.append("")
            report_lines.append("【近期趋势】")
            first_rzye = float(df.iloc[-1]['financing_balance']) / 100000000
            total_change = rzye - first_rzye
            report_lines.append(f"  • 近{len(df)}个数据日融资变化: {total_change:.2f} 亿元")

        # 杠杆情绪判断
        report_lines.append("")
        report_lines.append("【杠杆情绪】")
        if rzye > 17000:
            sentiment = "杠杆资金活跃 🔥"
        elif rzye > 15000:
            sentiment = "杠杆资金正常 📊"
        elif rzye > 13000:
            sentiment = "杠杆资金谨慎 📉"
        else:
            sentiment = "杠杆资金低迷 ❄️"
        report_lines.append(f"  • {sentiment}")

        return "\n".join(report_lines)

    except Exception as e:
        logger.error(f"两融余额分析失败: {e}")
        return f"❌ 两融余额分析失败: {e}"


async def get_limit_stats(trade_date: str) -> str:
    """
    获取涨跌停统计和涨跌家数分析

    Args:
        trade_date: 交易日期 (YYYY-MM-DD)

    Returns:
        涨跌停和涨跌家数分析报告
    """
    provider = _get_market_data_provider()

    try:
        actual_date = await _get_latest_trade_date(trade_date)
        actual_date_formatted = f"{actual_date[:4]}-{actual_date[4:6]}-{actual_date[6:8]}"

        report_lines = [
            "",
            "📈 涨跌停与涨跌家数分析",
            "=" * 50,
            f"📅 日期: {actual_date_formatted}",
            "",
        ]

        activity, pools = await asyncio.gather(
            provider.get_market_activity(),
            provider.get_limit_pools(actual_date),
        )
        activity_date = str(activity.get("data_time", ""))[:10].replace("-", "")
        activity_matches = activity and activity_date == actual_date

        if activity_matches:
            total = activity["up_count"] + activity["down_count"] + activity["flat_count"]
            up_ratio = activity["up_count"] / total * 100 if total else 0
            down_ratio = activity["down_count"] / total * 100 if total else 0
            report_lines.append("【涨跌家数】")
            report_lines.append(f"  • 上涨: {activity['up_count']} 家 ({up_ratio:.1f}%)")
            report_lines.append(f"  • 下跌: {activity['down_count']} 家 ({down_ratio:.1f}%)")
            report_lines.append(f"  • 平盘: {activity['flat_count']} 家")
            report_lines.append(f"  • 涨跌比: {activity['up_count']}:{activity['down_count']}")

            report_lines.append("")
            report_lines.append("【涨跌停统计】")
            report_lines.append(f"  • 涨停: {activity['limit_up_count']} 家")
            report_lines.append(f"  • 跌停: {activity['limit_down_count']} 家")
            report_lines.append("")
            report_lines.append("【市场情绪】")
            if up_ratio > 70:
                sentiment = "极度乐观 🔥"
            elif up_ratio > 55:
                sentiment = "偏向乐观 📈"
            elif up_ratio > 45:
                sentiment = "中性震荡 📊"
            elif up_ratio > 30:
                sentiment = "偏向悲观 📉"
            else:
                sentiment = "极度悲观 ❄️"
            report_lines.append(
                f"  • {sentiment} (涨跌比 {activity['up_count']}:{activity['down_count']})"
            )
        else:
            report_lines.append("⚠️ 该日期暂无匹配的全市场涨跌家数数据")

        limit_up_df = pools.get("limit_up", pd.DataFrame())
        limit_down_df = pools.get("limit_down", pd.DataFrame())
        if not limit_up_df.empty or not limit_down_df.empty:
            report_lines.extend(
                [
                    "",
                    "【涨跌停池详情】",
                    f"  • 涨停池: {len(limit_up_df)} 家",
                    f"  • 跌停池: {len(limit_down_df)} 家",
                ]
            )
            if "连板数" in limit_up_df.columns:
                multi_board = int((pd.to_numeric(limit_up_df["连板数"], errors="coerce") >= 2).sum())
                report_lines.append(f"  • 连板股: {multi_board} 家")

        return "\n".join(report_lines)

    except Exception as e:
        logger.error(f"涨跌停统计失败: {e}")
        return f"❌ 涨跌停统计失败: {e}"


async def get_index_technical(trade_date: str, lookback_days: int = 60) -> str:
    """
    获取指数技术指标分析（MACD, RSI, KDJ）

    Args:
        trade_date: 交易日期 (YYYY-MM-DD)
        lookback_days: 回看天数

    Returns:
        指数技术指标分析报告
    """
    provider = _get_market_data_provider()

    try:
        # 清理日期字符串，去掉可能的时间部分
        trade_date_clean = _clean_date_string(trade_date).replace('-', '')
        end_date = datetime.strptime(trade_date_clean, '%Y%m%d')
        start_date = end_date - timedelta(days=lookback_days + 30)

        report_lines = [
            "",
            "📉 指数技术指标分析",
            "=" * 50,
            f"📅 日期: {trade_date}",
            "",
        ]

        # 分析上证指数的技术指标
        index_code = '000001.SH'
        index_name = '上证指数'

        df = await provider.get_index_daily(
            ts_code=index_code,
            start_date=start_date.strftime('%Y%m%d'),
            end_date=trade_date_clean
        )

        if df is None or len(df) < 30:
            report_lines.append("⚠️ 数据不足，无法计算技术指标")
            return "\n".join(report_lines)

        df = df.sort_values('trade_date').reset_index(drop=True)
        latest_data_date = str(df.iloc[-1].get('trade_date', trade_date_clean))
        report_lines.append(
            f"📌 指标数据截止: {latest_data_date[:4]}-{latest_data_date[4:6]}-{latest_data_date[6:8]}"
        )
        report_lines.append("")

        # 计算技术指标
        close = df['close']

        # MACD
        ema12 = close.ewm(span=12, adjust=False).mean()
        ema26 = close.ewm(span=26, adjust=False).mean()
        dif = ema12 - ema26
        dea = dif.ewm(span=9, adjust=False).mean()
        macd = (dif - dea) * 2

        # RSI
        delta = close.diff()
        gain = (delta.where(delta > 0, 0)).rolling(window=14).mean()
        loss = (-delta.where(delta < 0, 0)).rolling(window=14).mean()
        rs = gain / loss
        rsi = 100 - (100 / (1 + rs))

        # KDJ
        low_min = df['low'].rolling(window=9).min()
        high_max = df['high'].rolling(window=9).max()
        rsv = (close - low_min) / (high_max - low_min) * 100
        k = rsv.ewm(com=2, adjust=False).mean()
        d = k.ewm(com=2, adjust=False).mean()
        j = 3 * k - 2 * d

        # 获取最新值
        latest_dif = dif.iloc[-1]
        latest_dea = dea.iloc[-1]
        latest_macd = macd.iloc[-1]
        latest_rsi = rsi.iloc[-1]
        latest_k = k.iloc[-1]
        latest_d = d.iloc[-1]
        latest_j = j.iloc[-1]

        report_lines.append(f"【{index_name} 技术指标】")
        report_lines.append("")

        # MACD 分析
        report_lines.append("📊 MACD 指标:")
        report_lines.append(f"  • DIF: {latest_dif:.2f}")
        report_lines.append(f"  • DEA: {latest_dea:.2f}")
        report_lines.append(f"  • MACD柱: {latest_macd:.2f}")

        macd_signal = ""
        if latest_dif > latest_dea:
            if latest_dif > 0:
                macd_signal = "多头趋势，DIF在零轴上方 📈"
            else:
                macd_signal = "底部金叉形成，待确认 🔄"
        else:
            if latest_dif < 0:
                macd_signal = "空头趋势，DIF在零轴下方 📉"
            else:
                macd_signal = "顶部死叉形成，注意风险 ⚠️"
        report_lines.append(f"  • 信号: {macd_signal}")

        # RSI 分析
        report_lines.append("")
        report_lines.append("📊 RSI 指标:")
        report_lines.append(f"  • RSI(14): {latest_rsi:.2f}")

        if latest_rsi > 80:
            rsi_signal = "超买区域，注意回调风险 🔴"
        elif latest_rsi > 70:
            rsi_signal = "偏强，接近超买 📈"
        elif latest_rsi > 50:
            rsi_signal = "多方占优 📊"
        elif latest_rsi > 30:
            rsi_signal = "空方占优 📉"
        elif latest_rsi > 20:
            rsi_signal = "偏弱，接近超卖 📉"
        else:
            rsi_signal = "超卖区域，关注反弹机会 🟢"
        report_lines.append(f"  • 信号: {rsi_signal}")

        # KDJ 分析
        report_lines.append("")
        report_lines.append("📊 KDJ 指标:")
        report_lines.append(f"  • K: {latest_k:.2f}")
        report_lines.append(f"  • D: {latest_d:.2f}")
        report_lines.append(f"  • J: {latest_j:.2f}")

        if latest_k > latest_d and latest_j > 80:
            kdj_signal = "高位金叉，注意回调 ⚠️"
        elif latest_k > latest_d:
            kdj_signal = "金叉向上，多头信号 📈"
        elif latest_k < latest_d and latest_j < 20:
            kdj_signal = "低位死叉，关注反弹 🔄"
        else:
            kdj_signal = "死叉向下，空头信号 📉"
        report_lines.append(f"  • 信号: {kdj_signal}")

        # 综合判断
        report_lines.append("")
        report_lines.append("【技术面综合】")
        bull_signals = 0
        bear_signals = 0

        if latest_dif > latest_dea:
            bull_signals += 1
        else:
            bear_signals += 1

        if latest_rsi > 50:
            bull_signals += 1
        else:
            bear_signals += 1

        if latest_k > latest_d:
            bull_signals += 1
        else:
            bear_signals += 1

        if bull_signals >= 2:
            summary = f"技术面偏多 📈 ({bull_signals}/3 指标看多)"
        elif bear_signals >= 2:
            summary = f"技术面偏空 📉 ({bear_signals}/3 指标看空)"
        else:
            summary = "技术面中性 📊 (多空信号分歧)"
        report_lines.append(f"  • {summary}")

        return "\n".join(report_lines)

    except Exception as e:
        logger.error(f"指数技术指标分析失败: {e}")
        return f"❌ 指数技术指标分析失败: {e}"


# 同步包装函数
def get_north_flow_sync(trade_date: str, lookback_days: int = 10) -> str:
    """get_north_flow 的同步版本"""
    return asyncio.run(get_north_flow(trade_date, lookback_days))


def get_margin_trading_sync(trade_date: str, lookback_days: int = 10) -> str:
    """get_margin_trading 的同步版本"""
    return asyncio.run(get_margin_trading(trade_date, lookback_days))


def get_limit_stats_sync(trade_date: str) -> str:
    """get_limit_stats 的同步版本"""
    return asyncio.run(get_limit_stats(trade_date))


def get_index_technical_sync(trade_date: str, lookback_days: int = 60) -> str:
    """get_index_technical 的同步版本"""
    return asyncio.run(get_index_technical(trade_date, lookback_days))
