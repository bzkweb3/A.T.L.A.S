from fastapi.testclient import TestClient

from backend.app.core.auth import AuthService
from backend.app.core.config import Settings
from backend.app.main import create_app
from tests.auth_helpers import TEST_PASSWORD


def _app():
    return create_app(settings=Settings(environment="test"))


def _local_client(app):
    return TestClient(app, base_url="http://127.0.0.1:8000", client=("127.0.0.1", 50000))


def _csrf(client):
    return client.get("/api/auth/csrf").json()["csrf_token"]


def _login(client, token, password=TEST_PASSWORD, label="Teste"):
    return client.post("/api/auth/login", headers={
        "Origin": "http://127.0.0.1:8000", "X-CSRF-Token": token,
    }, json={"password": password, "device_label": label})


def test_private_api_and_app_require_owner_session():
    app = _app()
    client = _local_client(app)
    assert client.get("/api/memory").status_code == 401
    assert client.get("/api/conversations").status_code == 401
    assert client.get("/api/diagnostics").status_code == 401
    assert client.post("/api/chat", json={"messages": [{"role": "user", "content": "teste"}]}).status_code == 403
    assert client.post("/api/chat/stream", json={"messages": [{"role": "user", "content": "teste"}]}).status_code == 403
    assert client.get("/app", follow_redirects=False).status_code == 303
    assert client.get("/login").status_code == 200


def test_host_origin_and_csrf_are_checked_before_mutations():
    app = _app()
    client = _local_client(app)
    app.state.auth_repository.create_owner(AuthService.hash_password(TEST_PASSWORD))
    token = _csrf(client)
    assert client.post("/api/auth/login", json={"password": TEST_PASSWORD}).status_code == 403
    assert client.post("/api/auth/login", headers={
        "Origin": "http://evil.example", "X-CSRF-Token": token,
    }, json={"password": TEST_PASSWORD}).status_code == 403
    assert client.get("/api/auth/status", headers={"Host": "evil.example"}).status_code == 403
    assert client.get("/api/auth/status", headers={"X-Forwarded-Host": "127.0.0.1"}).status_code == 403


def test_owner_password_is_hashed_and_bootstrap_cannot_overwrite():
    app = _app()
    repository = app.state.auth_repository
    first = AuthService.hash_password(TEST_PASSWORD)
    assert repository.create_owner(first) is True
    assert repository.create_owner(AuthService.hash_password("another test passphrase")) is False
    stored = repository.password_hash()
    assert stored != TEST_PASSWORD
    assert stored.startswith("$argon2id$")


def test_login_creates_opaque_session_and_logout_revokes_it():
    app = _app()
    client = _local_client(app)
    app.state.auth_repository.create_owner(AuthService.hash_password(TEST_PASSWORD))
    token = _csrf(client)
    response = _login(client, token)
    assert response.status_code == 200
    assert "atlas_session" in client.cookies
    assert "HttpOnly" in response.headers["set-cookie"]
    assert client.get("/api/memory").status_code == 200
    assert client.get("/app").status_code == 200
    csrf = client.get("/api/auth/csrf").json()["csrf_token"]
    logout = client.post("/api/auth/logout", headers={
        "Origin": "http://127.0.0.1:8000", "X-CSRF-Token": csrf,
    })
    assert logout.status_code == 200
    assert client.get("/api/memory").status_code == 401


def test_session_listing_and_api_revocation_cover_session_and_device():
    app = _app()
    client = _local_client(app)
    app.state.auth_repository.create_owner(AuthService.hash_password(TEST_PASSWORD))
    csrf = _csrf(client)
    first = _login(client, csrf, label="Laptop")
    second = _login(client, csrf, label="Laptop")
    assert first.status_code == second.status_code == 200
    sessions = client.get("/api/auth/sessions").json()["sessions"]
    assert len(sessions) == 2
    assert {item["label"] for item in sessions} == {"Laptop"}
    headers = {"Origin": "http://127.0.0.1:8000", "X-CSRF-Token": csrf}
    assert client.delete(f"/api/auth/sessions/{first.json()['session_id']}", headers=headers).status_code == 200
    remaining = client.get("/api/auth/sessions").json()["sessions"]
    assert len(remaining) == 1
    device_id = remaining[0]["device_id"]
    assert client.delete(f"/api/auth/devices/{device_id}", headers=headers).status_code == 200
    assert client.get("/api/auth/sessions").status_code == 401


def test_device_revocation_immediately_invalidates_all_its_sessions():
    app = _app()
    repository = app.state.auth_repository
    repository.create_owner(AuthService.hash_password(TEST_PASSWORD))
    service = app.state.auth_service
    token_a, session_a = service.issue_session("device-shared", "Laptop", "test-agent")
    token_b, session_b = service.issue_session("device-shared", "Laptop", "test-agent")
    assert repository.get_session(token_a)
    assert repository.get_session(token_b)
    assert repository.revoke_device("device-shared") is True
    assert repository.get_session(token_a) is None
    assert repository.get_session(token_b) is None
    assert session_a["device_id"] == session_b["device_id"] == "device-shared"


def test_session_expires_after_twelve_hours_inactivity_and_at_absolute_deadline():
    app = _app()
    repository = app.state.auth_repository
    repository.create_owner(AuthService.hash_password(TEST_PASSWORD))
    token, session = app.state.auth_service.issue_session("device", "Teste", "")
    with app.state.database.connection() as connection:
        connection.execute("UPDATE auth_sessions SET last_seen_at='2000-01-01T00:00:00+00:00' WHERE id=?", (session["id"],))
    assert repository.get_session(token) is None

    second_token, second_session = app.state.auth_service.issue_session("device", "Teste", "")
    with app.state.database.connection() as connection:
        connection.execute("UPDATE auth_sessions SET expires_at='2000-01-01T00:00:00+00:00' WHERE id=?", (second_session["id"],))
    assert repository.get_session(second_token) is None


def test_password_recovery_revokes_all_sessions_atomically():
    app = _app()
    repository = app.state.auth_repository
    repository.create_owner(AuthService.hash_password(TEST_PASSWORD))
    token, _ = app.state.auth_service.issue_session("device", "Teste", "")
    repository.reset_owner(AuthService.hash_password("recovered master passphrase"))
    assert repository.get_session(token) is None
    assert app.state.auth_service.authenticate("recovered master passphrase") is True


def test_failed_login_is_rate_limited_after_five_attempts():
    app = _app()
    client = _local_client(app)
    app.state.auth_repository.create_owner(AuthService.hash_password(TEST_PASSWORD))
    token = _csrf(client)
    for _ in range(5):
        assert _login(client, token, password="incorrect password").status_code == 401
    assert _login(client, token).status_code == 401
    assert client.get("/api/auth/status").json() == {"owner_configured": True}
