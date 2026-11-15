"""Sign-in is enforced only when SENSEI_AUTH_PROJECT is set."""

from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)


def test_api_is_open_without_an_auth_project(monkeypatch) -> None:
    monkeypatch.delenv("SENSEI_AUTH_PROJECT", raising=False)
    assert client.get("/tracks").status_code == 200


def test_api_needs_a_token_when_auth_is_on(monkeypatch) -> None:
    monkeypatch.setenv("SENSEI_AUTH_PROJECT", "example-project")
    response = client.get("/tracks")
    assert response.status_code == 401
    assert client.get("/tracks", headers={"authorization": "Bearer not-a-real-token"}).status_code == 401
    assert client.get("/health").status_code == 200
