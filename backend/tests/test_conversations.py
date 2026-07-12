import tempfile
import unittest
from pathlib import Path

from sqlmodel import Session, SQLModel, create_engine

from app.api.routes.conversations import (
    create_conversation,
    get_conversation,
    list_conversations,
    replace_conversation,
)
from app.models import Document, Project
from app.schemas.conversation import ConversationCreate, ConversationMessageIn, ConversationUpdate


class ConversationRouteTests(unittest.TestCase):
    def test_create_save_and_restore_conversation(self):
        with tempfile.TemporaryDirectory() as directory:
            engine = create_engine(
                f"sqlite:///{Path(directory) / 'test.db'}",
                connect_args={"check_same_thread": False},
            )
            SQLModel.metadata.create_all(engine)
            with Session(engine) as session:
                session.add(Project(id=1, name="p"))
                session.add(Document(id=1, project_id=1, filename="d.pdf", stored_path="d.pdf"))
                session.commit()

                created = create_conversation(1, ConversationCreate(profile="openai-gpt-5.5"), session)
                saved = replace_conversation(
                    1,
                    created.id,
                    ConversationUpdate(
                        profile="deepseek-v4-flash",
                        title="第一题",
                        messages=[
                            ConversationMessageIn(
                                role="user",
                                content="这页讲什么？",
                                request_content="这页讲什么？\n\n（提问时当前第 2 页。）",
                            ),
                            ConversationMessageIn(
                                role="assistant",
                                content="讲了 X。",
                                input_tokens=100,
                                output_tokens=20,
                                cached_tokens=64,
                                total_tokens=120,
                                activity_trace=[
                                    {"kind": "status", "message": "正在分析问题"},
                                    {
                                        "kind": "tool_call",
                                        "id": "tool-1",
                                        "tool": "get_text",
                                        "arguments": {"first_page": 2, "last_page": 2},
                                    },
                                ],
                                duration_ms=1234,
                            ),
                        ],
                    ),
                    session,
                )

                self.assertEqual(saved.title, "第一题")
                self.assertEqual(saved.profile, "deepseek-v4-flash")
                self.assertEqual(saved.message_count, 2)
                restored = get_conversation(1, created.id, session)
                self.assertEqual(restored.messages[0].request_content, "这页讲什么？\n\n（提问时当前第 2 页。）")
                self.assertEqual(restored.messages[1].cached_tokens, 64)
                self.assertEqual(restored.messages[1].duration_ms, 1234)
                self.assertEqual(
                    restored.messages[1].activity_trace[1]["tool"], "get_text"
                )
                self.assertEqual(list_conversations(1, session)[0].id, created.id)

                # 再次保存同一对话会替换旧消息，不应因 position=0/1 冲突失败。
                replace_conversation(
                    1,
                    created.id,
                    ConversationUpdate(
                        profile="deepseek-v4-flash",
                        messages=[ConversationMessageIn(role="user", content="第二次保存")],
                    ),
                    session,
                )
                self.assertEqual(get_conversation(1, created.id, session).messages[0].content, "第二次保存")
            engine.dispose()


if __name__ == "__main__":
    unittest.main()
