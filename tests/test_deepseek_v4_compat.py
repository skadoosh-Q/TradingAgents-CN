from unittest.mock import Mock, patch

from app.services.config_service import ConfigService
from langchain_core.messages import AIMessage, HumanMessage, ToolMessage

from tradingagents.llm_adapters.deepseek_adapter import ChatDeepSeek


def test_deepseek_v4_adapter_disables_thinking_by_default():
    llm = ChatDeepSeek(
        model="deepseek-v4-pro",
        api_key="sk-test-key-1234567890",
        max_tokens=4000,
    )

    assert llm.extra_body == {"thinking": {"type": "disabled"}}


def test_deepseek_v4_adapter_respects_explicit_thinking_setting():
    llm = ChatDeepSeek(
        model="deepseek-v4-pro",
        api_key="sk-test-key-1234567890",
        extra_body={"thinking": {"type": "enabled"}},
        reasoning_effort="high",
    )

    assert llm.extra_body == {"thinking": {"type": "enabled"}}
    assert llm.reasoning_effort == "high"


def test_legacy_deepseek_model_keeps_existing_request_behavior():
    llm = ChatDeepSeek(
        model="deepseek-chat",
        api_key="sk-test-key-1234567890",
    )

    assert llm.extra_body is None


def test_deepseek_v4_connection_test_disables_thinking():
    response = Mock(status_code=200)
    response.json.return_value = {
        "choices": [{"message": {"content": "OK"}}]
    }

    with patch("requests.post", return_value=response) as post:
        result = ConfigService._test_deepseek_api(
            object(),
            "sk-test-key-1234567890",
            "deepseek deepseek-v4-pro",
            "deepseek-v4-pro",
        )

    payload = post.call_args.kwargs["json"]
    assert result["success"] is True
    assert payload["max_tokens"] == 200
    assert payload["thinking"] == {"type": "disabled"}


def test_deepseek_connection_test_accepts_reasoning_only_response():
    response = Mock(status_code=200)
    response.json.return_value = {
        "choices": [{
            "message": {"content": "", "reasoning_content": "正在生成回复"}
        }]
    }

    with patch("requests.post", return_value=response):
        result = ConfigService._test_deepseek_api(
            object(),
            "sk-test-key-1234567890",
            "deepseek deepseek-v4-pro",
            "deepseek-v4-pro",
        )

    assert result["success"] is True


def test_deepseek_reasoning_content_is_preserved_across_tool_roundtrip():
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
    assert assistant_message.additional_kwargs["reasoning_content"] == "需要先读取行情数据"

    payload = llm._get_request_payload([
        HumanMessage(content="分析股票 000001"),
        assistant_message,
        ToolMessage(content="行情数据", tool_call_id="call-1"),
    ])

    assert payload["messages"][1]["reasoning_content"] == "需要先读取行情数据"
    assert payload["messages"][2]["content"] == "行情数据"
