#!/usr/bin/env python3
"""Generate an Apple Shortcuts file for Rednote capture.

The generated shortcut posts the Share Sheet input to the capture API as JSON:

{
  "platform": "xiaohongshu",
  "url": "",
  "share_text": <Shortcut Input>,
  "user_note": "iOS shortcut"
}

It embeds the capture token in the shortcut file, so the default output path is
under data/shortcuts/ (ignored by git).
"""

from __future__ import annotations

import argparse
import json
import os
import plistlib
import shutil
import subprocess
import sys
import uuid
from pathlib import Path
from typing import Any
from urllib.parse import quote

OBJECT_REPLACEMENT = "\ufffc"
DEFAULT_ENDPOINT = "http://120.24.177.252:8080/capture"
DEFAULT_NAME = "保存小红书原始帖子"
DEFAULT_OUTPUT = Path("data/shortcuts") / f"{DEFAULT_NAME}.shortcut"


def shortcut_run_url(name: str, *, input_value: str = "clipboard") -> str:
    return f"shortcuts://run-shortcut?name={quote(name)}&input={quote(input_value)}"


def parse_dotenv(path: Path) -> dict[str, str]:
    """Parse a small .env file without executing it as shell code."""

    values: dict[str, str] = {}
    if not path.exists():
        return values

    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip()
        if not key:
            continue
        if value and value[0] in {'"', "'"}:
            quote = value[0]
            if len(value) >= 2 and value[-1] == quote:
                value = value[1:-1]
            else:
                value = value[1:]
        else:
            value = value.split(" #", 1)[0].strip()
        values[key] = value
    return values


def env_or_dotenv(key: str, dotenv: Path = Path(".env")) -> str | None:
    return os.environ.get(key) or parse_dotenv(dotenv).get(key)


def load_user_token(users_file: Path, user: str) -> str:
    try:
        raw = json.loads(users_file.expanduser().read_text(encoding="utf-8"))
    except Exception as exc:
        raise ValueError(f"cannot read users file: {users_file}") from exc

    if not isinstance(raw, dict) or user not in raw:
        raise ValueError(f"user {user!r} not found in {users_file}")

    record = raw[user]
    token = record if isinstance(record, str) else record.get("token") if isinstance(record, dict) else None
    if not isinstance(token, str) or not token.strip():
        raise ValueError(f"user {user!r} in {users_file} is missing token")
    return token.strip()


def token_string(text: str) -> dict[str, Any]:
    return {
        "Value": {"string": text},
        "WFSerializationType": "WFTextTokenString",
    }


def shortcut_input_token_string() -> dict[str, Any]:
    return {
        "Value": {
            "attachmentsByRange": {
                "{0, 1}": {"Type": "ExtensionInput"},
            },
            "string": OBJECT_REPLACEMENT,
        },
        "WFSerializationType": "WFTextTokenString",
    }


def action_output_token_string(output_uuid: str) -> dict[str, Any]:
    return {
        "Value": {
            "attachmentsByRange": {
                "{0, 1}": {
                    "Type": "ActionOutput",
                    "OutputUUID": output_uuid,
                },
            },
            "string": OBJECT_REPLACEMENT,
        },
        "WFSerializationType": "WFTextTokenString",
    }


def dictionary_items(values: dict[str, Any]) -> dict[str, Any]:
    items: list[dict[str, Any]] = []
    for key, value in values.items():
        if isinstance(value, dict) and value.get("WFSerializationType") == "WFTextTokenString":
            wf_value = value
        else:
            wf_value = token_string(str(value))
        items.append(
            {
                "UUID": str(uuid.uuid4()).upper(),
                "WFItemType": 0,
                "WFKey": token_string(key),
                "WFValue": wf_value,
            }
        )
    return {
        "Value": {"WFDictionaryFieldValueItems": items},
        "WFSerializationType": "WFDictionaryFieldValue",
    }


def build_workflow(endpoint: str, token: str, name: str = DEFAULT_NAME, input_source: str = "clipboard") -> dict[str, Any]:
    """Build an unsigned Shortcut plist payload.

    input_source="clipboard" builds the Xiaohongshu-compatible flow:
    Copy Link in Rednote -> run Shortcut -> POST clipboard text.

    input_source="share-sheet" keeps the original Share Sheet flow for apps that
    expose the iOS system share sheet.
    """

    if input_source not in {"clipboard", "share-sheet"}:
        raise ValueError("input_source must be 'clipboard' or 'share-sheet'")

    input_uuid = str(uuid.uuid4()).upper()
    share_text_value = (
        action_output_token_string(input_uuid)
        if input_source == "clipboard"
        else shortcut_input_token_string()
    )
    input_actions = []
    if input_source == "clipboard":
        input_actions.append(
            {
                "WFWorkflowActionIdentifier": "is.workflow.actions.getclipboard",
                "WFWorkflowActionParameters": {
                    "UUID": input_uuid,
                },
            }
        )

    workflow = {
        "WFWorkflowClientRelease": "18.0",
        "WFWorkflowClientVersion": "1302.1.3",
        "WFWorkflowIcon": {
            "WFWorkflowIconGlyphNumber": 61440,
            "WFWorkflowIconStartColor": 4282601983,
        },
        "WFWorkflowImportQuestions": [],
        "WFWorkflowInputContentItemClasses": [
            "WFURLContentItem",
            "WFTextContentItem",
            "WFWebPageContentItem",
        ],
        "WFWorkflowMinimumClientVersion": 1300,
        "WFWorkflowMinimumClientVersionString": "1300",
        "WFWorkflowOutputContentItemClasses": [],
        "WFWorkflowHasOutputFallback": False,
        "WFWorkflowHasShortcutInputVariables": True,
        "WFWorkflowTypes": ["ActionExtension"],
        "WFWorkflowName": name,
        "WFWorkflowActions": [
            *input_actions,
            {
                "WFWorkflowActionIdentifier": "is.workflow.actions.downloadurl",
                "WFWorkflowActionParameters": {
                    "UUID": str(uuid.uuid4()).upper(),
                    "WFURL": endpoint,
                    "WFHTTPMethod": "POST",
                    "ShowHeaders": True,
                    "WFHTTPHeaders": dictionary_items(
                        {
                            "Content-Type": "application/json",
                            "X-Capture-Token": token,
                        }
                    ),
                    "WFHTTPBodyType": "JSON",
                    "WFJSONValues": dictionary_items(
                        {
                            "platform": "xiaohongshu",
                            # Leave URL empty; the worker extracts the xhslink URL from share_text.
                            "url": "",
                            "share_text": share_text_value,
                            "user_note": "iOS shortcut",
                        }
                    ),
                    "WFAllowsCellularAccess": 1,
                    "WFAllowsRedirects": 1,
                    "WFIgnoreCookies": 0,
                    "WFTimeout": 60,
                },
            },
            {
                "WFWorkflowActionIdentifier": "is.workflow.actions.notification",
                "WFWorkflowActionParameters": {
                    "UUID": str(uuid.uuid4()).upper(),
                    "WFNotificationActionTitle": token_string("小红书已提交"),
                    "WFNotificationActionBody": token_string("抓取任务已发送到服务器"),
                    "WFNotificationActionSound": True,
                },
            },
        ],
    }
    return workflow


def write_shortcut(workflow: dict[str, Any], output: Path) -> None:
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open("wb") as fh:
        plistlib.dump(workflow, fh, fmt=plistlib.FMT_BINARY, sort_keys=False)


def sign_shortcut(input_path: Path, output_path: Path, timeout_seconds: int) -> bool:
    shortcuts = shutil.which("shortcuts")
    if shortcuts is None:
        print("warning: macOS shortcuts CLI not found; wrote unsigned shortcut only", file=sys.stderr)
        return False

    try:
        subprocess.run(
            [shortcuts, "sign", "--mode", "anyone", "--input", str(input_path), "--output", str(output_path)],
            check=True,
            capture_output=True,
            text=True,
            timeout=timeout_seconds,
        )
    except subprocess.TimeoutExpired:
        print(
            f"warning: shortcuts sign timed out after {timeout_seconds}s; unsigned file kept at {input_path}",
            file=sys.stderr,
        )
        return False
    except subprocess.CalledProcessError as exc:
        detail = (exc.stderr or exc.stdout or "").strip()
        print(f"warning: shortcuts sign failed; unsigned file kept at {input_path}: {detail}", file=sys.stderr)
        return False
    return True


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Generate the iOS Shortcut for Rednote capture.")
    parser.add_argument("--endpoint", default=env_or_dotenv("IOS_SHORTCUT_ENDPOINT") or DEFAULT_ENDPOINT)
    parser.add_argument("--token", default=env_or_dotenv("CAPTURE_TOKEN"))
    parser.add_argument(
        "--users-file",
        type=Path,
        default=Path(env_or_dotenv("CAPTURE_USERS_FILE")) if env_or_dotenv("CAPTURE_USERS_FILE") else None,
        help="Multi-user token JSON file such as secrets/capture_users.json.",
    )
    parser.add_argument("--user", default=None, help="Owner id to read from --users-file, for example hongbin or zhangyu.")
    parser.add_argument("--name", default=DEFAULT_NAME)
    parser.add_argument(
        "--input-source",
        choices=["clipboard", "share-sheet"],
        default="clipboard",
        help="clipboard: run after Copy Link in Xiaohongshu; share-sheet: use iOS Share Sheet input.",
    )
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--no-sign", action="store_true", help="Skip macOS shortcuts signing.")
    parser.add_argument("--sign-timeout", type=int, default=45)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    token = args.token
    if args.user:
        if args.users_file is None:
            print("error: --user requires --users-file or CAPTURE_USERS_FILE", file=sys.stderr)
            return 2
        try:
            token = load_user_token(args.users_file, args.user)
        except ValueError as exc:
            print(f"error: {exc}", file=sys.stderr)
            return 2

    if not token:
        print(
            "error: token not found. Pass --token, set CAPTURE_TOKEN, or use --users-file with --user.",
            file=sys.stderr,
        )
        return 2
    if not args.endpoint.startswith(("http://", "https://")):
        print("error: --endpoint must start with http:// or https://", file=sys.stderr)
        return 2

    unsigned_output = args.output
    signed_output = args.output
    if not args.no_sign:
        unsigned_output = args.output.with_name(args.output.stem + ".unsigned.shortcut")

    workflow = build_workflow(endpoint=args.endpoint, token=token, name=args.name, input_source=args.input_source)
    write_shortcut(workflow, unsigned_output)

    signed = False
    if not args.no_sign:
        signed = sign_shortcut(unsigned_output, signed_output, timeout_seconds=args.sign_timeout)

    final_path = signed_output if signed else unsigned_output
    print(final_path)
    if signed:
        print("signed=true")
    else:
        print("signed=false")
    print(f"run_url={shortcut_run_url(args.name)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
