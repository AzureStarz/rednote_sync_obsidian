import base64

import pytest

from rednote_sync_obsidian.config import Settings
from rednote_sync_obsidian.jobs import build_job, clean_base64_image
from rednote_sync_obsidian.models import CaptureRequest
from rednote_sync_obsidian.security import CaptureUser, build_dedupe_key


def test_clean_base64_image_accepts_data_url():
    raw = base64.b64encode(b"fake-jpeg").decode("ascii")
    normalized, data = clean_base64_image(f"data:image/jpeg;base64,{raw}", max_bytes=100)
    assert normalized == raw
    assert data == b"fake-jpeg"


def test_clean_base64_image_rejects_large_image():
    raw = base64.b64encode(b"0123456789").decode("ascii")
    with pytest.raises(ValueError, match="too large"):
        clean_base64_image(raw, max_bytes=3)


def test_build_job_requires_some_content():
    with pytest.raises(ValueError, match="At least one"):
        build_job(CaptureRequest(), Settings())


def test_dedupe_key_is_stable_for_same_content():
    settings = Settings()
    payload = CaptureRequest(url="https://example.com/a", share_text="hello")
    job1 = build_job(payload, settings)
    job2 = dict(job1)
    job2["job_id"] = "xhs_other"
    assert build_dedupe_key(job1) == build_dedupe_key(job2)


def test_build_job_records_owner_without_token():
    settings = Settings()
    owner = CaptureUser(owner_id="hongbin", display_name="Hongbin", token="secret-token")
    job = build_job(CaptureRequest(url="https://example.com/a"), settings, owner=owner)

    assert job["owner_id"] == "hongbin"
    assert job["owner_display_name"] == "Hongbin"
    assert "secret-token" not in str(job)


def test_dedupe_key_is_isolated_by_owner():
    settings = Settings()
    payload = CaptureRequest(url="https://example.com/a", share_text="hello")
    hongbin_job = build_job(payload, settings, owner=CaptureUser("hongbin", "Hongbin", "a"))
    zhangyu_job = build_job(payload, settings, owner=CaptureUser("zhangyu", "Zhangyu", "b"))

    assert build_dedupe_key(hongbin_job) != build_dedupe_key(zhangyu_job)
