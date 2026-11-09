# 阶段 6：ContextManager 与 ChatService

## 职责边界
- SessionStore 保存完整、未裁剪的原始消息。
- ContextManager 按最大消息数构建本轮上下文。
- ChatService 自动加载历史、调用 Runtime、保存本轮新增消息。
- AgentRuntime 仍不直接依赖数据库。

## Sliding Window
ContextManager 按用户轮次分组，而不是按单条消息机械截断。assistant tool_calls 及其 tool result 和最终答复作为一个完整轮次保留，避免产生孤立工具结果。

max_messages 为历史上下文预算，并为当前新用户消息预留一个位置。若最近的单轮本身超过预算，则完整保留该轮，不拆分工具协议。

## 基础摘要
被滑动窗口移出的旧轮次会生成确定性抽取式摘要，保留用户陈述、助手答复、工具名称及有限长度的工具结果。摘要不额外调用 LLM。原始消息仍完整保存在 SQLite，摘要只在本轮请求时附加到 system message。

## 自动对话流程
1. 没有 session_id：创建新会话。
2. 有 session_id：验证 user_id 所有权并读取历史。
3. ContextManager 生成最近历史和摘要。
4. AgentRuntime 执行本轮对话。
5. ChatService 从 Runtime 结果中排除 system prompt 和已加载历史，只追加本轮新增消息。
6. 返回 session_id 和答复。

## 使用示例
~~~python
result = await chat_service.chat(
    user_id="user-001",
    message="继续刚才的计算，并解释结果",
    session_id="existing-session-id",
)
print(result.reply)
print(result.summary_used)
~~~

## 当前限制
摘要是确定性抽取式摘要，不是语义归纳；max_messages 是消息数量预算，不是精确 Token 预算。认证、HTTP Chat API、长期 Memory 和 Trace 在后续阶段实现。
