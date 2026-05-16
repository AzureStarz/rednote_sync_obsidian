import json

from rednote_sync_obsidian.llm import _build_chat_messages, _parse_summary_json


VALID_SUMMARY = {
    "title": "测试标题",
    "one_sentence_summary": "一句话总结",
    "summary": "摘要",
    "key_points": ["要点"],
    "why_it_matters": "值得保存",
    "action_items": ["行动"],
    "tags": ["小红书"],
    "category": "待处理",
    "author": "",
    "source_text": "原文",
    "confidence": 0.8,
}


def test_parse_summary_json_accepts_fenced_json():
    parsed = _parse_summary_json("```json\n" + json.dumps(VALID_SUMMARY, ensure_ascii=False) + "\n```")
    assert parsed["title"] == "测试标题"
    assert parsed["confidence"] == 0.8


def test_chat_messages_note_that_screenshot_is_not_sent():
    messages = _build_chat_messages(
        url="https://example.com",
        share_text="share",
        user_note="note",
        extracted_text="extracted",
        screenshot_b64="abc123",
    )
    assert messages[0]["role"] == "system"
    assert "valid JSON" in messages[0]["content"]
    assert "screenshot" in messages[1]["content"].lower()
    assert "does not send image bytes" in messages[1]["content"]
