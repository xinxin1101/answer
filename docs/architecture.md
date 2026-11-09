# 系统架构与关键设计

## 1. 目标与边界

本项目从零实现一个最小可用 Agent Runtime。FastAPI 只承担 HTTP 接入，不承担 Agent 决策；Agent Loop、工具注册、上下文管理、Session 和 Memory 均由项目自身实现。

明确不使用 LangGraph、OpenHands、OpenClaw 等 Agent 框架。LLM SDK 也不负责执行工具：模型只返回结构化调用请求，Runtime 负责验证、授权和执行。

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
          +---- JSON Schema validation
          +---- ToolExecutor
                  +---- calculator
                  +---- search (mockable)
                  +---- todo
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

## 3. Agent Loop

计划采用显式循环，而不是把流程交给 Agent 框架：

~~~python
for step in range(max_agent_steps):
    response = await llm.complete(messages, tools=registry.schemas())

    if response.tool_calls:
        for call in response.tool_calls:
            tool = registry.get(call.name)
            validated_args = tool.validate(call.arguments)
            result = await tool.execute(validated_args)
            messages.append(tool_result_message(call, result))
        continue

    return response.content or ""

return "本轮执行达到最大步骤限制，请缩小任务范围后重试。"
~~~

上面是流程示意，不是当前已经完成的实现。实际实现还需要处理并行/串行工具调用策略、工具错误回填、重复调用保护、超时和取消。

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

后续可以从最大消息数升级为 token 预算，但不在第一阶段引入复杂摘要模型。

## 5. Session 与 Memory 的边界

### Session（短期记忆）

Session 表示一个独立聊天窗口。同一用户可以有多个 session：

- 用户 A / 窗口 1：查询天气、添加待办。
- 用户 A / 窗口 2：编写周报、添加另一条待办。

两者使用不同 session_id。读取历史时必须同时校验用户身份和 session 归属，不能只依赖前端传入的 session_id。

短期记忆存储当前任务的消息历史、摘要、工具调用结果引用和会话状态。建议以 SQLite 的 sessions、messages 表持久化。

### Long-term Memory（长期记忆）

长期记忆存放跨会话仍然有用的信息，例如用户明确表达并且长期稳定的偏好、持续项目约束和反复出现的工作背景。

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

每个工具至少包含：

- name：稳定且唯一的工具名。
- description：模型可理解的用途和适用边界。
- parameters_schema：JSON Schema 参数定义。
- handler：真实执行函数。
- timeout / permission：执行超时和权限约束。

模型返回的参数必须先经过 JSON 解析、Schema 校验和权限检查，再进入 handler。禁止使用 eval 执行模型生成的 Python 表达式。Calculator 应使用安全的 AST 白名单解析；Search 第一版允许 Mock；Todo 的写操作应验证参数并持久化。

工具执行结果应有大小限制，避免大段文档或搜索结果挤占上下文。

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
| 2 | OpenAI 兼容 LLM Provider、响应解析、Fake Provider 测试 |
| 3 | Tool Registry、Schema 校验、Calculator / Search / Todo |
| 4 | Agent Loop、工具结果回填、停止条件 |
| 5 | SQLite Session、短期历史、长期 Memory、Context 压缩 |
| 6 | Trace、超时、重试边界、异常恢复 |
| 7 | 集成测试、README 完善、演示用例和最终验收 |
