"""chat 路由的提示词组装：确保 system 静态；页码随用户问题持久化，
从而 system + 工具 + 历史形成可递增的缓存前缀。"""

import json
import tempfile
import unittest
from pathlib import Path

from sqlmodel import Session, SQLModel, create_engine

from app.api.routes.chat import (
    _build_document_system,
    _document_prompt_cache_key,
    _sse,
    _tool_result_activity,
)
from app.models import Document, DocumentPage, Project
from app.services.llm.tools import ToolResult


class ChatPromptTests(unittest.TestCase):
    def _session_with_doc(self, engine):
        with Session(engine) as s:
            s.add(Project(id=1, name="p"))
            s.add(Document(id=1, project_id=1, filename="d.pdf",
                           stored_path="d.pdf", page_count=34,
                           table_of_contents="第1章 …\n第2章 …"))
            s.add(DocumentPage(id=1, document_id=1, page_number=1, markdown="x"))
            s.commit()

    def test_system_is_static_and_pageless(self):
        with tempfile.TemporaryDirectory() as d:
            engine = create_engine(
                f"sqlite:///{Path(d) / 't.db'}",
                connect_args={"check_same_thread": False},
            )
            SQLModel.metadata.create_all(engine)
            self._session_with_doc(engine)
            with Session(engine) as s:
                doc = s.get(Document, 1)
                # 不接收 current_page，两次构建逐字相同
                sys_a = _build_document_system(doc, s)
                sys_b = _build_document_system(doc, s)
            self.assertEqual(sys_a, sys_b)
            # system 里不含具体页码（"第 7 页" / "第 3 页" 这类真实当前页）
            for n in (3, 7, 9):
                self.assertNotIn(f"当前第 {n} 页", sys_a)
                self.assertNotIn(f"浏览到第 {n} 页", sys_a)
            engine.dispose()

    def test_system_defines_tool_routing_and_context_sufficiency(self):
        with tempfile.TemporaryDirectory() as d:
            engine = create_engine(
                f"sqlite:///{Path(d) / 't.db'}",
                connect_args={"check_same_thread": False},
            )
            SQLModel.metadata.create_all(engine)
            self._session_with_doc(engine)
            with Session(engine) as s:
                system = _build_document_system(s.get(Document, 1), s)

            self.assertIn("<document_grounding>", system)
            self.assertIn("<tool_routing>", system)
            self.assertIn("<context_sufficiency>", system)
            self.assertIn("必须先调用工具", system)
            self.assertIn("每次工具返回页面内容后", system)
            self.assertIn("通常先扩展相邻 1–2 页", system)
            self.assertIn("不要为了形式而调用工具", system)
            engine.dispose()

    def test_page_context_is_part_of_each_append_only_user_message(self):
        # 这是前端发送给后端的模型历史：页码必须跟随产生它的问题，
        # 不能在整段历史末尾另插一条当前页消息，否则下一轮前缀会断开。
        first_request = [
            {"role": "user", "content": "第一个问题\n\n（提问时当前第 3 页。）"},
        ]
        second_request = [
            *first_request,
            {"role": "assistant", "content": "第一个回答"},
            {"role": "user", "content": "第二个问题\n\n（提问时当前第 7 页。）"},
        ]

        self.assertEqual(second_request[: len(first_request)], first_request)
        self.assertIn("第 3 页", second_request[0]["content"])
        self.assertIn("第 7 页", second_request[-1]["content"])

    def test_document_cache_key_is_stable_and_model_scoped(self):
        first = _document_prompt_cache_key(42, "gpt-5.5")
        self.assertEqual(first, _document_prompt_cache_key(42, "gpt-5.5"))
        self.assertNotEqual(first, _document_prompt_cache_key(42, "gpt-4.1-mini"))
        self.assertNotIn("42", first)


class ChatSseTests(unittest.IsolatedAsyncioTestCase):
    async def test_stream_includes_activity_and_duration(self):
        class Provider:
            async def stream_chat(self, **_kwargs):
                yield "回答"

        chunks = [chunk async for chunk in _sse("system", Provider(), [])]
        events = [json.loads(chunk.removeprefix("data: ").strip()) for chunk in chunks]

        self.assertEqual(events[0]["type"], "activity")
        self.assertEqual(events[0]["activity"]["kind"], "status")
        self.assertTrue(any(event.get("type") == "delta" for event in events))
        done = next(event for event in events if event.get("type") == "done")
        self.assertGreaterEqual(done["duration_ms"], 0)

    def test_tool_result_preview_is_bounded(self):
        activity = _tool_result_activity(ToolResult(text="x" * 3000))
        self.assertTrue(activity["truncated"])
        self.assertEqual(activity["result_chars"], 3000)
        self.assertLess(len(activity["result"]), 2600)


if __name__ == "__main__":
    unittest.main()
