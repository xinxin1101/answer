# Minimal Agent Runtime

从零实现一个最小可用 Agent 的练习项目。核心目标是自行实现 Agent Runtime，不依赖 LangGraph、OpenHands、OpenClaw 等 Agent 框架。

## 当前进度

- [x] 阶段 1：项目骨架、配置管理、FastAPI 健康检查、基础领域模型与 CI
- [x] 阶段 2：OpenAI 兼容 LLM Provider、响应解析与 Mock 测试
- [x] 阶段 3：Tool Registry、JSON Schema 参数校验、Calculator / Search / Todo
- [ ] 阶段 4：Agent Loop、工具结果回填与停止条件
- [ ] 阶段 5：SQLite Session、短期历史、长期 Memory 与 Context 压缩
- [ ] 阶段 6：Trace、超时、重试边界与异常恢复
- [ ] 阶段 7：集成测试、演示用例与最终验收

当前已完成 LLM 接入和独立工具执行模块；尚未把它们串成完整 Agent 对话循环。每个阶段都配套测试和开发记录。

## 技术选型

| 模块 | 方案 |
| --- | --- |
| 语言 | Python 3.11+ |
| HTTP 服务 | FastAPI + Uvicorn |
| 配置与数据校验 | Pydantic Settings / Pydantic |
| LLM 接入 | httpx + OpenAI-compatible Chat Completions |
| 工具执行 | 自行实现 ToolRegistry + Pydantic JSON Schema |
| Todo 持久化 | SQLite |
| 测试 | Pytest + httpx.MockTransport |
| 代码规范 / CI | Ruff / GitHub Actions |

核心 Agent Loop、工具路由、上下文管理和记忆策略由本项目自行实现，不使用现成 Agent 框架。

## 项目结构

~~~text
.
├── .github/workflows/tests.yml
├── docs/
│   ├── ai-development-log.md
│   ├── architecture.md
│   ├── llm-integration.md
│   └── tools.md
├── src/min_agent/
│   ├── api/
│   ├── core/schemas.py
│   ├── llm/
│   │   ├── errors.py
│   │   ├── openai_compatible.py
│   │   ├── parser.py
│   │   └── protocol.py
│   ├── tools/
│   │   ├── base.py
│   │   ├── calculator.py
│   │   ├── defaults.py
│   │   ├── registry.py
│   │   ├── search.py
│   │   └── todo.py
│   ├── config.py
│   └── main.py
├── tests/
│   ├── test_builtin_tools.py
│   ├── test_health.py
│   ├── test_llm_parser.py
│   ├── test_llm_provider.py
│   ├── test_schemas.py
│   └── test_tool_registry.py
├── .env.example
├── .gitignore
└── pyproject.toml
~~~

## 本地运行

### 1. 创建虚拟环境

Windows PowerShell：

~~~powershell
python -m venv .venv
.venv\Scripts\Activate.ps1
~~~

macOS / Linux：

~~~bash
python3 -m venv .venv
source .venv/bin/activate
~~~

### 2. 安装依赖

~~~bash
python -m pip install --upgrade pip
pip install -e ".[dev]"
~~~

### 3. 配置环境变量

复制 .env.example 为 .env，再按需填写配置。

Windows PowerShell：

~~~powershell
Copy-Item .env.example .env
~~~

macOS / Linux：

~~~bash
cp .env.example .env
~~~

**不要将真实 API Key 写入代码或提交到 GitHub。** .env 已加入 .gitignore。LLM Provider 从环境变量读取密钥。

### 4. 启动服务

~~~bash
uvicorn min_agent.main:app --reload
~~~

健康检查地址：http://127.0.0.1:8000/api/v1/health

Swagger 文档：http://127.0.0.1:8000/docs

### 5. 运行测试

~~~bash
pytest
ruff check src tests
~~~

## 工具模块快速使用

~~~python
import asyncio

from min_agent.config import Settings
from min_agent.tools.defaults import build_default_registry


async def main() -> None:
    config = Settings(database_path="./data/agent.db")
    registry = build_default_registry(config)

    print(registry.schemas())

    result = await registry.execute(
        "calculator",
        {"expression": "(12 + 8) * 3 / 2"},
    )
    print(result.model_dump())


asyncio.run(main())
~~~

内置工具：
- calculator：受限 AST 数学计算，不使用 eval。
- search：确定性的本地 Mock 搜索，不访问外部网络。
- todo：SQLite 待办管理，支持 add / list / complete。

## 系统设计原则

1. **Runtime 自主实现**：Agent Loop 负责组织模型调用、工具执行、结果回填和停止条件。
2. **工具显式注册**：工具包含名称、描述、参数 Schema 和执行函数；模型只提出调用请求，Runtime 负责校验与执行。
3. **Session 隔离**：每个会话使用独立 session_id，消息历史不能跨会话混用。
4. **Context 有边界**：系统指令、必要历史、摘要和本轮工具结果按策略组装；设置最大轮次和上下文预算。
5. **Memory 与 Trace 分离**：对话记忆服务于后续回答；Trace 用于审计和排错，不把隐藏推理过程当作记忆保存。
6. **密钥不入库**：密钥通过环境变量注入，禁止提交 .env、Token 或真实请求头。

详细设计见：
- [系统架构](docs/architecture.md)
- [LLM 接入](docs/llm-integration.md)
- [工具注册与执行](docs/tools.md)
- [AI Prompt 与问题解决记录](docs/ai-development-log.md)
