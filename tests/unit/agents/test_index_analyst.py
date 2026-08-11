"""
大盘/指数分析师单元测试
"""

import pytest
import asyncio
from unittest.mock import Mock, patch, AsyncMock
import pandas as pd


class TestIndexTools:
    """测试指数分析工具函数"""
    
    @pytest.fixture
    def mock_market_provider(self):
        """模拟免费市场数据接口"""
        mock_provider = Mock()
        mock_provider.is_available.return_value = True
        return mock_provider
    
    @pytest.mark.asyncio
    async def test_get_index_trend(self, mock_market_provider):
        """测试指数走势分析"""
        # 模拟指数日线数据
        mock_market_provider.get_index_daily = AsyncMock(return_value=pd.DataFrame({
            'trade_date': [f'202412{i:02d}' for i in range(1, 22)],
            'close': [3000 + i * 10 for i in range(21)],
            'high': [3010 + i * 10 for i in range(21)],
            'low': [2990 + i * 10 for i in range(21)],
            'pct_chg': [0.5] * 21
        }))
        
        with patch('core.tools.index_tools._get_market_data_provider', return_value=mock_market_provider):
            from core.tools.index_tools import get_index_trend
            
            result = await get_index_trend("2024-12-21")
            
            assert "主要指数走势分析" in result
            assert "上证指数" in result or "暂无数据" in result
    
    @pytest.mark.asyncio
    async def test_get_market_breadth(self, mock_market_provider):
        """测试市场宽度分析"""
        mock_market_provider.get_market_activity = AsyncMock(return_value={
            'up_count': 2500, 'down_count': 1500, 'flat_count': 100,
            'limit_up_count': 50, 'limit_down_count': 5,
            'suspended_count': 0, 'activity_rate': 60.5,
            'data_time': '2024-12-21 15:00:00',
        })
        
        with patch('core.tools.index_tools._get_market_data_provider', return_value=mock_market_provider):
            from core.tools.index_tools import get_market_breadth
            
            result = await get_market_breadth("2024-12-21")
            
            assert "市场宽度分析" in result
            assert "涨跌分布" in result or "暂无" in result
    
    @pytest.mark.asyncio
    async def test_get_market_environment(self, mock_market_provider):
        """测试市场环境评估"""
        mock_market_provider.get_market_valuation = AsyncMock(return_value=pd.DataFrame({
            'trade_date': ['20241220'],
            'pe_ttm_median': [25.5],
            'pe_ttm_mean': [38.2],
            'pe_lyr_median': [26.1],
        }))
        mock_market_provider.get_index_daily = AsyncMock(return_value=pd.DataFrame({
            'trade_date': [f'202412{i:02d}' for i in range(1, 22)],
            'close': [3000 + i for i in range(21)],
            'pct_chg': [0.5, -0.3, 0.2, -0.1, 0.4] * 4 + [0.3]
        }))
        
        with patch('core.tools.index_tools._get_market_data_provider', return_value=mock_market_provider):
            from core.tools.index_tools import get_market_environment
            
            result = await get_market_environment("2024-12-21")
            
            assert "市场环境评估" in result
    
    @pytest.mark.asyncio
    async def test_identify_market_cycle(self, mock_market_provider):
        """测试市场周期识别"""
        # 创建模拟的上涨趋势数据
        mock_market_provider.get_index_daily = AsyncMock(return_value=pd.DataFrame({
            'trade_date': [f'2024{(i//30+1):02d}{(i%30+1):02d}' for i in range(120)],
            'close': [3000 + i * 5 for i in range(120)],
            'high': [3010 + i * 5 for i in range(120)],
            'low': [2990 + i * 5 for i in range(120)],
        }))
        
        with patch('core.tools.index_tools._get_market_data_provider', return_value=mock_market_provider):
            from core.tools.index_tools import identify_market_cycle
            
            result = await identify_market_cycle("2024-12-21")
            
            assert "市场周期判断" in result


class TestIndexAnalystAgent:
    """测试大盘分析师 Agent"""
    
    def test_agent_metadata(self):
        """测试 Agent 元数据"""
        from core.agents.adapters.index_analyst import IndexAnalystAgent
        
        metadata = IndexAnalystAgent.get_metadata()
        
        assert metadata.id == "index_analyst"
        assert metadata.name == "大盘/指数分析师"
        assert "大盘" in metadata.tags or "指数" in metadata.tags
    
    def test_agent_execute(self):
        """测试 Agent 执行"""
        from core.agents.adapters.index_analyst import IndexAnalystAgent
        
        agent = IndexAnalystAgent()
        
        # 模拟分析工具
        mock_report = "测试大盘分析报告"
        with patch('core.tools.index_tools.analyze_index_sync', return_value=mock_report):
            state = {
                "trade_date": "2024-12-21",
                "messages": []
            }
            
            result = agent.execute(state)
            
            assert "index_report" in result
            assert result["index_report"] == mock_report


class TestIndexReportCache:
    """测试大盘报告缓存版本隔离与失败报告过滤。"""

    def test_cache_uses_free_data_namespace(self):
        from core.agents.adapters import index_analyst_v2 as module

        cache = Mock()
        cache.find_cached_analysis_report.return_value = None

        with patch.object(module, "_get_cache_manager", return_value=cache):
            assert module._get_cached_index_report("2026-08-11") is None

        assert cache.find_cached_analysis_report.call_args.kwargs["symbol"] == "market_v2_free_v1"

    def test_failed_data_report_is_not_cached(self):
        from core.agents.adapters import index_analyst_v2 as module

        cache = Mock()
        report = "本次分析因数据源不可用，无法获取任何有效的市场数据。" * 10

        with patch.object(module, "_get_cache_manager", return_value=cache):
            assert module._save_index_report_to_cache("2026-08-11", report) is False

        cache.save_analysis_report.assert_not_called()

    def test_failed_cached_report_is_ignored(self):
        from core.agents.adapters import index_analyst_v2 as module

        cache = Mock()
        cache.find_cached_analysis_report.return_value = "cached-key"
        cache.load_analysis_report.return_value = (
            "受限于数据源连接问题及Tushare积分权限限制，绝大多数数据维度未能成功获取。" * 5
        )

        with patch.object(module, "_get_cache_manager", return_value=cache):
            assert module._get_cached_index_report("2026-08-11") is None


class TestAgentStateIndexField:
    """测试 AgentState 中的 index_report 字段"""
    
    def test_index_report_field_exists(self):
        """测试 index_report 字段存在"""
        from tradingagents.agents.utils.agent_states import AgentState
        
        annotations = AgentState.__annotations__
        
        assert 'index_report' in annotations


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
