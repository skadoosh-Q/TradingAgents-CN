"""Helpers for carrying optional holding information through stock analysis."""

import re
from typing import Any, Dict


def normalize_holding_info(values: Dict[str, Any]) -> Dict[str, Any]:
    """Normalize request or workflow values into one stable state object."""
    existing = values.get("holding_info")
    if isinstance(existing, dict):
        is_holding = bool(existing.get("is_holding"))
        shares = existing.get("shares")
        cost_price = existing.get("cost_price")
    else:
        is_holding = bool(values.get("is_holding", False))
        shares = values.get("holding_shares")
        cost_price = values.get("holding_cost_price")

    if not is_holding:
        return {"is_holding": False}

    return {
        "is_holding": True,
        "shares": shares,
        "cost_price": cost_price,
    }


def build_holding_context(state: Dict[str, Any]) -> str:
    """Build decision-stage guidance without changing objective analyst reports."""
    holding = normalize_holding_info(state)
    if not holding["is_holding"]:
        return (
            "【用户持仓背景】\n"
            "用户当前未持有该股票。请按潜在新建仓场景形成结论，重点说明是否适合介入、"
            "合理观察或建仓区间及触发条件；不要给出减仓、清仓或基于持仓成本的止损建议。"
        )

    shares = holding.get("shares")
    cost_price = holding.get("cost_price")
    if shares in (None, "") or cost_price in (None, ""):
        return (
            "【用户持仓背景】\n"
            "用户标记为已持有该股票，但历史任务未保存完整的股数或成本价。"
            "请按已有仓位场景给出方向性建议，不要计算浮盈浮亏或虚构成本数据。"
        )

    currency_symbol = state.get("currency_symbol") or ""
    context = (
        "【用户持仓背景】\n"
        f"用户当前已持有该股票 {shares} 股，持仓成本价为 "
        f"{currency_symbol}{float(cost_price):.2f}。这是已有仓位管理场景，不是单纯的新建仓判断。\n"
        "请结合成本价和分析结论，明确讨论继续持有、加仓、减仓或退出的条件，并给出"
        "止盈、止损参考。未提供总资产和其他持仓时，不得臆测仓位比例或组合集中度。"
    )

    current_price = state.get("current_price")
    if current_price not in (None, "", "未知"):
        match = re.search(r"-?\d+(?:\.\d+)?", str(current_price).replace(",", ""))
        if match and float(cost_price) > 0:
            price = float(match.group())
            pnl_pct = (price - float(cost_price)) / float(cost_price) * 100
            context += (
                f"\n按工作流取得的现价 {currency_symbol}{price:.2f} 估算，"
                f"相对成本价浮动约为 {pnl_pct:+.2f}%；请以报告中的行情时间为准。"
            )

    return context


def append_holding_context(prompt: str, state: Dict[str, Any]) -> str:
    """Append normalized holding guidance to a rendered prompt."""
    return f"{prompt.rstrip()}\n\n{build_holding_context(state)}"
