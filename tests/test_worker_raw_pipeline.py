import json

from rednote_sync_obsidian import worker
from rednote_sync_obsidian.config import Settings
from rednote_sync_obsidian.extractor import ImageFetchResult, PageFetchResult, VideoFetchResult
from rednote_sync_obsidian.raw_storage import RawBundleStorage


def test_process_job_writes_raw_bundle(monkeypatch, tmp_path):
    html = b"""
    <html>
      <head>
        <meta property="og:title" content="Raw Title">
        <meta name="description" content="Raw description">
      </head>
      <body>
        <img src="https://cdn.example.com/a.jpg">
        <script>{"video":"https:\\u002F\\u002Fsns-video-qc.xhscdn.com\\u002Fstream\\u002Fa\\u002Fvideo.mp4?sign=abc"}</script>
      </body>
    </html>
    """

    def fake_fetch_page(*_args, **_kwargs):
        return PageFetchResult(
            requested_url="https://www.xiaohongshu.com/explore/abc",
            final_url="https://www.xiaohongshu.com/explore/abc",
            status_code=200,
            headers={"content-type": "text/html", "set-cookie": "secret"},
            content=html,
            text=html.decode("utf-8"),
        )

    def fake_download_image(url, **_kwargs):
        return ImageFetchResult(
            url=url,
            final_url=url,
            status_code=200,
            headers={"content-type": "image/jpeg"},
            content=b"fake-image",
            content_type="image/jpeg",
        )

    def fake_download_video(url, **_kwargs):
        return VideoFetchResult(
            url=url,
            final_url=url,
            status_code=200,
            headers={"content-type": "video/mp4"},
            content=b"fake-video",
            content_type="video/mp4",
        )

    monkeypatch.setattr(worker, "fetch_page", fake_fetch_page)
    monkeypatch.setattr(worker, "download_image", fake_download_image)
    monkeypatch.setattr(worker, "download_video", fake_download_video)

    settings = Settings(redis_url="redis://test", raw_storage_root=str(tmp_path), crawl_cookie="cookie")
    job = {
        "job_id": "xhs_abc123",
        "platform": "xiaohongshu",
        "url": "https://www.xiaohongshu.com/explore/abc",
        "share_text": "share",
        "user_note": "note",
        "captured_at": "2026-05-16T00:00:00+00:00",
        "queued_at": "2026-05-16T00:00:01+00:00",
        "schema_version": 1,
    }

    bundle_path = worker.process_job(job, settings=settings, storage=RawBundleStorage(tmp_path))
    manifest = json.loads((tmp_path / "posts/2026/05/16/xhs_abc123/manifest.json").read_text())
    headers = json.loads((tmp_path / "posts/2026/05/16/xhs_abc123/response_headers.json").read_text())

    assert bundle_path.endswith("posts/2026/05/16/xhs_abc123")
    assert (tmp_path / "posts/2026/05/16/xhs_abc123/source.html").read_bytes() == html
    assert (tmp_path / "posts/2026/05/16/xhs_abc123/images/001.jpg").read_bytes() == b"fake-image"
    assert (tmp_path / "posts/2026/05/16/xhs_abc123/videos/001.mp4").read_bytes() == b"fake-video"
    assert (tmp_path / "posts/2026/05/16/xhs_abc123/index.md").exists()
    assert manifest["status"] == "complete"
    assert manifest["page"]["title"] == "Raw Title"
    assert manifest["images"][0]["sha256"]
    assert manifest["videos"][0]["sha256"]
    assert headers["set-cookie"] == "<redacted>"
