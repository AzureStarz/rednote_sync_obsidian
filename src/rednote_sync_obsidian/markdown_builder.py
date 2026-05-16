from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from pathlib import PurePosixPath
from typing import Any

INVALID_FILENAME_RE = re.compile(r"[/\\:*?\"<>|\x00-\x1f]")
WHITESPACE_RE = re.compile(r"\s+")


def _yaml_string(value: Any) -> str:
    return json.dumps("" if value is None else str(value), ensure_ascii=False)


def _normalize_tag(tag: str) -> str:
    clean = tag.strip().lstrip("#")
    clean = WHITESPACE_RE.sub("-", clean)
    clean = re.sub(r"[^0-9A-Za-z_\-\u4e00-\u9fff\u3040-\u30ff\uac00-\ud7af]", "", clean)
    return clean or "小红书"


def safe_title(title: str | None) -> str:
    clean = (title or "").strip() or "未命名小红书笔记"
    clean = WHITESPACE_RE.sub(" ", clean)
    return clean[:80]


def sanitize_filename_part(value: str, *, fallback: str = "xiaohongshu", max_length: int = 80) -> str:
    clean = INVALID_FILENAME_RE.sub("-", value).strip(" .-")
    clean = WHITESPACE_RE.sub(" ", clean)
    clean = clean[:max_length].strip(" .-")
    return clean or fallback


def _date_prefix(captured_at: str | None) -> str:
    if captured_at:
        raw = captured_at.strip().replace("Z", "+00:00")
        try:
            return datetime.fromisoformat(raw).strftime("%Y-%m-%d")
        except ValueError:
            pass
    return datetime.now(timezone.utc).strftime("%Y-%m-%d")


def _join_path(*parts: str) -> str:
    normalized = [str(PurePosixPath(p.strip("/"))) for p in parts if p]
    return str(PurePosixPath(*normalized))


def build_note_path(base_path: str, title: str, job_id: str, captured_at: str | None = None) -> str:
    filename_title = sanitize_filename_part(safe_title(title), max_length=60)
    filename = f"{_date_prefix(captured_at)}_{filename_title}_{sanitize_filename_part(job_id, fallback='xhs')}.md"
    return _join_path(base_path, filename)


def build_asset_path(asset_path: str, job_id: str, extension: str = ".jpg") -> str:
    ext = extension if extension.startswith(".") else f".{extension}"
    return _join_path(asset_path, f"{sanitize_filename_part(job_id, fallback='xhs')}{ext}")


def build_markdown(
    job: dict[str, Any],
    summary: dict[str, Any],
    *,
    asset_relative_path: str | None = None,
    status: str = "processed",
) -> str:
    title = safe_title(summary.get("title"))
    url = job.get("url") or ""
    captured_at = job.get("captured_at") or ""
    tags = [_normalize_tag(tag) for tag in summary.get("tags", []) if str(tag).strip()]
    if "小红书" not in tags:
        tags.insert(0, "小红书")
    tag_yaml = "\n".join(f"  - {_yaml_string(tag)}" for tag in tags)

    key_points = "\n".join(f"- {item}" for item in summary.get("key_points", []) if item) or "- 暂无"
    action_items = "\n".join(f"- [ ] {item}" for item in summary.get("action_items", []) if item) or "- [ ] 手动复查这条保存内容"

    screenshot_section = ""
    if asset_relative_path:
        screenshot_section = f"""
## 截图

![[{asset_relative_path}]]
"""

    source_text = summary.get("source_text") or ""
    user_note = job.get("user_note") or ""

    return f"""---
source: "xiaohongshu"
url: {_yaml_string(url)}
captured_at: {_yaml_string(captured_at)}
author: {_yaml_string(summary.get("author", ""))}
category: {_yaml_string(summary.get("category", ""))}
tags:
{tag_yaml}
status: {_yaml_string(status)}
confidence: {float(summary.get("confidence", 0) or 0):.2f}
job_id: {_yaml_string(job.get("job_id", ""))}
schema_version: 1
---

# {title}

## 一句话总结

{summary.get("one_sentence_summary", "")}

## 总结

{summary.get("summary", "")}

## 关键点

{key_points}

## 为什么值得保存

{summary.get("why_it_matters", "")}

## 可执行行动

{action_items}

## 原始链接

{url or "无"}

## 我的备注

{user_note or "无"}

## 原文 / OCR / 提取内容

{source_text or "无"}
{screenshot_section}
"""


def build_failure_markdown(job: dict[str, Any], error: str, summary: dict[str, Any]) -> str:
    return build_markdown(job, summary, status="failed") + f"\n## 错误信息\n\n```text\n{error}\n```\n"
