from rednote_sync_obsidian.raw_storage import RawBundleStorage, build_raw_index_markdown, extension_for_image, extension_for_video, redact_headers


def test_raw_bundle_storage_commits_atomically(tmp_path):
    storage = RawBundleStorage(tmp_path)
    job = {"job_id": "xhs_abc123", "captured_at": "2026-05-16T10:00:00+09:00"}
    staging = storage.create_staging_dir(job["job_id"])
    stored = storage.write_bytes(staging, "source.html", b"<html></html>")
    final_dir = storage.commit(staging, job)

    assert not staging.exists()
    assert (final_dir / "source.html").read_bytes() == b"<html></html>"
    assert stored.bytes == len(b"<html></html>")
    assert len(stored.sha256) == 64
    assert final_dir.relative_to(tmp_path).as_posix() == "posts/2026/05/16/xhs_abc123"


def test_redact_headers_removes_cookies():
    assert redact_headers({"Set-Cookie": "secret", "Content-Type": "text/html"}) == {
        "Set-Cookie": "<redacted>",
        "Content-Type": "text/html",
    }


def test_build_raw_index_markdown_links_raw_files():
    job = {"job_id": "xhs_abc", "captured_at": "2026-05-16T00:00:00+00:00", "share_text": "分享文本"}
    manifest = {
        "schema_version": 2,
        "status": "complete",
        "source_url": "https://example.com",
        "final_url": "https://example.com/final",
        "http": {"status_code": 200},
        "page": {"title": "标题", "description": "描述", "author": ""},
        "images": [{"status": "downloaded", "path": "images/001.jpg"}],
        "videos": [{"status": "downloaded", "path": "videos/001.mp4"}],
    }

    md = build_raw_index_markdown(job, manifest)

    assert "# 标题" in md
    assert "[[source.html]]" in md
    assert "![[images/001.jpg]]" in md
    assert "![[videos/001.mp4]]" in md


def test_extension_for_image_prefers_content_type():
    assert extension_for_image(content_type="image/webp", url="https://example.com/a.jpg") == ".webp"
    assert extension_for_image(content_type="", url="https://example.com/a.jpeg") == ".jpg"


def test_extension_for_video_prefers_content_type():
    assert extension_for_video(content_type="video/mp4", url="https://example.com/a.bin") == ".mp4"
    assert extension_for_video(content_type="", url="https://example.com/a.m3u8") == ".m3u8"
