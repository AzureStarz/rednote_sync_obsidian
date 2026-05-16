from __future__ import annotations

import base64
import binascii
import json
import uuid
from datetime import datetime, timezone
from typing import Any

from .config import Settings
from .models import CaptureRequest
from .security import CaptureUser


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def clean_base64_image(value: str, max_bytes: int) -> tuple[str, bytes]:
    """Validate and normalize a Base64 image string from Shortcuts.

    Accepts either raw Base64 or a data URL such as data:image/jpeg;base64,...
    Returns normalized raw Base64 plus decoded bytes.
    """

    raw = value.strip()
    if raw.startswith("data:"):
        marker = ";base64,"
        if marker not in raw:
            raise ValueError("screenshot_b64 data URL must be Base64 encoded")
        raw = raw.split(marker, 1)[1]

    try:
        image_bytes = base64.b64decode(raw, validate=True)
    except (binascii.Error, ValueError) as exc:
        raise ValueError("screenshot_b64 is not valid Base64") from exc

    if not image_bytes:
        raise ValueError("screenshot_b64 decoded to an empty file")
    if len(image_bytes) > max_bytes:
        raise ValueError(f"screenshot is too large: {len(image_bytes)} bytes > {max_bytes} bytes")

    return raw, image_bytes


def build_job(payload: CaptureRequest, settings: Settings, owner: CaptureUser | None = None) -> dict[str, Any]:
    share_text = payload.share_text
    user_note = payload.user_note

    if share_text and len(share_text) > settings.max_share_text_chars:
        share_text = share_text[: settings.max_share_text_chars]
    if user_note and len(user_note) > settings.max_user_note_chars:
        user_note = user_note[: settings.max_user_note_chars]

    screenshot_b64 = None
    screenshot_bytes = None
    if payload.screenshot_b64:
        screenshot_b64, screenshot_bytes = clean_base64_image(payload.screenshot_b64, settings.max_screenshot_bytes)

    if not any([payload.url, share_text, screenshot_b64]):
        raise ValueError("At least one of url, share_text, or screenshot_b64 is required")

    job_id = "xhs_" + uuid.uuid4().hex[:12]
    job = {
        "job_id": job_id,
        "owner_id": owner.owner_id if owner else "default",
        "owner_display_name": owner.display_name if owner else "Default",
        "platform": payload.platform or "xiaohongshu",
        "url": payload.url,
        "share_text": share_text,
        "user_note": user_note,
        "screenshot_b64": screenshot_b64,
        "screenshot_bytes": len(screenshot_bytes) if screenshot_bytes else 0,
        "captured_at": payload.captured_at or utc_now_iso(),
        "queued_at": utc_now_iso(),
        "status": "queued",
        "schema_version": 1,
    }
    return job


def serialize_job(job: dict[str, Any]) -> str:
    return json.dumps(job, ensure_ascii=False, separators=(",", ":"))


def deserialize_job(raw: str | bytes) -> dict[str, Any]:
    if isinstance(raw, bytes):
        raw = raw.decode("utf-8")
    data = json.loads(raw)
    if not isinstance(data, dict):
        raise ValueError("Job payload must be a JSON object")
    return data


def redacted_job(job: dict[str, Any]) -> dict[str, Any]:
    clean = dict(job)
    if clean.get("screenshot_b64"):
        clean["screenshot_b64"] = f"<redacted:{len(clean['screenshot_b64'])} chars>"
    return clean
