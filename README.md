# Minimal Agent Runtime

从零实现一个最小可用 Agent 的练习项目。核心目标是自行实现 Agent Runtime，不依赖 LangGraph、OpenHands、OpenClaw 等 Agent 框架。

## 当前进度

- [x] 阶段 1：项目骨架、配置管理、FastAPI 健康检查、基础领域模型、CI 与文档
- [ ] 阶段 2：LLM Provider 与模型输出解析
- [ ] 阶段 3：Tool Registry、JSON Schema 参数校验及内置工具
- [ ] 阶段 4：Agent Loop
- [ ] 阶段 5：Session、Memory 与 Context 压缩
- [ ] 阶段 6：异常处理、Trace 与执行日志
- [ ] 阶段 7：自动化测试与完整使用文档

> 当前仓库完成的是第一阶段脚手架，尚未声称实现完整 Agent 对话能力。后续按阶段提交，每一阶段都配套测试。

## 技术选型

| 模块 | 方案 |
| --- | --- |
| 语言 | Python 3.11+ |
| HTTP 服务 | FastAPI + Uvicorn |
| 配置与数据校验 | Pydantic Settings / Pydantic |
| LLM 接入 | 后续通过 OpenAI 兼容 HTTP API 接入 |
| Session 持久化 | SQLite（后续阶段） |
| 测试 | Pytest |
| 代码规范 | Ruff |
| CI | GitHub Actions |

核心 Agent Loop、工具路由、上下文管理和记忆策略由本项目自行实现，不使用现成 Agent 框架。

## 项目结构

~~~text
.
├── .github/
│   └── workflows/
│       └── tests.yml
├── docs/
│   ├── architecture.md
│   └── ai-development-log.md
├── src/
│   └── min_agent/
│       ├── api/
│       │   └── routes.py
│       ├── core/
│       │   └── schemas.py
│       ├── llm/
│       │   └── protocol.py
│       ├── config.py
│       └── main.py
├── tests/
│   └── test_health.py
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

**不要将真实 API Key 写入代码或提交到 GitHub。** .env 已加入 .gitignore。后续 LLM 接入将从环境变量读取密钥。

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

## 系统设计原则

1. **Runtime 自主实现**：Agent Loop 负责组织模型调用、工具执行、结果回填和停止条件。
2. **工具显式注册**：工具包含名称、描述、JSON Schema 和执行函数；模型只负责提出调用请求，Runtime 负责校验与执行。
3. **Session 隔离**：每个会话使用独立 session_id，消息历史不能跨会话混用。
4. **Context 有边界**：系统指令、必要历史、摘要和本轮工具结果按策略组装；设置最大轮次和上下文预算。
5. **Memory 与 Trace 分离**：对话记忆服务于后续回答；Trace 用于审计和排错，不把隐藏推理过程当作记忆保存。
6. **密钥不入库**：密钥通过环境变量注入，禁止提交 .env、Token 或真实请求头。

Memory 的召回时机、存储位置和上下文压缩策略见系统架构文档 docs/architecture.md。

## 开发记录

每次 Vibe Coding 迭代记录使用的 Prompt、修改文件、遇到的问题、定位过程和验证结果，模板见 docs/ai-development-log.md。
