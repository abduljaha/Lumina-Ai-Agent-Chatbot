"""Calculator tool - safe arithmetic expression evaluation."""
from __future__ import annotations

import ast
import operator
from typing import Any

from app.tools.base import ToolResult


class CalculatorTool:
    """Evaluates safe arithmetic expressions using Python's AST."""

    name = "calculator"
    description = "Perform mathematical calculations. Supports +, -, *, /, **, %, parentheses, and common functions."

    _ALLOWED_NODES = {
        ast.Expression,
        ast.BinOp,
        ast.UnaryOp,
        ast.Add,
        ast.Sub,
        ast.Mult,
        ast.Div,
        ast.Pow,
        ast.Mod,
        ast.USub,
        ast.UAdd,
        ast.Constant,
        ast.Call,
        ast.Name,
        ast.Load,
    }

    _FUNCTIONS = {
        "abs": abs,
        "round": round,
        "min": min,
        "max": max,
        "sqrt": lambda x: x ** 0.5,
        "pow": pow,
        "sin": lambda x: __import__("math").sin(x),
        "cos": lambda x: __import__("math").cos(x),
        "tan": lambda x: __import__("math").tan(x),
        "log": lambda x: __import__("math").log(x),
        "log10": lambda x: __import__("math").log10(x),
        "pi": __import__("math").pi,
        "e": __import__("math").e,
    }

    def _validate(self, node: ast.AST) -> None:
        """Ensure the AST only contains allowed, safe nodes."""
        if not isinstance(node, tuple(self._ALLOWED_NODES)):
            raise ValueError(f"Unsupported expression component: {type(node).__name__}")
        if isinstance(node, ast.Call):
            if not isinstance(node.func, ast.Name) or node.func.id not in self._FUNCTIONS:
                raise ValueError("Only the predefined functions are allowed")
        for child in ast.iter_child_nodes(node):
            self._validate(child)

    def _eval(self, node: ast.AST) -> Any:
        """Evaluate a validated AST node."""
        if isinstance(node, ast.Constant):
            return node.value
        if isinstance(node, ast.BinOp):
            left = self._eval(node.left)
            right = self._eval(node.right)
            return {
                ast.Add: operator.add,
                ast.Sub: operator.sub,
                ast.Mult: operator.mul,
                ast.Div: operator.truediv,
                ast.Pow: operator.pow,
                ast.Mod: operator.mod,
            }[type(node.op)](left, right)
        if isinstance(node, ast.UnaryOp):
            operand = self._eval(node.operand)
            return {ast.USub: operator.neg, ast.UAdd: operator.pos}[type(node.op)](operand)
        if isinstance(node, ast.Call):
            func = self._FUNCTIONS[node.func.id]
            args = [self._eval(arg) for arg in node.args]
            return func(*args)
        if isinstance(node, ast.Name):
            return self._FUNCTIONS[node.id]
        raise ValueError("Unsupported expression")

    async def invoke(self, expression: str = "", **kwargs: Any) -> ToolResult:
        """Evaluate a mathematical expression string."""
        if not expression:
            return ToolResult(success=False, error="No expression provided")
        try:
            tree = ast.parse(expression, mode="eval")
            self._validate(tree)
            result = self._eval(tree.body)
            return ToolResult(
                success=True,
                output=result,
                metadata={"expression": expression},
            )
        except (ValueError, SyntaxError, ZeroDivisionError, NameError) as exc:
            return ToolResult(success=False, error=f"Calculation error: {exc}")

    def to_dict(self) -> dict[str, Any]:
        """Return tool metadata."""
        return {
            "name": self.name,
            "description": self.description,
            "parameters": {
                "type": "object",
                "properties": {
                    "expression": {
                        "type": "string",
                        "description": "The mathematical expression to evaluate",
                    }
                },
                "required": ["expression"],
            },
        }
