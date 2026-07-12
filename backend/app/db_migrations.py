"""SQLite 轻量迁移。

项目仍处于本地单用户阶段；这里仅负责把早期数据库升级到 Project/Page 模型，
避免要求用户删除已经上传的 PDF。后续模型稳定后可替换为 Alembic。
"""

from datetime import datetime, timezone

from sqlalchemy import Engine


def migrate_schema(engine: Engine) -> None:
    with engine.begin() as connection:
        connection.exec_driver_sql(
            "CREATE TABLE IF NOT EXISTS appmeta "
            "(key TEXT PRIMARY KEY NOT NULL, value TEXT NOT NULL)"
        )
        row = connection.exec_driver_sql(
            "SELECT value FROM appmeta WHERE key = 'schema_version'"
        ).first()
        version = int(row[0]) if row else 0
        if version < 1:
            _migrate_v1(connection)
            connection.exec_driver_sql(
                "INSERT OR REPLACE INTO appmeta (key, value) VALUES ('schema_version', '1')"
            )
            version = 1

        if version < 2:
            _migrate_v2(connection)
            connection.exec_driver_sql(
                "INSERT OR REPLACE INTO appmeta (key, value) VALUES ('schema_version', '2')"
            )
            version = 2

        if version < 3:
            _migrate_v3(connection)
            connection.exec_driver_sql(
                "INSERT OR REPLACE INTO appmeta (key, value) VALUES ('schema_version', '3')"
            )


def _migrate_v1(connection) -> None:
        _add_column(connection, "document", "project_id", "INTEGER DEFAULT 1")
        _add_column(connection, "document", "summary", "TEXT NOT NULL DEFAULT ''")
        _add_column(
            connection, "document", "table_of_contents", "TEXT NOT NULL DEFAULT ''"
        )
        _add_column(connection, "document", "updated_at", "TIMESTAMP")

        _add_column(
            connection, "documentprocessing", "paddle_job_id", "TEXT DEFAULT NULL"
        )

        _add_column(connection, "imageasset", "page_id", "INTEGER DEFAULT NULL")
        _add_column(
            connection, "imageasset", "source_name", "TEXT NOT NULL DEFAULT ''"
        )
        _add_column(connection, "imageasset", "filename", "TEXT NOT NULL DEFAULT ''")
        _add_column(
            connection, "imageasset", "stored_path", "TEXT NOT NULL DEFAULT ''"
        )
        _add_column(
            connection,
            "imageasset",
            "mime_type",
            "TEXT NOT NULL DEFAULT 'image/png'",
        )
        _add_column(connection, "imageasset", "created_at", "TIMESTAMP")
        _add_column(connection, "imageasset", "updated_at", "TIMESTAMP")

        now = datetime.now(timezone.utc).isoformat()
        connection.exec_driver_sql(
            "INSERT OR IGNORE INTO project "
            "(id, name, summary, created_at, updated_at) VALUES (1, ?, '', ?, ?)",
            ("默认项目", now, now),
        )
        connection.exec_driver_sql(
            "UPDATE document SET project_id = 1 WHERE project_id IS NULL"
        )
        connection.exec_driver_sql(
            "UPDATE document SET updated_at = created_at WHERE updated_at IS NULL"
        )
        connection.exec_driver_sql(
            "UPDATE imageasset SET created_at = ?, updated_at = ? "
            "WHERE created_at IS NULL",
            (now, now),
        )
        connection.exec_driver_sql(
            "CREATE INDEX IF NOT EXISTS ix_document_project_id "
            "ON document (project_id)"
        )
        connection.exec_driver_sql(
            "CREATE INDEX IF NOT EXISTS ix_imageasset_page_id "
            "ON imageasset (page_id)"
        )
        # 之前的产物来自错误的本地解析链路，统一重新提交远程 PaddleOCR。
        connection.exec_driver_sql("UPDATE document SET page_count = 0")
        connection.exec_driver_sql(
            "UPDATE documentprocessing SET status = 'pending', "
            "processed_pages = 0, paddle_job_id = NULL, error_message = NULL"
        )


def _migrate_v2(connection) -> None:
    connection.exec_driver_sql(
        "CREATE TABLE IF NOT EXISTS chatconversation ("
        "id INTEGER PRIMARY KEY, document_id INTEGER NOT NULL, title TEXT NOT NULL, "
        "profile TEXT NOT NULL, created_at TIMESTAMP, updated_at TIMESTAMP)"
    )
    connection.exec_driver_sql(
        "CREATE TABLE IF NOT EXISTS chatconversationmessage ("
        "id INTEGER PRIMARY KEY, conversation_id INTEGER NOT NULL, position INTEGER NOT NULL, "
        "role TEXT NOT NULL, content TEXT NOT NULL, request_content TEXT, "
        "input_tokens INTEGER, output_tokens INTEGER, cached_tokens INTEGER, "
        "total_tokens INTEGER, created_at TIMESTAMP, "
        "UNIQUE(conversation_id, position))"
    )
    connection.exec_driver_sql(
        "CREATE INDEX IF NOT EXISTS ix_chatconversation_document_id "
        "ON chatconversation (document_id)"
    )
    connection.exec_driver_sql(
        "CREATE INDEX IF NOT EXISTS ix_chatconversationmessage_conversation_id "
        "ON chatconversationmessage (conversation_id)"
    )


def _migrate_v3(connection) -> None:
    """保存可展开的 Agent 活动轨迹与单轮耗时，供恢复对话后继续查看。"""
    _add_column(connection, "chatconversationmessage", "activity_trace", "JSON")
    _add_column(connection, "chatconversationmessage", "duration_ms", "INTEGER")


def _add_column(connection, table: str, column: str, definition: str) -> None:
    columns = {
        row[1]
        for row in connection.exec_driver_sql(f"PRAGMA table_info({table})").all()
    }
    if column not in columns:
        connection.exec_driver_sql(
            f"ALTER TABLE {table} ADD COLUMN {column} {definition}"
        )
