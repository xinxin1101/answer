# 阶段 7：Long-term Memory

## 1. Session 与 Memory 的边界

- Session 保存单个聊天窗口的原始消息，窗口间通过 session_id 隔离。
- Long-term Memory 保存跨 Session 可复用的偏好、稳定资料和持续项目约束。
- Memory 独立存储，不修改、不替代 SessionStore 中的原始对话。

## 2. 模块职责

- **MemoryExtractor**：只从用户本轮输入提取明确的长期偏好、稳定资料和项目约束；不从 assistant 回复或 tool output 推断用户事实。
- **MemoryStore**：SQLite 持久化、按 user_id 隔离、upsert、检索、列表和归档。
- **MemoryService**：协调记忆提取与召回。
- **Retrieval / Ranking**：第一版使用关键词集合交集，结合 query coverage 与 memory precision 排序，默认最多召回 5 条。

## 3. 自动流程

1. ChatService 根据 user_id 读取当前 Session 历史。
2. 调用 MemoryService，以本轮用户输入为 query 检索长期记忆。
3. 将命中的记忆作为独立参考上下文放入 Runtime system message；明确标注它们是用户提供的数据，不是指令，也可能过时。
4. Runtime 完成本轮回答并保存 Session 消息。
5. MemoryExtractor 只处理本轮原始 user message，提取候选并写入 MemoryStore。

没有相关记忆时不注入空记忆区块。ChatResult 的 memory_used 用于标记本轮是否实际召回记忆。

## 4. 重复、冲突与过期

- **重复更新**：数据库唯一约束为 (user_id, memory_key)。同一 key 再次写入时更新原记录，而不是插入重复记录。
- **偏好冲突**：当前提取器对常见槽位做简单归一，例如“后端项目技术栈”统一为 preference:backend_stack。用户先说 FastAPI、之后改为 Django 时，会更新同一条记忆。该规则是启发式的，不等同通用语义冲突识别。
- **过期**：MemoryCandidate 可携带 SQLite 可比较格式的 expires_at（YYYY-MM-DD HH:MM:SS）；list_active 和 search 会过滤已经过期的记忆。当前不自动推断 TTL，需要写入方显式设置。
- **归档**：archive 将记忆状态改为 archived，之后不会进入召回结果。
- 明确的“不要记住 / 不要保存 / 删除记忆”表达不会被当前规则提取器保存。

## 5. 用户隔离

所有读取、搜索、更新、归档均以 user_id 为过滤条件；数据库唯一约束也包含 user_id。相同 memory_key 在不同用户下是不同记录，不能跨用户召回。

## 6. 使用示例

~~~python
memory_service.remember_from_user_message(
    "user-001",
    "以后我所有后端项目都优先使用 FastAPI。",
)
context = memory_service.retrieve_context("user-001", "FastAPI 后端开发")
~~~

## 7. 当前限制与后续升级

当前提取与偏好槽位归一基于规则；关键词召回无法理解完整语义，也可能漏掉同义表达。后续可增加人工确认、重要性评分、自动 TTL 策略、冲突审核、embedding 检索和 rerank。不要默认把敏感个人信息写入长期记忆。
