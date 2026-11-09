# 第九阶段：工程化完善与最终验收

## 1. 本阶段目标

本阶段不重复实现已有能力，而是对阶段 1–8 的模块进行工程化加固，并通过 Mock LLM 的端到端场景验证真实调用链。

## 2. 已完成的工程化改造

### 2.1 Todo 用户隔离

- Todo 表增加 `user_id`，并建立 `(user_id, id)` 索引。
- add / list / complete 每次都从 Runtime 提供的可信 `ToolExecutionContext.user_id` 获取用户身份。
- 模型参数中不接受 user_id，防止模型伪造租户。
- 完成操作使用 `WHERE id = ? AND user_id = ?`，其他用户无法修改该记录。
- 旧版无 user_id 的数据迁移为 `__legacy_unassigned__`，不会自动归属到任意用户。
- 缺失可信上下文时拒绝执行。

### 2.2 API 身份认证

- 使用 PyJWT 验证 Bearer Token。
- 验证 HS256 签名、issuer、audience、exp 和 sub。
- user_id 只从已验证 token 的 sub 中取得。
- 不再信任 `X-User-ID` 请求头。
- production / prod 环境拒绝使用仓库内置的开发 JWT Secret。

本地测试可以用测试密钥签发 JWT；生产环境应由独立身份服务签发 Token，Secret 通过 Secret Manager 注入并定期轮换。当前实现是 API 侧 JWT 验证，不包含用户注册、登录和 Refresh Token 服务。

### 2.3 SQLite 与 Session 并发安全

- SQLite 统一设置 busy_timeout、foreign_keys，并对文件数据库启用 WAL。
- Session 使用数据库租约锁，同一 Session 同一时刻只允许一个 Chat turn 持有锁。
- 锁等待超时返回 SessionBusyError，由 API 映射为 409 和 Retry-After。
- 幂等键按 user_id 隔离，保存请求体哈希和处理状态。
- 同一幂等键、同一请求体重放已完成响应；同一幂等键对应不同请求体返回 409；正在处理时返回 409。
- 幂等请求记录支持过期清理。

### 2.4 Trace 增强

- Trace 详情支持 event_id 游标分页，单页最多 500 条事件。
- Trace 列表支持按开始时间向前翻页。
- 配置 `TRACE_RETENTION_DAYS`，应用启动时清理超过保留期的已结束 Trace。
- 统一异常分类：`timeout`、`provider`、`storage`、`validation`、`tool_execution`、`cancelled`、`internal`。
- 异常详情只保存异常类型，不持久化原始异常消息，降低凭据泄露风险。

## 3. 端到端验收

新增 Mock Provider 场景，不需要真实模型 API Key，验证：

1. 单次 Agent 规划中发起多个工具调用。
2. calculator 与 Todo 工具执行并将结果回填模型上下文。
3. Todo 只能读取和修改当前用户的数据。
4. Long-term Memory 跨 Session 召回。
5. ContextManager 对较早消息进行摘要压缩，保留近期上下文。
6. Session 消息历史正确持久化，工具调用 ID 与工具结果关联。
7. Trace 保存模型调用、工具执行、成功状态和耗时。
8. 模型超时后 Trace 标记失败并分类为 timeout，敏感异常文本不落库。
9. JWT 缺失、伪造、过期 Token 和伪造 X-User-ID 均不能通过认证。
10. 幂等请求重放不会再次调用模型；冲突请求返回 409。
11. 同一 Session 的并发请求按顺序执行。

## 4. 本地验收命令

~~~bash
pip install -e ".[dev]"
ruff check src tests
pytest
~~~

GitHub Actions 验收结果：

- Ruff：All checks passed
- Pytest：87 passed
- Run: https://github.com/xinxin1101/answer/actions/runs/42635895504

## 5. 运行配置

`.env.example` 已包含：

~~~env
APP_ENV=dev
DATABASE_PATH=./data/agent.db
JWT_SECRET=dev-only-insecure-secret-change-before-deploy-000000000000
JWT_ISSUER=minimal-agent-runtime
JWT_AUDIENCE=minimal-agent-api
TRACE_RETENTION_DAYS=30
~~~

开发环境可以使用示例 Secret 运行本地服务。部署环境必须替换为随机高强度密钥，且不要提交到 Git。

## 6. 当前边界与后续建议

本阶段完成的是单机 / 单数据库的工程化 Demo 验收，不等于已经具备大规模生产部署能力：

- SQLite WAL 适合本地与中小规模单机访问；多实例部署应迁移 PostgreSQL。
- Session 锁是数据库租约锁，长任务要关注 lease 超时和续租；高并发分布式任务可使用 Redis 锁或队列协调。
- JWT 验证已经接入，但用户登录、Token 签发、刷新、吊销和密钥轮换应由正式身份服务负责。
- 幂等机制可避免常见客户端重试造成的重复处理，但外部工具副作用仍应根据业务增加工具级幂等键。
- Trace 当前为同步 SQLite 写入；更高吞吐场景可接入异步队列和 OpenTelemetry。
- 本阶段使用 Mock LLM 完成可重复测试；真实模型的端到端演示仍需要在本地配置 API Key 后执行。
