from __future__ import annotations

import json
import re
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator

from .config import Settings


class Summary(BaseModel):
    model_config = ConfigDict(extra="forbid")

    title: str = Field(min_length=1, max_length=120)
    one_sentence_summary: str = Field(max_length=240)
    summary: str = Field(max_length=1200)
    key_points: list[str] = Field(default_factory=list, min_length=0, max_length=7)
    why_it_matters: str = Field(max_length=800)
    action_items: list[str] = Field(default_factory=list, min_length=0, max_length=8)
    tags: list[str] = Field(default_factory=list, min_length=1, max_length=10)
    category: str = Field(max_length=80)
    author: str = Field(default="", max_length=120)
    source_text: str = Field(default="", max_length=20_000)
    confidence: float = Field(ge=0, le=1)

    @field_validator("key_points", "action_items", "tags")
    @classmethod
    def strip_items(cls, values: list[str]) -> list[str]:
        return [v.strip() for v in values if isinstance(v, str) and v.strip()]


SUMMARY_JSON_SCHEMA: dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "properties": {
        "title": {"type": "string", "description": "Concise Obsidian note title, <= 60 Chinese chars or <= 120 English chars."},
        "one_sentence_summary": {"type": "string"},
        "summary": {"type": "string", "description": "100-200 Chinese chars when enough evidence exists; shorter if source is sparse."},
        "key_points": {"type": "array", "items": {"type": "string"}, "minItems": 0, "maxItems": 7},
        "why_it_matters": {"type": "string"},
        "action_items": {"type": "array", "items": {"type": "string"}, "minItems": 0, "maxItems": 8},
        "tags": {"type": "array", "items": {"type": "string"}, "minItems": 1, "maxItems": 10},
        "category": {"type": "string"},
        "author": {"type": "string"},
        "source_text": {"type": "string", "description": "Relevant original share text / OCR / extracted text used for the summary."},
        "confidence": {"type": "number", "minimum": 0, "maximum": 1},
    },
    "required": [
        "title",
        "one_sentence_summary",
        "summary",
        "key_points",
        "why_it_matters",
        "action_items",
        "tags",
        "category",
        "author",
        "source_text",
        "confidence",
    ],
}

DEVELOPER_INSTRUCTIONS = """You are a personal knowledge-base curator for Rednote/Xiaohongshu captures.
Outcome: convert one user-saved item into a compact, evidence-grounded Obsidian note summary.
Rules:
- Write primarily in Chinese unless the source is mostly another language.
- Do not invent facts not present in URL/share text/extracted text/screenshot/user note.
- If evidence is weak, keep claims cautious and lower confidence.
- Prefer practical, searchable tags and concrete action items.
- Preserve important original text in source_text; summarize spammy UI/navigation text away.
- If a screenshot is provided to the model, incorporate visible text as visual/OCR evidence.
"""

CHAT_JSON_INSTRUCTIONS = """Return exactly one valid JSON object and no Markdown fences.
The JSON object must contain these keys:
- title: string
- one_sentence_summary: string
- summary: string
- key_points: array of strings, 0-7 items
- why_it_matters: string
- action_items: array of strings, 0-8 items
- tags: array of strings, 1-10 items
- category: string
- author: string, empty if unknown
- source_text: string, preserve relevant original text used as evidence
- confidence: number from 0 to 1
"""

JSON_FENCE_RE = re.compile(r"```(?:json)?\s*(.*?)\s*```", re.DOTALL | re.IGNORECASE)


def _build_user_text(
    *,
    url: str | None,
    share_text: str | None,
    user_note: str | None,
    extracted_text: str | None,
) -> str:
    return "\n\n".join(
        [
            "Saved Rednote/Xiaohongshu item. Summarize it for my Obsidian vault.",
            f"URL:\n{url or ''}",
            f"Share text:\n{share_text or ''}",
            f"My note:\n{user_note or ''}",
            f"Best-effort public page extraction:\n{extracted_text or ''}",
        ]
    )


def _client_kwargs(settings: Settings) -> dict[str, Any]:
    kwargs: dict[str, Any] = {
        "api_key": settings.llm_api_key,
        "timeout": settings.llm_timeout_seconds,
    }
    if settings.llm_base_url:
        kwargs["base_url"] = settings.llm_base_url
    return kwargs


def _parse_summary_json(text: str) -> dict[str, Any]:
    raw = text.strip()
    fence = JSON_FENCE_RE.search(raw)
    if fence:
        raw = fence.group(1).strip()
    if not raw.startswith("{"):
        start = raw.find("{")
        end = raw.rfind("}")
        if start != -1 and end != -1 and end > start:
            raw = raw[start : end + 1]
    data = json.loads(raw)
    return Summary.model_validate(data).model_dump()


def _extract_response_text(response: Any) -> str:
    output_text = getattr(response, "output_text", None)
    if output_text:
        return str(output_text)

    # Defensive fallback for SDK versions that do not expose output_text.
    pieces: list[str] = []
    for output in getattr(response, "output", []) or []:
        for item in getattr(output, "content", []) or []:
            item_type = getattr(item, "type", None)
            if item_type == "refusal":
                refusal = getattr(item, "refusal", "")
                raise RuntimeError(f"LLM refused the summarization request: {refusal}")
            text = getattr(item, "text", None)
            if text:
                pieces.append(str(text))
    if not pieces:
        raise RuntimeError("LLM response did not contain output text")
    return "\n".join(pieces)


def _extract_chat_completion_text(completion: Any) -> str:
    choices = getattr(completion, "choices", None) or []
    if not choices:
        raise RuntimeError("Chat completion did not contain any choices")
    message = getattr(choices[0], "message", None)
    content = getattr(message, "content", None) if message is not None else None
    if not content:
        raise RuntimeError("Chat completion did not contain message content")
    return str(content)


def _build_responses_content(
    *,
    settings: Settings,
    url: str | None,
    share_text: str | None,
    user_note: str | None,
    extracted_text: str | None,
    screenshot_b64: str | None,
) -> list[dict[str, Any]]:
    content: list[dict[str, Any]] = [
        {"type": "input_text", "text": _build_user_text(url=url, share_text=share_text, user_note=user_note, extracted_text=extracted_text)}
    ]
    if screenshot_b64:
        content.append(
            {
                "type": "input_image",
                "image_url": f"data:image/jpeg;base64,{screenshot_b64}",
                "detail": settings.llm_image_detail,
            }
        )
    return content


def _build_chat_messages(
    *,
    url: str | None,
    share_text: str | None,
    user_note: str | None,
    extracted_text: str | None,
    screenshot_b64: str | None,
) -> list[dict[str, str]]:
    user_text = _build_user_text(url=url, share_text=share_text, user_note=user_note, extracted_text=extracted_text)
    if screenshot_b64:
        user_text += (
            "\n\nScreenshot note:\n"
            "A screenshot was attached to the capture and will still be saved as an Obsidian asset, "
            "but this chat-completions provider adapter does not send image bytes to the model. "
            "Use share text, extracted page text, and user note only for the summary."
        )
    return [
        {"role": "system", "content": DEVELOPER_INSTRUCTIONS + "\n" + CHAT_JSON_INSTRUCTIONS},
        {"role": "user", "content": user_text},
    ]


def _summarize_with_responses(
    *,
    settings: Settings,
    url: str | None,
    share_text: str | None,
    user_note: str | None,
    extracted_text: str | None,
    screenshot_b64: str | None,
) -> dict[str, Any]:
    from openai import OpenAI

    client = OpenAI(**_client_kwargs(settings))
    text_config: dict[str, Any] = {
        "format": {
            "type": "json_schema",
            "name": "rednote_obsidian_summary",
            "schema": SUMMARY_JSON_SCHEMA,
            "strict": True,
        },
        "verbosity": settings.llm_verbosity,
    }

    response = client.responses.create(
        model=settings.llm_model,
        instructions=DEVELOPER_INSTRUCTIONS,
        input=[
            {
                "role": "user",
                "content": _build_responses_content(
                    settings=settings,
                    url=url,
                    share_text=share_text,
                    user_note=user_note,
                    extracted_text=extracted_text,
                    screenshot_b64=screenshot_b64,
                ),
            }
        ],
        text=text_config,
        reasoning={"effort": settings.llm_reasoning_effort},
        max_output_tokens=settings.llm_max_output_tokens,
        store=False,
    )
    return _parse_summary_json(_extract_response_text(response))


def _summarize_with_chat_completions(
    *,
    settings: Settings,
    url: str | None,
    share_text: str | None,
    user_note: str | None,
    extracted_text: str | None,
    screenshot_b64: str | None,
) -> dict[str, Any]:
    from openai import OpenAI

    client = OpenAI(**_client_kwargs(settings))
    completion = client.chat.completions.create(
        model=settings.llm_model,
        messages=_build_chat_messages(
            url=url,
            share_text=share_text,
            user_note=user_note,
            extracted_text=extracted_text,
            screenshot_b64=screenshot_b64,
        ),
        response_format={"type": "json_object"},
        max_tokens=settings.llm_max_output_tokens,
        temperature=settings.llm_temperature,
        stream=False,
    )
    return _parse_summary_json(_extract_chat_completion_text(completion))


def summarize_xhs_note(
    *,
    settings: Settings,
    url: str | None,
    share_text: str | None,
    user_note: str | None,
    extracted_text: str | None,
    screenshot_b64: str | None,
) -> dict[str, Any]:
    """Summarize one capture using the configured LLM provider.

    `responses` mode supports OpenAI Responses API and screenshot image input.
    `chat_completions` mode supports DeepSeek and other OpenAI-compatible chat APIs;
    it uses JSON mode plus local Pydantic validation, and currently summarizes text only.
    """

    if settings.llm_api_style == "responses":
        return _summarize_with_responses(
            settings=settings,
            url=url,
            share_text=share_text,
            user_note=user_note,
            extracted_text=extracted_text,
            screenshot_b64=screenshot_b64,
        )
    return _summarize_with_chat_completions(
        settings=settings,
        url=url,
        share_text=share_text,
        user_note=user_note,
        extracted_text=extracted_text,
        screenshot_b64=screenshot_b64,
    )


def fallback_summary_from_job(job: dict[str, Any], error: str | None = None) -> dict[str, Any]:
    source = "\n\n".join(
        part
        for part in [
            job.get("share_text") or "",
            f"User note: {job.get('user_note')}" if job.get("user_note") else "",
            f"URL: {job.get('url')}" if job.get("url") else "",
            f"Error: {error}" if error else "",
        ]
        if part
    )
    title = "小红书保存失败" if error else "未总结的小红书笔记"
    if job.get("share_text"):
        title = str(job["share_text"]).replace("\n", " ")[:40]
    return Summary(
        title=title or "未总结的小红书笔记",
        one_sentence_summary="这条内容已保存，但自动总结暂时失败，需要稍后重试或手动整理。" if error else "这条内容已保存，等待后续整理。",
        summary="自动总结未完成；已保留原始链接、分享文本、备注和错误信息，避免资料丢失。" if error else "已保留原始信息。",
        key_points=[],
        why_it_matters="这是你主动保存的内容，可能对后续知识整理有价值。",
        action_items=["稍后重试失败队列", "必要时手动补充摘要"],
        tags=["小红书", "待处理"],
        category="待处理",
        author="",
        source_text=source,
        confidence=0.1,
    ).model_dump()
