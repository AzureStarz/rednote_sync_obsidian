from rednote_sync_obsidian.extractor import (
    extract_image_candidates,
    extract_page_metadata,
    extract_url_from_text,
    extract_video_candidates,
    sniff_image_content_type,
    sniff_video_content_type,
)


def test_extract_url_from_rednote_share_text():
    text = "复制打开小红书，看看这个笔记 https://www.xiaohongshu.com/explore/abc123?xsec_token=tok 更多内容"
    assert extract_url_from_text(text) == "https://www.xiaohongshu.com/explore/abc123?xsec_token=tok"




def test_extract_url_from_copied_xhslink_share_text():
    text = "阿嬷主演官宣入行? 我记得南枝好像在路演的时候说过要... http://xhslink.com/o/85VkKb2G75I \n複製後開啟小紅書查看筆記"
    assert extract_url_from_text(text) == "http://xhslink.com/o/85VkKb2G75I"

def test_extract_url_returns_none_for_empty_text():
    assert extract_url_from_text(None) is None
    assert extract_url_from_text("no link") is None


def test_extract_page_metadata_and_image_candidates():
    html = """
    <html>
      <head>
        <title>Fallback</title>
        <meta property="og:title" content="小红书标题">
        <meta name="description" content="页面描述">
        <meta property="og:image" content="/cover.jpg">
      </head>
      <body>
        <img src="//cdn.example.com/a.webp" alt="A">
        <img data-src="/b.png">
        <script>window.__x='https:\\/\\/cdn.example.com\\/c.jpg?x=1'</script>
      </body>
    </html>
    """
    metadata = extract_page_metadata(html, base_url="https://www.xiaohongshu.com/explore/abc")
    images = extract_image_candidates(html, base_url="https://www.xiaohongshu.com/explore/abc", max_images=10)

    assert metadata["title"] == "小红书标题"
    assert metadata["description"] == "页面描述"
    assert [item.url for item in images] == [
        "https://www.xiaohongshu.com/cover.jpg",
        "https://cdn.example.com/a.webp",
        "https://www.xiaohongshu.com/b.png",
        "https://cdn.example.com/c.jpg?x=1",
    ]


def test_extract_xhs_name_meta_and_escaped_cdn_images():
    html = """
    <html>
      <head>
        <meta name="og:title" content="小红书 name og title">
        <meta name="og:image" content="http://sns-webpic-qc.xhscdn.com/202605161531/a/spectrum/abc!nd_dft_wgth_jpg_3">
        <meta name="og:image" content="http://sns-webpic-qc.xhscdn.com/202605161531/b/spectrum/def!nd_dft_wgth_jpg_3">
      </head>
      <body>
        <script>
          window.__INITIAL_STATE__ = {"urlDefault":"http:\\u002F\\u002Fsns-webpic-qc.xhscdn.com\\u002F202605161531\\u002Fc\\u002Fspectrum\\u002Fghi!nd_dft_wgth_jpg_3"};
        </script>
      </body>
    </html>
    """

    metadata = extract_page_metadata(html)
    images = extract_image_candidates(html, max_images=10)

    assert metadata["title"] == "小红书 name og title"
    assert [item.url for item in images] == [
        "http://sns-webpic-qc.xhscdn.com/202605161531/a/spectrum/abc!nd_dft_wgth_jpg_3",
        "http://sns-webpic-qc.xhscdn.com/202605161531/b/spectrum/def!nd_dft_wgth_jpg_3",
        "http://sns-webpic-qc.xhscdn.com/202605161531/c/spectrum/ghi!nd_dft_wgth_jpg_3",
    ]


def test_extract_xhs_author_from_embedded_note_user():
    html = """
    <html><head><meta name="og:title" content="标题"></head>
    <script>
      window.__INITIAL_STATE__ = {"noteDetailMap":{"abc":{"note":{
        "noteId":"abc",
        "user":{"userId":"u1","nickname":"大模型幻想家(日更版)","avatar":"https:\\u002F\\u002Fexample.com\\u002Fa.jpg"}
      }}}};
    </script></html>
    """

    metadata = extract_page_metadata(html)

    assert metadata["author"] == "大模型幻想家(日更版)"


def test_extract_xhs_skips_preview_and_avatar_variants():
    html = """
    <meta name="og:image" content="http://sns-webpic-qc.xhscdn.com/a/full!nd_dft_wgth_jpg_3">
    <script>
      window.__INITIAL_STATE__ = {
        "preview": "http:\\u002F\\u002Fsns-webpic-qc.xhscdn.com\\u002Fa\\u002Ffull!nd_prv_wgth_jpg_3",
        "avatar": "https:\\u002F\\u002Fsns-avatar-qc.xhscdn.com\\u002Favatar\\u002Fabc"
      }
    </script>
    """

    images = extract_image_candidates(html, max_images=10)

    assert [item.url for item in images] == [
        "http://sns-webpic-qc.xhscdn.com/a/full!nd_dft_wgth_jpg_3",
    ]


def test_sniff_image_content_type_rejects_html():
    assert sniff_image_content_type(b"\xff\xd8\xff\xe0fake") == "image/jpeg"
    assert sniff_image_content_type(b"<html>not an image</html>") == ""


def test_extract_xhs_video_candidates():
    html = """
    <meta name="og:video" content="https://sns-video-qc.xhscdn.com/stream/a/video.mp4?sign=abc&t=1">
    <script>{"backup":"https:\\u002F\\u002Fsns-video-qc.xhscdn.com\\u002Fstream\\u002Fb\\u002Fbackup.mp4?sign=def"}</script>
    """

    videos = extract_video_candidates(html, max_videos=10)

    assert [item.url for item in videos] == [
        "https://sns-video-qc.xhscdn.com/stream/a/video.mp4?sign=abc&t=1",
        "https://sns-video-qc.xhscdn.com/stream/b/backup.mp4?sign=def",
    ]


def test_sniff_video_content_type():
    assert sniff_video_content_type(b"\x00\x00\x00 ftypisom\x00\x00\x02\x00") == "video/mp4"
    assert sniff_video_content_type(b"#EXTM3U\n#EXT-X-VERSION:3") == "application/vnd.apple.mpegurl"
    assert sniff_video_content_type(b"<html>not a video</html>") == ""
