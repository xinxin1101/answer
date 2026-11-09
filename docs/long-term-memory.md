# 阶段 7：Long-term Memory

- Session 保存单个聊天窗口的原始消息；Memory 保存跨 Session 可复用的偏好、稳定资料和项目约束。
- MemoryExtractor 只处理用户本轮输入，不从助手答复或工具结果推断用户事实。
- MemoryStore 使用 SQLite，唯一键为 (user_id, memory_key)，支持 upsert、检索、列表和归档。
- Retrieval 第一版采用关键词交集评分，结合 query coverage 和记忆文本 precision 排序。
- ChatService 请求前召回相关记忆，作为参考数据注入 Runtime；回答后从用户原始输入提取候选并持久化。
- 所有读写均限定 user_id，防止跨用户记忆泄漏。
- 当前限制：规则提取和关键词检索不等同语义理解；复杂冲突检测、自动 TTL、人工确认和向量检索留待后续。
