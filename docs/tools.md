# 阶段 3：Tool Registry 与内置工具

## 1. 工具定义

每个工具由 ToolDefinition 描述：

- name：唯一工具名。
- description：模型用于判断何时调用该工具的说明。
- args_model：Pydantic 参数模型，同时作为参数校验规则和 JSON Schema 来源。
- handler：实际执行函数，可为同步或异步函数。
- timeout_seconds：异步执行的超时上限。

工具不需要继承 Agent 框架的 BaseTool，也不依赖 LangChain。

## 2. 注册和 Schema 导出

~~~python
registry.register(build_calculator_tool())
registry.register(build_search_tool())
registry.register(build_todo_tool("./data/agent.db"))

schemas = registry.schemas()
~~~

schemas() 返回 OpenAI-compatible function calling 结构。Provider 把该结构传给模型；模型只能提出 ToolCall，不能直接运行 Python 函数。

## 3. 执行流程

1. Runtime 从 LLMResponse.tool_calls 取出工具名称和 JSON 参数。
2. ToolRegistry 根据名称查找已注册的 ToolDefinition。
3. args_model.model_validate(arguments) 验证字段类型、范围和额外字段。
4. 校验成功后才调用 handler。
5. 异步 handler 由 asyncio.wait_for 执行超时控制。
6. 最终统一返回 ToolExecutionResult：tool_name、success、output、error。

未知工具、参数错误、超时和 handler 异常都会变成结构化失败结果，不会让工具异常直接破坏 Runtime 主流程。

## 4. 内置工具

### calculator

- 参数：expression。
- 支持：加减乘除、整除、取模、乘方、正负号和括号。
- 实现：Python ast.parse + 节点白名单递归求值。
- 限制：表达式长度、AST 节点数量、数字字面量和指数范围。
- 不支持变量、函数调用、属性访问、导入或任意 Python 语句。

### search

- 参数：query、limit。
- 数据源：代码内置的 MOCK_DOCUMENTS。
- 结果：按查询词与关键词交集排序，返回确定性结果。
- 用途：在不申请搜索 API Key 的情况下验证工具选择、参数传递和结果回填。

### todo

- 参数：action、title、todo_id。
- action=add：添加待办。
- action=list：列出待办。
- action=complete：将指定待办标记为完成。
- 存储：SQLite，默认数据库路径由 DATABASE_PATH 配置。
- SQL：全部使用参数化查询。

Todo 工具是跨进程重启仍可保留的文件数据库数据；测试可以使用临时数据库或 :memory:。

## 5. 本地运行示例

~~~python
import asyncio

from min_agent.config import Settings
from min_agent.tools.defaults import build_default_registry


async def main() -> None:
    registry = build_default_registry(Settings(database_path="./data/agent.db"))

    calc = await registry.execute("calculator", {"expression": "(12 + 8) * 3 / 2"})
    print(calc.model_dump())

    created = await registry.execute("todo", {"action": "add", "title": "Review Agent Loop"})
    print(created.model_dump())

    todos = await registry.execute("todo", {"action": "list"})
    print(todos.model_dump())


asyncio.run(main())
~~~

## 6. 测试

~~~bash
pytest tests/test_tool_registry.py tests/test_builtin_tools.py
ruff check src tests
~~~

测试覆盖 Schema 导出、重复注册、未知工具、参数拒绝、执行超时、计算表达式安全边界、Mock Search、Todo 增删查完成与内存数据库。
