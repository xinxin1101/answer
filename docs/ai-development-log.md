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
- **设计决策**：
  1. 使用 Python 3.11+、FastAPI、Pydantic Settings 和 Pytest。
  2. 先定义 LLM Provider Protocol，使 Runtime 不绑定某个 SDK；实际 HTTP 适配器留到阶段 2。
  3. 先建立 Agent 请求、消息、工具调用和 LLM 响应的领域 Schema。
  4. API Key 只允许从本地环境变量读取；仓库只提交无真实凭据的 .env.example。
  5. 第一阶段只交付基础服务和工程骨架，不虚报 Agent Loop 已完成。
- **遇到的问题**：目标仓库最初为空，没有可读取的 README 或已有目录。首次 CI 运行时，Ruff I001 检查发现两个文件在模块级变量前多留了一行空行。
- **定位与解决**：先初始化 README 和 main 分支，再基于首个提交创建其余项目文件；根据 GitHub Actions 日志定位多余空行并修复，同时移除临时诊断步骤。
- **验证命令及结果**：GitHub Actions 最新运行通过依赖安装、ruff check src tests 和 pytest；本次未在本地执行测试。运行记录：https://github.com/xinxin1101/answer/actions/runs/42584726796
- **遗留事项**：实现 LLM HTTP 适配器、响应解析与 Fake Provider 测试。
