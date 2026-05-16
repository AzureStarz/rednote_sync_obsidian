import json

import pytest

from rednote_sync_obsidian.security import load_capture_users, resolve_capture_user, validate_owner_id


def test_load_capture_users_validates_and_returns_users(tmp_path):
    users_file = tmp_path / "capture_users.json"
    users_file.write_text(
        json.dumps(
            {
                "hongbin": {"display_name": "Hongbin", "token": "hongbin-token"},
                "zhangyu": {"display_name": "Zhangyu", "token": "zhangyu-token"},
            }
        )
    )

    users = load_capture_users(users_file)

    assert users["hongbin"].display_name == "Hongbin"
    assert users["zhangyu"].token == "zhangyu-token"


def test_resolve_capture_user_from_users_file(tmp_path):
    users_file = tmp_path / "capture_users.json"
    users_file.write_text(json.dumps({"hongbin": {"display_name": "Hongbin", "token": "hongbin-token"}}))

    assert resolve_capture_user("wrong", users_file=str(users_file)) is None
    assert resolve_capture_user(None, users_file=str(users_file)) is None
    user = resolve_capture_user("hongbin-token", users_file=str(users_file))
    assert user is not None
    assert user.owner_id == "hongbin"


def test_resolve_capture_user_falls_back_to_single_token():
    user = resolve_capture_user("secret", fallback_token="secret")

    assert user is not None
    assert user.owner_id == "default"
    assert resolve_capture_user("wrong", fallback_token="secret") is None


def test_capture_users_reject_duplicate_tokens(tmp_path):
    users_file = tmp_path / "capture_users.json"
    users_file.write_text(json.dumps({"hongbin": {"token": "same"}, "zhangyu": {"token": "same"}}))

    with pytest.raises(RuntimeError, match="duplicate tokens"):
        load_capture_users(users_file)


def test_validate_owner_id_rejects_path_like_values():
    assert validate_owner_id("hongbin") == "hongbin"
    with pytest.raises(ValueError):
        validate_owner_id("../zhangyu")
