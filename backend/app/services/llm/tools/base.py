"""LLM 工具的通用骨架（provider 无关）。

三件事：
1. 用 ``@register`` 装饰器把工具登记进全局注册表，声明名称 / 描述 / JSON Schema；
2. 把执行绑定到一次请求的 ``ToolContext``（session + 当前文档 + 当前页）；
3. 统一执行入口 ``run_tool``，结果包成 ``ToolResult``（文本或图片），
   并提供 ``openai_tools`` / ``anthropic_tools`` 两种风格的工具定义转换。

新增工具只需在本包内某个模块里用 ``@register(...)`` 声明一个
``(ctx, args) -> ToolResult`` 的函数即可，无需改动本文件。
"""

from __future__ import annotations

import base64
import json
from collections.abc import Callable
from dataclasses import dataclass, field

from sqlmodel import Session


# ── 结果与上下文 ────────────────────────────────────────────


@dataclass
class ToolImage:
    """工具返回的图片，provider 负责转成各自的多模态 tool_result 块。"""

    data: bytes
    mime_type: str

    def as_base64(self) -> str:
        return base64.b64encode(self.data).decode("ascii")


@dataclass
class ToolResult:
    text: str | None = None
    image: ToolImage | None = None
    is_error: bool = False

    @classmethod
    def json(cls, payload: object) -> "ToolResult":
        return cls(text=json.dumps(payload, ensure_ascii=False))

    @classmethod
    def error(cls, message: str) -> "ToolResult":
        return cls(text=message, is_error=True)


@dataclass
class ToolContext:
    """一次对话请求的工具执行上下文。"""

    session: Session
    document_id: int
    current_page: int


# ── 注册表 ──────────────────────────────────────────────────


@dataclass(frozen=True)
class ToolSpec:
    name: str
    description: str
    parameters: dict = field(default_factory=dict)


Handler = Callable[[ToolContext, dict], ToolResult]


@dataclass(frozen=True)
class _RegisteredTool:
    spec: ToolSpec
    handler: Handler


_REGISTRY: dict[str, _RegisteredTool] = {}


def register(name: str, description: str, parameters: dict) -> Callable[[Handler], Handler]:
    """把一个 ``(ctx, args) -> ToolResult`` 函数登记为可供大模型调用的工具。"""

    def decorator(handler: Handler) -> Handler:
        if name in _REGISTRY:
            raise ValueError(f"工具名重复：{name}")
        _REGISTRY[name] = _RegisteredTool(ToolSpec(name, description, parameters), handler)
        return handler

    return decorator


def registered_names() -> list[str]:
    return list(_REGISTRY)


def tool_specs() -> list[ToolSpec]:
    return [entry.spec for entry in _REGISTRY.values()]


# ── provider 风格转换 ───────────────────────────────────────


def openai_tools(specs: list[ToolSpec] | None = None) -> list[dict]:
    """OpenAI 风格的 tools 定义。"""
    specs = specs if specs is not None else tool_specs()
    return [
        {
            "type": "function",
            "function": {
                "name": spec.name,
                "description": spec.description,
                "parameters": spec.parameters,
            },
        }
        for spec in specs
    ]


def anthropic_tools(specs: list[ToolSpec] | None = None) -> list[dict]:
    """Anthropic 风格的 tools 定义。"""
    specs = specs if specs is not None else tool_specs()
    return [
        {
            "name": spec.name,
            "description": spec.description,
            "input_schema": spec.parameters,
        }
        for spec in specs
    ]


# ── 执行 ────────────────────────────────────────────────────


def run_tool(ctx: ToolContext, name: str, arguments: dict) -> ToolResult:
    """按名称执行工具。未知工具或参数错误都转成 is_error 的文本结果，
    以便 provider 把它作为 tool_result 回给模型，让模型自我纠正而非中断。"""
    entry = _REGISTRY.get(name)
    if entry is None:
        return ToolResult.error(f"未知工具：{name}")
    try:
        return entry.handler(ctx, arguments)
    # KeyError 是 LookupError 的子类，缺参数要先于“数据未找到”捕获。
    except KeyError as exc:
        return ToolResult.error(f"缺少参数：{exc}")
    except (TypeError, ValueError) as exc:
        return ToolResult.error(f"参数错误：{exc}")
    except LookupError as exc:
        return ToolResult.error(str(exc))
