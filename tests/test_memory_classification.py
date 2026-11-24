import sqlite3

import pytest
from fastapi.testclient import TestClient

from backend.app.core.config import Settings
from backend.app.core.long_term_memory import LongTermMemory
from backend.app.intelligence.provider import ChatMessage
from backend.app.main import create_app
from tests.auth_helpers import owner_client


def test_memory_stores_classifications_and_updates_them(tmp_path):
    memory = LongTermMemory(str(tmp_path / "memory.db"))
    memory.remember("test", "general", "PUBLIC_TEST_VALUE", classification="general")
    memory.remember("test", "personal", "PERSONAL_TEST_VALUE", classification="personal")
    memory.remember("test", "sensitive", "SENSITIVE_TEST_VALUE", classification="sensitive")

    memory.remember("test", "general", "UPDATED_TEST_VALUE", classification="sensitive")

    facts = {fact["key"]: fact for fact in memory.list_facts()}
    assert facts["general"]["value"] == "UPDATED_TEST_VALUE"
    assert facts["general"]["classification"] == "sensitive"
    assert facts["personal"]["classification"] == "personal"
    assert facts["sensitive"]["classification"] == "sensitive"

    with sqlite3.connect(memory.database.database_path) as connection:
        with pytest.raises(sqlite3.IntegrityError):
            connection.execute(
                "UPDATE user_facts SET classification = 'invalid' WHERE fact_key = 'personal'"
            )


def test_memory_service_rejects_invalid_classification(tmp_path):
    memory = LongTermMemory(str(tmp_path / "memory.db"))

    with pytest.raises(ValueError, match="Classificação"):
        memory.remember("test", "invalid", "INVALID_TEST_VALUE", classification="invalid")


def test_build_context_excludes_sensitive_values(tmp_path):
    memory = LongTermMemory(str(tmp_path / "memory.db"))
    memory.remember("test", "general", "PUBLIC_TEST_VALUE", classification="general")
    memory.remember("test", "personal", "PERSONAL_TEST_VALUE", classification="personal")
    memory.remember("test", "sensitive", "SENSITIVE_TEST_VALUE", classification="sensitive")

    context = memory.build_context()

    assert "PUBLIC_TEST_VALUE" in context
    assert "PERSONAL_TEST_VALUE" in context
    assert "SENSITIVE_TEST_VALUE" not in context


def test_api_classification_crud_and_default():
    client = owner_client(create_app(settings=Settings(environment="test")))

    for classification in ("general", "personal", "sensitive"):
        response = client.post("/api/memory/facts", json={
            "category": "api-test",
            "key": classification,
            "value": f"{classification.upper()}_API_TEST_VALUE",
            "classification": classification,
        })
        assert response.status_code == 200
        assert response.json()["saved"]["classification"] == classification

    default_response = client.post("/api/memory/facts", json={
        "category": "api-test", "key": "default", "value": "DEFAULT_API_TEST_VALUE"
    })
    assert default_response.status_code == 200
    assert default_response.json()["saved"]["classification"] == "personal"

    listed = client.get("/api/memory")
    assert listed.status_code == 200
    classifications = {fact["key"]: fact["classification"] for fact in listed.json()["facts"]}
    assert classifications == {
        "default": "personal",
        "general": "general",
        "personal": "personal",
        "sensitive": "sensitive",
    }

    deleted = client.delete("/api/memory/facts/api-test/sensitive")
    assert deleted.status_code == 200
    assert not any(
        fact["key"] == "sensitive" for fact in client.get("/api/memory").json()["facts"]
    )

    invalid = client.post("/api/memory/facts", json={
        "category": "api-test", "key": "invalid", "value": "INVALID_API_TEST_VALUE",
        "classification": "invalid",
    })
    assert invalid.status_code == 422


def test_sensitive_fact_is_not_sent_to_ai_provider():
    class InspectingProvider:
        received_messages = None

        async def generate_reply(self, messages: list[ChatMessage]) -> str:
            self.received_messages = messages
            return "Resposta simulada."

    provider = InspectingProvider()
    client = owner_client(create_app(
        settings=Settings(environment="test"), ai_provider=provider
    ))
    client.post("/api/memory/facts", json={
        "category": "test", "key": "general", "value": "PUBLIC_PROVIDER_TEST_VALUE",
        "classification": "general",
    })
    client.post("/api/memory/facts", json={
        "category": "test", "key": "personal", "value": "PERSONAL_PROVIDER_TEST_VALUE",
        "classification": "personal",
    })
    client.post("/api/memory/facts", json={
        "category": "test", "key": "sensitive", "value": "SENSITIVE_PROVIDER_TEST_VALUE",
        "classification": "sensitive",
    })

    response = client.post("/api/chat", json={
        "messages": [{"role": "user", "content": "Considere as informações que você lembra."}]
    })

    assert response.status_code == 200
    delivered_text = "\n".join(message.content for message in provider.received_messages)
    assert "PUBLIC_PROVIDER_TEST_VALUE" in delivered_text
    assert "PERSONAL_PROVIDER_TEST_VALUE" in delivered_text
    assert "SENSITIVE_PROVIDER_TEST_VALUE" not in delivered_text
