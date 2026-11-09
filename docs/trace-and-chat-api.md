# 第八阶段：TraceRecorder 与 Chat HTTP API

## 1. Trace 设计

每次 ChatService 请求开始时创建一个 trace_id。Trace 与 Session、Memory 分开存储：Session 保存对话，Memory 保存跨会话信息，Trace 只用于审计和故障排查。

SQLite 表：

- `traces`：trace_id、user_id、session_id、状态、开始/结束时间、总耗时、停止原因、异常类型。
- `trace_events`：事件序号、事件类型、step_index、tool_call_id、tool_name、状态、耗时和受限的结构化详情。

Runtime 记录的事件包括：

| Event | 说明 |
| --- | --- |
| runtime.started | Agent 执行开始 |
| llm.started | 一次模型请求开始 |
| llm.completed | 模型响应完成 |
| llm.failed | 模型请求抛出异常 |
| tool.started | 工具执行开始 |
| tool.completed | 工具执行结束，含成功/失败状态 |
| runtime.completed | 正常完成或达到 max_steps |
| runtime.failed | ChatService 捕获到未处理异常 |

所有事件按 event_id 排序，耗时使用 monotonic clock 计算。Trace 写入失败不会中断 Agent Runtime 的主流程。

## 2. 隐私与安全

Trace 不保存原始用户消息、模型完整回复、工具参数值、工具输出正文、API Key 或 Authorization Header。

- 工具事件只保存工具名、tool_call_id、参数 key 列表、输出字符数和执行状态。
- LLM 事件只保存响应字符数、finish_reason 和工具调用数量。
- 异常只保存异常类型，不保存可能包含敏感内容的异常原文。
- details 会过滤名称中包含 api_key、authorization、token、password、secret 的字段，并限制序列化长度。
- Trace 查询必须同时匹配 user_id 和 trace_id；不能通过猜测 trace_id 读取其他用户数据。

## 3. Chat API

默认 API 前缀：`/api/v1`。

所有业务接口使用 `X-User-ID` 作为演示项目的用户身份标识。生产系统必须改为从已验证的登录态 / JWT / OAuth 身份中获取 user_id，不能信任客户端任意传入的身份头。

### 发送消息

`POST /api/v1/chat`

请求：

~~~json
{
  "message": "帮我计算 100 * 25",
  "session_id": null
}
~~~

新建会话时不传 session_id 或传 null；继续会话时传之前响应中的 session_id。

响应主要字段：

~~~json
{
  "session_id": "session-uuid",
  "trace_id": "trace-uuid",
  "reply": "计算结果是 2500。",
  "steps": 2,
  "tool_calls_executed": 1,
  "summary_used": false,
  "memory_used": false
}
~~~

### Session

- `GET /api/v1/sessions`：列出当前用户的会话。
- `GET /api/v1/sessions/{session_id}/messages`：读取会话消息。
- `DELETE /api/v1/sessions/{session_id}`：删除会话及其消息。

### Trace

- `GET /api/v1/traces?limit=20`：列出当前用户最近的执行记录。
- `GET /api/v1/traces/{trace_id}`：读取 Trace 元数据和有序事件。

不存在或不属于当前用户的 Session / Trace 均返回 404，避免泄露资源是否存在。

## 4. 本地启动

~~~bash
git pull origin main
pip install -e ".[dev]"
~~~

复制 `.env.example` 为 `.env`，只在本地配置模型服务参数：

~~~env
LLM_API_KEY=your_key
LLM_BASE_URL=https://api.openai.com/v1
LLM_MODEL=gpt-4o-mini
DATABASE_PATH=./data/agent.db
~~~

启动：

~~~bash
uvicorn min_agent.main:app --reload
~~~

打开 `http://127.0.0.1:8000/docs` 查看 Swagger。

PowerShell 测试：

~~~powershell
$headers = @{ "X-User-ID" = "demo-user" }
$body = @{ message = "请计算 100 * 25" } | ConvertTo-Json
$result = Invoke-RestMethod -Method Post -Uri http://127.0.0.1:8000/api/v1/chat -Headers $headers -ContentType "application/json" -Body $body
$result
Invoke-RestMethod -Uri "http://127.0.0.1:8000/api/v1/traces/$($result.trace_id)" -Headers $headers
~~~

## 5. 当前限制

- Trace 目前为同步 SQLite 写入，适合学习项目和低并发场景；高并发时可改为队列 / 异步批量写入。
- 尚未实现 Trace retention、分页游标、采样和分布式 trace context。
- 用户身份头仅用于演示，生产必须接认证中间件。
- 目前 Trace 记录可观察事件，不收集或输出模型隐藏推理过程。
