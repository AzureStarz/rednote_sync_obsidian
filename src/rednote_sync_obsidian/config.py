from __future__ import annotations

import os
from dataclasses import dataclass
from functools import lru_cache
from typing import Literal

try:  # keep tests/imports usable before python-dotenv is installed
    from dotenv import load_dotenv
except Exception:  # pragma: no cover - exercised only in minimal envs
    def load_dotenv(*_args: object, **_kwargs: object) -> bool:
        return False


LLMProvider = Literal["openai", "deepseek", "openai_compatible"]
LLMApiStyle = Literal["responses", "chat_completions"]
ReasoningEffort = Literal["low", "medium", "high", "xhigh"]
Verbosity = Literal["low", "medium", "high"]
ImageDetail = Literal["low", "high", "original", "auto"]


def _bool_env(name: str, default: bool) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "y", "on"}


def _int_env(name: str, default: int) -> int:
    raw = os.getenv(name)
    if raw is None or raw.strip() == "":
        return default
    try:
        return int(raw)
    except ValueError as exc:
        raise RuntimeError(f"{name} must be an integer") from exc


def _float_env(name: str, default: float) -> float:
    raw = os.getenv(name)
    if raw is None or raw.strip() == "":
        return default
    try:
        return float(raw)
    except ValueError as exc:
        raise RuntimeError(f"{name} must be a number") from exc


def _normalize_provider(raw: str | None) -> LLMProvider:
    provider = (raw or "openai").strip().lower().replace("-", "_")
    if provider in {"openai", "deepseek", "openai_compatible"}:
        return provider  # type: ignore[return-value]
    if provider in {"compatible", "openai_chat", "chat_compatible", "custom"}:
        return "openai_compatible"
    raise RuntimeError("LLM_PROVIDER must be one of: openai, deepseek, openai_compatible")


def _normalize_api_style(raw: str | None, provider: LLMProvider) -> LLMApiStyle:
    if raw is None or raw.strip() == "":
        return "chat_completions" if provider in {"deepseek", "openai_compatible"} else "responses"
    style = raw.strip().lower().replace("-", "_")
    if style in {"responses", "chat_completions"}:
        return style  # type: ignore[return-value]
    if style in {"chat", "chat_completion", "chat_completions"}:
        return "chat_completions"
    raise RuntimeError("LLM_API_STYLE must be one of: responses, chat_completions")


def _env_first(*names: str) -> str:
    for name in names:
        value = os.getenv(name)
        if value is not None and value.strip() != "":
            return value.strip()
    return ""


def _default_base_url(provider: LLMProvider) -> str:
    if provider == "deepseek":
        return "https://api.deepseek.com"
    return ""


def _default_model(provider: LLMProvider, api_style: LLMApiStyle) -> str:
    if provider == "deepseek":
        return "deepseek-v4-pro"
    if api_style == "responses":
        return "gpt-5.5"
    return "gpt-5.5"


@dataclass(frozen=True)
class Settings:
    # API / queue
    capture_token: str = ""
    redis_url: str = "redis://redis:6379/0"
    queue_name: str = "xhs_capture_queue"
    failed_queue_name: str = "xhs_capture_failed"
    request_dedupe_ttl_seconds: int = 60 * 60 * 24 * 30
    enable_dedupe: bool = True

    # Input guardrails
    max_screenshot_bytes: int = 4 * 1024 * 1024
    max_share_text_chars: int = 20_000
    max_extracted_text_chars: int = 12_000
    max_user_note_chars: int = 4_000

    # Raw capture storage / crawler
    raw_storage_root: str = "/data/rednote_raw"
    crawl_cookie: str = ""
    crawl_user_agent: str = (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0 Safari/537.36"
    )
    crawl_timeout_seconds: int = 20
    download_images: bool = True
    download_videos: bool = True
    max_images_per_post: int = 50
    max_videos_per_post: int = 5
    max_image_bytes: int = 10 * 1024 * 1024
    max_video_bytes: int = 200 * 1024 * 1024
    max_html_bytes: int = 10 * 1024 * 1024
    raw_index_markdown: bool = True

    # LLM provider. Backward compatible with existing OPENAI_* env vars.
    # Kept as an optional/offline summarization surface; the worker no longer
    # requires or calls an LLM in the raw capture pipeline.
    llm_provider: LLMProvider = "openai"
    llm_api_style: LLMApiStyle = "responses"
    llm_api_key: str = ""
    llm_base_url: str = ""
    llm_model: str = "gpt-5.5"
    llm_reasoning_effort: ReasoningEffort = "low"
    llm_verbosity: Verbosity = "low"
    llm_image_detail: ImageDetail = "high"
    llm_timeout_seconds: int = 90
    llm_max_output_tokens: int = 1800
    llm_temperature: float = 0.2

    # GitHub / Obsidian
    github_token: str = ""
    github_repo: str = ""
    github_branch: str = "main"
    github_api_base: str = "https://api.github.com"
    obsidian_base_path: str = "00_Inbox/Xiaohongshu"
    obsidian_asset_path: str = "90_Assets/xiaohongshu"
    write_failure_markdown: bool = True

    @classmethod
    def from_env(cls) -> "Settings":
        load_dotenv()
        provider = _normalize_provider(os.getenv("LLM_PROVIDER"))
        api_style = _normalize_api_style(os.getenv("LLM_API_STYLE") or os.getenv("OPENAI_API_STYLE"), provider)
        if provider == "deepseek":
            base_url = _env_first("LLM_BASE_URL", "DEEPSEEK_BASE_URL") or _default_base_url(provider)
            model = _env_first("LLM_MODEL", "DEEPSEEK_MODEL") or _default_model(provider, api_style)
            api_key = _env_first("LLM_API_KEY", "DEEPSEEK_API_KEY")
        elif provider == "openai":
            base_url = _env_first("LLM_BASE_URL", "OPENAI_BASE_URL") or _default_base_url(provider)
            model = _env_first("LLM_MODEL", "OPENAI_MODEL") or _default_model(provider, api_style)
            api_key = _env_first("LLM_API_KEY", "OPENAI_API_KEY")
        else:
            base_url = _env_first("LLM_BASE_URL", "OPENAI_BASE_URL", "DEEPSEEK_BASE_URL") or _default_base_url(provider)
            model = _env_first("LLM_MODEL", "OPENAI_MODEL", "DEEPSEEK_MODEL") or _default_model(provider, api_style)
            api_key = _env_first("LLM_API_KEY", "OPENAI_API_KEY", "DEEPSEEK_API_KEY")

        return cls(
            capture_token=os.getenv("CAPTURE_TOKEN", ""),
            redis_url=os.getenv("REDIS_URL", "redis://redis:6379/0"),
            queue_name=os.getenv("QUEUE_NAME", "xhs_capture_queue"),
            failed_queue_name=os.getenv("FAILED_QUEUE_NAME", "xhs_capture_failed"),
            request_dedupe_ttl_seconds=_int_env("REQUEST_DEDUPE_TTL_SECONDS", 60 * 60 * 24 * 30),
            enable_dedupe=_bool_env("ENABLE_DEDUPE", True),
            max_screenshot_bytes=_int_env("MAX_SCREENSHOT_BYTES", 4 * 1024 * 1024),
            max_share_text_chars=_int_env("MAX_SHARE_TEXT_CHARS", 20_000),
            max_extracted_text_chars=_int_env("MAX_EXTRACTED_TEXT_CHARS", 12_000),
            max_user_note_chars=_int_env("MAX_USER_NOTE_CHARS", 4_000),
            raw_storage_root=os.getenv("RAW_STORAGE_ROOT", "/data/rednote_raw"),
            crawl_cookie=os.getenv("CRAWL_COOKIE", ""),
            crawl_user_agent=os.getenv(
                "CRAWL_USER_AGENT",
                (
                    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0 Safari/537.36"
                ),
            ),
            crawl_timeout_seconds=_int_env("CRAWL_TIMEOUT_SECONDS", 20),
            download_images=_bool_env("DOWNLOAD_IMAGES", True),
            download_videos=_bool_env("DOWNLOAD_VIDEOS", True),
            max_images_per_post=_int_env("MAX_IMAGES_PER_POST", 50),
            max_videos_per_post=_int_env("MAX_VIDEOS_PER_POST", 5),
            max_image_bytes=_int_env("MAX_IMAGE_BYTES", 10 * 1024 * 1024),
            max_video_bytes=_int_env("MAX_VIDEO_BYTES", 200 * 1024 * 1024),
            max_html_bytes=_int_env("MAX_HTML_BYTES", 10 * 1024 * 1024),
            raw_index_markdown=_bool_env("RAW_INDEX_MARKDOWN", True),
            llm_provider=provider,
            llm_api_style=api_style,
            llm_api_key=api_key,
            llm_base_url=base_url,
            llm_model=model,
            llm_reasoning_effort=_env_first("LLM_REASONING_EFFORT", "OPENAI_REASONING_EFFORT") or "low",  # type: ignore[arg-type]
            llm_verbosity=_env_first("LLM_VERBOSITY", "OPENAI_VERBOSITY") or "low",  # type: ignore[arg-type]
            llm_image_detail=_env_first("LLM_IMAGE_DETAIL", "OPENAI_IMAGE_DETAIL") or "high",  # type: ignore[arg-type]
            llm_timeout_seconds=_int_env("LLM_TIMEOUT_SECONDS", _int_env("OPENAI_TIMEOUT_SECONDS", 90)),
            llm_max_output_tokens=_int_env("LLM_MAX_OUTPUT_TOKENS", _int_env("OPENAI_MAX_OUTPUT_TOKENS", 1800)),
            llm_temperature=_float_env("LLM_TEMPERATURE", 0.2),
            github_token=os.getenv("GITHUB_TOKEN", ""),
            github_repo=os.getenv("GITHUB_REPO", ""),
            github_branch=os.getenv("GITHUB_BRANCH", "main"),
            github_api_base=os.getenv("GITHUB_API_BASE", "https://api.github.com"),
            obsidian_base_path=os.getenv("OBSIDIAN_BASE_PATH", "00_Inbox/Xiaohongshu"),
            obsidian_asset_path=os.getenv("OBSIDIAN_ASSET_PATH", "90_Assets/xiaohongshu"),
            write_failure_markdown=_bool_env("WRITE_FAILURE_MARKDOWN", True),
        )

    def require_api(self) -> None:
        missing = []
        if not self.capture_token:
            missing.append("CAPTURE_TOKEN")
        if not self.redis_url:
            missing.append("REDIS_URL")
        if missing:
            raise RuntimeError(f"Missing required API environment variables: {', '.join(missing)}")

    def require_worker(self) -> None:
        missing = []
        if not self.redis_url:
            missing.append("REDIS_URL")
        if not self.raw_storage_root:
            missing.append("RAW_STORAGE_ROOT")
        if missing:
            raise RuntimeError(f"Missing required worker environment variables: {', '.join(missing)}")


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings.from_env()
