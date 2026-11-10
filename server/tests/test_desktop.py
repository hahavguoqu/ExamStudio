import os

from fastapi.testclient import TestClient
import desktop_settings
import main


def test_encrypted_key_and_authenticated_settings(tmp_path, monkeypatch):
    monkeypatch.setenv("SHIJUAN_PROFILE", str(tmp_path))
    monkeypatch.setenv("SERVICE_TOKEN", "private-desktop-token")
    monkeypatch.setenv("DEEPSEEK_API_KEY", "")
    client = TestClient(main.app)
    key = "sk-test-not-a-real-key"
    assert client.post("/settings/key", json={"api_key": key}).status_code == 401
    headers = {"Authorization": "Bearer private-desktop-token"}
    result = client.post("/settings/key", json={"api_key": key}, headers=headers)
    assert result.status_code == 200
    assert key not in result.text
    assert key.encode() not in (tmp_path / "credential.bin").read_bytes()
    monkeypatch.setenv("DEEPSEEK_API_KEY", "")
    desktop_settings.load()
    assert os.environ["DEEPSEEK_API_KEY"] == key
    assert key not in client.get("/health", headers=headers).text
    assert client.post("/settings/key", json={"api_key": " "}, headers=headers).status_code == 422


def test_settings_unavailable_on_hosted_service(monkeypatch):
    monkeypatch.delenv("SHIJUAN_PROFILE", raising=False)
    monkeypatch.setenv("SERVICE_TOKEN", "")
    assert TestClient(main.app).post("/settings/key", json={"api_key": "sk-test"}).status_code == 403
