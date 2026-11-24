"""Long-term memory service for explicit user facts and contextual recall."""

import re
import unicodedata

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

    @staticmethod
    def _normalize(value: str) -> str:
        normalized = unicodedata.normalize("NFKD", value.casefold())
        return " ".join(
            "".join(char for char in normalized if not unicodedata.combining(char))
            .replace("_", " ")
            .replace(".", " ")
            .split()
        )

    @staticmethod
    def _tokens(value: str) -> set[str]:
        return {token for token in re.findall(r"[a-z0-9]+", value) if len(token) > 2}

    def _relevant_facts(
        self,
        query: str,
        recent_messages: list[dict] | None = None,
    ) -> list[dict]:
        normalized_query = self._normalize(query)
        query_tokens = self._tokens(normalized_query)
        history_text = " ".join(
            str(message.get("content", "")) if isinstance(message, dict) else str(message)
            for message in (recent_messages or [])
        )
        normalized_history = self._normalize(history_text)
        history_tokens = self._tokens(normalized_history)
        follow_up = any(phrase in normalized_query for phrase in (
            "o que decidimos", "qual foi a decisao", "sobre o projeto", "esse projeto",
            "aquele projeto", "continue de onde", "onde paramos", "por que mencionou",
            "porque mencionou", "por que voce mencionou", "porque voce mencionou",
            "de onde veio", "qual a origem", "essa informacao",
            "isso que voce falou", "voce mencionou", "voce disse",
        ))
        preference_correction = any(phrase in normalized_query for phrase in (
            "nao pedi recomend", "nao solicitei recomend", "nao quero recomend",
            "nao pedi para usar preferencia", "nao solicitei preferencia",
        ))
        explicit_personalization = any(term in normalized_query for term in (
            "minhas preferencias", "o que eu prefiro", "com base no que eu gosto",
            "com base nas minhas preferencias", "personalize", "personalizada",
        )) and not preference_correction
        recommendation_request = any(term in normalized_query for term in (
            "recomende", "recomend", "sugira", "sugestao", "indique",
        )) and not preference_correction
        asks_location = any(term in normalized_query for term in (
            "onde moro", "onde eu moro", "qual minha cidade", "qual cidade eu moro",
            "perto de mim", "perto daqui", "aqui perto", "na minha cidade",
            "na regiao", "minha localizacao",
        ))
        asks_name = any(term in normalized_query for term in (
            "meu nome", "como me chamo", "como eu me chamo", "lembra meu nome",
        ))
        asks_origin = any(term in normalized_query for term in (
            "por que mencionou", "porque mencionou", "de onde veio", "qual a origem",
            "por que voce mencionou", "porque voce mencionou", "por que voce disse", "porque voce disse",
        ))
        asks_decision = any(term in normalized_query for term in (
            "o que decidimos", "qual foi a decisao", "decisao do projeto", "decidimos sobre",
        ))

        relevant = []
        for fact in self.list_facts():
            if fact["classification"] == "sensitive":
                continue
            category = fact["category"].casefold()
            key = self._normalize(fact["key"])
            value = self._normalize(fact["value"])
            fact_tokens = self._tokens(f"{category} {key} {value}")
            value_tokens = self._tokens(value)
            compact_key = key.replace(" ", "")
            mentioned_in_query = bool(fact_tokens & query_tokens) or (
                compact_key and compact_key in normalized_query.replace(" ", "")
            )
            mentioned_in_history = follow_up and (
                bool(fact_tokens & history_tokens)
                or (compact_key and compact_key in normalized_history.replace(" ", ""))
            )
            is_relevant = False

            if preference_correction:
                is_relevant = False
            elif category == "profile":
                is_relevant = (
                    (fact["key"] in {"name", "preferred_name"} and asks_name)
                    or (fact["key"] == "location" and asks_location)
                    or (asks_origin and bool(value_tokens & (query_tokens | history_tokens)))
                    or (bool(value_tokens & query_tokens) and asks_origin)
                )
            elif category == "preferences":
                preference_text = f"{fact['key']} {fact['value']}".casefold()
                domain_terms = {
                    "food": ("comida", "restaurante", "receita", "alimento", "jantar", "almoco", "prato", "culin", "food", "meal", "recipe", "restaurant", "vegetarian", "vegan"),
                    "travel": ("viagem", "viajar", "hotel", "passeio", "roteiro", "destino", "travel", "trip", "hotel", "tour"),
                    "shopping": ("comprar", "compra", "produto", "loja", "material", "shopping", "product", "store"),
                    "communication": ("resposta", "resum", "detalh", "explica", "texto", "answer", "summary", "detail", "explain"),
                }
                matches_domain = any(
                    term in normalized_query and any(domain in preference_text for domain in terms)
                    for terms in domain_terms.values() for term in terms
                )
                is_relevant = (
                    explicit_personalization
                    or (recommendation_request and matches_domain)
                    or bool(fact_tokens & query_tokens)
                )
            elif category == "projects":
                explicit_project = "projeto" in query_tokens
                key_in_query = bool(self._tokens(key) & query_tokens) or (
                    compact_key and compact_key in normalized_query.replace(" ", "")
                )
                key_in_history = follow_up and (
                    bool(self._tokens(key) & history_tokens)
                    or (compact_key and compact_key in normalized_history.replace(" ", ""))
                )
                is_relevant = (
                    key_in_query
                    or key_in_history
                    or (explicit_project and bool(value_tokens & query_tokens))
                )
            elif category == "decisions":
                explicit_project = "projeto" in query_tokens
                is_relevant = (
                    mentioned_in_query
                    or mentioned_in_history
                    or (asks_decision and (explicit_project or follow_up))
                )
            else:
                is_relevant = mentioned_in_query

            if is_relevant:
                relevant.append(fact)
        return relevant

    def build_context(self, query: str = "", recent_messages: list[dict] | None = None) -> str:
        # Sensitive facts remain available to local memory APIs but are never
        # sent to an AI provider through the prompt context. Other facts are
        # retrieved selectively for the current request, never injected wholesale.
        if not query.strip():
            return ""
        facts = self._relevant_facts(query, recent_messages)
        if not facts:
            return ""
        category_labels = {
            "profile": "Perfil",
            "preferences": "Preferências",
            "projects": "Projetos",
            "decisions": "Decisões",
        }
        lines = ["CONTEXTO RECUPERADO (use somente o que for pertinente ao pedido atual):"]
        for fact in facts:
            category = category_labels.get(fact["category"], fact["category"])
            lines.append(
                f"- {category} / {fact['key']}: {fact['value']} "
                f"(origem registrada: {fact['source']}; atualizado em: {fact['updated_at']})"
            )
        return "\n".join(lines)
