from __future__ import annotations

import re
import json
from dataclasses import dataclass
from html import unescape
from typing import Iterable
from urllib.parse import urljoin, urlparse

import httpx
from bs4 import BeautifulSoup

URL_RE = re.compile(r"https?://[^\s<>'\"）)]+", re.IGNORECASE)
IMAGE_URL_RE = re.compile(r"https?:\\?/\\?/[^\"'\s<>);]+?\.(?:jpg|jpeg|png|webp|gif|avif)(?:\?[^\"'\s<>);]*)?", re.IGNORECASE)
XHS_CDN_URL_RE = re.compile(
    r"https?:\\?/\\?/[^\"'\s<>);]*(?:sns-webpic[^\"'\s<>);]*\.xhscdn\.(?:com|net)|(?:ci|edith)\.xiaohongshu\.com)/[^\"'\s<>);]+",
    re.IGNORECASE,
)
VIDEO_URL_RE = re.compile(
    r"https?:\\?/\\?/[^\"'\s<>);]*(?:sns-video[^\"'\s<>);]*\.xhscdn\.(?:com|net)|[^\"'\s<>);]+\.xhscdn\.(?:com|net))[^\"'\s<>);]*\.(?:mp4|m3u8)(?:\?[^\"'\s<>);]*)?",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class PageFetchResult:
    requested_url: str | None
    final_url: str | None
    status_code: int | None
    headers: dict[str, str]
    content: bytes
    text: str
    error: str | None = None
    truncated: bool = False


@dataclass(frozen=True)
class ImageCandidate:
    url: str
    source: str
    alt: str = ""


@dataclass(frozen=True)
class VideoCandidate:
    url: str
    source: str


@dataclass(frozen=True)
class ImageFetchResult:
    url: str
    final_url: str | None
    status_code: int | None
    headers: dict[str, str]
    content: bytes
    content_type: str
    error: str | None = None
    truncated: bool = False


@dataclass(frozen=True)
class VideoFetchResult:
    url: str
    final_url: str | None
    status_code: int | None
    headers: dict[str, str]
    content: bytes
    content_type: str
    error: str | None = None
    truncated: bool = False


def sniff_image_content_type(content: bytes) -> str:
    head = content[:32]
    if head.startswith(b"\xff\xd8\xff"):
        return "image/jpeg"
    if head.startswith(b"\x89PNG\r\n\x1a\n"):
        return "image/png"
    if head.startswith(b"GIF87a") or head.startswith(b"GIF89a"):
        return "image/gif"
    if len(head) >= 12 and head[:4] == b"RIFF" and head[8:12] == b"WEBP":
        return "image/webp"
    if len(head) >= 12 and head[4:8] == b"ftyp" and head[8:12] in {b"avif", b"avis"}:
        return "image/avif"
    if content.lstrip()[:5].lower() == b"<svg " or content.lstrip()[:4].lower() == b"<svg":
        return "image/svg+xml"
    return ""


def sniff_video_content_type(content: bytes) -> str:
    head = content[:64]
    if len(head) >= 12 and head[4:8] == b"ftyp":
        return "video/mp4"
    stripped = content.lstrip()[:16]
    if stripped.startswith(b"#EXTM3U"):
        return "application/vnd.apple.mpegurl"
    return ""


def extract_url_from_text(text: str | None) -> str | None:
    if not text:
        return None
    match = URL_RE.search(text)
    return match.group(0).rstrip(".,;，。；") if match else None


def _default_headers(*, cookie: str = "", user_agent: str = "", referer: str | None = None, accept: str = "*/*") -> dict[str, str]:
    headers = {
        "User-Agent": user_agent
        or (
            "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
            "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0 Safari/537.36"
        ),
        "Accept": accept,
        "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
    }
    if cookie:
        headers["Cookie"] = cookie
    if referer:
        headers["Referer"] = referer
    return headers


def _read_response_content(response: httpx.Response, *, max_bytes: int) -> tuple[bytes, bool]:
    chunks: list[bytes] = []
    total = 0
    truncated = False
    for chunk in response.iter_bytes():
        if not chunk:
            continue
        next_total = total + len(chunk)
        if next_total > max_bytes:
            remaining = max_bytes - total
            if remaining > 0:
                chunks.append(chunk[:remaining])
            truncated = True
            break
        chunks.append(chunk)
        total = next_total
    return b"".join(chunks), truncated


def fetch_page(
    url: str | None,
    *,
    cookie: str = "",
    user_agent: str = "",
    timeout_seconds: float = 20.0,
    max_bytes: int = 10 * 1024 * 1024,
) -> PageFetchResult:
    """Fetch and retain the raw public page response.

    The optional cookie is caller-provided login state. This function does not
    bypass signatures, CAPTCHAs, app-only APIs, or other access controls.
    """

    if not url:
        return PageFetchResult(
            requested_url=None,
            final_url=None,
            status_code=None,
            headers={},
            content=b"",
            text="",
            error="No URL available for page fetch",
        )

    try:
        headers = _default_headers(cookie=cookie, user_agent=user_agent, accept="text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8")
        with httpx.Client(timeout=timeout_seconds, follow_redirects=True, headers=headers) as client:
            with client.stream("GET", url) as response:
                content, truncated = _read_response_content(response, max_bytes=max_bytes)
                encoding = response.encoding or "utf-8"
                text = content.decode(encoding, errors="replace")
                return PageFetchResult(
                    requested_url=url,
                    final_url=str(response.url),
                    status_code=response.status_code,
                    headers=dict(response.headers),
                    content=content,
                    text=text,
                    error=None if response.status_code < 400 else f"HTTP {response.status_code}",
                    truncated=truncated,
                )
    except Exception as exc:
        return PageFetchResult(
            requested_url=url,
            final_url=None,
            status_code=None,
            headers={},
            content=b"",
            text="",
            error=f"{type(exc).__name__}: {exc}",
        )


def _first_meta_content(soup: BeautifulSoup, selectors: Iterable[dict[str, str]]) -> str:
    for attrs in selectors:
        tag = soup.find("meta", attrs=attrs)
        if tag and tag.get("content"):
            return str(tag.get("content", "")).strip()
    return ""


def _meta_contents(soup: BeautifulSoup, selectors: Iterable[dict[str, str]]) -> list[str]:
    values: list[str] = []
    for attrs in selectors:
        for tag in soup.find_all("meta", attrs=attrs):
            if tag and tag.get("content"):
                values.append(str(tag.get("content", "")).strip())
    return values


def _decode_json_string(value: str) -> str:
    try:
        decoded = json.loads(f'"{value}"')
        return str(decoded).strip()
    except Exception:
        return unescape(value).replace("\\u002F", "/").replace("\\/", "/").strip()


def _extract_xhs_author(html: str) -> str:
    """Extract Rednote note author from embedded SSR state.

    Rednote often does not expose the note author through standard
    `<meta name="author">`; it stores the note owner inside script state as
    `note.user.nickname`.
    """

    patterns = [
        re.compile(r'"note"\s*:\s*\{.*?"user"\s*:\s*\{[^{}]*?"nickname"\s*:\s*"((?:\\.|[^"\\]){1,160})"', re.DOTALL),
        re.compile(r'"user"\s*:\s*\{[^{}]*?"nickname"\s*:\s*"((?:\\.|[^"\\]){1,160})"', re.DOTALL),
    ]
    for pattern in patterns:
        match = pattern.search(html or "")
        if match:
            author = _decode_json_string(match.group(1))
            if author:
                return author[:120]
    return ""


def extract_page_metadata(html: str, *, base_url: str | None = None) -> dict[str, str]:
    soup = BeautifulSoup(html or "", "html.parser")
    title = ""
    if soup.title and soup.title.string:
        title = soup.title.string.strip()
    og_title = _first_meta_content(soup, [{"property": "og:title"}, {"name": "og:title"}, {"name": "twitter:title"}])
    description = _first_meta_content(
        soup,
        [
            {"name": "description"},
            {"property": "og:description"},
            {"name": "og:description"},
            {"name": "twitter:description"},
        ],
    )
    author = _first_meta_content(soup, [{"name": "author"}, {"property": "article:author"}]) or _extract_xhs_author(html or "")
    canonical = ""
    canonical_tag = soup.find("link", attrs={"rel": "canonical"})
    if canonical_tag and canonical_tag.get("href"):
        canonical = str(canonical_tag.get("href", "")).strip()
        if base_url:
            canonical = urljoin(base_url, canonical)
    return {
        "title": og_title or title,
        "description": description,
        "author": author,
        "canonical_url": canonical,
    }


def _normalize_image_url(raw_url: str, base_url: str | None) -> str | None:
    url = unescape(raw_url or "").replace("\\u002F", "/").replace("\\/", "/").strip().strip("\"'")
    if not url or url.startswith("data:") or url.startswith("blob:"):
        return None
    if url.startswith("//"):
        url = "https:" + url
    elif base_url:
        url = urljoin(base_url, url)
    parsed = urlparse(url)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        return None
    return url


def _is_undesired_image_url(url: str) -> bool:
    """Filter known non-primary Rednote image variants.

    Rednote embeds both full/default images and preview placeholders for the
    same asset. Preview URLs contain markers such as `!nd_prv_...`; they decode
    as valid JPEGs but are tiny/blurred placeholder variants, which look
    corrupted in Obsidian. Avatars are also page chrome, not post content.
    """

    lower = url.lower()
    if "sns-avatar" in lower:
        return True
    if "!nd_prv_" in lower or "_prv_" in lower:
        return True
    return False


def _srcset_urls(srcset: str) -> Iterable[str]:
    for item in srcset.split(","):
        candidate = item.strip().split(" ", 1)[0]
        if candidate:
            yield candidate


def extract_image_candidates(html: str, *, base_url: str | None = None, max_images: int = 50) -> list[ImageCandidate]:
    soup = BeautifulSoup(html or "", "html.parser")
    candidates: list[ImageCandidate] = []
    seen: set[str] = set()

    def add(raw_url: str, source: str, alt: str = "") -> None:
        if len(candidates) >= max_images:
            return
        normalized = _normalize_image_url(raw_url, base_url)
        if not normalized or _is_undesired_image_url(normalized) or normalized in seen:
            return
        seen.add(normalized)
        candidates.append(ImageCandidate(url=normalized, source=source, alt=alt.strip()))

    for value in _meta_contents(
        soup,
        (
            {"property": "og:image"},
            {"name": "og:image"},
            {"property": "og:image:secure_url"},
            {"name": "og:image:secure_url"},
            {"name": "twitter:image"},
        ),
    ):
        add(value, "meta")

    for tag in soup.find_all(["img", "source"]):
        alt = str(tag.get("alt", "") or "")
        for attr in ("src", "data-src", "data-original", "data-lazy-src"):
            value = tag.get(attr)
            if value:
                add(str(value), f"{tag.name}.{attr}", alt=alt)
        srcset = tag.get("srcset")
        if srcset:
            for url in _srcset_urls(str(srcset)):
                add(url, f"{tag.name}.srcset", alt=alt)

    searchable_html = (html or "").replace("\\u002F", "/").replace("\\/", "/")
    for regex in (IMAGE_URL_RE, XHS_CDN_URL_RE):
        for match in regex.finditer(searchable_html):
            add(match.group(0), "html-regex")

    return candidates


def extract_video_candidates(html: str, *, base_url: str | None = None, max_videos: int = 5) -> list[VideoCandidate]:
    soup = BeautifulSoup(html or "", "html.parser")
    candidates: list[VideoCandidate] = []
    seen: set[str] = set()
    seen_paths: set[str] = set()

    def add(raw_url: str, source: str) -> None:
        if len(candidates) >= max_videos:
            return
        normalized = _normalize_image_url(raw_url, base_url)
        if not normalized or normalized in seen:
            return
        lower = normalized.lower()
        if not (".mp4" in lower or ".m3u8" in lower):
            return
        path_key = urlparse(normalized).path.lower()
        if path_key in seen_paths:
            return
        seen.add(normalized)
        seen_paths.add(path_key)
        candidates.append(VideoCandidate(url=normalized, source=source))

    for value in _meta_contents(
        soup,
        (
            {"property": "og:video"},
            {"name": "og:video"},
            {"property": "og:video:url"},
            {"name": "og:video:url"},
            {"property": "og:video:secure_url"},
            {"name": "og:video:secure_url"},
            {"name": "twitter:player:stream"},
        ),
    ):
        add(value, "meta")

    searchable_html = (html or "").replace("\\u002F", "/").replace("\\/", "/")
    for match in VIDEO_URL_RE.finditer(searchable_html):
        add(match.group(0), "html-regex")

    return candidates


def download_image(
    url: str,
    *,
    cookie: str = "",
    user_agent: str = "",
    referer: str | None = None,
    timeout_seconds: float = 20.0,
    max_bytes: int = 10 * 1024 * 1024,
) -> ImageFetchResult:
    try:
        headers = _default_headers(cookie=cookie, user_agent=user_agent, referer=referer, accept="image/avif,image/webp,image/apng,image/svg+xml,image/*,*/*;q=0.8")
        with httpx.Client(timeout=timeout_seconds, follow_redirects=True, headers=headers) as client:
            with client.stream("GET", url) as response:
                content, truncated = _read_response_content(response, max_bytes=max_bytes)
                content_type = response.headers.get("content-type", "").split(";", 1)[0].strip().lower()
                error = None
                if response.status_code >= 400:
                    error = f"HTTP {response.status_code}"
                elif truncated:
                    error = f"Image exceeded MAX_IMAGE_BYTES={max_bytes}"
                sniffed_type = sniff_image_content_type(content)
                if not error and not (content_type.startswith("image/") or sniffed_type):
                    error = f"Response is not an image: content-type={content_type or 'unknown'}"
                if not content_type and sniffed_type:
                    content_type = sniffed_type
                return ImageFetchResult(
                    url=url,
                    final_url=str(response.url),
                    status_code=response.status_code,
                    headers=dict(response.headers),
                    content=content if not truncated else b"",
                    content_type=content_type,
                    error=error,
                    truncated=truncated,
                )
    except Exception as exc:
        return ImageFetchResult(
            url=url,
            final_url=None,
            status_code=None,
            headers={},
            content=b"",
            content_type="",
            error=f"{type(exc).__name__}: {exc}",
        )


def download_video(
    url: str,
    *,
    cookie: str = "",
    user_agent: str = "",
    referer: str | None = None,
    timeout_seconds: float = 30.0,
    max_bytes: int = 200 * 1024 * 1024,
) -> VideoFetchResult:
    try:
        headers = _default_headers(cookie=cookie, user_agent=user_agent, referer=referer, accept="video/mp4,application/vnd.apple.mpegurl,application/x-mpegURL,video/*,*/*;q=0.8")
        with httpx.Client(timeout=timeout_seconds, follow_redirects=True, headers=headers) as client:
            with client.stream("GET", url) as response:
                content, truncated = _read_response_content(response, max_bytes=max_bytes)
                content_type = response.headers.get("content-type", "").split(";", 1)[0].strip().lower()
                error = None
                if response.status_code >= 400:
                    error = f"HTTP {response.status_code}"
                elif truncated:
                    error = f"Video exceeded MAX_VIDEO_BYTES={max_bytes}"
                sniffed_type = sniff_video_content_type(content)
                if not error and not (content_type.startswith("video/") or "mpegurl" in content_type or sniffed_type):
                    error = f"Response is not a video: content-type={content_type or 'unknown'}"
                if not content_type and sniffed_type:
                    content_type = sniffed_type
                return VideoFetchResult(
                    url=url,
                    final_url=str(response.url),
                    status_code=response.status_code,
                    headers=dict(response.headers),
                    content=content if not truncated else b"",
                    content_type=content_type,
                    error=error,
                    truncated=truncated,
                )
    except Exception as exc:
        return VideoFetchResult(
            url=url,
            final_url=None,
            status_code=None,
            headers={},
            content=b"",
            content_type="",
            error=f"{type(exc).__name__}: {exc}",
        )


def extract_public_page_text(url: str | None, *, max_chars: int = 12_000, timeout_seconds: float = 8.0) -> str:
    """Best-effort public page extraction.

    This intentionally does not bypass login, anti-bot, app signatures, or paywalls.
    Rednote/Xiaohongshu pages often restrict content; share text and screenshots are
    therefore first-class fallbacks in the pipeline.
    """

    if not url:
        return ""

    try:
        headers = {
            "User-Agent": (
                "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0 Safari/537.36"
            ),
            "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
        }
        with httpx.Client(timeout=timeout_seconds, follow_redirects=True, headers=headers) as client:
            response = client.get(url)
        if response.status_code >= 400:
            return f"Fetch status: {response.status_code}"

        soup = BeautifulSoup(response.text, "html.parser")
        for tag in soup(["script", "style", "noscript", "svg"]):
            tag.decompose()

        title = ""
        if soup.title and soup.title.string:
            title = soup.title.string.strip()
        og_title = _first_meta_content(soup, [{"property": "og:title"}, {"name": "twitter:title"}])
        description = _first_meta_content(
            soup,
            [
                {"name": "description"},
                {"property": "og:description"},
                {"name": "twitter:description"},
            ],
        )
        body_text = soup.get_text("\n", strip=True)
        body_text = re.sub(r"\n{3,}", "\n\n", unescape(body_text))

        sections = [
            f"URL: {url}",
            f"Title: {og_title or title}",
            f"Description: {description}",
            "Body:",
            body_text,
        ]
        return "\n".join(part for part in sections if part).strip()[:max_chars]
    except Exception as exc:  # best-effort fallback; worker still has share text/screenshot
        return f"Extraction failed: {type(exc).__name__}: {exc}"
