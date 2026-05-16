from __future__ import annotations

import base64
import hashlib
import json
import os
import re
import shutil
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from .security import validate_owner_id

INVALID_FILENAME_RE = re.compile(r"[/\\:*?\"<>|\x00-\x1f]")


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def sanitize_filename_part(value: str, *, fallback: str = "item", max_length: int = 80) -> str:
    clean = INVALID_FILENAME_RE.sub("-", value).strip(" .-")
    clean = re.sub(r"\s+", " ", clean)
    clean = clean[:max_length].strip(" .-")
    return clean or fallback


def captured_date_parts(captured_at: str | None) -> tuple[str, str, str]:
    if captured_at:
        try:
            dt = datetime.fromisoformat(captured_at.strip().replace("Z", "+00:00"))
            return f"{dt.year:04d}", f"{dt.month:02d}", f"{dt.day:02d}"
        except ValueError:
            pass
    now = datetime.now(timezone.utc)
    return f"{now.year:04d}", f"{now.month:02d}", f"{now.day:02d}"


def sha256_bytes(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def yaml_string(value: Any) -> str:
    return json.dumps("" if value is None else str(value), ensure_ascii=False)


def redact_headers(headers: dict[str, str]) -> dict[str, str]:
    redacted = {}
    sensitive = {"set-cookie", "cookie", "authorization", "proxy-authorization"}
    for key, value in headers.items():
        if key.lower() in sensitive:
            redacted[key] = "<redacted>"
        else:
            redacted[key] = value
    return redacted


def extension_for_image(*, content_type: str = "", url: str = "", fallback: str = ".bin") -> str:
    mapping = {
        "image/jpeg": ".jpg",
        "image/jpg": ".jpg",
        "image/png": ".png",
        "image/webp": ".webp",
        "image/gif": ".gif",
        "image/avif": ".avif",
        "image/svg+xml": ".svg",
    }
    if content_type in mapping:
        return mapping[content_type]
    suffix = Path(urlparse(url).path).suffix.lower()
    if suffix in {".jpg", ".jpeg", ".png", ".webp", ".gif", ".avif", ".svg"}:
        return ".jpg" if suffix == ".jpeg" else suffix
    return fallback


def extension_for_video(*, content_type: str = "", url: str = "", fallback: str = ".bin") -> str:
    mapping = {
        "video/mp4": ".mp4",
        "application/mp4": ".mp4",
        "application/vnd.apple.mpegurl": ".m3u8",
        "application/x-mpegurl": ".m3u8",
    }
    if content_type in mapping:
        return mapping[content_type]
    suffix = Path(urlparse(url).path).suffix.lower()
    if suffix in {".mp4", ".m3u8"}:
        return suffix
    return fallback


def decode_screenshot_b64(value: str) -> bytes:
    raw = value.strip()
    if raw.startswith("data:") and ";base64," in raw:
        raw = raw.split(";base64,", 1)[1]
    return base64.b64decode(raw, validate=True)


@dataclass(frozen=True)
class StoredFile:
    path: str
    bytes: int
    sha256: str


class RawBundleStorage:
    """Write one Rednote capture as an atomic raw bundle on local/server disk."""

    def __init__(self, root: str | os.PathLike[str]) -> None:
        self.root = Path(root).expanduser().resolve()

    def create_staging_dir(self, job_id: str) -> Path:
        safe_job_id = sanitize_filename_part(job_id, fallback="xhs")
        staging = self.root / ".tmp" / f"{safe_job_id}.{uuid.uuid4().hex[:8]}"
        staging.mkdir(parents=True, exist_ok=False)
        return staging

    def final_dir_for_job(self, job: dict[str, Any]) -> Path:
        year, month, day = captured_date_parts(job.get("captured_at"))
        job_id = sanitize_filename_part(str(job.get("job_id") or "xhs"), fallback="xhs")
        owner_id = validate_owner_id(str(job.get("owner_id") or "default"))
        return self.root / "users" / owner_id / "posts" / year / month / day / job_id

    def cleanup_staging_dir(self, staging: Path) -> None:
        try:
            if staging.exists() and staging.is_dir():
                shutil.rmtree(staging)
        except OSError:
            pass

    def commit(self, staging: Path, job: dict[str, Any]) -> Path:
        final_dir = self.final_dir_for_job(job)
        final_dir.parent.mkdir(parents=True, exist_ok=True)
        if final_dir.exists():
            shutil.rmtree(final_dir)
        os.replace(staging, final_dir)
        return final_dir

    def _target_path(self, staging: Path, relative_path: str) -> Path:
        target = (staging / relative_path).resolve()
        staging_root = staging.resolve()
        if not target.is_relative_to(staging_root):
            raise ValueError(f"Refusing to write outside bundle staging directory: {relative_path}")
        return target

    def write_bytes(self, staging: Path, relative_path: str, content: bytes) -> StoredFile:
        target = self._target_path(staging, relative_path)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(content)
        return StoredFile(path=relative_path, bytes=len(content), sha256=sha256_bytes(content))

    def write_text(self, staging: Path, relative_path: str, content: str) -> StoredFile:
        return self.write_bytes(staging, relative_path, content.encode("utf-8"))

    def write_json(self, staging: Path, relative_path: str, data: Any) -> StoredFile:
        content = json.dumps(data, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
        return self.write_text(staging, relative_path, content)


def build_capture_request_record(job: dict[str, Any], *, has_crawl_cookie: bool) -> dict[str, Any]:
    return {
        "job_id": job.get("job_id"),
        "owner_id": job.get("owner_id") or "default",
        "owner_display_name": job.get("owner_display_name") or "Default",
        "platform": job.get("platform"),
        "url": job.get("url"),
        "share_text": job.get("share_text"),
        "user_note": job.get("user_note"),
        "captured_at": job.get("captured_at"),
        "queued_at": job.get("queued_at"),
        "schema_version": job.get("schema_version"),
        "screenshot_bytes": job.get("screenshot_bytes", 0),
        "has_screenshot": bool(job.get("screenshot_b64")),
        "has_crawl_cookie": has_crawl_cookie,
    }


def build_raw_index_markdown(job: dict[str, Any], manifest: dict[str, Any]) -> str:
    page = manifest.get("page", {})
    title = page.get("title") or job.get("share_text") or job.get("url") or "未命名小红书原始笔记"
    title = str(title).replace("\n", " ")[:120]
    images = manifest.get("images", [])
    image_links = "\n".join(
        f"- ![[{item['path']}]]"
        for item in images
        if item.get("status") == "downloaded" and item.get("path")
    )
    failed_images = "\n".join(
        f"- `{item.get('url', '')}` — {item.get('error', 'unknown error')}"
        for item in images
        if item.get("status") != "downloaded"
    )
    videos = manifest.get("videos", [])
    video_links = "\n".join(
        f"- ![[{item['path']}]]"
        for item in videos
        if item.get("status") == "downloaded" and item.get("path")
    )
    failed_videos = "\n".join(
        f"- `{item.get('url', '')}` — {item.get('error', 'unknown error')}"
        for item in videos
        if item.get("status") != "downloaded"
    )
    share_text = job.get("share_text") or "无"
    user_note = job.get("user_note") or "无"
    source_url = manifest.get("source_url") or ""
    final_url = manifest.get("final_url") or ""
    status = manifest.get("status") or "unknown"

    return f"""---
source: "xiaohongshu"
capture_type: "raw"
status: "{status}"
job_id: {yaml_string(job.get("job_id", ""))}
owner_id: {yaml_string(job.get("owner_id", "default"))}
url: {yaml_string(source_url)}
final_url: {yaml_string(final_url)}
captured_at: {yaml_string(job.get("captured_at", ""))}
schema_version: {manifest.get("schema_version", 2)}
---

# {title}

## 原始链接

{source_url or "无"}

## 最终链接

{final_url or "无"}

## 页面元数据

- 标题：{page.get("title") or "无"}
- 描述：{page.get("description") or "无"}
- 作者：{page.get("author") or "无"}
- HTTP 状态：{manifest.get("http", {}).get("status_code") or "无"}

## 原始文件

- HTML：[[source.html]]
- Manifest：[[manifest.json]]
- 请求记录：[[request.json]]
- 响应头：[[response_headers.json]]
- 提取报告：[[extraction_report.json]]

## 我的备注

{user_note}

## 分享文本

{share_text}

## 图片

{image_links or "无已下载图片"}

## 图片下载失败

{failed_images or "无"}

## 视频

{video_links or "无已下载视频"}

## 视频下载失败

{failed_videos or "无"}
"""
