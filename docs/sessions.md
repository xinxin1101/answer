# 阶段 5：SessionStore 与 MessageStore

## 1. 为什么拆分 Session 和 Message

Session 表示一个独立聊天窗口；Message 表示该窗口内按时间顺序发生的一条对话消息。

同一用户可以创建多个 Session。每个 Session 有自己的消息序列，读取和写入必须同时验证 user_id 与 session_id，不能仅凭客户端提供的 session_id 访问数据。

## 2. SQLite 数据结构

### sessions

| 字段 | 含义 |
| --- | --- |
| session_id | UUID 主键 |
| user_id | 会话所有者 |
| title | 会话标题 |
| created_at | 创建时间 |
| updated_at | 最近消息写入时间 |

### messages

| 字段 | 含义 |
| --- | --- |
| id | 自增消息序号，用于稳定排序 |
| session_id | 所属会话，外键关联 sessions |
| role | user / assistant / tool |
| payload | 完整 ChatMessage JSON |
| created_at | 消息写入时间 |

messages.payload 保存完整消息结构，而不是只保存 content。这样 assistant 的 tool_calls、工具调用 ID、工具参数、tool_call_id 和工具结果都能在恢复后保持原样。

System Prompt 不写入 Session：它属于 Runtime 配置，每次请求由 Runtime 重新注入。避免旧系统指令被误当成用户对话历史。

## 3. 所有权与隔离

所有查询都同时使用 user_id 和 session_id。即使用户猜到其他人的 session_id，也不能读取、追加或删除对方的会话。

当前项目还没有用户认证模块。user_id 是存储层的所有权边界，正式对外提供 API 时必须从经过认证的身份中取得，不能直接信任请求体中的 user_id。

## 4. Python 使用方式

~~~python
from min_agent.core.schemas import ChatMessage
from min_agent.sessions.store import SessionStore

store = SessionStore("./data/agent.db")

session = store.create_session("user-001", "Weather assistant")
store.append_messages(
    "user-001",
    session.session_id,
    [
        ChatMessage(role="user", content="What's the weather in Guilin?"),
        ChatMessage(role="assistant", content="I need a weather source to check."),
    ],
)

history = store.get_messages("user-001", session.session_id)
~~~

## 5. 和 AgentRuntime 的衔接方式

当前阶段提供可靠的持久化接口，但尚未把 SessionStore 直接耦合进 AgentRuntime。下一阶段的 Chat Service/API 层将按以下顺序编排：

1. 创建新会话，或根据 user_id + session_id 验证并恢复已有会话。
2. 通过 get_messages() 读取历史。
3. 将历史传入 AgentRuntime.run(message, history=history)。
4. Runtime 返回的 result.messages 包含 system prompt，因此只将本轮新增的非 system 消息追加到 MessageStore；不能把整份历史重复保存。
5. 返回 session_id 和 reply。

## 6. 当前范围

本阶段实现会话元数据、消息持久化、消息顺序、工具消息往返序列化、所有权校验和重启恢复。

暂不实现：
- 自动识别和创建用户身份 / 登录认证。
- Chat API 路由。
- Context 滑动窗口与摘要压缩。
- 跨 Session Long-term Memory。
- Trace 和耗时统计。
