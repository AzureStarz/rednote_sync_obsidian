from __future__ import annotations

import hashlib
import hmac
import json
from typing import Mapping, Any


def is_authorized(provided_token: str | None, expected_token: str) -> bool:
    if not provided_token or not expected_token:
        return False
    return hmac.compare_digest(provided_token, expected_token)


def build_dedupe_key(job: Mapping[str, Any]) -> str:
    """Build a stable dedupe key without storing full screenshots in Redis keys."""

    url = (job.get("url") or "").strip()
    share_text = (job.get("share_text") or "")[:500]
    screenshot_b64 = job.get("screenshot_b64") or ""
    screenshot_hash = hashlib.sha256(screenshot_b64[:4096].encode("utf-8")).hexdigest() if screenshot_b64 else ""
    raw = json.dumps(
        {
            "platform": job.get("platform") or "xiaohongshu",
            "url": url,
            "share_text": share_text,
            "screenshot_hash": screenshot_hash,
        },
        ensure_ascii=False,
        sort_keys=True,
    )
    return "dedupe:" + hashlib.sha256(raw.encode("utf-8")).hexdigest()
