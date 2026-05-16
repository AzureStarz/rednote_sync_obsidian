from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator


class CaptureRequest(BaseModel):
    """Payload sent from iOS Shortcuts or other capture clients."""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    platform: str = Field(default="xiaohongshu", max_length=32)
    url: str | None = Field(default=None, max_length=2048)
    share_text: str | None = Field(default=None)
    user_note: str | None = Field(default=None)
    screenshot_b64: str | None = Field(default=None)
    captured_at: str | None = Field(default=None, max_length=128)

    @field_validator("url", "share_text", "user_note", "screenshot_b64", "captured_at", mode="before")
    @classmethod
    def blank_to_none(cls, value: Any) -> Any:
        if isinstance(value, str) and value.strip() == "":
            return None
        return value


class CaptureResponse(BaseModel):
    status: str
    job_id: str | None = None
    dedupe_key: str | None = None
    message: str | None = None
