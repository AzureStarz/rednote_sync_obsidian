from __future__ import annotations

from typing import Any

from .config import Settings


def create_redis_client(settings: Settings) -> Any:
    # Import lazily so unit tests for non-Redis modules can run before deps are installed.
    import redis

    return redis.Redis.from_url(settings.redis_url, decode_responses=True)


def enqueue_job(redis_client: Any, settings: Settings, job_json: str) -> int:
    return int(redis_client.lpush(settings.queue_name, job_json))


def enqueue_failed(redis_client: Any, settings: Settings, job_json: str) -> int:
    return int(redis_client.lpush(settings.failed_queue_name, job_json))
