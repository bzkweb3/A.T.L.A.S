from backend.app.core.config import Settings
from backend.app.main import create_app
from tests.auth_helpers import owner_client


def test_authenticated_frontend_removes_diagnostics_panel_but_keeps_internal_api():
    client = owner_client(create_app(settings=Settings(environment="test")))

    page = client.get("/app")
    assert page.status_code == 200
    assert 'src="/assets/Logotipo.png"' in page.text
    assert 'alt="A.T.L.A.S."' in page.text
    assert "brand-mark" not in page.text
    login = client.get("/login")
    assert login.status_code == 200
    assert 'src="/assets/Logotipo.png"' in login.text
    assert login.text.count('alt="A.T.L.A.S."') == 1
    logo = client.get("/assets/Logotipo.png")
    assert logo.status_code == 200
    assert logo.headers["content-type"] == "image/png"
    assert logo.content.startswith(bytes((137, 80, 78, 71, 13, 10, 26, 10)))
    assert client.get("/assets/nucleo.png").status_code == 404
    assert "DIAGNÓSTICO DO SISTEMA" not in page.text
    assert "/api/diagnostics" not in page.text
    assert "data-state=\"idle\"" in page.text
    assert "/api/chat/stream" in page.text
    assert "/api/auth/sessions" in page.text
    assert "/api/conversations" in page.text
    assert "/api/tasks/pending" not in page.text
    assert "showPending" not in page.text
    assert "pendingNotice" not in page.text
    assert "pendingBackdrop" not in page.text
    assert "/api/tasks/pending" in create_app(settings=Settings(environment="test")).openapi()["paths"]
    for removed in (
        "N\u00daCLEO LOCAL",
        "INTERFACE NEURAL",
        "VOZ ATLAS",
        "MEM\u00d3RIA CONTEXTUAL ATIVA",
        "ME ESCREVA UMA HIST\u00d3RIA CURTA",
        "PALAVRA DE ATIVA\u00c7\u00c3O FUTURA",
        "N\u00daCLEO DE INTELIG\u00caNCIA",
        "CONEX\u00c3O LOCAL PROTEGIDA",
        "RESPOSTA CONCLU\u00cdDA",
    ):
        assert removed not in page.text
    assert "A.T.L.A.S." in page.text
    assert "class=\"core-energy\"" in page.text
    assert 'class="core-halo"' in page.text
    assert '<svg class="core-energy" viewBox="0 0 260 260"' in page.text
    assert '<canvas class="core-energy"' not in page.text
    assert 'src="/assets/nucleo.png"' not in page.text
    assert "class AtlasCore" in page.text
    assert 'id="atlasCoreClip"' in page.text
    assert 'class="energy-ribbon secondary"' in page.text
    assert 'class="energy-filament alt"' in page.text
    assert 'class="energy-particle violet"' in page.text
    assert 'class="core-orbit"' in page.text
    assert "@keyframes ribbon-flow" in page.text
    assert 'states = new Set(["idle", "listening", "processing", "speaking", "executing", "offline"])' in page.text
    for state in ("idle", "listening", "processing", "speaking", "executing", "offline"):
        assert state in page.text
    assert '.core[data-state="processing"] .core-energy' in page.text
    assert '.core[data-state="speaking"] .core-energy' in page.text
    assert '.core[data-state="executing"] .energy-ribbon' in page.text
    assert '.core[data-state="offline"] .core-energy' in page.text
    assert "#de8c74" not in page.text
    assert "#030713" in page.text
    assert "@media (max-width: 760px)" in page.text
    assert "@media (max-width: 420px)" in page.text
    assert "place-items: center" in page.text
    assert "height: 100dvh" in page.text
    assert "overflow: hidden" in page.text
    assert "overflow-y: auto" in page.text
    assert ".stage.has-messages .core-stage" in page.text
    assert "overflow: hidden" in page.text
    assert "overscroll-behavior: contain" in page.text
    assert 'eventName === "reset"' in page.text
    assert "refreshCompletedConversation, 4000" in page.text
    assert "fonts.googleapis.com" not in page.text

    diagnostics = client.get("/api/diagnostics")
    assert diagnostics.status_code == 200
