# AI Prompt 与问题解决记录

本文件记录 Vibe Coding 过程中的需求 Prompt、设计决策、问题定位和验证结果。每轮开发完成后追加一条，不记录任何真实密钥或隐私数据。

## 记录模板

### 日期 / 阶段

- **目标**：
- **输入 Prompt**：
- **修改文件**：
- **设计决策**：
- **遇到的问题**：
- **定位与解决**：
- **验证命令及结果**：
- **遗留事项**：

---

## 2026-11-09 / 阶段 1：初始化项目骨架

- **目标**：在指定 GitHub 仓库中建立从零实现 Agent Runtime 的 Python 项目基础结构。
- **输入 Prompt 摘要**：不依赖 LangGraph、OpenHands、OpenClaw 等 Agent 框架；后续需要实现 Agent Loop、工具注册、Session 隔离、Context 管理、Memory、异常处理、Trace 和测试。
- **修改文件**：README、pyproject、环境变量模板、gitignore、FastAPI 入口、配置模块、基础领域 Schema、LLM Provider Protocol、测试、架构文档、GitHub Actions。
- **设计决策**：使用 Python 3.11+、FastAPI、Pydantic Settings 和 Pytest；先定义 LLM Provider Protocol，使 Runtime 不绑定某个 SDK；API Key 只从环境变量读取。
- **遇到的问题**：目标仓库最初为空；首次 CI 运行时 Ruff I001 检查发现两个文件的导入格式问题。
- **定位与解决**：根据 GitHub Actions 日志修复导入格式，并重新执行 CI。
- **验证命令及结果**：GitHub Actions 通过依赖安装、Ruff 和 Pytest。运行记录：https://github.com/xinxin1101/answer/actions/runs/42584901354
- **遗留事项**：实现 LLM HTTP 适配器、响应解析与 Fake Provider 测试。

## 2026-11-09 / 阶段 2：LLM Provider 与输出解析

- **目标**：不使用 Agent 框架或 LLM SDK，自行封装 OpenAI-compatible Chat Completions HTTP 请求和响应解析。
- **输入 Prompt 摘要**：实现 LLM Client，支持普通文本和工具调用响应解析；API Key 不得写入代码。
- **修改文件**：llm/errors.py、llm/parser.py、llm/openai_compatible.py、test_llm_parser.py、test_llm_provider.py、docs/llm-integration.md。
- **设计决策**：使用 httpx.AsyncClient；通过 Pydantic LLMResponse / ToolCall 归一化响应；使用 httpx.MockTransport 测试，不调用真实模型。
- **安全边界**：Provider 只解析 ToolCall，不执行工具；错误消息不回显服务端错误正文；密钥仅通过环境变量注入。
- **验证命令及结果**：阶段 2 提交曾通过 GitHub Actions，运行记录：https://github.com/xinxin1101/answer/actions/runs/42588957663
- **遗留事项**：与 Tool Registry 和 Agent Loop 集成。

## 2026-11-09 / 阶段 3：Tool Registry 与内置工具

- **目标**：实现自有工具注册、JSON Schema 暴露、参数校验、受控执行和三个必需工具。
- **输入 Prompt 摘要**：实现 calculator、mock search 和 todo；模型按 Schema 自主选择工具；执行前必须校验参数。
- **修改文件**：tools/base.py、tools/registry.py、tools/calculator.py、tools/search.py、tools/todo.py、tools/defaults.py、test_tool_registry.py、test_builtin_tools.py、docs/tools.md，并恢复阶段 2 的 LLM Provider、解析器和测试文件。
- **设计决策**：
  1. ToolDefinition 用 Pydantic 参数模型生成 JSON Schema。
  2. ToolRegistry 负责名称查找、参数校验、超时和结构化错误结果。
  3. Calculator 使用 AST 白名单，不使用 eval。
  4. Search 使用离线 Mock 数据，便于可重复测试。
  5. Todo 使用 SQLite 参数化查询，支持 add / list / complete。
- **遇到的问题**：首次 CI 因 Ruff I001 和 E501 未通过；修复后发现一次 Git Tree 更新没有保留上一阶段的 LLM 文件。
- **定位与解决**：根据 Actions 日志修复导入排序和超长行；通过递归检查 Git Tree 发现 LLM 文件缺失，再从阶段 2 的提交恢复，并将阶段 2 和阶段 3 文件放入同一完整仓库树。
- **验证命令及结果**：恢复阶段 2 的 LLM Provider、解析器、集成文档和测试后，GitHub Actions 完整执行 Ruff 与 Pytest，31 项测试全部通过。运行记录：https://github.com/xinxin1101/answer/actions/runs/42590669474
- **遗留事项**：实现 Agent Loop，将 LLMProvider、ToolRegistry 和 ChatMessage/ToolCall 连接起来。

## 2026-11-09 / 阶段 4：Agent Loop 与工具结果回填

- **目标**：连接 LLM Provider 和 Tool Registry，让模型能够自主提出工具调用、由 Runtime 执行并将结果交回模型，直到生成最终答案。
- **输入 Prompt 摘要**：实现 AgentRuntime、run() 循环、assistant tool_calls / tool result 消息、多工具调用和最大步数限制。
- **修改文件**：runtime.py、core/schemas.py、llm/protocol.py、llm/openai_compatible.py、test_runtime.py、test_schemas.py、test_llm_provider.py、README、architecture.md、agent-loop.md。
- **设计决策**：
  1. AgentRuntime 通过依赖注入接收 LLMProvider 和 ToolRegistry，不绑定具体模型 SDK。
  2. 每次 LLM 请求计为一个 step；同一响应中的多个工具调用按返回顺序串行执行，降低数据库写操作等副作用并发造成的竞态。
  3. 工具调用结果以 role=tool 的消息回填，并使用 tool_call_id 与 assistant tool_calls 关联。
  4. ToolRegistry 的未知工具、参数校验失败和 handler 异常会作为结构化失败结果交给模型，而不是直接丢弃。
  5. history 只接收既有会话消息；system prompt 由 Runtime 统一注入，避免外部历史覆盖系统约束。
  6. 达到 max_steps 后停止继续请求模型，并返回明确的停止原因。
- **遇到的问题**：第一次 CI 检查发现 runtime.py 的 Ruff I001 导入块格式问题。
- **定位与解决**：根据 GitHub Actions 日志逐步对齐 Ruff 的导入块与空行规则，随后完整执行 Lint 和测试。
- **验证命令及结果**：GitHub Actions Ruff 检查通过，Pytest 收集 43 项并全部通过。运行记录：https://github.com/xinxin1101/answer/actions/runs/42593722485
- **遗留事项**：下一阶段实现 SQLite Session、短期历史持久化、长期 Memory 召回和 Context 压缩；随后增加 API 路由、Trace 和异常恢复。

## 2026-11-09 / 阶段 5：SQLite SessionStore 与 MessageStore

- **目标**：实现多聊天窗口隔离、历史消息持久化、重启恢复和会话所有权校验。
- **输入 Prompt 摘要**：为每个用户的多个窗口建立独立 session；消息通过 user_id + session_id 读写；工具调用消息必须能完整恢复。
- **修改文件**：sessions/store.py、sessions/__init__.py、test_sessions.py、docs/sessions.md、README.md、docs/architecture.md。
- **设计决策**：
  1. sessions 表保存会话元数据，messages 表保存按自增 id 排序的完整 ChatMessage JSON。
  2. 所有读写操作都同时校验 user_id 和 session_id，防止跨用户读取或修改。
  3. System Prompt 不持久化，由 Runtime 每次请求注入。
  4. assistant tool_calls 与 role=tool 结果完整序列化，恢复后保留 tool_call_id 关联。
  5. SessionStore 与 AgentRuntime 解耦，下一阶段由 Chat Service 负责读取历史、调用 Runtime 并只追加本轮新消息。
- **测试覆盖**：同一用户多个 Session 隔离、不同用户隔离、服务重启恢复、工具调用/结果往返、system prompt 拒绝持久化、删除会话级联删除、空 user_id 校验。
- **遗留事项**：接入 Chat Service/API；实现 ContextManager 的消息窗口和摘要压缩；明确 Todo 数据按 user 还是 session 隔离。
