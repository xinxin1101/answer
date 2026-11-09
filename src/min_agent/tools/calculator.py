"""A deliberately restricted arithmetic calculator (no eval or exec)."""

import ast
import math
import operator

from pydantic import BaseModel, ConfigDict, Field

from min_agent.tools.base import ToolDefinition


class CalculatorArgs(BaseModel):
    model_config = ConfigDict(extra="forbid")

    expression: str = Field(min_length=1, max_length=200, description="Arithmetic expression.")


_BINARY_OPERATORS = {
    ast.Add: operator.add,
    ast.Sub: operator.sub,
    ast.Mult: operator.mul,
    ast.Div: operator.truediv,
    ast.FloorDiv: operator.floordiv,
    ast.Mod: operator.mod,
    ast.Pow: operator.pow,
}
_UNARY_OPERATORS = {ast.UAdd: operator.pos, ast.USub: operator.neg}
_MAX_NUMBER = 10**12
_MAX_RESULT = 10**100
_MAX_NODES = 50


def _check_number(value: int | float) -> int | float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError("Only numeric values are allowed.")
    if abs(value) > _MAX_RESULT:
        raise ValueError("Result is too large.")
    if isinstance(value, float) and not math.isfinite(value):
        raise ValueError("Result must be finite.")
    return value


def _evaluate(node: ast.AST) -> int | float:
    if isinstance(node, ast.Expression):
        return _evaluate(node.body)

    if isinstance(node, ast.Constant):
        if isinstance(node.value, bool) or not isinstance(node.value, (int, float)):
            raise ValueError("Only numeric constants are allowed.")
        if abs(node.value) > _MAX_NUMBER:
            raise ValueError("Numeric literal is too large.")
        return node.value

    if isinstance(node, ast.UnaryOp) and type(node.op) in _UNARY_OPERATORS:
        return _check_number(_UNARY_OPERATORS[type(node.op)](_evaluate(node.operand)))

    if isinstance(node, ast.BinOp) and type(node.op) in _BINARY_OPERATORS:
        left = _evaluate(node.left)
        right = _evaluate(node.right)
        if isinstance(node.op, ast.Pow) and abs(right) > 10:
            raise ValueError("Exponent magnitude must not exceed 10.")
        return _check_number(_BINARY_OPERATORS[type(node.op)](left, right))

    raise ValueError("Expression contains an unsupported operation.")


async def calculate(args: CalculatorArgs) -> dict[str, int | float | str]:
    """Evaluate a bounded arithmetic expression using a safe AST allowlist."""
    try:
        parsed = ast.parse(args.expression, mode="eval")
        if sum(1 for _ in ast.walk(parsed)) > _MAX_NODES:
            raise ValueError("Expression is too complex.")
        value = _evaluate(parsed)
        return {"expression": args.expression, "result": value}
    except (SyntaxError, ZeroDivisionError, OverflowError) as exc:
        raise ValueError("Expression is invalid or cannot be evaluated.") from exc


def build_calculator_tool() -> ToolDefinition:
    return ToolDefinition(
        name="calculator",
        description=(
            "Evaluate a basic arithmetic expression. Supports +, -, *, /, //, %, ** "
            "and parentheses. Does not support variables, names or code."
        ),
        args_model=CalculatorArgs,
        handler=calculate,
        timeout_seconds=2.0,
    )
