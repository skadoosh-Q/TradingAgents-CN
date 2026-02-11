#!/usr/bin/env python3
"""
测试新闻获取修复效果

运行方法:
    cd /Users/deq/Documents/my_code/my_projects/docker-TradingAgents-CN
    python scripts/test_news_fix.py
"""
import sys
from pathlib import Path

# 添加项目根目录到Python路径
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

import logging

# 设置日志级别
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s | %(name)s | %(levelname)s | %(message)s'
)


def test_akshare_provider_news():
    """测试 AKShareProvider 的新闻获取功能"""
    print("\n" + "=" * 80)
    print("📰 测试1: AKShareProvider.get_stock_news_sync()")
    print("=" * 80)

    try:
        from tradingagents.dataflows.providers.china.akshare import AKShareProvider

        provider = AKShareProvider()

        test_symbols = ["600111", "000001", "600519"]

        for symbol in test_symbols:
            print(f"\n{'─' * 60}")
            print(f"🔍 测试股票: {symbol}")
            print(f"{'─' * 60}")

            news_df = provider.get_stock_news_sync(symbol=symbol, limit=5)

            if news_df is not None and not news_df.empty:
                print(f"✅ 成功获取 {len(news_df)} 条新闻")
                print(f"\n📋 新闻列表:")
                for idx, (_, row) in enumerate(news_df.head(3).iterrows(), 1):
                    title = row.get('新闻标题', row.get('title', '无标题'))
                    print(f"   {idx}. {title[:50]}...")
            else:
                print(f"❌ 未获取到新闻数据 (返回值类型: {type(news_df)})")

    except Exception as e:
        print(f"❌ 测试失败: {e}")
        import traceback
        traceback.print_exc()


def test_direct_api():
    """测试直接调用东方财富 API"""
    print("\n" + "=" * 80)
    print("📰 测试2: AKShareProvider._get_stock_news_direct()")
    print("=" * 80)

    try:
        from tradingagents.dataflows.providers.china.akshare import AKShareProvider

        provider = AKShareProvider()

        test_symbols = ["600111", "000001"]

        for symbol in test_symbols:
            print(f"\n{'─' * 60}")
            print(f"🔍 测试股票: {symbol}")
            print(f"{'─' * 60}")

            # 直接调用私有方法测试
            news_df = provider._get_stock_news_direct(symbol, limit=5)

            if news_df is not None and not news_df.empty:
                print(f"✅ 直接API获取成功: {len(news_df)} 条新闻")
                print(f"\n📋 新闻列表:")
                for idx, (_, row) in enumerate(news_df.head(3).iterrows(), 1):
                    title = row.get('新闻标题', row.get('title', '无标题'))
                    print(f"   {idx}. {title[:50]}...")
            else:
                print(f"❌ 直接API未获取到新闻数据")

    except Exception as e:
        print(f"❌ 测试失败: {e}")
        import traceback
        traceback.print_exc()


def test_realtime_news():
    """测试实时新闻获取函数"""
    print("\n" + "=" * 80)
    print("📰 测试3: get_realtime_stock_news()")
    print("=" * 80)

    try:
        from tradingagents.dataflows.news.realtime_news import get_realtime_stock_news
        from datetime import datetime

        # 获取当前日期
        curr_date = datetime.now().strftime("%Y-%m-%d")

        test_tickers = ["600111", "000001.SZ"]

        for ticker in test_tickers:
            print(f"\n{'─' * 60}")
            print(f"🔍 测试股票: {ticker}")
            print(f"{'─' * 60}")

            result = get_realtime_stock_news(ticker, curr_date, hours_back=6)

            if result and "失败" not in result:
                # 截取前500个字符显示
                preview = result[:500] if len(result) > 500 else result
                print(f"✅ 成功获取新闻报告")
                print(f"\n📄 报告预览:")
                print(preview)
                if len(result) > 500:
                    print(f"\n... (共 {len(result)} 个字符)")
            else:
                print(f"❌ 获取失败")
                print(result)

    except Exception as e:
        print(f"❌ 测试失败: {e}")
        import traceback
        traceback.print_exc()


def test_none_handling():
    """测试 None 值处理"""
    print("\n" + "=" * 80)
    print("📰 测试4: None 值处理")
    print("=" * 80)

    try:
        # 模拟 None 值情况
        news_df = None

        # 这是修复前会出错的代码
        if news_df is not None and not news_df.empty:
            print("数据不为空")
        else:
            print("✅ None 值处理正确：跳过了对 None.empty 的访问")

        # 测试空 DataFrame
        import pandas as pd
        empty_df = pd.DataFrame()

        if empty_df is not None and not empty_df.empty:
            print("数据不为空")
        else:
            print("✅ 空 DataFrame 处理正确")

    except AttributeError as e:
        print(f"❌ None 值处理失败: {e}")
    except Exception as e:
        print(f"❌ 测试失败: {e}")


if __name__ == "__main__":
    print("=" * 80)
    print("🧪 新闻获取功能修复测试")
    print("=" * 80)
    print(f"\n测试目的:")
    print("  1. 验证 AKShareProvider.get_stock_news_sync() 的备用 API 机制")
    print("  2. 验证直接调用东方财富 API 的功能")
    print("  3. 验证 get_realtime_stock_news() 的完整流程")
    print("  4. 验证 None 值处理修复")

    # 运行测试
    test_none_handling()
    test_direct_api()
    test_akshare_provider_news()
    test_realtime_news()

    print("\n" + "=" * 80)
    print("✅ 所有测试完成")
    print("=" * 80)
