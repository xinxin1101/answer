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
