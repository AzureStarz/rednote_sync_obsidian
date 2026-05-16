#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "src"))

from rednote_sync_obsidian.config import Settings  # noqa: E402
from rednote_sync_obsidian.extractor import download_image, download_video, extract_image_candidates, extract_page_metadata, extract_video_candidates  # noqa: E402
from rednote_sync_obsidian.raw_storage import build_raw_index_markdown, extension_for_image, extension_for_video, sha256_bytes  # noqa: E402


def _write_json(path: Path, data: Any) -> None:
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2, sort_keys=True) + "\n")


def _file_record(path: Path, relative_path: str) -> dict[str, Any]:
    content = path.read_bytes()
    return {"path": relative_path, "bytes": len(content), "sha256": sha256_bytes(content)}


def _next_image_index(bundle: Path) -> int:
    existing = []
    for path in (bundle / "images").glob("[0-9][0-9][0-9].*"):
        try:
            existing.append(int(path.stem))
        except ValueError:
            pass
    return max(existing, default=0) + 1


def _next_video_index(bundle: Path) -> int:
    existing = []
    for path in (bundle / "videos").glob("[0-9][0-9][0-9].*"):
        try:
            existing.append(int(path.stem))
        except ValueError:
            pass
    return max(existing, default=0) + 1


def backfill_bundle(
    bundle: Path,
    *,
    settings: Settings,
    max_images: int | None = None,
    max_videos: int | None = None,
    rebuild_images: bool = False,
    rebuild_videos: bool = False,
) -> dict[str, Any]:
    manifest_path = bundle / "manifest.json"
    request_path = bundle / "request.json"
    html_path = bundle / "source.html"
    if not manifest_path.exists() or not html_path.exists():
        return {"bundle": str(bundle), "status": "skipped", "reason": "missing manifest.json or source.html"}

    manifest = json.loads(manifest_path.read_text())
    request = json.loads(request_path.read_text()) if request_path.exists() else {"job_id": manifest.get("job_id")}
    html = html_path.read_text(errors="replace")
    base_url = manifest.get("final_url") or manifest.get("source_url")
    manifest["page"] = extract_page_metadata(html, base_url=base_url)
    candidates = extract_image_candidates(
        html,
        base_url=base_url,
        max_images=max_images or settings.max_images_per_post,
    )
    video_candidates = extract_video_candidates(
        html,
        base_url=base_url,
        max_videos=max_videos or settings.max_videos_per_post,
    )

    image_records = [dict(item) for item in manifest.get("images", [])]
    image_dir = bundle / "images"
    image_dir.mkdir(exist_ok=True)
    if rebuild_images:
        kept_records: list[dict[str, Any]] = []
        for item in image_records:
            source = str(item.get("source") or "")
            path = item.get("path")
            if source.startswith("capture."):
                kept_records.append(item)
                continue
            if path:
                try:
                    (bundle / path).unlink()
                except FileNotFoundError:
                    pass
        image_records = kept_records
    existing_urls = {item.get("url") for item in image_records if item.get("url")}
    next_index = _next_image_index(bundle)
    added = 0

    for candidate in candidates:
        if candidate.url in existing_urls:
            continue
        result = download_image(
            candidate.url,
            cookie=settings.crawl_cookie,
            user_agent=settings.crawl_user_agent,
            referer=base_url,
            timeout_seconds=settings.crawl_timeout_seconds,
            max_bytes=settings.max_image_bytes,
        )
        record: dict[str, Any] = {
            "status": "failed",
            "source": candidate.source,
            "alt": candidate.alt,
            "url": candidate.url,
            "final_url": result.final_url,
            "status_code": result.status_code,
            "path": None,
            "bytes": 0,
            "sha256": None,
            "content_type": result.content_type,
            "truncated": result.truncated,
            "error": result.error,
        }
        if result.content and result.error is None:
            ext = extension_for_image(content_type=result.content_type, url=result.final_url or candidate.url)
            relative_path = f"images/{next_index:03d}{ext}"
            next_index += 1
            image_path = bundle / relative_path
            image_path.write_bytes(result.content)
            record.update(
                {
                    "status": "downloaded",
                    "path": relative_path,
                    "bytes": len(result.content),
                    "sha256": sha256_bytes(result.content),
                    "error": None,
                }
            )
            added += 1
        image_records.append(record)
        existing_urls.add(candidate.url)

    video_records = [dict(item) for item in manifest.get("videos", [])]
    video_dir = bundle / "videos"
    video_dir.mkdir(exist_ok=True)
    if rebuild_videos:
        for item in video_records:
            path = item.get("path")
            if path:
                try:
                    (bundle / path).unlink()
                except FileNotFoundError:
                    pass
        video_records = []
    existing_video_urls = {item.get("url") for item in video_records if item.get("url")}
    next_video_index = _next_video_index(bundle)
    added_videos = 0
    for candidate in video_candidates:
        if candidate.url in existing_video_urls:
            continue
        result = download_video(
            candidate.url,
            cookie=settings.crawl_cookie,
            user_agent=settings.crawl_user_agent,
            referer=base_url,
            timeout_seconds=settings.crawl_timeout_seconds,
            max_bytes=settings.max_video_bytes,
        )
        record = {
            "status": "failed",
            "source": candidate.source,
            "url": candidate.url,
            "final_url": result.final_url,
            "status_code": result.status_code,
            "path": None,
            "bytes": 0,
            "sha256": None,
            "content_type": result.content_type,
            "truncated": result.truncated,
            "error": result.error,
        }
        if result.content and result.error is None:
            ext = extension_for_video(content_type=result.content_type, url=result.final_url or candidate.url)
            relative_path = f"videos/{next_video_index:03d}{ext}"
            next_video_index += 1
            video_path = bundle / relative_path
            video_path.write_bytes(result.content)
            record.update(
                {
                    "status": "downloaded",
                    "path": relative_path,
                    "bytes": len(result.content),
                    "sha256": sha256_bytes(result.content),
                    "error": None,
                }
            )
            added_videos += 1
        video_records.append(record)
        existing_video_urls.add(candidate.url)

    downloaded_count = sum(1 for item in image_records if item.get("status") == "downloaded")
    failed_count = sum(1 for item in image_records if item.get("status") != "downloaded")
    downloaded_video_count = sum(1 for item in video_records if item.get("status") == "downloaded")
    failed_video_count = sum(1 for item in video_records if item.get("status") != "downloaded")
    manifest["images"] = image_records
    manifest["videos"] = video_records
    if manifest.get("http", {}).get("html_bytes", 0) and not manifest.get("http", {}).get("error") and failed_count == 0 and failed_video_count == 0:
        manifest["status"] = "complete"
    elif manifest.get("http", {}).get("html_bytes", 0) or downloaded_count or downloaded_video_count:
        manifest["status"] = "partial"
    else:
        manifest["status"] = "failed"

    report = {
        "status": "backfilled",
        "page_error": manifest.get("http", {}).get("error"),
        "candidate_count": len(candidates),
        "downloaded_count": downloaded_count,
        "failed_count": failed_count,
        "video_candidate_count": len(video_candidates),
        "downloaded_video_count": downloaded_video_count,
        "failed_video_count": failed_video_count,
        "added_count": added,
        "added_video_count": added_videos,
        "download_images": True,
        "download_videos": True,
    }
    report_path = bundle / "extraction_report.json"
    _write_json(report_path, report)
    manifest.setdefault("files", {})["extraction_report"] = _file_record(report_path, "extraction_report.json")

    index_path = bundle / "index.md"
    index_path.write_text(build_raw_index_markdown(request, manifest))
    manifest["files"]["index"] = _file_record(index_path, "index.md")

    _write_json(manifest_path, manifest)
    manifest["files"]["manifest"] = _file_record(manifest_path, "manifest.json")
    _write_json(manifest_path, manifest)

    return {
        "bundle": str(bundle),
        "status": "updated",
        "candidates": len(candidates),
        "downloaded": downloaded_count,
        "failed": failed_count,
        "added": added,
        "video_candidates": len(video_candidates),
        "videos_downloaded": downloaded_video_count,
        "videos_failed": failed_video_count,
        "videos_added": added_videos,
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Backfill image/video downloads for existing raw Rednote bundles.")
    parser.add_argument("--root", default=None, help="Raw storage root. Defaults to RAW_STORAGE_ROOT from .env.")
    parser.add_argument("--bundle", action="append", help="Specific bundle directory to backfill. Can be repeated.")
    parser.add_argument("--max-images", type=int, default=None, help="Override MAX_IMAGES_PER_POST for this run.")
    parser.add_argument("--max-videos", type=int, default=None, help="Override MAX_VIDEOS_PER_POST for this run.")
    parser.add_argument(
        "--rebuild-images",
        action="store_true",
        help="Delete existing downloaded page images and rebuild them from source.html. Attached screenshots are kept.",
    )
    parser.add_argument(
        "--rebuild-videos",
        action="store_true",
        help="Delete existing downloaded videos and rebuild them from source.html.",
    )
    return parser.parse_args()


def discover_bundles(root: str | Path) -> list[Path]:
    root_path = Path(root)
    bundles = list(root_path.glob("users/*/posts/*/*/*/*"))
    bundles.extend(root_path.glob("posts/*/*/*/*"))  # legacy pre-user-namespace layout
    return sorted(path for path in bundles if path.is_dir())


def main() -> int:
    args = parse_args()
    settings = Settings.from_env()
    if args.root:
        settings = Settings(**{**settings.__dict__, "raw_storage_root": args.root})
    bundles = [Path(item) for item in args.bundle] if args.bundle else discover_bundles(settings.raw_storage_root)
    for bundle in bundles:
        result = backfill_bundle(
            bundle,
            settings=settings,
            max_images=args.max_images,
            max_videos=args.max_videos,
            rebuild_images=args.rebuild_images,
            rebuild_videos=args.rebuild_videos,
        )
        print(json.dumps(result, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
