# 系统架构与关键设计

## 1. 目标与边界

本项目从零实现一个最小可用 Agent Runtime。FastAPI 只承担 HTTP 接入，不承担 Agent 决策；Agent Loop、工具注册、上下文管理、Session 和 Memory 均由项目自身实现。

明确不使用 LangGraph、OpenHands、OpenClaw 等 Agent 框架。LLM Provider 只负责模型 HTTP 请求和响应归一化；模型只提出结构化工具调用请求，Runtime 负责校验、授权和执行。

## 2. 目标架构

~~~text
Client
  |
  v
FastAPI / Chat API
  |
  v
AgentRuntime ---------------------- TraceRecorder
  |                                      |
  +---- ContextManager                   +---- execution events
  |       |
  |       +---- SessionStore
  |       +---- MemoryStore
  |
  +---- LLMProvider
  |       |
  |       +---- OpenAI-compatible HTTP API
  |
  +---- ToolRegistry
          |
          +---- Pydantic / JSON Schema validation
          +---- ToolExecutor
                  +---- calculator
                  +---- search (mock)
                  +---- todo (SQLite)
~~~

### 模块职责

| 模块 | 职责 |
| --- | --- |
| API | 接收请求、校验输入、返回结果 |
| AgentRuntime | 控制模型调用、工具执行、循环退出和最大轮次 |
| LLMProvider | 屏蔽不同模型服务的 HTTP 请求与响应格式 |
| OutputParser | 解析文本回复、工具调用和结束状态 |
| ToolRegistry | 注册工具定义、描述、参数 Schema 和 handler |
| ContextManager | 组装上下文、控制消息数量和执行基础压缩 |
| SessionStore | 按用户和 session 保存消息历史 |
| MemoryStore | 保存可跨会话复用的长期信息 |
| TraceRecorder | 记录步骤、工具、耗时、状态和异常 |

## 3. Agent Loop（阶段 4 已实现）

AgentRuntime 使用显式循环组织模型调用和工具执行：

~~~python
for step in range(1, max_steps + 1):
    response = await llm.complete(
        messages,
        tools=tool_registry.schemas(),
    )

    if response.tool_calls:
        messages.append(assistant_tool_call_message(response.tool_calls))
        for call in response.tool_calls:
            result = await tool_registry.execute(call.name, call.arguments)
            messages.append(tool_result_message(call.id, result))
        continue

    return response.content or fallback_reply

return max_steps_reply
~~~

一个 step 表示一次 LLM 请求。一次响应可以包含多个工具调用；当前按模型返回顺序串行执行，确保带副作用工具的执行次序可预测。工具调用结果使用匹配的 tool_call_id 回填，然后进入下一轮模型请求。

当前 AgentRuntime 支持传入历史消息并返回本轮完整消息序列。阶段 5 已实现 SQLite SessionStore / MessageStore，负责会话创建、消息追加、历史恢复和 user_id + session_id 所有权校验；Runtime 与存储仍保持解耦，由后续 Chat Service 编排。

## 4. Context 如何构建

每次请求不应无条件把数据库中的全部历史消息塞给模型。建议按以下优先级构建：

1. **System Prompt**：稳定的角色约束、工具使用规则和安全边界，每次请求都提供。
2. **当前用户消息**：本轮任务的原始输入，必须保留。
3. **相关长期记忆**：只召回与当前任务有关、可信且有来源的信息。
4. **会话摘要**：较早对话的压缩结果，用于保留任务背景、约束和未完成事项。
5. **最近若干轮消息**：优先保留最近的用户消息、助手最终答复和必要的工具调用/结果。
6. **本轮工具结果**：工具结果需要以结构化 tool message 回填，让模型可以据此继续决策。

不要把隐藏内部推理过程当作普通对话消息保存。可以记录模型明确提供的简短决策摘要、工具调用参数、工具输出和执行状态；这些是可观察的运行信息，不等同于隐藏推理。

### 基础压缩策略

第一版采用简单、可预测的策略：

- 配置最大消息数或上下文预算。
- System Prompt 和当前用户消息永远不参与裁剪。
- 保留最近的完整消息轮次，避免留下孤立的 tool result。
- 将更早的完整轮次压缩成摘要，摘要保留目标、关键事实、用户约束、已完成步骤和待办事项。
- 完整原始历史仍保存在 SessionStore；压缩只影响发送给 LLM 的 Context。

后续可以从最大消息数升级为 token 预算，但不在初期引入复杂摘要模型。

## 5. Session 与 Memory 的边界

### Session（短期记忆）

Session 表示一个独立聊天窗口。同一用户可以有多个 session：

- 用户 A / 窗口 1：查询天气、添加待办。
- 用户 A / 窗口 2：编写周报、添加另一条待办。

两者使用不同 session_id。读取历史时必须同时校验用户身份和 session 归属，不能只依赖前端传入的 session_id。

短期记忆存储当前任务的消息历史和工具调用结果。当前已使用 SQLite 的 sessions、messages 表持久化；消息 payload 保留完整 ChatMessage JSON，确保 tool_calls 与 tool result 可以恢复。

### Long-term Memory（长期记忆，阶段 7 已实现基础版）

长期记忆存放跨会话仍然有用的信息，例如用户明确表达并且长期稳定的偏好、持续项目约束和反复出现的工作背景。阶段 7 已实现独立 SQLite memories 表、规则提取、关键词召回、同 key upsert、归档及 user_id 隔离。ChatService 在本轮模型调用前召回相关记忆，并仅从用户本轮输入提取候选后保存。

不应把每句话都写入长期记忆。候选信息应经过规则判断：是否稳定、未来是否可能复用、是否由用户明确确认、是否敏感，以及是否有明确来源。

### 记忆召回时机

建议在每轮请求开始时执行：

1. 根据 user_id 和 session_id 读取当前会话摘要及最近消息。
2. 对当前用户输入提取主题、实体和任务关键词。
3. 从长期记忆中检索少量相关条目；第一版可以用 SQLite + 关键词匹配，之后再考虑向量检索。
4. 将相关记忆作为独立的上下文区块放在 System Prompt 之后、会话历史之前，并标注为参考信息而非指令。
5. 完成本轮任务后，判断是否存在值得长期保存的新信息；满足规则才写入 MemoryStore。

记忆召回应当按相关性触发，而不是把用户的全部长期记忆无差别注入每次请求。

## 6. 工具调用与安全

### Tool Registry 已实现的机制

- 工具通过 ToolDefinition 注册，包含唯一名称、描述、Pydantic 参数模型、handler 和超时。
- ToolRegistry 根据 Pydantic 模型自动生成 JSON Schema，并转换为 OpenAI-compatible function tools 格式。
- 执行前调用 model_validate；额外字段默认拒绝，类型和字段约束不通过时不调用 handler。
- 未注册工具、参数错误、超时和 handler 异常均返回统一的 ToolExecutionResult。
- LLM Provider 只发送工具 Schema、解析 ToolCall，不会直接执行任何工具。

### 三个内置工具

| 工具 | 行为 | 安全边界 |
| --- | --- | --- |
| calculator | AST 白名单计算 +、-、*、/、//、%、** 和括号 | 不允许函数调用、变量、属性访问；限制表达式长度、节点数和指数 |
| search | 在内置小型知识集合中做确定性 Mock 检索 | 不访问外网，结果明确标记 mock=true |
| todo | SQLite add / list / complete | 参数按 action 校验，SQL 使用参数化查询 |

模型返回的参数始终是不可信输入。JSON 解析成功不代表参数可信，仍必须经过工具 Schema 校验和后续权限检查。禁止使用 eval 执行模型生成的表达式。

工具执行结果应有大小限制，避免大段文档或搜索结果挤占上下文。当前 Registry 已有超时和统一错误结构；权限策略、调用去重和完整 Trace 将在后续阶段接入。

## 7. Trace 与异常

一次 Agent 请求分配 trace_id。建议记录：

- trace_id、session_id、step_index。
- LLM 请求开始/结束时间、耗时和响应状态。
- 模型提出的工具名、参数校验结果。
- 工具执行开始/结束时间、耗时、成功/失败状态。
- 循环退出原因：final_answer、max_steps、error、cancelled。

不要记录 API Key、Authorization Header 或其他凭据。日志中对用户输入和工具输出应考虑长度限制及敏感信息脱敏。

## 8. 分阶段交付

| 阶段 | 交付 |
| --- | --- |
| 1 | 项目骨架、配置、健康检查、领域 Schema、CI |
| 2 | OpenAI 兼容 LLM Provider、响应解析、Mock Provider 测试 |
| 3 | Tool Registry、Schema 校验、Calculator / Search / Todo |
| 4 | Agent Loop、工具结果回填、停止条件 |
| 5 | SQLite Session、短期历史、长期 Memory、Context 压缩 |
| 6 | Trace、超时、重试边界、异常恢复 |
| 7 | 集成测试、README 完善、演示用例和最终验收 |
