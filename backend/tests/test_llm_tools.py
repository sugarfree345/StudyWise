"""页面与图片工具层（app/services/llm/tools.py）的单元测试。

用内存 SQLite + 临时目录里的真图片文件，覆盖 5 个工具的正常路径、
装饰图简介代替原图的约定、以及未知工具/缺参数/坏类型/数据未找到的错误分类。
不依赖真实数据库或模型 key，`python -m unittest` 即可运行。
"""

import json
import tempfile
import unittest
from pathlib import Path

from sqlmodel import Session, SQLModel, create_engine

from app.models import Document, DocumentPage, ImageAsset, Project
from app.services.llm import tools

# 1x1 PNG，用来在临时目录里落一张真图片文件。
_PNG_1PX = bytes.fromhex(
    "89504e470d0a1a0a0000000d49484452000000010000000108060000001f15c4"
    "890000000d49444154789c6360000002000100ffff03000006000557bfabd400"
    "00000049454e44ae426082"
)


class ToolLayerTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        root = Path(self._tmp.name)
        self.engine = create_engine(
            f"sqlite:///{root / 'test.db'}",
            connect_args={"check_same_thread": False},
        )
        SQLModel.metadata.create_all(self.engine)

        img_path = root / "img001.jpg"
        img_path.write_bytes(_PNG_1PX)
        render_path = root / "p1_render.png"
        render_path.write_bytes(_PNG_1PX)

        with Session(self.engine) as session:
            session.add(Project(id=1, name="测试项目"))
            document = Document(
                id=1, project_id=1, filename="资料.pdf", stored_path="x.pdf",
                page_count=12,
            )
            session.add(document)
            page = DocumentPage(
                id=1, document_id=1, page_number=1,
                markdown="# 第一页\n正文内容。", render_path=str(render_path),
            )
            session.add(page)
            session.add(DocumentPage(
                id=2, document_id=1, page_number=2,
                markdown="# 第二页\n贝叶斯公式的前提。",
            ))
            session.add(DocumentPage(
                id=3, document_id=1, page_number=3,
                markdown="# 第三页\n贝叶斯公式的推导与解答。",
            ))
            for page_number in range(4, 13):
                session.add(DocumentPage(
                    id=page_number,
                    document_id=1,
                    page_number=page_number,
                    markdown=f"# 第{page_number}页\n正文。",
                ))
            session.add(ImageAsset(
                id=1, document_id=1, page_id=1, page_number=1, image_index=1,
                stored_path=str(img_path), mime_type="application/octet-stream",
            ))
            session.commit()

        self.session = Session(self.engine)
        self.ctx = tools.ToolContext(session=self.session, document_id=1, current_page=1)

    def tearDown(self) -> None:
        self.session.close()
        self.engine.dispose()
        self._tmp.cleanup()

    def _payload(self, result: tools.ToolResult) -> dict:
        self.assertFalse(result.is_error, result.text)
        assert result.text is not None
        return json.loads(result.text)

    # ── 正常路径 ──────────────────────────────────────────

    def test_get_page_content(self) -> None:
        result = tools.run_tool(self.ctx, "get_page_content", {"page_number": 1})
        payload = self._payload(result)
        self.assertIn("正文内容", payload["markdown"])
        self.assertEqual(payload["images"][0]["id"], 1)
        self.assertEqual(result.page_numbers, [1])

    def test_get_full_pdf_text(self) -> None:
        result = tools.run_tool(self.ctx, "get_full_pdf_text", {})
        self.assertFalse(result.is_error)
        self.assertIn("第 1 页", result.text)
        self.assertIn("正文内容", result.text)
        self.assertEqual(result.page_numbers, list(range(1, 13)))

    def test_get_text_single_and_range(self) -> None:
        # 单页
        single = tools.run_tool(
            self.ctx, "get_text", {"first_page": 1, "last_page": 1}
        )
        self.assertFalse(single.is_error)
        self.assertIn("第 1 页", single.text)
        self.assertIn("正文内容", single.text)
        self.assertEqual(single.page_numbers, [1])

        # 请求超过 8 页时，只返回从起始页开始的连续 8 页。
        bounded = tools.run_tool(
            self.ctx, "get_text", {"first_page": 5, "last_page": 40}
        )
        self.assertFalse(bounded.is_error)
        self.assertEqual(bounded.page_numbers, list(range(5, 13)))
        self.assertIn("第 12 页", bounded.text)
        self.assertNotIn("第 13 页", bounded.text)
        self.assertIn("原请求结束于第 40 页", bounded.text)

    def test_document_search(self) -> None:
        search = self._payload(
            tools.run_tool(self.ctx, "search_document", {"query": "贝叶斯公式"})
        )
        self.assertEqual([match["page_number"] for match in search["matches"]], [2, 3])

    def test_get_image_returns_bytes_with_corrected_mime(self) -> None:
        result = tools.run_tool(self.ctx, "get_image", {"image_id": 1})
        self.assertFalse(result.is_error)
        self.assertIsNotNone(result.image)
        # 存库 mime 是 application/octet-stream，工具应按扩展名纠正为 image/jpeg
        self.assertEqual(result.image.mime_type, "image/jpeg")
        self.assertTrue(result.image.as_base64())
        # 读原图应累加检索次数
        self.session.expire_all()
        self.assertEqual(self.session.get(ImageAsset, 1).retrieval_count, 1)

    def test_get_page_render(self) -> None:
        result = tools.run_tool(self.ctx, "get_page_render", {"page_number": 1})
        self.assertFalse(result.is_error)
        self.assertEqual(result.image.mime_type, "image/png")

    def test_classify_then_get_image_uses_summary(self) -> None:
        classified = self._payload(tools.run_tool(self.ctx, "classify_image", {
            "image_id": 1, "is_useful": False,
            "summary": "装饰性横幅", "importance": 0,
        }))
        self.assertFalse(classified["is_useful"])

        # 判定为装饰图后，get_image 只回简介、不再回传原图
        result = tools.run_tool(self.ctx, "get_image", {"image_id": 1})
        self.assertIsNone(result.image)
        self.assertIn("装饰性横幅", result.text)

    def test_get_useful_images_reflects_classification(self) -> None:
        empty = self._payload(
            tools.run_tool(self.ctx, "get_useful_images", {"page_number": 1})
        )
        self.assertEqual(empty["images"], [])

        tools.run_tool(self.ctx, "classify_image", {
            "image_id": 1, "is_useful": True, "summary": "关键示意图", "importance": 5,
        })
        useful = self._payload(
            tools.run_tool(self.ctx, "get_useful_images", {"page_number": 1})
        )
        self.assertEqual(len(useful["images"]), 1)

    # ── 错误分类 ──────────────────────────────────────────

    def test_error_classification(self) -> None:
        cases = {
            "未知工具": tools.run_tool(self.ctx, "nope", {}),
            "缺少参数": tools.run_tool(self.ctx, "get_image", {}),
            "参数错误": tools.run_tool(self.ctx, "get_image", {"image_id": "abc"}),
            "数据未找到": tools.run_tool(self.ctx, "get_image", {"image_id": 999}),
        }
        for prefix, result in cases.items():
            self.assertTrue(result.is_error, f"{prefix} 应为错误")
        self.assertTrue(cases["未知工具"].text.startswith("未知工具"))
        self.assertTrue(cases["缺少参数"].text.startswith("缺少参数"))
        self.assertTrue(cases["参数错误"].text.startswith("参数错误"))
        self.assertEqual(cases["数据未找到"].text, "图片不存在")

    # ── provider 定义转换 ─────────────────────────────────

    def test_tool_specs_match_handlers(self) -> None:
        specs = {spec.name: spec for spec in tools.tool_specs()}
        spec_names = set(specs)
        self.assertEqual(spec_names, set(tools.registered_names()))
        self.assertEqual(len(tools.openai_tools()), len(tools.tool_specs()))
        self.assertEqual(len(tools.anthropic_tools()), len(tools.tool_specs()))
        self.assertEqual(tools.openai_tools()[0]["type"], "function")
        self.assertIn("input_schema", tools.anthropic_tools()[0])
        # 8 个页面/图片/文本工具应全部注册
        self.assertEqual(len(tools.tool_specs()), 8)
        self.assertIn("get_text", tools.registered_names())
        self.assertIn("get_full_pdf_text", tools.registered_names())
        self.assertIn("search_document", tools.registered_names())
        self.assertIn("必须继续读取", specs["get_text"].description)
        self.assertIn("高成本工具", specs["get_full_pdf_text"].description)
        self.assertIn("命中只是候选", specs["search_document"].description)
        self.assertIn("OCR", specs["get_page_render"].description)


if __name__ == "__main__":
    unittest.main()
