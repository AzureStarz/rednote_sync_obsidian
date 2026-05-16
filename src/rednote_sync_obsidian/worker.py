from __future__ import annotations

import json
import logging
import traceback
from typing import Any

from .config import Settings, get_settings
from .extractor import (
    download_image,
    download_video,
    extract_image_candidates,
    extract_page_metadata,
    extract_url_from_text,
    extract_video_candidates,
    fetch_page,
)
from .jobs import deserialize_job, redacted_job, serialize_job
from .queue import create_redis_client, enqueue_failed
from .raw_storage import (
    RawBundleStorage,
    build_capture_request_record,
    build_raw_index_markdown,
    decode_screenshot_b64,
    extension_for_image,
    extension_for_video,
    redact_headers,
    utc_now_iso,
)

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
logger = logging.getLogger("rednote_sync_obsidian.worker")


def _bundle_status(*, page_error: str | None, html_bytes: int, image_records: list[dict[str, Any]], video_records: list[dict[str, Any]] | None = None) -> str:
    video_records = video_records or []
    downloaded_images = sum(1 for item in image_records if item.get("status") == "downloaded")
    downloaded_videos = sum(1 for item in video_records if item.get("status") == "downloaded")
    failed_media = sum(1 for item in [*image_records, *video_records] if item.get("status") != "downloaded")
    if html_bytes and not page_error and not failed_media:
        return "complete"
    if html_bytes or downloaded_images or downloaded_videos:
        return "partial"
    return "failed"


def _write_error_bundle(job: dict[str, Any], *, settings: Settings, storage: RawBundleStorage, error: str, tb: str) -> str | None:
    staging = storage.create_staging_dir(str(job.get("job_id") or "xhs_failed"))
    try:
        request_file = storage.write_json(
            staging,
            "request.json",
            build_capture_request_record(job, has_crawl_cookie=bool(settings.crawl_cookie)),
        )
        report = {
            "status": "failed",
            "error": error,
            "traceback": tb,
            "processed_at": utc_now_iso(),
            "candidate_count": 0,
            "downloaded_count": 0,
            "failed_count": 0,
        }
        report_file = storage.write_json(staging, "extraction_report.json", report)
        manifest = {
            "schema_version": 2,
            "job_id": job.get("job_id"),
            "owner_id": job.get("owner_id") or "default",
            "owner_display_name": job.get("owner_display_name") or "Default",
            "platform": job.get("platform"),
            "status": "failed",
            "source_url": job.get("url"),
            "final_url": None,
            "captured_at": job.get("captured_at"),
            "queued_at": job.get("queued_at"),
            "processed_at": utc_now_iso(),
            "http": {"status_code": None, "error": error, "html_bytes": 0, "truncated": False},
            "page": {},
            "files": {
                "request": request_file.__dict__,
                "extraction_report": report_file.__dict__,
            },
            "images": [],
            "videos": [],
            "errors": [error],
        }
        if settings.raw_index_markdown:
            manifest["files"]["index"] = storage.write_text(staging, "index.md", build_raw_index_markdown(job, manifest)).__dict__
        storage.write_json(staging, "manifest.json", manifest)
        return str(storage.commit(staging, job))
    except Exception:
        storage.cleanup_staging_dir(staging)
        raise


def process_job(job: dict[str, Any], *, settings: Settings, storage: RawBundleStorage | None = None) -> str:
    if not job.get("url"):
        job["url"] = extract_url_from_text(job.get("share_text"))

    storage = storage or RawBundleStorage(settings.raw_storage_root)
    page = fetch_page(
        job.get("url"),
        cookie=settings.crawl_cookie,
        user_agent=settings.crawl_user_agent,
        timeout_seconds=settings.crawl_timeout_seconds,
        max_bytes=settings.max_html_bytes,
    )

    base_url = page.final_url or job.get("url")
    page_metadata = extract_page_metadata(page.text, base_url=base_url)
    candidates = (
        extract_image_candidates(page.text, base_url=base_url, max_images=settings.max_images_per_post)
        if settings.download_images and page.text
        else []
    )
    video_candidates = (
        extract_video_candidates(page.text, base_url=base_url, max_videos=settings.max_videos_per_post)
        if settings.download_videos and page.text
        else []
    )

    staging = storage.create_staging_dir(job["job_id"])
    try:
        files: dict[str, Any] = {}
        image_records: list[dict[str, Any]] = []
        video_records: list[dict[str, Any]] = []

        files["request"] = storage.write_json(
            staging,
            "request.json",
            build_capture_request_record(job, has_crawl_cookie=bool(settings.crawl_cookie)),
        ).__dict__
        files["response_headers"] = storage.write_json(
            staging,
            "response_headers.json",
            redact_headers(page.headers),
        ).__dict__
        files["source_html"] = storage.write_bytes(staging, "source.html", page.content).__dict__

        image_index = 1
        if job.get("screenshot_b64"):
            try:
                screenshot_bytes = decode_screenshot_b64(job["screenshot_b64"])
                relative_path = "images/screenshot.jpg"
                stored = storage.write_bytes(staging, relative_path, screenshot_bytes)
                image_records.append(
                    {
                        "status": "downloaded",
                        "source": "capture.screenshot_b64",
                        "url": None,
                        "final_url": None,
                        "path": relative_path,
                        "bytes": stored.bytes,
                        "sha256": stored.sha256,
                        "content_type": "image/jpeg",
                        "error": None,
                    }
                )
            except Exception as exc:
                image_records.append(
                    {
                        "status": "failed",
                        "source": "capture.screenshot_b64",
                        "url": None,
                        "final_url": None,
                        "path": None,
                        "bytes": 0,
                        "sha256": None,
                        "content_type": "",
                        "error": f"{type(exc).__name__}: {exc}",
                    }
                )

        for candidate in candidates:
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
                relative_path = f"images/{image_index:03d}{ext}"
                image_index += 1
                stored = storage.write_bytes(staging, relative_path, result.content)
                record.update(
                    {
                        "status": "downloaded",
                        "path": relative_path,
                        "bytes": stored.bytes,
                        "sha256": stored.sha256,
                        "error": None,
                    }
                )
            image_records.append(record)

        video_index = 1
        for candidate in video_candidates:
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
                relative_path = f"videos/{video_index:03d}{ext}"
                video_index += 1
                stored = storage.write_bytes(staging, relative_path, result.content)
                record.update(
                    {
                        "status": "downloaded",
                        "path": relative_path,
                        "bytes": stored.bytes,
                        "sha256": stored.sha256,
                        "error": None,
                    }
                )
            video_records.append(record)

        downloaded_count = sum(1 for item in image_records if item.get("status") == "downloaded")
        failed_count = sum(1 for item in image_records if item.get("status") != "downloaded")
        downloaded_video_count = sum(1 for item in video_records if item.get("status") == "downloaded")
        failed_video_count = sum(1 for item in video_records if item.get("status") != "downloaded")
        report = {
            "status": "processed",
            "page_error": page.error,
            "candidate_count": len(candidates),
            "downloaded_count": downloaded_count,
            "failed_count": failed_count,
            "video_candidate_count": len(video_candidates),
            "downloaded_video_count": downloaded_video_count,
            "failed_video_count": failed_video_count,
            "processed_at": utc_now_iso(),
            "download_images": settings.download_images,
            "download_videos": settings.download_videos,
        }
        files["extraction_report"] = storage.write_json(staging, "extraction_report.json", report).__dict__

        status = _bundle_status(page_error=page.error, html_bytes=len(page.content), image_records=image_records, video_records=video_records)
        manifest: dict[str, Any] = {
            "schema_version": 2,
            "job_id": job.get("job_id"),
            "owner_id": job.get("owner_id") or "default",
            "owner_display_name": job.get("owner_display_name") or "Default",
            "platform": job.get("platform"),
            "status": status,
            "source_url": job.get("url"),
            "final_url": page.final_url,
            "captured_at": job.get("captured_at"),
            "queued_at": job.get("queued_at"),
            "processed_at": utc_now_iso(),
            "http": {
                "status_code": page.status_code,
                "error": page.error,
                "html_bytes": len(page.content),
                "truncated": page.truncated,
                "content_type": page.headers.get("content-type", ""),
            },
            "page": page_metadata,
            "files": files,
            "images": image_records,
            "videos": video_records,
            "errors": [page.error] if page.error else [],
        }
        if settings.raw_index_markdown:
            files["index"] = storage.write_text(staging, "index.md", build_raw_index_markdown(job, manifest)).__dict__
        storage.write_json(staging, "manifest.json", manifest)
        final_dir = storage.commit(staging, job)
        return str(final_dir)
    except Exception:
        storage.cleanup_staging_dir(staging)
        raise


def run_worker(settings: Settings | None = None) -> None:
    settings = settings or get_settings()
    settings.require_worker()
    redis_client = create_redis_client(settings)
    storage = RawBundleStorage(settings.raw_storage_root)
    logger.info(
        "Worker started queue=%s failed_queue=%s raw_storage_root=%s",
        settings.queue_name,
        settings.failed_queue_name,
        settings.raw_storage_root,
    )

    while True:
        item = redis_client.brpop(settings.queue_name, timeout=5)
        if item is None:
            continue
        _queue_name, raw_job = item
        try:
            job = deserialize_job(raw_job)
            bundle_path = process_job(job, settings=settings, storage=storage)
            logger.info("Processed job_id=%s bundle_path=%s", job.get("job_id"), bundle_path)
        except Exception as exc:  # keep original data recoverable
            error = f"{type(exc).__name__}: {exc}"
            try:
                failed_job = deserialize_job(raw_job)
            except Exception:
                failed_job = {"raw_job": raw_job, "job_id": "unknown"}
            failed_job["status"] = "failed"
            failed_job["error"] = error
            failed_job["traceback"] = traceback.format_exc()
            enqueue_failed(redis_client, settings, serialize_job(failed_job))
            logger.exception("Failed job=%s", json.dumps(redacted_job(failed_job), ensure_ascii=False))
            try:
                failure_path = _write_error_bundle(
                    failed_job,
                    settings=settings,
                    storage=storage,
                    error=error,
                    tb=failed_job["traceback"],
                )
                if failure_path:
                    logger.info("Wrote failure bundle job_id=%s bundle_path=%s", failed_job.get("job_id"), failure_path)
            except Exception:
                logger.exception("Could not write failure bundle for job_id=%s", failed_job.get("job_id"))


if __name__ == "__main__":
    run_worker()
