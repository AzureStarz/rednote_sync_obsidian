from __future__ import annotations

import importlib.util
import json
import plistlib
from pathlib import Path

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "make_ios_shortcut.py"
spec = importlib.util.spec_from_file_location("make_ios_shortcut", SCRIPT)
make_ios_shortcut = importlib.util.module_from_spec(spec)
assert spec.loader is not None
spec.loader.exec_module(make_ios_shortcut)


def _dict_values(items: list[dict]) -> dict[str, str]:
    return {
        item["WFKey"]["Value"]["string"]: item["WFValue"]["Value"]["string"]
        for item in items
        if "string" in item["WFValue"]["Value"]
    }


def test_build_workflow_defaults_to_clipboard_input_for_xiaohongshu() -> None:
    workflow = make_ios_shortcut.build_workflow(
        endpoint="http://127.0.0.1:8080/capture",
        token="test-token",
        name="保存小红书原始帖子",
    )

    assert workflow["WFWorkflowTypes"] == ["ActionExtension"]
    assert "WFURLContentItem" in workflow["WFWorkflowInputContentItemClasses"]

    clipboard_action = workflow["WFWorkflowActions"][0]
    assert clipboard_action["WFWorkflowActionIdentifier"] == "is.workflow.actions.getclipboard"
    clipboard_uuid = clipboard_action["WFWorkflowActionParameters"]["UUID"]

    post_action = workflow["WFWorkflowActions"][1]
    params = post_action["WFWorkflowActionParameters"]
    assert post_action["WFWorkflowActionIdentifier"] == "is.workflow.actions.downloadurl"
    assert params["WFURL"] == "http://127.0.0.1:8080/capture"
    assert params["WFHTTPMethod"] == "POST"

    headers = params["WFHTTPHeaders"]["Value"]["WFDictionaryFieldValueItems"]
    header_values = _dict_values(headers)
    assert header_values["X-Capture-Token"] == "test-token"
    assert header_values["Content-Type"] == "application/json"

    body = params["WFJSONValues"]["Value"]["WFDictionaryFieldValueItems"]
    share_text = next(item for item in body if item["WFKey"]["Value"]["string"] == "share_text")
    assert share_text["WFValue"]["WFSerializationType"] == "WFTextTokenString"
    assert share_text["WFValue"]["Value"]["attachmentsByRange"] == {
        "{0, 1}": {"Type": "ActionOutput", "OutputUUID": clipboard_uuid}
    }


def test_build_workflow_can_still_use_share_sheet_input() -> None:
    workflow = make_ios_shortcut.build_workflow(
        endpoint="http://127.0.0.1:8080/capture",
        token="test-token",
        input_source="share-sheet",
    )

    post_action = workflow["WFWorkflowActions"][0]
    body = post_action["WFWorkflowActionParameters"]["WFJSONValues"]["Value"]["WFDictionaryFieldValueItems"]
    share_text = next(item for item in body if item["WFKey"]["Value"]["string"] == "share_text")
    assert share_text["WFValue"]["Value"]["attachmentsByRange"] == {
        "{0, 1}": {"Type": "ExtensionInput"}
    }


def test_write_shortcut_is_binary_plist(tmp_path: Path) -> None:
    output = tmp_path / "rednote.shortcut"
    workflow = make_ios_shortcut.build_workflow("http://127.0.0.1:8080/capture", "token")
    make_ios_shortcut.write_shortcut(workflow, output)

    assert output.read_bytes().startswith(b"bplist00")
    with output.open("rb") as fh:
        loaded = plistlib.load(fh)
    assert loaded["WFWorkflowName"] == "保存小红书原始帖子"

def test_shortcut_run_url_encodes_shortcut_name() -> None:
    assert make_ios_shortcut.shortcut_run_url("保存小红书原始帖子") == (
        "shortcuts://run-shortcut?name="
        "%E4%BF%9D%E5%AD%98%E5%B0%8F%E7%BA%A2%E4%B9%A6%E5%8E%9F%E5%A7%8B%E5%B8%96%E5%AD%90"
        "&input=clipboard"
    )


def test_load_user_token_reads_capture_users_file(tmp_path: Path) -> None:
    users_file = tmp_path / "capture_users.json"
    users_file.write_text(
        json.dumps(
            {
                "hongbin": {"display_name": "Hongbin", "token": "hongbin-token"},
                "zhangyu": {"display_name": "Zhangyu", "token": "zhangyu-token"},
            }
        )
    )

    assert make_ios_shortcut.load_user_token(users_file, "zhangyu") == "zhangyu-token"


def test_parse_dotenv_handles_quoted_values(tmp_path: Path) -> None:
    dotenv = tmp_path / ".env"
    dotenv.write_text('CAPTURE_TOKEN="abc(123)"\nIOS_SHORTCUT_ENDPOINT=http://x.test # comment\n')

    assert make_ios_shortcut.parse_dotenv(dotenv) == {
        "CAPTURE_TOKEN": "abc(123)",
        "IOS_SHORTCUT_ENDPOINT": "http://x.test",
    }
