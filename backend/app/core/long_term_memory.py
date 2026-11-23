"""Long-term memory service for explicit user facts and contextual recall."""

import re

from backend.app.persistence.repositories import MemoryRepository
from backend.app.persistence.sqlite import SQLiteDatabase


class LongTermMemory:
    """Apply memory rules while delegating SQLite operations to a repository."""

    def __init__(self, database: str | SQLiteDatabase) -> None:
        self.database = database if isinstance(database, SQLiteDatabase) else SQLiteDatabase(database)
        self.repository = MemoryRepository(self.database)

    def remember(
        self,
        category: str,
        key: str,
        value: str,
        source: str = "conversation",
        classification: str = "personal",
    ) -> dict:
        category, key, value = category.strip(), key.strip(), value.strip()
        if not category or not key or not value:
            raise ValueError("Categoria, chave e valor são obrigatórios.")
        if classification not in {"general", "personal", "sensitive"}:
            raise ValueError("Classificação deve ser general, personal ou sensitive.")
        self.repository.remember(category, key, value, source, classification)
        return {"category": category, "key": key, "value": value, "classification": classification}

    def extract_explicit_facts(self, text: str) -> list[dict]:
        patterns = [
            (r"\bmeu nome é\s+([\wÀ-ÿ][\wÀ-ÿ .'-]{0,70})", "profile", "name"),
            (r"\bpode me chamar de\s+([\wÀ-ÿ][\wÀ-ÿ .'-]{0,50})", "profile", "preferred_name"),
            (r"\beu moro em\s+([\wÀ-ÿ][\wÀ-ÿ ,'-]{0,70})", "profile", "location"),
            (r"\bprefiro\s+([^.!?\n;]{2,120})", "preferences", "general"),
            (r"\bminha preferência é\s+([^.!?\n;]{2,120})", "preferences", "general"),
            (r"\bdecidi que\s+([^.!?\n;]{2,180})", "decisions", "latest"),
            (r"\bno projeto\s+([\wÀ-ÿ][\wÀ-ÿ .'-]{1,50}?),\s*(?:estamos|estou|o objetivo é|a decisão é)\s*([^.!?\n;]{2,180})", "projects", "named"),
        ]
        saved = []
        for pattern, category, key in patterns:
            match = re.search(pattern, text, re.IGNORECASE)
            if match:
                if category == "projects":
                    project_name = match.group(1).strip().strip(" .'-")
                    detail = match.group(2).strip()
                    project_key = re.sub(r"[^a-z0-9]+", "_", project_name.lower()).strip("_")
                    if project_key and detail:
                        saved.append(self.remember("projects", project_key, detail))
                    continue
                delimiters = r"[.!?\n;]" if key == "location" else r"[.!?\n,;]"
                value = re.split(delimiters, match.group(1), maxsplit=1)[0].strip()
                if value:
                    saved.append(self.remember(category, key, value))
        return saved

    def forget(self, category: str, key: str) -> bool:
        """Remove one explicitly identified fact without affecting other memories."""
        category, key = category.strip(), key.strip()
        if not category or not key:
            raise ValueError("Categoria e chave são obrigatórias.")
        return self.repository.forget(category, key)

    def list_facts(self) -> list[dict]:
        return self.repository.list_facts()

    def build_context(self) -> str:
        # Sensitive facts remain available to local memory APIs but are never
        # sent to an AI provider through the prompt context.
        facts = [fact for fact in self.list_facts() if fact["classification"] != "sensitive"]
        if not facts:
            return ""
        category_labels = {
            "profile": "Perfil",
            "preferences": "Preferências",
            "projects": "Projetos",
            "decisions": "Decisões",
        }
        lines = ["MEMÓRIA PERSISTENTE DO USUÁRIO (informações fornecidas explicitamente):"]
        for fact in facts:
            category = category_labels.get(fact["category"], fact["category"])
            lines.append(f"- {category} / {fact['key']}: {fact['value']}")
        lines.append(
            "Use essas informações silenciosamente para personalizar respostas quando forem relevantes. "
            "Não anuncie que está consultando uma memória, banco de dados, perfil ou ficha. "
            "Não repita nem liste dados pessoais espontaneamente. "
            "Só fale sobre informações armazenadas quando o usuário perguntar ou quando forem diretamente necessárias. "
            "Nunca peça desculpas por consultar informações já fornecidas. "
            "Não invente nem contradiga fatos registrados."
        )
        return "\n".join(lines)
