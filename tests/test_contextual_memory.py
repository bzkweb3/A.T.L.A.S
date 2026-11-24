import pytest

from backend.app.core.config import Settings
from backend.app.core.context_policy import ATLAS_CONTEXT_POLICY
from backend.app.intelligence.gemini_provider import ATLAS_INSTRUCTIONS as GEMINI_INSTRUCTIONS
from backend.app.intelligence.openai_provider import ATLAS_INSTRUCTIONS as OPENAI_INSTRUCTIONS
from backend.app.intelligence.provider import ChatMessage
from backend.app.main import create_app
from tests.auth_helpers import owner_client


class ContextCaptureProvider:
    def __init__(self):
        self.calls = []

    async def generate_reply(self, messages: list[ChatMessage]) -> str:
        self.calls.append(messages)
        return "Resposta de teste."


def _client(provider=None):
    provider = provider or ContextCaptureProvider()
    app = create_app(settings=Settings(environment="test"), ai_provider=provider)
    return owner_client(app), app, provider


def _sent_context(provider):
    return "\n".join(
        message.content for message in provider.calls[-1] if message.role == "system"
    )


def test_greeting_does_not_send_saved_location_name_or_preferences():
    client, app, provider = _client()
    memory = app.state.long_term_memory
    memory.remember("profile", "name", "PRIVATE_NAME_CONTEXT_TEST")
    memory.remember("profile", "location", "PRIVATE_CITY_CONTEXT_TEST")
    memory.remember("preferences", "food", "PRIVATE_PREFERENCE_CONTEXT_TEST")

    response = client.post("/api/chat", json={"messages": [{"role": "user", "content": "oi"}]})

    assert response.status_code == 200
    sent = "\n".join(message.content for message in provider.calls[-1])
    assert "PRIVATE_NAME_CONTEXT_TEST" not in sent
    assert "PRIVATE_CITY_CONTEXT_TEST" not in sent
    assert "PRIVATE_PREFERENCE_CONTEXT_TEST" not in sent


def test_question_about_unprompted_city_has_provenance_and_correction_guidance():
    client, app, provider = _client()
    app.state.long_term_memory.remember("profile", "location", "Cariacica", source="conversation")
    response = client.post("/api/chat", json={"messages": [
        {"role": "user", "content": "oi"},
        {"role": "assistant", "content": "Você mora em Cariacica."},
        {"role": "user", "content": "Por que você mencionou essa cidade?"},
    ]})

    assert response.status_code == 200
    context = _sent_context(provider)
    assert "Cariacica" in context
    assert "origem registrada: conversation" in context
    assert "sem inventar consultas" in GEMINI_INSTRUCTIONS
    assert "sem inventar consultas" in OPENAI_INSTRUCTIONS
    assert "sem necessidade foi inadequado" in GEMINI_INSTRUCTIONS
    assert "sem necessidade foi inadequado" in OPENAI_INSTRUCTIONS


def test_preference_correction_is_turn_scoped_and_keeps_memory():
    client, app, provider = _client()
    memory = app.state.long_term_memory
    memory.remember("preferences", "recommendations", "PRIVATE_PREFERENCE_CONTEXT_TEST")

    response = client.post("/api/chat", json={"messages": [{
        "role": "user",
        "content": "Não pedi recomendações baseadas nas minhas preferências.",
    }]})

    assert response.status_code == 200
    sent = "\n".join(message.content for message in provider.calls[-1])
    assert "PRIVATE_PREFERENCE_CONTEXT_TEST" not in sent
    assert memory.list_facts()[0]["value"] == "PRIVATE_PREFERENCE_CONTEXT_TEST"
    assert "não cria preferência permanente" in GEMINI_INSTRUCTIONS
    assert "não cria preferência permanente" in OPENAI_INSTRUCTIONS


def test_prior_project_question_retrieves_only_matching_project_context():
    client, app, provider = _client()
    memory = app.state.long_term_memory
    memory.remember("projects", "a_t_l_a_s", "Projeto principal de assistente pessoal.")
    memory.remember("projects", "obra", "PRIVATE_UNRELATED_PROJECT_CONTEXT_TEST")

    response = client.post("/api/chat", json={"messages": [
        {"role": "user", "content": "No projeto A.T.L.A.S., estamos construindo a memória."},
        {"role": "assistant", "content": "A memória deve ser persistente e estruturada."},
        {"role": "user", "content": "O que decidimos para o projeto A.T.L.A.S.?"},
    ]})

    assert response.status_code == 200
    sent = "\n".join(message.content for message in provider.calls[-1])
    assert "Projeto principal de assistente pessoal" in sent
    assert "PRIVATE_UNRELATED_PROJECT_CONTEXT_TEST" not in sent


def test_generic_question_does_not_receive_personal_context():
    client, app, provider = _client()
    app.state.long_term_memory.remember("profile", "location", "PRIVATE_CITY_CONTEXT_TEST")
    app.state.long_term_memory.remember("preferences", "style", "PRIVATE_PREFERENCE_CONTEXT_TEST")

    response = client.post("/api/chat", json={"messages": [{
        "role": "user", "content": "Explique como funciona a fotossíntese.",
    }]})

    assert response.status_code == 200
    sent = "\n".join(message.content for message in provider.calls[-1])
    assert "PRIVATE_CITY_CONTEXT_TEST" not in sent
    assert "PRIVATE_PREFERENCE_CONTEXT_TEST" not in sent


def test_correction_uses_recent_turns_without_becoming_a_saved_rule():
    client, app, provider = _client()
    memory = app.state.long_term_memory
    before = memory.list_facts()

    response = client.post("/api/chat", json={"messages": [
        {"role": "user", "content": "Crie um plano de compra para a obra."},
        {"role": "assistant", "content": "Vou recomendar materiais para uma casa."},
        {"role": "user", "content": "Não é uma casa; é uma reforma comercial."},
    ]})

    assert response.status_code == 200
    sent = "\n".join(message.content for message in provider.calls[-1])
    assert "Não é uma casa; é uma reforma comercial." in sent
    assert "Vou recomendar materiais para uma casa." in sent
    assert memory.list_facts() == before


@pytest.mark.parametrize("instructions", [GEMINI_INSTRUCTIONS, OPENAI_INSTRUCTIONS])
def test_each_provider_contract_contains_the_shared_context_policy(instructions):
    assert ATLAS_CONTEXT_POLICY in instructions
    for phrase in (
        "Não mencione espontaneamente nome, localização, preferências ou histórico",
        "explique a origem registrada",
        "Uma correção pontual não cria preferência permanente",
    ):
        assert phrase in instructions
