import tempfile
import unittest
from pathlib import Path

import tiktoken
from sqlmodel import Session, SQLModel, create_engine, select

from app.models import (
    ChatConversation,
    ChatConversationPageContext,
    Document,
    DocumentPage,
    Project,
)
from app.services.conversation_page_context import (
    MAX_CONTEXT_TOKENS,
    build_recent_page_context,
    record_pages,
)


class ConversationPageContextTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.engine = create_engine(
            f"sqlite:///{Path(self._tmp.name) / 'test.db'}",
            connect_args={"check_same_thread": False},
        )
        SQLModel.metadata.create_all(self.engine)
        self.session = Session(self.engine)
        self.session.add(Project(id=1, name="p"))
        self.session.add(
            Document(
                id=1,
                project_id=1,
                filename="d.pdf",
                stored_path="d.pdf",
                page_count=30,
            )
        )
        self.session.add(ChatConversation(id=1, document_id=1, profile="test"))
        for page_number in range(1, 31):
            self.session.add(
                DocumentPage(
                    document_id=1,
                    page_number=page_number,
                    markdown=f"这是第 {page_number} 页的正文。",
                )
            )
        self.session.commit()

    def tearDown(self) -> None:
        self.session.close()
        self.engine.dispose()
        self._tmp.cleanup()

    def test_fifo_keeps_at_most_eight_pages(self):
        self.assertEqual(
            record_pages(
                self.session,
                conversation_id=1,
                page_numbers=list(range(1, 9)),
                turn=1,
            ),
            list(range(1, 9)),
        )
        self.assertEqual(
            record_pages(
                self.session,
                conversation_id=1,
                page_numbers=[9, 10],
                turn=3,
            ),
            list(range(3, 11)),
        )
        rows = self.session.exec(
            select(ChatConversationPageContext).where(
                ChatConversationPageContext.conversation_id == 1
            )
        ).all()
        self.assertEqual(len(rows), 8)

    def test_reused_pages_move_to_queue_tail(self):
        record_pages(
            self.session,
            conversation_id=1,
            page_numbers=[1, 2, 3, 4],
            turn=1,
        )
        queue = record_pages(
            self.session,
            conversation_id=1,
            page_numbers=[2, 5],
            turn=3,
        )
        self.assertEqual(queue, [1, 3, 4, 2, 5])

    def test_every_request_receives_entire_recent_queue(self):
        record_pages(
            self.session,
            conversation_id=1,
            page_numbers=[19, 20, 21, 22],
            turn=1,
        )
        context, pages, truncated = build_recent_page_context(
            self.session,
            conversation_id=1,
            document_id=1,
        )

        self.assertEqual(pages, [19, 20, 21, 22])
        self.assertFalse(truncated)
        self.assertIn("最近使用页面临时参考", context)
        for page_number in pages:
            self.assertIn(f"第 {page_number} 页", context)

    def test_context_is_hard_truncated_to_1600_tokens(self):
        page = self.session.exec(
            select(DocumentPage).where(
                DocumentPage.document_id == 1,
                DocumentPage.page_number == 1,
            )
        ).one()
        page.markdown = "很长的页面正文。" * 3_000
        self.session.add(page)
        self.session.commit()
        record_pages(
            self.session,
            conversation_id=1,
            page_numbers=[1],
            turn=1,
        )

        context, pages, truncated = build_recent_page_context(
            self.session,
            conversation_id=1,
            document_id=1,
        )

        self.assertEqual(pages, [1])
        self.assertTrue(truncated)
        self.assertIn("已截断至 1600 tokens", context)
        encoding = tiktoken.get_encoding("o200k_base")
        self.assertLessEqual(len(encoding.encode(context)), MAX_CONTEXT_TOKENS)

    def test_truncation_keeps_newest_pages_before_old_queue_entries(self):
        for page_number in range(1, 9):
            page = self.session.exec(
                select(DocumentPage).where(
                    DocumentPage.document_id == 1,
                    DocumentPage.page_number == page_number,
                )
            ).one()
            page.markdown = f"第{page_number}页" + "正文。" * 700
            self.session.add(page)
        self.session.commit()
        record_pages(
            self.session,
            conversation_id=1,
            page_numbers=list(range(1, 9)),
            turn=1,
        )

        context, pages, truncated = build_recent_page_context(
            self.session,
            conversation_id=1,
            document_id=1,
        )

        self.assertTrue(truncated)
        self.assertEqual(pages, [8])
        self.assertIn("第 8 页", context)
        self.assertNotIn("第 1 页", context)


if __name__ == "__main__":
    unittest.main()
