from rednote_sync_obsidian.markdown_builder import build_asset_path, build_markdown, build_note_path, sanitize_filename_part


def test_sanitize_filename_part_removes_invalid_chars():
    assert sanitize_filename_part('护肤/笔记:*?"<>|') == "护肤-笔记"


def test_build_note_path_uses_captured_date_and_job_id():
    path = build_note_path("00_Inbox/Xiaohongshu", "护肤笔记", "xhs_abc123", captured_at="2026-05-11T10:00:00+08:00")
    assert path.startswith("00_Inbox/Xiaohongshu/2026-05-11_护肤笔记_xhs_abc123")
    assert path.endswith(".md")


def test_build_markdown_contains_frontmatter_and_screenshot_wikilink():
    job = {"job_id": "xhs_abc", "url": "https://example.com", "captured_at": "2026-05-11T00:00:00+00:00", "user_note": "try it"}
    summary = {
        "title": "测试标题",
        "one_sentence_summary": "一句话",
        "summary": "总结",
        "key_points": ["A", "B"],
        "why_it_matters": "有用",
        "action_items": ["行动"],
        "tags": ["生活 技巧"],
        "category": "生活",
        "author": "",
        "source_text": "原文",
        "confidence": 0.86,
    }
    asset = build_asset_path("90_Assets/xiaohongshu", "xhs_abc")
    md = build_markdown(job, summary, asset_relative_path=asset)
    assert 'source: "xiaohongshu"' in md
    assert '# 测试标题' in md
    assert '  - "生活-技巧"' in md
    assert f"![[{asset}]]" in md
