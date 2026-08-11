from datetime import datetime
from unittest.mock import AsyncMock, Mock, patch
import asyncio

from langchain_core.messages import HumanMessage, ToolMessage

from app.models.analysis import AnalysisParameters, UnifiedAnalysisTask, AnalysisTaskType
from app.models.config import LLMConfig, SystemConfig
from app.models.user import PyObjectId
from app.services.config_service import ConfigService
from core.tools.implementations.news import stock_news
from core.tools.implementations.news.stock_news import _primary_window_start
from core.agents.holding_context import build_holding_context, normalize_holding_info
from core.workflow.engine import WorkflowEngine
from tradingagents.llm_adapters.deepseek_adapter import ChatDeepSeek


def test_news_primary_window_starts_on_previous_monday():
    assert _primary_window_start(datetime(2026, 8, 10)) == datetime(2026, 8, 3)
    assert _primary_window_start(datetime(2026, 8, 12)) == datetime(2026, 8, 3)
    assert _primary_window_start(datetime(2026, 8, 16)) == datetime(2026, 8, 3)


def test_current_a_share_analysis_refreshes_before_database_query():
    events = []

    def refresh(*_args, **_kwargs):
        events.append("refresh")
        return []

    def query(*_args, **_kwargs):
        events.append("database")
        return [{
            "title": "近期公告",
            "publish_time": datetime.now(),
            "source": "东方财富",
            "content": "公告内容",
        }]

    with patch.object(stock_news, "_refresh_a_share_news", side_effect=refresh), patch.object(
        stock_news, "_query_news_from_database", side_effect=query
    ):
        result = stock_news.get_stock_news_unified.invoke({
            "ticker": "000661",
            "curr_date": datetime.now().strftime("%Y-%m-%d"),
        })

    assert events[:2] == ["refresh", "database"]
    assert "核心新闻窗口" in result


def test_workflow_extracts_completed_partial_reports():
    reports = WorkflowEngine._extract_partial_reports({
        "market_report": "技术面报告",
        "investment_debate_state": {
            "bull_history": "多头观点",
            "bear_history": "空头观点",
            "judge_decision": "研究经理结论",
        },
        "risk_debate_state": {
            "risky_history": "激进观点",
            "safe_history": "保守观点",
            "neutral_history": "中性观点",
            "judge_decision": "风险经理结论",
        },
    })

    assert reports == {
        "market_report": "技术面报告",
        "bull_researcher": "多头观点",
        "bear_researcher": "空头观点",
        "research_team_decision": "研究经理结论",
        "risky_analyst": "激进观点",
        "safe_analyst": "保守观点",
        "neutral_analyst": "中性观点",
        "risk_management_decision": "风险经理结论",
    }


def test_unified_task_persists_partial_reports():
    task = UnifiedAnalysisTask(
        task_id="task-1",
        user_id=PyObjectId(),
        task_type=AnalysisTaskType.STOCK_ANALYSIS,
        partial_reports={"news_report": "新闻报告"},
    )

    assert task.model_dump()["partial_reports"] == {"news_report": "新闻报告"}


def test_holding_parameters_require_shares_and_cost_price():
    params = AnalysisParameters(
        is_holding=True,
        holding_shares=1200,
        holding_cost_price=18.35,
    )
    assert params.holding_shares == 1200

    try:
        AnalysisParameters(is_holding=True, holding_shares=1200)
    except ValueError as exc:
        assert "持仓成本价" in str(exc)
    else:
        raise AssertionError("holding cost validation did not run")


def test_holding_context_distinguishes_existing_and_new_positions():
    holding = normalize_holding_info({
        "is_holding": True,
        "holding_shares": 1200,
        "holding_cost_price": 18.35,
    })
    context = build_holding_context({
        "holding_info": holding,
        "current_price": "20.10",
        "currency_symbol": "¥",
    })

    assert holding == {
        "is_holding": True,
        "shares": 1200,
        "cost_price": 18.35,
    }
    assert "已有仓位管理场景" in context
    assert "浮动约为 +9.54%" in context
    assert "不得臆测仓位比例" in context

    no_holding_context = build_holding_context({"is_holding": False})
    assert "潜在新建仓场景" in no_holding_context


def test_deepseek_v4_adapter_preserves_reasoning_across_tool_roundtrip():
    llm = ChatDeepSeek(
        model="deepseek-v4-pro",
        api_key="sk-test-key-1234567890",
        extra_body={"thinking": {"type": "enabled"}},
        reasoning_effort="high",
    )
    response = {
        "choices": [{
            "message": {
                "role": "assistant",
                "content": None,
                "reasoning_content": "需要先读取行情数据",
                "tool_calls": [{
                    "id": "call-1",
                    "type": "function",
                    "function": {
                        "name": "get_market_data",
                        "arguments": "{\"symbol\":\"000001\"}",
                    },
                }],
            },
            "finish_reason": "tool_calls",
        }],
        "model": "deepseek-v4-pro",
        "usage": {
            "prompt_tokens": 10,
            "completion_tokens": 20,
            "total_tokens": 30,
        },
    }

    chat_result = llm._create_chat_result(response)
    assistant_message = chat_result.generations[0].message
    payload = llm._get_request_payload([
        HumanMessage(content="分析股票 000001"),
        assistant_message,
        ToolMessage(content="行情数据", tool_call_id="call-1"),
    ])

    assert assistant_message.additional_kwargs["reasoning_content"] == "需要先读取行情数据"
    assert payload["messages"][1]["reasoning_content"] == "需要先读取行情数据"


def test_deepseek_v4_connection_test_disables_thinking():
    response = Mock(status_code=200)
    response.json.return_value = {"choices": [{"message": {"content": "OK"}}]}

    with patch("requests.post", return_value=response) as post:
        result = ConfigService._test_deepseek_api(
            object(),
            "sk-test-key-1234567890",
            "deepseek deepseek-v4-pro",
            "deepseek-v4-pro",
        )

    assert result["success"] is True
    assert post.call_args.kwargs["json"]["thinking"] == {"type": "disabled"}
    assert post.call_args.kwargs["json"]["max_tokens"] == 200


def test_delete_llm_config_does_not_require_provider_catalog_entry():
    service = ConfigService()
    config = SystemConfig(
        config_name="test",
        config_type="system",
        llm_configs=[LLMConfig(provider="deepseek", model_name="deepseek-chat")],
        default_llm="deepseek-chat",
        system_settings={
            "quick_analysis_model": "deepseek-chat",
            "deep_analysis_model": "deepseek-chat",
        },
    )
    service.get_system_config = AsyncMock(return_value=config)
    service.save_system_config = AsyncMock(return_value=True)

    assert asyncio.run(
        service.delete_llm_config("DEEPSEEK", "deepseek-chat")
    ) is True
    assert config.llm_configs == []
    assert config.default_llm is None
    assert config.system_settings["quick_analysis_model"] == ""
