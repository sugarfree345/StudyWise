"""供大模型调用的工具集合。

导入本包即会触发各工具模块的注册（``page_image`` 等）。以后新增工具，
在本包内新建模块用 ``@register`` 声明，然后在下方 import 一行触发注册即可。
"""

from app.services.llm.tools.base import (
    ToolContext,
    ToolImage,
    ToolResult,
    ToolSpec,
    anthropic_tools,
    openai_tools,
    register,
    registered_names,
    run_tool,
    tool_specs,
)

# 触发注册（保持在导出之后，避免循环导入困扰）。
from app.services.llm.tools import page_image  # noqa: E402,F401

__all__ = [
    "ToolContext",
    "ToolImage",
    "ToolResult",
    "ToolSpec",
    "anthropic_tools",
    "openai_tools",
    "register",
    "registered_names",
    "run_tool",
    "tool_specs",
]
