# 阶段 2：LLM Provider 与响应解析

## 为什么直接使用 httpx

本项目要理解 Agent Runtime 的边界，因此 LLM 接入层只负责 HTTP 请求和协议解析，不把 Agent 决策、工具执行或记忆管理交给 SDK。

OpenAI-compatible Chat Completions API 的基本流程：

1. 将内部 ChatMessage 转换成 messages 数组。
2. 请求 POST {LLM_BASE_URL}/chat/completions。
3. 使用 Authorization: Bearer ... 传递 API Key。
4. 解析 choices[0].message。
5. 如果 message 有 tool_calls，解析每个 function 的 name 和 arguments。
6. 将响应归一化为项目内部的 LLMResponse。

## 关键边界

- Provider 不执行工具，只返回 ToolCall。
- 工具 arguments 是不可信输入；即使成功解析 JSON，也必须在后续 Tool Registry 阶段进行 JSON Schema 校验和权限校验。
- HTTP 错误不会把服务端响应正文直接暴露给上层，避免错误正文意外包含敏感信息。
- API Key 只从环境变量读取，不写入日志、异常或测试快照。
- 测试使用 httpx.MockTransport，不需要真实 API Key 或真实模型调用。

## 本地配置

在 .env 中设置：

~~~dotenv
LLM_BASE_URL=https://api.openai.com/v1
LLM_API_KEY=your_key_here
LLM_MODEL=gpt-4o-mini
~~~

不同厂商只要兼容 Chat Completions 请求/响应格式，通常只需替换 LLM_BASE_URL 和模型名。部分厂商对 tool calling、字段或路径存在差异，需要单独适配和测试。

## 使用示例

~~~python
import asyncio

from min_agent.core.schemas import ChatMessage
from min_agent.llm.openai_compatible import OpenAICompatibleProvider


async def main() -> None:
    async with OpenAICompatibleProvider() as provider:
        result = await provider.complete(
            [ChatMessage(role="user", content="用一句话解释 Agent Runtime。")]
        )
        print(result.content)


asyncio.run(main())
~~~

## 验证

~~~bash
pytest tests/test_llm_parser.py tests/test_llm_provider.py
ruff check src tests
~~~

当前阶段完成的是模型接入和响应归一化，不包含 Agent Loop，也不会自动执行模型返回的工具调用。
