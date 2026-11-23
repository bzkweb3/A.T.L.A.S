"""Long-term personal memory stored separately from conversation history."""

from datetime import datetime, timezone
from pathlib import Path
import re
import sqlite3


class LongTermMemory:
    """Stores explicit user facts and builds a compact context for the AI."""

    def __init__(self, database_path: str) -> None:
        self.database_path = database_path
        self._uri = database_path.startswith("file:")
        if database_path != ":memory:" and not self._uri:
            Path(database_path).parent.mkdir(parents=True, exist_ok=True)
        self._keeper = None
        if database_path == ":memory:":
            self.database_path = "file:atlas-profile?mode=memory&cache=shared"
            self._uri = True
            self._keeper = sqlite3.connect(self.database_path, uri=True)
        with self._connect() as db:
            db.execute("""
                CREATE TABLE IF NOT EXISTS user_facts (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    category TEXT NOT NULL,
                    fact_key TEXT NOT NULL,
                    fact_value TEXT NOT NULL,
                    source TEXT NOT NULL DEFAULT 'conversation',
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    UNIQUE(category, fact_key)
                )
            """)

    def _connect(self):
        db = sqlite3.connect(self.database_path, uri=self._uri)
        db.row_factory = sqlite3.Row
        return db

    def remember(self, category: str, key: str, value: str, source: str = "conversation") -> dict:
        category, key, value = category.strip(), key.strip(), value.strip()
        if not category or not key or not value:
            raise ValueError("Categoria, chave e valor são obrigatórios.")
        now = datetime.now(timezone.utc).isoformat()
        with self._connect() as db:
            db.execute("""
                INSERT INTO user_facts(category, fact_key, fact_value, source, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?)
                ON CONFLICT(category, fact_key) DO UPDATE SET
                    fact_value=excluded.fact_value, source=excluded.source, updated_at=excluded.updated_at
            """, (category, key, value, source, now, now))
        return {"category": category, "key": key, "value": value}

    def extract_explicit_facts(self, text: str) -> list[dict]:
        patterns = [
            (r"\bmeu nome é\s+([\wÀ-ÿ][\wÀ-ÿ .'-]{0,70})", "profile", "name"),
            (r"\bpode me chamar de\s+([\wÀ-ÿ][\wÀ-ÿ .'-]{0,50})", "profile", "preferred_name"),
            (r"\beu moro em\s+([\wÀ-ÿ][\wÀ-ÿ ,'-]{0,70})", "profile", "location"),
        ]
        saved = []
        for pattern, category, key in patterns:
            match = re.search(pattern, text, re.IGNORECASE)
            if match:
                value = re.split(r"[.!?\n,;]", match.group(1), maxsplit=1)[0].strip()
                if value:
                    saved.append(self.remember(category, key, value))
        return saved

    def list_facts(self) -> list[dict]:
        with self._connect() as db:
            rows = db.execute(
                "SELECT category, fact_key AS key, fact_value AS value, source, updated_at "
                "FROM user_facts ORDER BY category, fact_key"
            ).fetchall()
        return [dict(row) for row in rows]

    def build_context(self) -> str:
        facts = self.list_facts()
        if not facts:
            return ""
        lines = ["MEMÓRIA PERSISTENTE DO USUÁRIO (informações fornecidas explicitamente):"]
        for fact in facts:
            lines.append(f"- {fact['key']}: {fact['value']}")
        lines.append("Use essas informações quando forem relevantes. Não invente nem contradiga fatos registrados.")
        return "\n".join(lines)
