import sqlite3

import pytest

from backend.app.persistence.sqlite import SQLiteDatabase


def _create_version_1_database(path):
    with sqlite3.connect(path) as connection:
        connection.executescript(
            """
            CREATE TABLE conversations (
                id TEXT PRIMARY KEY,
                title TEXT NOT NULL,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );
            CREATE TABLE messages (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                conversation_id TEXT NOT NULL REFERENCES conversations(id) ON DELETE CASCADE,
                role TEXT NOT NULL CHECK(role IN ('user', 'assistant')),
                content TEXT NOT NULL,
                provider TEXT,
                model TEXT,
                fallback_used INTEGER NOT NULL DEFAULT 0,
                created_at TEXT NOT NULL
            );
            CREATE TABLE user_facts (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                category TEXT NOT NULL,
                fact_key TEXT NOT NULL,
                fact_value TEXT NOT NULL,
                source TEXT NOT NULL DEFAULT 'conversation',
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                UNIQUE(category, fact_key)
            );
            INSERT INTO conversations VALUES ('conv-1', 'Teste', 'created', 'updated');
            INSERT INTO messages
                (id, conversation_id, role, content, provider, model, fallback_used, created_at)
                VALUES (7, 'conv-1', 'user', 'Mensagem antiga', NULL, NULL, 0, 'message-time');
            INSERT INTO user_facts
                (id, category, fact_key, fact_value, source, created_at, updated_at)
                VALUES (11, 'profile', 'name', 'Pessoa de Teste', 'user', 'fact-created', 'fact-updated');
            PRAGMA user_version = 1;
            """
        )


def test_version_1_database_migrates_without_losing_existing_data(tmp_path):
    database_path = tmp_path / "version-1.db"
    _create_version_1_database(database_path)

    database = SQLiteDatabase(str(database_path))

    with database.connection() as connection:
        assert connection.execute("PRAGMA user_version").fetchone()[0] == 4
        assert dict(connection.execute("SELECT * FROM conversations WHERE id = 'conv-1'").fetchone()) == {
            "id": "conv-1",
            "title": "Teste",
            "created_at": "created",
            "updated_at": "updated",
        }
        assert dict(connection.execute("SELECT * FROM messages WHERE id = 7").fetchone()) == {
            "id": 7,
            "conversation_id": "conv-1",
            "role": "user",
            "content": "Mensagem antiga",
            "provider": None,
            "model": None,
            "fallback_used": 0,
            "created_at": "message-time",
        }
        fact = connection.execute("SELECT * FROM user_facts WHERE id = 11").fetchone()
        assert fact["fact_value"] == "Pessoa de Teste"
        assert fact["source"] == "user"
        assert fact["classification"] == "personal"


def test_new_database_starts_at_schema_version_4(tmp_path):
    database = SQLiteDatabase(str(tmp_path / "new.db"))

    with database.connection() as connection:
        assert connection.execute("PRAGMA user_version").fetchone()[0] == 4
        columns = {row["name"] for row in connection.execute("PRAGMA table_info(user_facts)")}
        assert "classification" in columns
        assert connection.execute("SELECT COUNT(*) FROM user_facts").fetchone()[0] == 0
        assert connection.execute("SELECT COUNT(*) FROM auth_owner").fetchone()[0] == 0


def test_version_2_database_migrates_to_auth_schema_without_touching_user_data(tmp_path):
    database_path = tmp_path / "version-2.db"
    _create_version_1_database(database_path)
    with sqlite3.connect(database_path) as connection:
        connection.execute(
            "ALTER TABLE user_facts ADD COLUMN classification TEXT NOT NULL DEFAULT 'personal' "
            "CHECK(classification IN ('general','personal','sensitive'))"
        )
        connection.execute("PRAGMA user_version=2")

    database = SQLiteDatabase(str(database_path))
    with database.connection() as connection:
        assert connection.execute("PRAGMA user_version").fetchone()[0] == 4
        assert connection.execute("SELECT content FROM messages WHERE id=7").fetchone()[0] == "Mensagem antiga"
        fact = connection.execute("SELECT fact_value,classification FROM user_facts WHERE id=11").fetchone()
        assert tuple(fact) == ("Pessoa de Teste", "personal")
        assert connection.execute("SELECT COUNT(*) FROM auth_sessions").fetchone()[0] == 0


def test_failed_auth_migration_rolls_back_all_new_tables(tmp_path, monkeypatch):
    database_path = tmp_path / "failed-auth-migration.db"
    _create_version_1_database(database_path)
    original = SQLiteDatabase._migrate_to_version_3

    def fail_after_auth_schema(connection):
        original(connection)
        raise RuntimeError("simulated auth migration failure")

    monkeypatch.setattr(SQLiteDatabase, "_migrate_to_version_3", staticmethod(fail_after_auth_schema))
    with pytest.raises(RuntimeError, match="simulated auth migration failure"):
        SQLiteDatabase(str(database_path))

    with sqlite3.connect(database_path) as connection:
        assert connection.execute("PRAGMA user_version").fetchone()[0] == 1
        tables = {row[0] for row in connection.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        assert not {"auth_owner", "auth_devices", "auth_sessions", "auth_login_throttle"}.intersection(tables)
        assert connection.execute("SELECT content FROM messages WHERE id=7").fetchone()[0] == "Mensagem antiga"


def test_failed_migration_rolls_back_schema_and_version(tmp_path, monkeypatch):
    database_path = tmp_path / "failed-migration.db"
    _create_version_1_database(database_path)

    def fail_after_adding_column(connection):
        connection.execute(
            "ALTER TABLE user_facts ADD COLUMN classification TEXT NOT NULL DEFAULT 'personal'"
        )
        raise RuntimeError("simulated migration failure")

    monkeypatch.setattr(
        SQLiteDatabase,
        "_migrate_to_version_2",
        staticmethod(fail_after_adding_column),
    )

    with pytest.raises(RuntimeError, match="simulated migration failure"):
        SQLiteDatabase(str(database_path))

    with sqlite3.connect(database_path) as connection:
        assert connection.execute("PRAGMA user_version").fetchone()[0] == 1
        columns = {row[1] for row in connection.execute("PRAGMA table_info(user_facts)")}
        assert "classification" not in columns
        assert connection.execute("SELECT fact_value FROM user_facts WHERE id = 11").fetchone()[0] == "Pessoa de Teste"


def test_failed_task_migration_rolls_back_tasks_schema_and_version(tmp_path, monkeypatch):
    database_path = tmp_path / "failed-task-migration.db"
    _create_version_1_database(database_path)
    with sqlite3.connect(database_path) as connection:
        connection.execute("ALTER TABLE user_facts ADD COLUMN classification TEXT NOT NULL DEFAULT 'personal'")
        connection.execute("PRAGMA user_version=3")

    original = SQLiteDatabase._migrate_to_version_4

    def fail_after_task_schema(connection):
        original(connection)
        raise RuntimeError("simulated task migration failure")

    monkeypatch.setattr(SQLiteDatabase, "_migrate_to_version_4", staticmethod(fail_after_task_schema))
    with pytest.raises(RuntimeError, match="simulated task migration failure"):
        SQLiteDatabase(str(database_path))

    with sqlite3.connect(database_path) as connection:
        assert connection.execute("PRAGMA user_version").fetchone()[0] == 3
        tables = {row[0] for row in connection.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        assert "conversation_tasks" not in tables
        assert "task_attempts" not in tables


def test_connection_closes_if_initial_configuration_fails(tmp_path, monkeypatch):
    database = SQLiteDatabase(str(tmp_path / "connection.db"))

    class FailingConfigurationConnection:
        closed = False
        row_factory = None

        def execute(self, statement):
            raise RuntimeError("simulated connection configuration failure")

        def close(self):
            self.closed = True

    fake_connection = FailingConfigurationConnection()
    monkeypatch.setattr(sqlite3, "connect", lambda *args, **kwargs: fake_connection)

    with pytest.raises(RuntimeError, match="simulated connection configuration failure"):
        with database.connection():
            pass

    assert fake_connection.closed is True
