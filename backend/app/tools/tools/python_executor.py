"""Python code execution tool with sandboxed environment."""
from __future__ import annotations

import asyncio
import io
import contextlib
import sys
from typing import Any

from app.tools.base import ToolResult


class PythonExecutorTool:
    """Executes Python code in a restricted, time-limited sandbox."""

    name = "python_executor"
    description = "Execute Python code and return the output. Useful for data analysis, calculations, and scripting."

    _FORBIDDEN_MODULES = {"os", "subprocess", "sys", "importlib", "socket", "shutil"}

    async def invoke(self, code: str = "", timeout: int = 10, **kwargs: Any) -> ToolResult:
        """Execute the given Python code."""
        if not code:
            return ToolResult(success=False, error="No code provided")
        if any(module in code for module in self._FORBIDDEN_MODULES) and "import" in code:
            return ToolResult(success=False, error="Code contains forbidden imports")

        stdout_capture = io.StringIO()
        stderr_capture = io.StringIO()
        result = {"output": None}

        def _run() -> None:
            ns: dict[str, Any] = {}
            try:
                with contextlib.redirect_stdout(stdout_capture), contextlib.redirect_stderr(stderr_capture):
                    exec(compile(code, "<sandbox>", "exec"), ns)  # noqa: S102
                result["output"] = ns.get("result", stdout_capture.getvalue())
            except Exception as exc:  # noqa: BLE001
                stderr_capture.write(f"{type(exc).__name__}: {exc}")
                result["error"] = stderr_capture.getvalue()

        try:
            await asyncio.wait_for(asyncio.to_thread(_run), timeout=timeout)
        except asyncio.TimeoutError:
            return ToolResult(success=False, error=f"Execution timed out after {timeout}s")

        if result.get("error"):
            return ToolResult(success=False, error=result["error"], output=stdout_capture.getvalue())

        return ToolResult(
            success=True,
            output=result["output"],
            metadata={"stdout": stdout_capture.getvalue(), "stderr": stderr_capture.getvalue()},
        )

    def to_dict(self) -> dict[str, Any]:
        """Return tool metadata."""
        return {
            "name": self.name,
            "description": self.description,
            "parameters": {
                "type": "object",
                "properties": {
                    "code": {"type": "string", "description": "Python code to execute"},
                    "timeout": {"type": "integer", "description": "Timeout in seconds", "default": 10},
                },
                "required": ["code"],
            },
        }
