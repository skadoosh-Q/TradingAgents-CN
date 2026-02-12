# TradingAgents/graph/propagation.py

from typing import Dict, Any

# 导入统一日志系统
from tradingagents.utils.logging_init import get_logger
logger = get_logger("default")
from tradingagents.agents.utils.agent_states import (
    AgentState,
    InvestDebateState,
    RiskDebateState,
)


class Propagator:
    """Handles state initialization and propagation through the graph."""

    def __init__(self, max_recur_limit=100):
        """Initialize with configuration parameters."""
        self.max_recur_limit = max_recur_limit

    def create_initial_state(
        self, company_name: str, trade_date: str, config: Dict[str, Any] = None
    ) -> Dict[str, Any]:
        """Create the initial state for the agent graph."""
        from langchain_core.messages import HumanMessage

        # 🔥 修复：创建明确的分析请求消息，而不是只传递股票代码
        # 这样可以确保所有LLM（包括DeepSeek）都能理解任务
        analysis_request = f"请对股票 {company_name} 进行全面分析，交易日期为 {trade_date}。"

        # 📌 如果用户有持仓信息，注入到初始消息中
        holding_info = None
        if config and config.get("holding_info"):
            holding_info = config["holding_info"]
            shares = holding_info.get("shares")
            cost_price = holding_info.get("cost_price")
            if shares and cost_price:
                analysis_request += (
                    f"\n\n📌 用户持仓信息：用户当前持有该股票 {shares} 股，"
                    f"持仓成本价为 {cost_price} 元/股。"
                    f"请在分析中特别考虑用户的持仓状况，提供针对性的操作建议"
                    f"（如继续持有、加仓、减仓、止盈、止损等）。"
                )

        return {
            "messages": [HumanMessage(content=analysis_request)],
            "company_of_interest": company_name,
            "trade_date": str(trade_date),
            "holding_info": holding_info,  # 📌 传递持仓信息到 state
            "investment_debate_state": InvestDebateState(
                {"history": "", "current_response": "", "count": 0}
            ),
            "risk_debate_state": RiskDebateState(
                {
                    "history": "",
                    "current_risky_response": "",
                    "current_safe_response": "",
                    "current_neutral_response": "",
                    "count": 0,
                }
            ),
            "market_report": "",
            "fundamentals_report": "",
            "sentiment_report": "",
            "news_report": "",
        }

    def get_graph_args(self, use_progress_callback: bool = False) -> Dict[str, Any]:
        """Get arguments for the graph invocation.

        Args:
            use_progress_callback: If True, use 'updates' mode for node-level progress tracking.
                                  If False, use 'values' mode for complete state updates.
        """
        # 使用 'updates' 模式可以获取节点级别的更新，用于进度跟踪
        # 使用 'values' 模式可以获取完整的状态更新
        stream_mode = "updates" if use_progress_callback else "values"

        return {
            "stream_mode": stream_mode,
            "config": {"recursion_limit": self.max_recur_limit},
        }
