import tempfile
import unittest
from pathlib import Path

from sqlalchemy import create_engine

from app.db_migrations import migrate_schema


class DatabaseMigrationTests(unittest.TestCase):
    def test_latest_migration_adds_activity_trace_and_page_context(self):
        with tempfile.TemporaryDirectory() as directory:
            engine = create_engine(f"sqlite:///{Path(directory) / 'old.db'}")
            with engine.begin() as connection:
                connection.exec_driver_sql(
                    "CREATE TABLE appmeta (key TEXT PRIMARY KEY NOT NULL, value TEXT NOT NULL)"
                )
                connection.exec_driver_sql(
                    "INSERT INTO appmeta (key, value) VALUES ('schema_version', '2')"
                )
                connection.exec_driver_sql(
                    "CREATE TABLE chatconversationmessage (id INTEGER PRIMARY KEY)"
                )

            migrate_schema(engine)

            with engine.connect() as connection:
                columns = {
                    row[1]
                    for row in connection.exec_driver_sql(
                        "PRAGMA table_info(chatconversationmessage)"
                    ).all()
                }
                version = connection.exec_driver_sql(
                    "SELECT value FROM appmeta WHERE key = 'schema_version'"
                ).scalar_one()
            self.assertEqual(version, "5")
            self.assertIn("activity_trace", columns)
            self.assertIn("duration_ms", columns)
            with engine.connect() as connection:
                page_context_tables = connection.exec_driver_sql(
                    "SELECT name FROM sqlite_master WHERE type = 'table' "
                    "AND name = 'chatconversationpagecontext'"
                ).all()
            self.assertTrue(page_context_tables)
            with engine.connect() as connection:
                page_context_columns = {
                    row[1]
                    for row in connection.exec_driver_sql(
                        "PRAGMA table_info(chatconversationpagecontext)"
                    ).all()
                }
            self.assertIn("queue_position", page_context_columns)
            engine.dispose()

    def test_v5_migration_trims_legacy_page_context_to_eight(self):
        with tempfile.TemporaryDirectory() as directory:
            engine = create_engine(f"sqlite:///{Path(directory) / 'v4.db'}")
            with engine.begin() as connection:
                connection.exec_driver_sql(
                    "CREATE TABLE appmeta (key TEXT PRIMARY KEY NOT NULL, value TEXT NOT NULL)"
                )
                connection.exec_driver_sql(
                    "INSERT INTO appmeta (key, value) VALUES ('schema_version', '4')"
                )
                connection.exec_driver_sql(
                    "CREATE TABLE chatconversationpagecontext ("
                    "id INTEGER PRIMARY KEY, conversation_id INTEGER NOT NULL, "
                    "page_number INTEGER NOT NULL, last_turn INTEGER NOT NULL, "
                    "updated_at TIMESTAMP, UNIQUE(conversation_id, page_number))"
                )
                for page_number in range(1, 11):
                    connection.exec_driver_sql(
                        "INSERT INTO chatconversationpagecontext "
                        "(id, conversation_id, page_number, last_turn) VALUES (?, 1, ?, ?)",
                        (page_number, page_number, page_number),
                    )

            migrate_schema(engine)

            with engine.connect() as connection:
                rows = connection.exec_driver_sql(
                    "SELECT page_number, queue_position "
                    "FROM chatconversationpagecontext ORDER BY queue_position"
                ).all()
            self.assertEqual([row[0] for row in rows], list(range(3, 11)))
            self.assertEqual([row[1] for row in rows], list(range(8)))
            engine.dispose()


if __name__ == "__main__":
    unittest.main()
