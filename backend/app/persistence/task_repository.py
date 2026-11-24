"""Durable storage for resumable chat requests and isolated attempts."""

import json
import sqlite3
from datetime import datetime, timezone
from uuid import uuid4

from backend.app.persistence.sqlite import SQLiteDatabase


class TaskConflictError(Exception):
    """Raised when a task is already running or cannot be resumed."""


class TaskRepository:
    def __init__(self, database: SQLiteDatabase) -> None:
        self.database = database

    @staticmethod
    def _now() -> str:
        return datetime.now(timezone.utc).isoformat()

    def create(self, messages: list[dict], conversation_id: str | None) -> dict:
        prompt = next((item["content"] for item in reversed(messages) if item["role"] == "user"), None)
        if not prompt:
            raise ValueError("A tarefa precisa de uma mensagem do usuário.")
        now, task_id = self._now(), str(uuid4())
        with self.database.connection() as connection:
            if conversation_id is None:
                conversation_id = str(uuid4())
                title = prompt.strip().replace("\n", " ")[:80] or "Nova conversa"
                connection.execute(
                    "INSERT INTO conversations (id, title, created_at, updated_at) VALUES (?, ?, ?, ?)",
                    (conversation_id, title, now, now),
                )
            elif connection.execute("SELECT 1 FROM conversations WHERE id = ?", (conversation_id,)).fetchone() is None:
                raise KeyError(conversation_id)
            connection.execute(
                """INSERT INTO conversation_tasks
                   (id, conversation_id, prompt, messages_json, status, created_at, updated_at)
                   VALUES (?, ?, ?, ?, 'pending', ?, ?)""",
                (task_id, conversation_id, prompt, json.dumps(messages, ensure_ascii=False), now, now),
            )
        return self.get(task_id)

    def get(self, task_id: str) -> dict | None:
        with self.database.connection() as connection:
            task = connection.execute("SELECT * FROM conversation_tasks WHERE id = ?", (task_id,)).fetchone()
            if task is None:
                return None
            attempts = connection.execute(
                """SELECT attempt_number, status, partial_text, provider, model, error_code,
                          started_at, updated_at, completed_at
                   FROM task_attempts WHERE task_id = ? ORDER BY attempt_number""", (task_id,)
            ).fetchall()
        value = dict(task)
        value["messages"] = json.loads(value.pop("messages_json"))
        value["attempts"] = [dict(row) for row in attempts]
        return value

    def pending(self, conversation_id: str | None = None) -> list[dict]:
        query = "SELECT id FROM conversation_tasks WHERE status IN ('pending','partially_completed','failed')"
        params: tuple = ()
        if conversation_id:
            query += " AND conversation_id = ?"
            params = (conversation_id,)
        query += " ORDER BY updated_at DESC"
        with self.database.connection() as connection:
            rows = connection.execute(query, params).fetchall()
        return [self.get(row["id"]) for row in rows]

    def latest_resumable(self, conversation_id: str) -> dict | None:
        tasks = self.pending(conversation_id)
        return tasks[0] if tasks else None

    def start_attempt(self, task_id: str) -> dict:
        now = self._now()
        with self.database.connection() as connection:
            connection.execute("BEGIN IMMEDIATE")
            task = connection.execute("SELECT * FROM conversation_tasks WHERE id = ?", (task_id,)).fetchone()
            if task is None:
                raise KeyError(task_id)
            if task["status"] == "processing":
                raise TaskConflictError("Esta solicitação já está em processamento.")
            if task["status"] in {"completed", "cancelled"}:
                raise TaskConflictError("Esta solicitação não pode ser retomada.")
            attempt = int(task["attempt_count"]) + 1
            connection.execute(
                """INSERT INTO task_attempts(task_id, attempt_number, status, started_at, updated_at)
                   VALUES (?, ?, 'processing', ?, ?)""", (task_id, attempt, now, now)
            )
            connection.execute(
                """UPDATE conversation_tasks SET status='processing', active_attempt=?,
                   attempt_count=?, last_error=NULL, updated_at=? WHERE id=?""",
                (attempt, attempt, now, task_id),
            )
        return self.get(task_id)

    def append_partial(self, task_id: str, attempt: int, text: str) -> None:
        now = self._now()
        with self.database.connection() as connection:
            cursor = connection.execute(
                """UPDATE task_attempts SET partial_text=partial_text || ?, updated_at=?
                   WHERE task_id=? AND attempt_number=? AND status='processing'""",
                (text, now, task_id, attempt),
            )
            if cursor.rowcount != 1:
                raise TaskConflictError("A tentativa não está ativa.")
            connection.execute(
                "UPDATE conversation_tasks SET updated_at=? WHERE id=? AND active_attempt=? AND status='processing'",
                (now, task_id, attempt),
            )

    def complete(self, task_id: str, attempt: int, reply: str, provider: str, model: str, fallback: bool) -> None:
        now = self._now()
        with self.database.connection() as connection:
            connection.execute("BEGIN IMMEDIATE")
            task = connection.execute("SELECT * FROM conversation_tasks WHERE id=?", (task_id,)).fetchone()
            active = connection.execute(
                "SELECT status FROM task_attempts WHERE task_id=? AND attempt_number=?", (task_id, attempt)
            ).fetchone()
            if task is None or active is None or task["status"] != "processing" or active["status"] != "processing":
                raise TaskConflictError("A tarefa não está ativa.")
            messages = json.loads(task["messages_json"])
            user = next(item for item in reversed(messages) if item["role"] == "user")
            connection.execute(
                "INSERT INTO messages(conversation_id, role, content, created_at) VALUES (?, 'user', ?, ?)",
                (task["conversation_id"], user["content"], now),
            )
            connection.execute(
                """INSERT INTO messages(conversation_id, role, content, provider, model, fallback_used, created_at)
                   VALUES (?, 'assistant', ?, ?, ?, ?, ?)""",
                (task["conversation_id"], reply, provider, model, int(fallback), now),
            )
            connection.execute("UPDATE conversations SET updated_at=? WHERE id=?", (now, task["conversation_id"]))
            connection.execute(
                """UPDATE task_attempts SET status='completed', provider=?, model=?, updated_at=?, completed_at=?
                   WHERE task_id=? AND attempt_number=?""", (provider, model, now, now, task_id, attempt)
            )
            connection.execute(
                """UPDATE conversation_tasks SET status='completed', updated_at=?, completed_at=? WHERE id=?""",
                (now, now, task_id),
            )

    def fail(self, task_id: str, attempt: int, error_code: str, *, cancelled: bool = False) -> None:
        now = self._now()
        status = "cancelled" if cancelled else "failed"
        with self.database.connection() as connection:
            row = connection.execute(
                "SELECT partial_text FROM task_attempts WHERE task_id=? AND attempt_number=? AND status='processing'",
                (task_id, attempt),
            ).fetchone()
            if row is None:
                return
            attempt_status = status if cancelled else ("partially_completed" if row["partial_text"] else "failed")
            task_status = status if cancelled else ("partially_completed" if row["partial_text"] else "failed")
            connection.execute(
                """UPDATE task_attempts SET status=?, error_code=?, updated_at=?, completed_at=?
                   WHERE task_id=? AND attempt_number=?""",
                (attempt_status, error_code[:80], now, now, task_id, attempt),
            )
            connection.execute(
                "UPDATE conversation_tasks SET status=?, last_error=?, updated_at=? WHERE id=? AND active_attempt=?",
                (task_status, error_code[:80], now, task_id, attempt),
            )

    def recover_interrupted(self) -> None:
        """Mark executions from a previous process as resumable; never execute them automatically."""
        now = self._now()
        with self.database.connection() as connection:
            connection.execute("BEGIN IMMEDIATE")
            connection.execute(
                """UPDATE task_attempts SET status=CASE WHEN partial_text='' THEN 'failed'
                   ELSE 'partially_completed' END, error_code='server_interrupted', updated_at=?, completed_at=?
                   WHERE status='processing'""", (now, now)
            )
            connection.execute(
                """UPDATE conversation_tasks SET status=CASE WHEN EXISTS (
                       SELECT 1 FROM task_attempts a WHERE a.task_id=conversation_tasks.id
                         AND a.attempt_number=conversation_tasks.active_attempt AND a.partial_text!=''
                   ) THEN 'partially_completed' ELSE 'failed' END,
                   last_error='server_interrupted', updated_at=? WHERE status='processing'""", (now,)
            )

    def cancel(self, task_id: str) -> dict:
        now = self._now()
        with self.database.connection() as connection:
            connection.execute("BEGIN IMMEDIATE")
            task = connection.execute("SELECT status, active_attempt FROM conversation_tasks WHERE id=?", (task_id,)).fetchone()
            if task is None:
                raise KeyError(task_id)
            if task["status"] == "completed":
                raise TaskConflictError("Uma solicitação concluída não pode ser cancelada.")
            if task["status"] != "cancelled":
                connection.execute(
                    """UPDATE task_attempts SET status='cancelled', error_code='user_cancelled',
                       updated_at=?, completed_at=? WHERE task_id=? AND attempt_number=? AND status='processing'""",
                    (now, now, task_id, task["active_attempt"]),
                )
                connection.execute(
                    "UPDATE conversation_tasks SET status='cancelled', last_error='user_cancelled', updated_at=? WHERE id=?",
                    (now, task_id),
                )
        result = self.get(task_id)
        assert result is not None
        return result
