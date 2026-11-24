"""Authenticated HTTP clients for tests of private API routes."""

from fastapi.testclient import TestClient

from backend.app.core.auth import AuthService

TEST_PASSWORD = "test-owner-master-passphrase"


def owner_client(app) -> TestClient:
    app.state.auth_repository.create_owner(AuthService.hash_password(TEST_PASSWORD))
    client = TestClient(app, base_url="http://127.0.0.1:8000", client=("127.0.0.1", 50000))
    token = client.get("/api/auth/csrf").json()["csrf_token"]
    response = client.post(
        "/api/auth/login",
        headers={"Origin": "http://127.0.0.1:8000", "X-CSRF-Token": token},
        json={"password": TEST_PASSWORD, "device_label": "Teste"},
    )
    assert response.status_code == 200
    client.headers.update({"Origin": "http://127.0.0.1:8000", "X-CSRF-Token": token})
    return client
