import tempfile
import unittest
from pathlib import Path

from sqlalchemy import create_engine

from app.db_migrations import migrate_schema


class DatabaseMigrationTests(unittest.TestCase):
    def test_v3_adds_activity_trace_columns(self):
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
            self.assertEqual(version, "3")
            self.assertIn("activity_trace", columns)
            self.assertIn("duration_ms", columns)
            engine.dispose()


if __name__ == "__main__":
    unittest.main()
