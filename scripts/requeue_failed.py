#!/usr/bin/env python3
from __future__ import annotations

from rednote_sync_obsidian.config import get_settings
from rednote_sync_obsidian.queue import create_redis_client


def main() -> None:
    settings = get_settings()
    redis_client = create_redis_client(settings)
    count = 0
    while True:
        raw = redis_client.rpop(settings.failed_queue_name)
        if raw is None:
            break
        redis_client.lpush(settings.queue_name, raw)
        count += 1
    print(f"Requeued {count} failed job(s) from {settings.failed_queue_name} to {settings.queue_name}.")


if __name__ == "__main__":
    main()
