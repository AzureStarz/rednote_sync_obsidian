from __future__ import annotations

import hashlib
import hmac
import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping

OWNER_ID_RE = re.compile(r"^[a-z0-9][a-z0-9_-]{0,62}$")


@dataclass(frozen=True)
class CaptureUser:
    owner_id: str
    display_name: str
    token: str


def is_authorized(provided_token: str | None, expected_token: str) -> bool:
    if not provided_token or not expected_token:
        return False
    return hmac.compare_digest(provided_token, expected_token)


def validate_owner_id(owner_id: str) -> str:
    clean = owner_id.strip()
    if not OWNER_ID_RE.fullmatch(clean):
        raise ValueError("owner_id must match ^[a-z0-9][a-z0-9_-]{0,62}$")
    return clean


def load_capture_users(path: str | Path) -> dict[str, CaptureUser]:
    user_path = Path(path).expanduser()
    try:
        raw = json.loads(user_path.read_text(encoding="utf-8"))
    except Exception as exc:
        raise RuntimeError(f"Cannot read CAPTURE_USERS_FILE: {user_path}") from exc

    if not isinstance(raw, dict) or not raw:
        raise RuntimeError("CAPTURE_USERS_FILE must be a non-empty JSON object")

    users: dict[str, CaptureUser] = {}
    seen_tokens: set[str] = set()
    for owner_id, record in raw.items():
        if not isinstance(owner_id, str):
            raise RuntimeError("CAPTURE_USERS_FILE owner ids must be strings")
        try:
            safe_owner_id = validate_owner_id(owner_id)
        except ValueError as exc:
            raise RuntimeError(f"Invalid CAPTURE_USERS_FILE owner id {owner_id!r}: {exc}") from exc

        if isinstance(record, str):
            token = record.strip()
            display_name = safe_owner_id
        elif isinstance(record, dict):
            token = str(record.get("token") or "").strip()
            display_name = str(record.get("display_name") or safe_owner_id).strip() or safe_owner_id
        else:
            raise RuntimeError(f"CAPTURE_USERS_FILE record for {safe_owner_id!r} must be an object or token string")

        if not token:
            raise RuntimeError(f"CAPTURE_USERS_FILE record for {safe_owner_id!r} is missing token")
        if token in seen_tokens:
            raise RuntimeError("CAPTURE_USERS_FILE contains duplicate tokens")
        seen_tokens.add(token)
        users[safe_owner_id] = CaptureUser(owner_id=safe_owner_id, display_name=display_name, token=token)

    return users


def resolve_capture_user(
    provided_token: str | None,
    *,
    users_file: str = "",
    fallback_token: str = "",
) -> CaptureUser | None:
    if users_file:
        if not provided_token:
            return None
        for user in load_capture_users(users_file).values():
            if hmac.compare_digest(provided_token, user.token):
                return user
        return None

    if is_authorized(provided_token, fallback_token):
        return CaptureUser(owner_id="default", display_name="Default", token=fallback_token)
    return None


def build_dedupe_key(job: Mapping[str, Any]) -> str:
    """Build a stable dedupe key without storing full screenshots in Redis keys."""

    url = (job.get("url") or "").strip()
    share_text = (job.get("share_text") or "")[:500]
    screenshot_b64 = job.get("screenshot_b64") or ""
    screenshot_hash = hashlib.sha256(screenshot_b64[:4096].encode("utf-8")).hexdigest() if screenshot_b64 else ""
    raw = json.dumps(
        {
            "owner_id": job.get("owner_id") or "default",
            "platform": job.get("platform") or "xiaohongshu",
            "url": url,
            "share_text": share_text,
            "screenshot_hash": screenshot_hash,
        },
        ensure_ascii=False,
        sort_keys=True,
    )
    return "dedupe:" + hashlib.sha256(raw.encode("utf-8")).hexdigest()
