# 阶段 4：Agent Loop 与工具结果回填

## 1. 模块职责

AgentRuntime 是整个 Agent 的控制器，负责：

1. 组装 System Prompt、历史消息和当前用户消息。
2. 将消息与已注册工具的 JSON Schema 发送给 LLM。
3. 判断模型返回的是工具调用还是最终文本。
4. 逐个执行模型提出的工具调用。
5. 将工具执行结果以 tool message 回填到消息历史。
6. 再次请求模型，直到得到最终答案或达到最大步数。

LLM Provider 不执行工具；Tool Registry 不负责向模型发请求。AgentRuntime 将两者连接起来。

## 2. 一次完整的工具调用

用户输入：

~~~text
请计算 100 * 25。
~~~

模型可能返回：

~~~json
{
  "role": "assistant",
  "content": null,
  "tool_calls": [
    {
      "id": "call-calc-1",
      "type": "function",
      "function": {
        "name": "calculator",
        "arguments": "{\"expression\": \"100 * 25\"}"
      }
    }
  ]
}
~~~

Runtime 不会直接相信模型参数，而是调用 ToolRegistry：

~~~python
result = await tool_registry.execute(
    tool_call.name,
    tool_call.arguments,
)
~~~

Registry 执行 Pydantic 参数验证，通过后才进入工具 handler。然后 Runtime 追加两条消息：

- assistant：保存原始 tool_calls，保留调用 ID 和参数。
- tool：tool_call_id 与对应调用 ID 一致，content 是 JSON 格式的 ToolExecutionResult。

接下来把完整上下文再次交给模型，模型根据工具结果生成自然语言答案。

## 3. 消息协议

内部 ToolCall 使用简洁的结构：

~~~python
ToolCall(
    id="call-calc-1",
    name="calculator",
    arguments={"expression": "100 * 25"},
)
~~~

发送给 OpenAI-compatible Chat Completions API 时，会转换成其要求的嵌套格式：

~~~json
{
  "id": "call-calc-1",
  "type": "function",
  "function": {
    "name": "calculator",
    "arguments": "{\"expression\": \"100 * 25\"}"
  }
}
~~~

工具结果消息示例：

~~~json
{
  "role": "tool",
  "tool_call_id": "call-calc-1",
  "name": "calculator",
  "content": "{\"tool_name\": \"calculator\", \"success\": true, \"output\": {\"result\": 2500}}"
}
~~~

因此 ChatMessage 提供 to_openai_dict()，统一处理普通消息、assistant tool_calls 和 tool result 消息。工具调用 ID 必须与结果消息中的 tool_call_id 对应。

## 4. 多工具调用策略

如果模型在一次响应中返回多个 tool_calls，Runtime 按原始顺序逐个执行：

~~~text
assistant: tool_calls [A, B, C]
       |
       v
执行 A -> 追加 A 的 tool result
       |
       v
执行 B -> 追加 B 的 tool result
       |
       v
执行 C -> 追加 C 的 tool result
       |
       v
下一轮 LLM 请求
~~~

当前采用串行执行，而不是 asyncio.gather 并行执行。原因是工具可能包含数据库写入、文件修改等副作用；串行方式更容易保证顺序和可预测性。后续可根据工具声明的副作用类型增加并行策略。

未知工具或参数校验失败不会被静默忽略。ToolRegistry 返回 success=false 的结构化结果，Runtime 将它作为 tool message 回填，让模型决定如何向用户解释或调整后续动作。

## 5. 最大步数与停止条件

max_steps 表示一次 run 中最多进行多少次 LLM 请求，不是工具调用总数。

例如 max_steps=3：

- 第 1 次模型请求：提出两个工具调用，Runtime 执行两个工具。
- 第 2 次模型请求：提出一个工具调用，Runtime 执行。
- 第 3 次模型请求：提出工具调用，但达到本轮上限，不再发起第 4 次模型请求。

如果模型在上限前返回普通文本，stop_reason 为 final_answer；如果循环耗尽，stop_reason 为 max_steps，并返回明确的停止提示。

## 6. run() 接口

~~~python
result = await agent.run(
    "请计算 100 * 25。",
    history=previous_messages,
)

print(result.reply)
print(result.steps)
print(result.tool_calls_executed)
print(result.stop_reason)
~~~

history 只允许传入先前的会话消息，不允许调用方传入 system 消息覆盖 Runtime 的系统提示。Runtime 返回的 messages 包含当前执行形成的完整消息序列，下一阶段可以将其交给 SessionStore 持久化。

## 7. 当前边界与下一步

当前阶段已完成 Agent Loop 的核心执行逻辑，但暂不包含：

- SQLite Session 持久化和跨请求恢复。
- Token 预算与上下文滑动窗口。
- 长期 Memory 的检索和写入。
- Trace ID、每一步耗时与结构化审计日志。
- LLM 网络错误重试、取消和断点续跑。
- 面向外部用户的 Chat API 路由。

这些能力分别属于后续 Session/Memory、Trace/异常处理和 API 集成阶段。
