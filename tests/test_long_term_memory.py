from fastapi.testclient import TestClient

from backend.app.core.config import Settings
from backend.app.main import create_app
from backend.app.intelligence.provider import ChatMessage


class MemoryAwareProvider:
    async def generate_reply(self, messages: list[ChatMessage]) -> str:
        system = next((m.content for m in messages if m.role == "system"), "")
        assert "Brendo" in system
        return "Seu nome é Brendo."


def test_explicit_name_is_remembered_and_injected_into_new_chat():
    client = TestClient(create_app(settings=Settings(environment="test"), ai_provider=MemoryAwareProvider()))
    saved = client.post("/api/memory/facts", json={"category": "profile", "key": "name", "value": "Brendo"})
    assert saved.status_code == 200
    assert client.get("/api/memory").json()["facts"][0]["value"] == "Brendo"
    response = client.post("/api/chat", json={"messages": [{"role": "user", "content": "Você sabe meu nome?"}]})
    assert response.status_code == 200
    assert "Brendo" in response.json()["reply"]


def test_name_is_extracted_from_explicit_user_statement():
    class EchoMemoryProvider:
        async def generate_reply(self, messages):
            return "Registrado."
    client = TestClient(create_app(settings=Settings(environment="test"), ai_provider=EchoMemoryProvider()))
    response = client.post("/api/chat", json={"messages": [{"role": "user", "content": "Meu nome é Brendo."}]})
    assert response.status_code == 200
    facts = client.get("/api/memory").json()["facts"]
    assert any(f["key"] == "name" and f["value"] == "Brendo" for f in facts)



def test_personal_memory_questions_are_answered_without_calling_ai():
    class MustNotRunProvider:
        async def generate_reply(self, messages):
            raise AssertionError("Pergunta simples de memória não deve chamar a IA.")

    client = TestClient(create_app(
        settings=Settings(environment="test"),
        ai_provider=MustNotRunProvider(),
    ))
    client.post("/api/memory/facts", json={
        "category": "profile", "key": "name", "value": "Sr. Brendo"
    })
    client.post("/api/memory/facts", json={
        "category": "profile", "key": "location", "value": "Cariacica, Espírito Santo"
    })

    name = client.post("/api/chat", json={
        "messages": [{"role": "user", "content": "sabe meu nome?"}]
    })
    location = client.post("/api/chat", json={
        "messages": [{"role": "user", "content": "onde eu moro?"}]
    })

    assert name.status_code == 200
    assert "Sr. Brendo" in name.json()["reply"]
    assert location.status_code == 200
    assert "Cariacica" in location.json()["reply"]



def test_explicit_location_is_saved_and_acknowledged_without_ai():
    class MustNotRunProvider:
        async def generate_reply(self, messages):
            raise AssertionError("Declaração explícita de perfil não deve chamar a IA.")

    client = TestClient(create_app(
        settings=Settings(environment="test"),
        ai_provider=MustNotRunProvider(),
    ))
    response = client.post("/api/chat", json={
        "messages": [{"role": "user", "content": "Eu moro em Cariacica, no Espírito Santo."}]
    })

    assert response.status_code == 200
    assert "Cariacica" in response.json()["reply"]
    facts = client.get("/api/memory").json()["facts"]
    assert any(f["key"] == "location" and f["value"] == "Cariacica, no Espírito Santo" for f in facts)


def test_memory_fact_can_be_deleted_without_removing_other_facts():
    client = TestClient(create_app(settings=Settings(environment="test"), ai_provider=MemoryAwareProvider()))
    client.post("/api/memory/facts", json={
        "category": "profile", "key": "name", "value": "Brendo"
    })
    client.post("/api/memory/facts", json={
        "category": "preferences", "key": "communication", "value": "Respostas objetivas"
    })

    deleted = client.delete("/api/memory/facts/profile/name")

    assert deleted.status_code == 200
    remaining = client.get("/api/memory").json()["facts"]
    assert not any(f["category"] == "profile" and f["key"] == "name" for f in remaining)
    assert any(f["category"] == "preferences" and f["key"] == "communication" for f in remaining)


def test_deleting_unknown_memory_fact_returns_404():
    client = TestClient(create_app(settings=Settings(environment="test"), ai_provider=MemoryAwareProvider()))
    response = client.delete("/api/memory/facts/profile/unknown")
    assert response.status_code == 404


def test_explicit_preferences_and_decisions_are_saved():
    from backend.app.core.long_term_memory import LongTermMemory

    memory = LongTermMemory(":memory:")
    memory.extract_explicit_facts("Prefiro respostas objetivas. Decidi que o sistema será híbrido.")
    facts = {(fact["category"], fact["key"]): fact["value"] for fact in memory.list_facts()}

    assert facts[("preferences", "general")] == "respostas objetivas"
    assert facts[("decisions", "latest")] == "o sistema será híbrido"


def test_named_project_context_is_saved_and_categorized():
    from backend.app.core.long_term_memory import LongTermMemory

    memory = LongTermMemory(":memory:")
    memory.extract_explicit_facts(
        "No projeto A.T.L.A.S., estamos desenvolvendo memória contextual."
    )

    facts = memory.list_facts()
    assert any(
        fact["category"] == "projects"
        and fact["key"] == "a_t_l_a_s"
        and fact["value"] == "desenvolvendo memória contextual"
        for fact in facts
    )
    assert "Projetos / a_t_l_a_s" in memory.build_context()
