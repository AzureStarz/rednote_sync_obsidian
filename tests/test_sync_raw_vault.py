import hashlib
import json

from scripts.sync_raw_vault import build_remote_prune_command, build_rsync_command, owner_remote_root, verify_local_vault


def test_build_rsync_command_defaults_to_non_destructive_sync():
    cmd = build_rsync_command(
        server="user@example.com",
        remote_root="/data/rednote_raw",
        local_vault="~/Documents/raw_rednote_post_vault",
    )

    assert cmd[:2] == ["rsync", "-az"]
    assert "--delete" not in cmd
    assert "--dry-run" not in cmd
    assert ".tmp/" in cmd
    assert cmd[-2] == "user@example.com:/data/rednote_raw/"
    assert cmd[-1].endswith("/Documents/raw_rednote_post_vault/")


def test_build_rsync_command_supports_dry_run_prune_and_port():
    cmd = build_rsync_command(
        server="user@example.com",
        remote_root="/data/rednote_raw/",
        local_vault="/tmp/raw",
        ssh_port=2222,
        dry_run=True,
        prune=True,
        verbose=True,
    )

    assert "--dry-run" in cmd
    assert "--delete" in cmd
    assert ["-e", "ssh -p 2222"] == cmd[cmd.index("-e") : cmd.index("-e") + 2]
    assert "--info=stats2,progress2" in cmd


def test_build_remote_prune_command_can_target_one_owner():
    cmd = build_remote_prune_command(
        server="user@example.com",
        remote_root="/data/rednote_raw",
        days=30,
        owner="zhangyu",
    )

    assert "/data/rednote_raw/users/zhangyu" in cmd


def test_build_rsync_command_can_sync_one_owner():
    cmd = build_rsync_command(
        server="user@example.com",
        remote_root="/data/rednote_raw",
        owner="hongbin",
        local_vault="/tmp/raw",
    )

    assert cmd[-2] == "user@example.com:/data/rednote_raw/users/hongbin/"


def test_verify_local_vault_checks_manifest_hashes(tmp_path):
    bundle = tmp_path / "posts/2026/05/16/xhs_abc"
    bundle.mkdir(parents=True)
    source = bundle / "source.html"
    source.write_bytes(b"<html>ok</html>")
    image = bundle / "images/001.jpg"
    image.parent.mkdir()
    image.write_bytes(b"fake-image")
    manifest = {
        "files": {
            "source_html": {
                "path": "source.html",
                "bytes": source.stat().st_size,
                "sha256": hashlib.sha256(source.read_bytes()).hexdigest(),
            }
        },
        "images": [
            {
                "status": "downloaded",
                "path": "images/001.jpg",
                "bytes": image.stat().st_size,
                "sha256": hashlib.sha256(image.read_bytes()).hexdigest(),
            }
        ],
        "videos": [],
    }
    (bundle / "manifest.json").write_text(json.dumps(manifest))

    result = verify_local_vault(tmp_path)

    assert result.ok
    assert result.checked_bundles == 1
    assert result.checked_files == 2


def test_verify_local_vault_reports_hash_mismatch(tmp_path):
    bundle = tmp_path / "posts/2026/05/16/xhs_abc"
    bundle.mkdir(parents=True)
    source = bundle / "source.html"
    source.write_bytes(b"changed")
    (bundle / "manifest.json").write_text(
        json.dumps({"files": {"source_html": {"path": "source.html", "sha256": "0" * 64}}, "images": [], "videos": []})
    )

    result = verify_local_vault(tmp_path)

    assert not result.ok
    assert "sha256 mismatch" in result.errors[0]


def test_build_remote_prune_command_uses_ssh_and_dry_run():
    cmd = build_remote_prune_command(
        server="user@example.com",
        remote_root="/data/rednote_raw",
        days=30,
        ssh_port=2222,
        dry_run=True,
        remote_sudo=True,
    )

    assert cmd[:4] == ["ssh", "-p", "2222", "user@example.com"]
    assert "sudo" in cmd
    assert "--root" in cmd
    assert "/data/rednote_raw" in cmd
    assert "--days" in cmd
    assert "30" in cmd
    assert "--dry-run" in cmd


def test_owner_remote_root_rejects_path_traversal():
    assert owner_remote_root("/data/rednote_raw", "zhangyu") == "/data/rednote_raw/users/zhangyu"
    try:
        owner_remote_root("/data/rednote_raw", "../zhangyu")
    except ValueError as exc:
        assert "owner must match" in str(exc)
    else:
        raise AssertionError("path-like owner should be rejected")
