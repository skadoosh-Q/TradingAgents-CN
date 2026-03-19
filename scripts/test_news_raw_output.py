#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
新闻原始数据验证脚本

⚠️ 此脚本需要在 Docker 容器内运行！

用法 (宿主机):
    docker exec -it tradingagents-backend python scripts/test_news_raw_output.py 600968
    docker exec -it tradingagents-backend python scripts/test_news_raw_output.py 600968 --limit 20
    docker exec -it tradingagents-backend python scripts/test_news_raw_output.py 600968 --source all
    docker exec -it tradingagents-backend python scripts/test_news_raw_output.py 600968 --source akshare
    docker exec -it tradingagents-backend python scripts/test_news_raw_output.py 600968 --source eastmoney
    docker exec -it tradingagents-backend python scripts/test_news_raw_output.py 600968 --source google

功能:
    直接调用底层新闻获取接口，输出原始新闻数据（标题、内容、时间、来源、链接），
    方便验证新闻数据的实时性和准确性。
"""

import os
import sys
import argparse
import re
from datetime import datetime, timedelta
from pathlib import Path

# 添加项目根目录到 Python 路径
# Docker 容器内项目在 /app
# 本地运行时在 scripts 的上级目录
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

# 尝试加载 .env 文件
try:
    from dotenv import load_dotenv
    load_dotenv(project_root / ".env")
except ImportError:
    pass  # dotenv 可能未安装，容器内环境变量已设置


def print_header(title: str):
    """打印美化的标题"""
    width = 80
    print("\n" + "=" * width)
    print(f"  {title}")
    print("=" * width)


def print_news_item(index: int, title: str, content: str, time_str: str,
                     source: str, url: str):
    """打印单条新闻"""
    print(f"\n{'─' * 70}")
    print(f"  📰 [{index}] {title}")
    print(f"  🕐 时间: {time_str}")
    print(f"  📌 来源: {source}")
    if url:
        print(f"  🔗 链接: {url[:120]}{'...' if len(url) > 120 else ''}")
    if content:
        # 限制内容长度，但保留足够多用于验证
        content_preview = content[:500] + '...' if len(content) > 500 else content
        # 去除 HTML 标签
        content_preview = re.sub(r'<[^>]+>', '', content_preview)
        content_preview = content_preview.strip()
        if content_preview:
            print(f"  📝 内容: {content_preview}")


def test_akshare_sync(symbol: str, limit: int):
    """测试 AKShare 同步方式获取新闻（东方财富接口）
    
    这是项目中 A 股新闻的主要数据源。
    内部调用 akshare 库的 ak.stock_news_em() 函数，
    实际上是请求东方财富网的搜索 API 获取新闻。
    """
    print_header(f"📡 数据源: AKShare/东方财富 - {symbol}")
    print(f"  💡 说明: 调用 akshare 库 → 东方财富搜索 API")
    
    try:
        from tradingagents.dataflows.providers.china.akshare import AKShareProvider
        
        provider = AKShareProvider()
        print(f"  ✅ AKShare Provider 初始化成功")
        print(f"  🔍 正在获取 {symbol} 的新闻...")
        
        start_time = datetime.now()
        news_df = provider.get_stock_news_sync(symbol=symbol, limit=limit)
        elapsed = (datetime.now() - start_time).total_seconds()
        
        print(f"  ⏱️  耗时: {elapsed:.2f} 秒")
        
        if news_df is not None and not news_df.empty:
            print(f"  ✅ 获取到 {len(news_df)} 条新闻")
            print(f"  📊 DataFrame 列名: {list(news_df.columns)}")
            
            for idx, (_, row) in enumerate(news_df.iterrows(), 1):
                title = str(row.get('新闻标题', row.get('title', '无标题')))
                content = str(row.get('新闻内容', row.get('content', '')))
                time_str = str(row.get('发布时间', row.get('publish_time', '未知')))
                source = str(row.get('新闻来源', row.get('source', '东方财富')))
                url = str(row.get('新闻链接', row.get('url', '')))
                
                print_news_item(idx, title, content, time_str, source, url)
            
            # 时间统计
            print(f"\n  {'─' * 50}")
            print(f"  📅 新闻时间统计:")
            times = []
            for _, row in news_df.iterrows():
                t = row.get('发布时间', row.get('publish_time', ''))
                if t:
                    try:
                        if isinstance(t, datetime):
                            times.append(t)
                        elif isinstance(t, str):
                            for fmt in ['%Y-%m-%d %H:%M:%S', '%Y-%m-%d']:
                                try:
                                    times.append(datetime.strptime(t, fmt))
                                    break
                                except:
                                    continue
                    except:
                        pass
            
            if times:
                latest = max(times)
                oldest = min(times)
                now = datetime.now()
                print(f"  ✅ 最新新闻: {latest.strftime('%Y-%m-%d %H:%M:%S')}")
                print(f"  ✅ 最旧新闻: {oldest.strftime('%Y-%m-%d %H:%M:%S')}")
                diff = now - latest
                hours_ago = diff.total_seconds() / 3600
                if hours_ago < 1:
                    print(f"  🟢 最新新闻距现在: {diff.total_seconds()/60:.0f} 分钟 (非常新)")
                elif hours_ago < 24:
                    print(f"  🟡 最新新闻距现在: {hours_ago:.1f} 小时")
                else:
                    print(f"  🔴 最新新闻距现在: {diff.days} 天 {diff.seconds//3600} 小时 (较旧)")
            
            return len(news_df)
        else:
            print(f"  ❌ 未获取到新闻数据")
            return 0
            
    except Exception as e:
        print(f"  ❌ 获取失败: {e}")
        import traceback
        traceback.print_exc()
        return 0


def test_eastmoney_direct(symbol: str, limit: int):
    """测试直接调用东方财富搜索 API（绕过 akshare 库）"""
    print_header(f"📡 数据源: 东方财富直接 API - {symbol}")
    print(f"  💡 说明: 直接调用 search-api-web.eastmoney.com 接口")
    
    try:
        from tradingagents.dataflows.providers.china.akshare import AKShareProvider
        
        provider = AKShareProvider()
        symbol_6 = symbol.zfill(6)
        
        print(f"  🔍 正在直接调用东方财富搜索 API...")
        
        start_time = datetime.now()
        news_df = provider._get_stock_news_direct(symbol_6, limit)
        elapsed = (datetime.now() - start_time).total_seconds()
        
        print(f"  ⏱️  耗时: {elapsed:.2f} 秒")
        
        if news_df is not None and not news_df.empty:
            print(f"  ✅ 获取到 {len(news_df)} 条新闻")
            print(f"  📊 DataFrame 列名: {list(news_df.columns)}")
            
            for idx, (_, row) in enumerate(news_df.iterrows(), 1):
                title = str(row.get('新闻标题', '无标题'))
                content = str(row.get('新闻内容', ''))
                time_str = str(row.get('发布时间', '未知'))
                source = str(row.get('新闻来源', '东方财富'))
                url = str(row.get('新闻链接', ''))
                
                print_news_item(idx, title, content, time_str, source, url)
            
            return len(news_df)
        else:
            print(f"  ❌ 未获取到新闻数据")
            return 0
            
    except Exception as e:
        print(f"  ❌ 获取失败: {e}")
        import traceback
        traceback.print_exc()
        return 0


def test_realtime_aggregator(symbol: str):
    """测试实时新闻聚合器（FinnHub / Alpha Vantage / 东方财富）"""
    print_header(f"📡 数据源: 实时新闻聚合器 - {symbol}")
    print(f"  💡 说明: 聚合 FinnHub + Alpha Vantage + 东方财富/AKShare + 财联社RSS")
    
    try:
        from tradingagents.dataflows.news.realtime_news import RealtimeNewsAggregator
        
        aggregator = RealtimeNewsAggregator()
        
        print(f"  📋 可用新闻源:")
        print(f"     - FinnHub API: {'✅ 已配置' if aggregator.finnhub_key else '❌ 未配置'}")
        print(f"     - Alpha Vantage: {'✅ 已配置' if aggregator.alpha_vantage_key else '❌ 未配置'}")
        print(f"     - 东方财富/AKShare: ✅ 内置")
        print(f"  🔍 正在獲取新闻...")
        
        start_time = datetime.now()
        news_items = aggregator.get_realtime_stock_news(symbol, hours_back=72, max_news=10)
        elapsed = (datetime.now() - start_time).total_seconds()
        
        print(f"  ⏱️  耗时: {elapsed:.2f} 秒")
        
        if news_items:
            print(f"  ✅ 获取到 {len(news_items)} 条新闻")
            
            for idx, item in enumerate(news_items, 1):
                time_str = item.publish_time.strftime('%Y-%m-%d %H:%M:%S') if item.publish_time else '未知'
                print_news_item(idx, item.title, item.content, time_str, item.source, item.url)
            
            return len(news_items)
        else:
            print(f"  ❌ 未获取到新闻数据")
            return 0
            
    except Exception as e:
        print(f"  ❌ 获取失败: {e}")
        import traceback
        traceback.print_exc()
        return 0


def test_google_news(symbol: str):
    """测试 Google 新闻爬虫"""
    print_header(f"📡 数据源: Google 新闻 - {symbol}")
    print(f"  💡 说明: 爬取 Google 新闻搜索页面")
    print(f"  ⚠️  注意: 需要容器内能访问 Google（可能需要代理）")
    
    try:
        from tradingagents.dataflows.news.google_news import getNewsData
        
        end_date = datetime.now().strftime("%Y-%m-%d")
        start_date = (datetime.now() - timedelta(days=7)).strftime("%Y-%m-%d")
        
        query = f"{symbol} 股票 新闻"
        print(f"  🔍 搜索关键词: {query}")
        print(f"  📅 时间范围: {start_date} ~ {end_date}")
        
        start_time = datetime.now()
        news_results = getNewsData(query, start_date, end_date)
        elapsed = (datetime.now() - start_time).total_seconds()
        
        print(f"  ⏱️  耗时: {elapsed:.2f} 秒")
        
        if news_results:
            print(f"  ✅ 获取到 {len(news_results)} 条新闻")
            
            for idx, news in enumerate(news_results, 1):
                print_news_item(
                    idx,
                    news.get('title', '无标题'),
                    news.get('snippet', ''),
                    news.get('date', '未知'),
                    news.get('source', '未知'),
                    news.get('link', '')
                )
            
            return len(news_results)
        else:
            print(f"  ❌ 未获取到新闻数据（可能是网络问题或 Google 限流）")
            return 0
            
    except Exception as e:
        print(f"  ❌ 获取失败: {e}")
        import traceback
        traceback.print_exc()
        return 0


def test_database_news(symbol: str, limit: int):
    """测试从 MongoDB 数据库获取新闻"""
    print_header(f"📡 数据源: MongoDB 数据库缓存 - {symbol}")
    print(f"  💡 说明: 查询 MongoDB 中已缓存的新闻数据")
    
    try:
        # 在 Docker 容器内使用环境变量配置的 MongoDB
        import pymongo
        
        mongo_url = os.environ.get(
            'MONGODB_URL',
            os.environ.get('MONGODB_CONNECTION_STRING', 'mongodb://localhost:27017/tradingagents')
        )
        
        print(f"  📡 MongoDB URL: {mongo_url[:50]}...")
        
        client = pymongo.MongoClient(mongo_url, serverSelectionTimeoutMS=5000)
        # 测试连接
        client.admin.command('ping')
        print(f"  ✅ MongoDB 连接成功")
        
        db = client.get_database('tradingagents')
        collection = db.stock_news
        
        # 标准化股票代码
        clean_code = symbol.replace('.SH', '').replace('.SZ', '').replace('.SS', '')
        
        # 尝试多种查询
        query_list = [
            {'symbol': clean_code},
            {'symbol': symbol},
            {'symbols': clean_code},
        ]
        
        total = 0
        news_items = []
        used_query = None
        
        for query in query_list:
            total = collection.count_documents(query)
            if total > 0:
                cursor = collection.find(query).sort('publish_time', -1).limit(limit)
                news_items = list(cursor)
                used_query = query
                break
        
        print(f"  📊 数据库中 {clean_code} 的新闻总数: {total} 条")
        if used_query:
            print(f"  🔍 使用查询: {used_query}")
        
        if news_items:
            print(f"  ✅ 获取到最新 {len(news_items)} 条新闻")
            
            for idx, news in enumerate(news_items, 1):
                title = news.get('title', '无标题')
                content = news.get('content', '') or news.get('summary', '')
                publish_time = news.get('publish_time', '未知')
                source = news.get('source', '未知')
                url = news.get('url', '')
                data_source = news.get('data_source', '未知')
                
                if isinstance(publish_time, datetime):
                    time_str = publish_time.strftime('%Y-%m-%d %H:%M:%S')
                else:
                    time_str = str(publish_time)
                
                source_info = f"{source} (数据源: {data_source})"
                print_news_item(idx, title, content, time_str, source_info, url)
            
            return len(news_items)
        else:
            print(f"  ❌ 数据库中没有 {clean_code} 的新闻")
            
            # 列出数据库中有哪些股票的新闻
            try:
                symbols = collection.distinct('symbol')
                if symbols:
                    print(f"  📋 数据库中有以下股票的新闻 (共 {len(symbols)} 只):")
                    for s in symbols[:20]:
                        count = collection.count_documents({'symbol': s})
                        print(f"     - {s}: {count} 条")
                    if len(symbols) > 20:
                        print(f"     ... 还有 {len(symbols) - 20} 只")
            except:
                pass
            
            return 0
            
    except pymongo.errors.ServerSelectionTimeoutError:
        print(f"  ❌ 无法连接到 MongoDB（超时）")
        return 0
    except Exception as e:
        print(f"  ❌ 数据库查询失败: {e}")
        import traceback
        traceback.print_exc()
        return 0


def main():
    parser = argparse.ArgumentParser(
        description="新闻原始数据验证脚本 - 输出指定股票的原始新闻数据（标题、内容、时间、链接）",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
示例 (在宿主机运行):
  docker exec -it tradingagents-backend python scripts/test_news_raw_output.py 600968
  docker exec -it tradingagents-backend python scripts/test_news_raw_output.py 600968 --limit 20
  docker exec -it tradingagents-backend python scripts/test_news_raw_output.py 600968 --source all
  docker exec -it tradingagents-backend python scripts/test_news_raw_output.py 600968 --source akshare
  docker exec -it tradingagents-backend python scripts/test_news_raw_output.py 600968 --source eastmoney
  docker exec -it tradingagents-backend python scripts/test_news_raw_output.py 600968 --source google
  docker exec -it tradingagents-backend python scripts/test_news_raw_output.py 600968 --source db
        """
    )
    parser.add_argument('symbol', help='股票代码，如 600968')
    parser.add_argument('--limit', type=int, default=10, help='获取新闻数量，默认 10')
    parser.add_argument(
        '--source', 
        choices=['akshare', 'eastmoney', 'realtime', 'google', 'db', 'all'],
        default='akshare',
        help='数据源: akshare(默认,东方财富), eastmoney(直接API), realtime(聚合器), google, db(数据库), all'
    )
    
    args = parser.parse_args()
    symbol = args.symbol
    limit = args.limit
    source = args.source
    
    print("\n" + "🚀" * 30)
    print(f"\n  📊 新闻原始数据验证")
    print(f"  📌 股票代码: {symbol}")
    print(f"  📏 获取数量: {limit}")
    print(f"  📡 数据源: {source}")
    print(f"  🕐 测试时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"  🐳 容器环境: {'是' if os.environ.get('DOCKER_CONTAINER') else '否'}")
    print("\n" + "🚀" * 30)
    
    results = {}
    
    if source in ('akshare', 'all'):
        results['AKShare(东方财富)'] = test_akshare_sync(symbol, limit)
    
    if source in ('eastmoney', 'all'):
        results['东方财富直接API'] = test_eastmoney_direct(symbol, limit)
    
    if source in ('realtime', 'all'):
        results['实时新闻聚合器'] = test_realtime_aggregator(symbol)
    
    if source in ('google', 'all'):
        results['Google新闻'] = test_google_news(symbol)
    
    if source in ('db', 'all'):
        results['MongoDB数据库'] = test_database_news(symbol, limit)
    
    # 汇总
    print_header("📋 测试结果汇总")
    for src_name, count in results.items():
        status = "✅" if count > 0 else "❌"
        print(f"  {status} {src_name}: {count} 条新闻")
    
    total = sum(results.values())
    print(f"\n  📊 总计: {total} 条新闻")
    
    if total == 0:
        print(f"\n  ⚠️ 所有数据源都未获取到新闻，请检查:")
        print(f"     1. 容器网络是否正常（能否访问外网）")
        print(f"     2. 东方财富 API 是否可用")
        print(f"     3. MongoDB 是否正常运行")
    print()


if __name__ == "__main__":
    main()
