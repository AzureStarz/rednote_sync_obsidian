from fastapi.testclient import TestClient

from rednote_sync_obsidian.api import create_app
from rednote_sync_obsidian.config import Settings


class FakeRedis:
    def __init__(self):
        self.values = {}
        self.queue = []

    def set(self, key, value, nx=False, ex=None):
        if nx and key in self.values:
            return None
        self.values[key] = value
        return True

    def get(self, key):
        return self.values.get(key)

    def lpush(self, queue_name, value):
        self.queue.append((queue_name, value))
        return len(self.queue)


def make_client():
    redis = FakeRedis()
    settings = Settings(capture_token="secret", redis_url="redis://test", enable_dedupe=True)
    app = create_app(settings=settings, redis_client=redis)
    return TestClient(app), redis


def test_capture_requires_token():
    client, _redis = make_client()
    response = client.post("/capture", json={"url": "https://example.com"})
    assert response.status_code == 401


def test_capture_queues_valid_payload():
    client, redis = make_client()
    response = client.post(
        "/capture",
        headers={"X-Capture-Token": "secret"},
        json={"url": "https://example.com", "share_text": "hello"},
    )
    assert response.status_code == 202
    assert response.json()["status"] == "queued"
    assert len(redis.queue) == 1


def test_capture_duplicate_returns_existing_job():
    client, redis = make_client()
    payload = {"url": "https://example.com", "share_text": "hello"}
    first = client.post("/capture", headers={"X-Capture-Token": "secret"}, json=payload)
    second = client.post("/capture", headers={"X-Capture-Token": "secret"}, json=payload)
    assert first.status_code == 202
    assert second.status_code == 200
    assert second.json()["status"] == "duplicate"
    assert len(redis.queue) == 1
