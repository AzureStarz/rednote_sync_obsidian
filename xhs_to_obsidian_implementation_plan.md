# 小红书一键保存、LLM 总结并归档到 Obsidian：完整实现方案

## 1. 目标

实现一个在 iPhone 上刷小红书时可一键保存内容的系统：

```text
小红书 App
  ↓ 分享链接 / 截图
iOS 快捷指令
  ↓ POST 到 Webhook
后端 API
  ↓ 立即返回“已入队”
任务队列 Redis
  ↓
内容提取器
  ↓
LLM 总结器
  ↓
生成 Markdown
  ↓
GitHub 私有仓库
  ↓
Obsidian Vault 同步
```

最终使用体验：

```text
看到小红书笔记
→ 分享
→ 点击“保存到 Obsidian”
→ 手机立即提示“已入队”
→ 继续刷小红书
→ 后台自动总结
→ Markdown 自动出现在 Obsidian
```

---

## 2. 设计原则

### 2.1 手机端只做“投递”

iPhone 快捷指令只负责：

- 获取分享链接
- 获取分享文案
- 可选：获取截图
- 可选：输入个人备注
- POST 到后端 Webhook
- 立即显示“已入队”

手机端不做：

- 网页抓取
- OCR
- LLM 总结
- Markdown 生成
- Obsidian 写入

这样可以保证你点击后马上继续刷小红书，不会被后台处理阻塞。

### 2.2 后端异步处理

后端 API 收到请求后立刻入队，然后返回：

```json
{
  "status": "queued",
  "job_id": "xhs_abcd1234"
}
```

实际处理由 Worker 异步完成。

### 2.3 Obsidian 通过 GitHub 同步

云端后端无法直接写入 iPhone 本地 Obsidian Vault，因此采用：

```text
后端 → GitHub 私有仓库 → Obsidian Vault
```

后端将总结后的 Markdown 提交到 GitHub 私有仓库。你的 Mac / iPhone / iPad 上的 Obsidian 再通过 Git、Obsidian Sync 或其他同步方式拿到这些 Markdown 文件。

---

## 3. 推荐技术栈

| 模块 | 推荐方案 |
|---|---|
| 手机入口 | iOS 快捷指令 |
| Webhook API | FastAPI |
| 任务队列 | Redis |
| 后台 Worker | Python Worker |
| LLM 总结 | OpenAI Responses API |
| 图片理解 | OpenAI 图像输入 |
| Markdown 生成 | Python 模板 |
| Obsidian 同步桥 | GitHub 私有仓库 |
| 部署环境 | 阿里云 ECS |
| HTTPS 入口 | Nginx + Certbot |
| 服务编排 | Docker Compose |

---

## 4. 系统架构

```text
┌────────────────────┐
│   小红书 iOS App    │
└─────────┬──────────┘
          │ 分享链接 / 截图
          ▼
┌────────────────────┐
│   iOS 快捷指令      │
│ 保存到 Obsidian     │
└─────────┬──────────┘
          │ HTTPS POST
          ▼
┌────────────────────┐
│   Nginx HTTPS       │
│ capture.domain.com  │
└─────────┬──────────┘
          │ reverse proxy
          ▼
┌────────────────────┐
│   FastAPI /capture  │
│ 验权 + 入队 + 返回   │
└─────────┬──────────┘
          │ Redis queue
          ▼
┌────────────────────┐
│   Python Worker     │
│ 提取 / 总结 / 归档   │
└─────────┬──────────┘
          │ GitHub API
          ▼
┌────────────────────┐
│ GitHub 私有仓库      │
│ Obsidian Vault      │
└─────────┬──────────┘
          │ sync / pull
          ▼
┌────────────────────┐
│     Obsidian        │
└────────────────────┘
```

---

## 5. 阿里云部署架构

你的阿里云服务器有公网 IP，可以直接作为后端部署环境。

推荐在同一台 ECS 上跑：

```text
阿里云 ECS
  ├── Nginx
  ├── Docker Compose
  │   ├── api      FastAPI
  │   ├── redis    Redis 队列
  │   └── worker   后台处理器
  └── 日志与失败队列
```

公网只开放：

| 端口 | 用途 |
|---:|---|
| 22 | SSH 登录 |
| 80 | HTTP / 证书申请 |
| 443 | HTTPS Webhook |

不要开放：

| 端口 | 原因 |
|---:|---|
| 6379 | Redis 不应暴露公网 |
| 8000 | FastAPI 只应由 Nginx 本地反代 |
| 5432 / 3306 | 数据库不应裸奔公网 |

---

## 6. Obsidian Vault 目录设计

建议 GitHub 私有仓库本身就是一个 Obsidian Vault。

目录结构：

```text
ObsidianVault/
  00_Inbox/
    Xiaohongshu/
      2026-05-09_xhs_护肤笔记_xhs_abcd1234.md
  90_Assets/
    xiaohongshu/
      xhs_abcd1234.jpg
  Templates/
```

说明：

- `00_Inbox/Xiaohongshu/`：保存总结后的 Markdown 笔记
- `90_Assets/xiaohongshu/`：保存截图、封面图等素材
- `Templates/`：未来可以放 Obsidian 模板

---

## 7. 生成的 Markdown 格式

每条小红书内容生成一个 Markdown 文件：

```markdown
---
source: xiaohongshu
url: "https://www.xiaohongshu.com/..."
captured_at: "2026-05-09T14:20:00+08:00"
author: ""
category: "生活技巧"
tags:
  - 小红书
  - 生活技巧
  - 护肤
status: processed
confidence: 0.86
job_id: "xhs_abcd1234"
---

# 小红书笔记标题

## 一句话总结

这篇笔记主要讲……

## 总结

这里是 100-200 字总结。

## 关键点

- 关键点 1
- 关键点 2
- 关键点 3

## 为什么值得保存

这条内容对我有价值的原因是……

## 可执行行动

- [ ] 行动 1
- [ ] 行动 2

## 原始链接

https://www.xiaohongshu.com/...

## 我的备注

这里是我保存时补充的备注。

## 原文 / OCR 识别内容

这里放分享文案、网页提取文本或截图识别结果。

## 截图

![[90_Assets/xiaohongshu/xhs_abcd1234.jpg]]
```

---

## 8. iOS 快捷指令设计

建议做两个快捷指令：

1. 分享链接保存
2. 截图保存兜底

---

### 8.1 快捷指令 A：保存小红书到 Obsidian

用途：从小红书分享菜单触发。

名称：

```text
保存小红书到 Obsidian
```

设置：

```text
快捷指令详情
→ 在共享表单中显示：开启
→ 接收类型：URL、文本、富文本、图片
```

动作流程：

```text
1. 获取快捷指令输入
2. 从输入中提取 URL
3. 如果没有 URL，读取剪贴板
4. 询问输入：我的备注，可选
5. 创建 JSON 字典
6. 获取 URL 内容
7. 显示通知：已入队
```

Webhook：

```text
https://capture.yourdomain.com/capture
```

请求方法：

```text
POST
```

请求头：

```text
Content-Type: application/json
X-Capture-Token: 你的 CAPTURE_TOKEN
```

请求体：

```json
{
  "platform": "xiaohongshu",
  "url": "分享链接",
  "share_text": "分享文案",
  "user_note": "你的备注",
  "captured_at": "当前日期"
}
```

---

### 8.2 快捷指令 B：截图保存到 Obsidian

用途：当分享链接拿不到完整内容时，用截图兜底。

名称：

```text
截图保存到 Obsidian
```

动作流程：

```text
1. 截图
2. 调整图像大小，例如宽度 1200px
3. 转换图像为 JPEG，质量 70%
4. Base64 编码
5. 读取剪贴板，尝试获取小红书链接
6. 询问输入：我的备注，可选
7. POST 到 /capture
8. 显示通知：已入队
```

请求体：

```json
{
  "platform": "xiaohongshu",
  "url": "剪贴板中的链接，可选",
  "share_text": "分享文案，可选",
  "user_note": "你的备注",
  "screenshot_b64": "Base64 编码后的截图",
  "captured_at": "当前日期"
}
```

可选绑定：

```text
设置 → 辅助功能 → 触控 → 轻点背面 → 轻点三下 → 截图保存到 Obsidian
```

---

## 9. 后端项目结构

```text
xhs-to-obsidian/
  app.py
  worker.py
  extractor.py
  llm.py
  markdown_builder.py
  github_writer.py
  requirements.txt
  Dockerfile
  docker-compose.yml
  .env
```

---

## 10. 环境变量

`.env`：

```bash
CAPTURE_TOKEN=换成一个很长的随机字符串
REDIS_URL=redis://redis:6379/0

OPENAI_API_KEY=你的_openai_api_key
OPENAI_MODEL=gpt-5.5

GITHUB_TOKEN=你的_github_pat
GITHUB_REPO=你的GitHub用户名/obsidian-vault
GITHUB_BRANCH=main

OBSIDIAN_BASE_PATH=00_Inbox/Xiaohongshu
OBSIDIAN_ASSET_PATH=90_Assets/xiaohongshu
```

生成随机 token：

```bash
openssl rand -hex 32
```

---

## 11. requirements.txt

```txt
fastapi
uvicorn[standard]
redis
python-dotenv
httpx
beautifulsoup4
openai
python-slugify
pydantic
```

---

## 12. Dockerfile

```dockerfile
FROM python:3.12-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

CMD ["uvicorn", "app:app", "--host", "0.0.0.0", "--port", "8000"]
```

---

## 13. docker-compose.yml

```yaml
services:
  redis:
    image: redis:7
    restart: unless-stopped
    volumes:
      - redis_data:/data
    command: redis-server --appendonly yes

  api:
    build: .
    restart: unless-stopped
    command: uvicorn app:app --host 0.0.0.0 --port 8000
    env_file:
      - .env
    depends_on:
      - redis
    ports:
      - "127.0.0.1:8000:8000"

  worker:
    build: .
    restart: unless-stopped
    command: python worker.py
    env_file:
      - .env
    depends_on:
      - redis

volumes:
  redis_data:
```

说明：

- `api` 只绑定到 `127.0.0.1:8000`
- 公网无法直接访问 8000
- Nginx 负责把 HTTPS 请求转发到本地 8000

---

## 14. API 服务：app.py

```python
import os
import json
import uuid
from datetime import datetime, timezone
from typing import Optional

import redis
from dotenv import load_dotenv
from fastapi import FastAPI, Header, HTTPException
from pydantic import BaseModel

load_dotenv()

app = FastAPI()

r = redis.Redis.from_url(os.environ["REDIS_URL"], decode_responses=True)

CAPTURE_TOKEN = os.environ["CAPTURE_TOKEN"]
QUEUE_NAME = "xhs_capture_queue"


class CaptureRequest(BaseModel):
    platform: str = "xiaohongshu"
    url: Optional[str] = None
    share_text: Optional[str] = None
    user_note: Optional[str] = None
    screenshot_b64: Optional[str] = None
    captured_at: Optional[str] = None


@app.post("/capture")
def capture(
    payload: CaptureRequest,
    x_capture_token: Optional[str] = Header(default=None),
):
    if x_capture_token != CAPTURE_TOKEN:
        raise HTTPException(status_code=401, detail="Unauthorized")

    job_id = "xhs_" + uuid.uuid4().hex[:12]

    job = {
        "job_id": job_id,
        "platform": payload.platform,
        "url": payload.url,
        "share_text": payload.share_text,
        "user_note": payload.user_note,
        "screenshot_b64": payload.screenshot_b64,
        "captured_at": payload.captured_at or datetime.now(timezone.utc).isoformat(),
        "status": "queued",
    }

    r.lpush(QUEUE_NAME, json.dumps(job, ensure_ascii=False))

    return {
        "status": "queued",
        "job_id": job_id,
    }


@app.get("/health")
def health():
    return {"ok": True}
```

---

## 15. 内容提取器：extractor.py

```python
import re
import httpx
from bs4 import BeautifulSoup


def extract_url_from_text(text: str | None) -> str | None:
    if not text:
        return None

    match = re.search(r"https?://[^\s]+", text)
    return match.group(0) if match else None


def extract_public_page_text(url: str | None) -> str:
    if not url:
        return ""

    try:
        headers = {
            "User-Agent": "Mozilla/5.0"
        }

        with httpx.Client(timeout=8, follow_redirects=True, headers=headers) as client:
            resp = client.get(url)

        if resp.status_code >= 400:
            return ""

        soup = BeautifulSoup(resp.text, "html.parser")

        title = soup.title.get_text(strip=True) if soup.title else ""

        meta_desc = ""
        desc_tag = soup.find("meta", attrs={"name": "description"})
        if desc_tag:
            meta_desc = desc_tag.get("content", "")

        body_text = soup.get_text("\n", strip=True)
        body_text = body_text[:8000]

        return "\n".join([
            f"Title: {title}",
            f"Description: {meta_desc}",
            body_text,
        ])

    except Exception:
        return ""
```

说明：

- 不做反爬绕过
- 不做登录态模拟
- 不做批量抓取
- 只处理你主动保存的内容
- 页面不可访问时，由分享文本和截图兜底

---

## 16. LLM 总结器：llm.py

```python
import os
import json
from typing import Optional

from openai import OpenAI

client = OpenAI(api_key=os.environ["OPENAI_API_KEY"])


SUMMARY_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "properties": {
        "title": {"type": "string"},
        "one_sentence_summary": {"type": "string"},
        "summary": {"type": "string"},
        "key_points": {
            "type": "array",
            "items": {"type": "string"}
        },
        "why_it_matters": {"type": "string"},
        "action_items": {
            "type": "array",
            "items": {"type": "string"}
        },
        "tags": {
            "type": "array",
            "items": {"type": "string"}
        },
        "category": {"type": "string"},
        "author": {"type": "string"},
        "source_text": {"type": "string"},
        "confidence": {"type": "number"}
    },
    "required": [
        "title",
        "one_sentence_summary",
        "summary",
        "key_points",
        "why_it_matters",
        "action_items",
        "tags",
        "category",
        "author",
        "source_text",
        "confidence"
    ]
}


def summarize_xhs_note(
    url: Optional[str],
    share_text: Optional[str],
    user_note: Optional[str],
    extracted_text: Optional[str],
    screenshot_b64: Optional[str],
):
    prompt = f"""
你是我的个人知识库整理助手。下面是我从小红书保存的一条内容。

请完成：
1. 生成一个适合 Obsidian 的标题
2. 用一句话总结
3. 写一段 100-200 字总结
4. 提取 3-7 个关键点
5. 提取可执行行动项
6. 判断分类
7. 生成 3-8 个标签
8. 保留原始信息
9. 不要编造文本或截图中没有的信息
10. 如果信息不足，请降低 confidence，并在 source_text 中保留已有材料

URL:
{url or ""}

分享文本:
{share_text or ""}

我的备注:
{user_note or ""}

网页提取文本:
{extracted_text or ""}
"""

    content = [
        {
            "type": "input_text",
            "text": prompt,
        }
    ]

    if screenshot_b64:
        content.append({
            "type": "input_image",
            "image_url": f"data:image/jpeg;base64,{screenshot_b64}",
        })

    response = client.responses.create(
        model=os.environ.get("OPENAI_MODEL", "gpt-5.5"),
        input=[
            {
                "role": "user",
                "content": content,
            }
        ],
        text={
            "format": {
                "type": "json_schema",
                "name": "xhs_summary",
                "schema": SUMMARY_SCHEMA,
                "strict": True,
            }
        },
    )

    return json.loads(response.output_text)
```

---

## 17. Markdown 生成器：markdown_builder.py

```python
from datetime import datetime
from slugify import slugify


def safe_title(title: str) -> str:
    title = title.strip() or "未命名小红书笔记"
    return title[:60]


def build_markdown(
    job: dict,
    summary: dict,
    asset_relative_path: str | None = None,
) -> str:
    url = job.get("url") or ""
    captured_at = job.get("captured_at") or ""
    title = safe_title(summary["title"])

    tags = summary.get("tags", [])
    tag_yaml = "\n".join([f"  - {t}" for t in tags]) or "  - 小红书"

    key_points = "\n".join([f"- {p}" for p in summary.get("key_points", [])])
    action_items = "\n".join([f"- [ ] {a}" for a in summary.get("action_items", [])])

    screenshot_section = ""
    if asset_relative_path:
        screenshot_section = f"""
## 截图

![[{asset_relative_path}]]
"""

    return f"""---
source: xiaohongshu
url: "{url}"
captured_at: "{captured_at}"
author: "{summary.get("author", "")}"
category: "{summary.get("category", "")}"
tags:
{tag_yaml}
status: processed
confidence: {summary.get("confidence", 0)}
job_id: "{job.get("job_id")}"
---

# {title}

## 一句话总结

{summary.get("one_sentence_summary", "")}

## 总结

{summary.get("summary", "")}

## 关键点

{key_points}

## 为什么值得保存

{summary.get("why_it_matters", "")}

## 可执行行动

{action_items}

## 原始链接

{url}

## 我的备注

{job.get("user_note") or ""}

## 原文 / OCR 识别内容

{summary.get("source_text", "")}
{screenshot_section}
"""


def build_note_path(base_path: str, title: str, job_id: str) -> str:
    date_prefix = datetime.now().strftime("%Y-%m-%d")
    slug = slugify(title, lowercase=False, max_length=40) or "xiaohongshu"
    return f"{base_path}/{date_prefix}_{slug}_{job_id}.md"
```

---

## 18. GitHub 写入器：github_writer.py

```python
import os
import base64
import httpx


GITHUB_TOKEN = os.environ["GITHUB_TOKEN"]
GITHUB_REPO = os.environ["GITHUB_REPO"]
GITHUB_BRANCH = os.environ.get("GITHUB_BRANCH", "main")


def put_file_to_github(path: str, content_bytes: bytes, message: str):
    encoded = base64.b64encode(content_bytes).decode("utf-8")

    url = f"https://api.github.com/repos/{GITHUB_REPO}/contents/{path}"

    headers = {
        "Authorization": f"Bearer {GITHUB_TOKEN}",
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
    }

    payload = {
        "message": message,
        "content": encoded,
        "branch": GITHUB_BRANCH,
    }

    with httpx.Client(timeout=20) as client:
        resp = client.put(url, json=payload, headers=headers)

    if resp.status_code not in (200, 201):
        raise RuntimeError(f"GitHub write failed: {resp.status_code} {resp.text}")

    return resp.json()
```

---

## 19. Worker：worker.py

```python
import os
import json
import base64
import traceback

import redis
from dotenv import load_dotenv

from extractor import extract_url_from_text, extract_public_page_text
from llm import summarize_xhs_note
from markdown_builder import build_markdown, build_note_path
from github_writer import put_file_to_github

load_dotenv()

r = redis.Redis.from_url(os.environ["REDIS_URL"], decode_responses=True)

QUEUE_NAME = "xhs_capture_queue"
FAILED_QUEUE_NAME = "xhs_capture_failed"

OBSIDIAN_BASE_PATH = os.environ["OBSIDIAN_BASE_PATH"]
OBSIDIAN_ASSET_PATH = os.environ["OBSIDIAN_ASSET_PATH"]


def process_job(job: dict):
    if not job.get("url"):
        job["url"] = extract_url_from_text(job.get("share_text"))

    extracted_text = extract_public_page_text(job.get("url"))

    summary = summarize_xhs_note(
        url=job.get("url"),
        share_text=job.get("share_text"),
        user_note=job.get("user_note"),
        extracted_text=extracted_text,
        screenshot_b64=job.get("screenshot_b64"),
    )

    asset_relative_path = None

    if job.get("screenshot_b64"):
        image_bytes = base64.b64decode(job["screenshot_b64"])
        asset_path = f"{OBSIDIAN_ASSET_PATH}/{job['job_id']}.jpg"

        put_file_to_github(
            path=asset_path,
            content_bytes=image_bytes,
            message=f"Add screenshot for {job['job_id']}",
        )

        asset_relative_path = asset_path

    markdown = build_markdown(
        job=job,
        summary=summary,
        asset_relative_path=asset_relative_path,
    )

    note_path = build_note_path(
        base_path=OBSIDIAN_BASE_PATH,
        title=summary["title"],
        job_id=job["job_id"],
    )

    put_file_to_github(
        path=note_path,
        content_bytes=markdown.encode("utf-8"),
        message=f"Add Xiaohongshu note {job['job_id']}",
    )

    print(f"Done: {job['job_id']} -> {note_path}")


def main():
    print("Worker started")

    while True:
        _, raw = r.brpop(QUEUE_NAME)
        job = json.loads(raw)

        try:
            process_job(job)
        except Exception as e:
            job["error"] = str(e)
            job["traceback"] = traceback.format_exc()
            r.lpush(FAILED_QUEUE_NAME, json.dumps(job, ensure_ascii=False))
            print(f"Failed: {job.get('job_id')}: {e}")


if __name__ == "__main__":
    main()
```

---

## 20. 去重设计

避免同一个链接重复保存。

可以在入队前增加：

```python
import hashlib


def build_dedupe_key(job: dict) -> str:
    raw = "|".join([
        job.get("url") or "",
        (job.get("share_text") or "")[:200],
    ])
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()
```

在 `app.py` 的 `/capture` 中加入：

```python
dedupe_key = "dedupe:" + build_dedupe_key(job)

if r.set(dedupe_key, job_id, nx=True, ex=60 * 60 * 24 * 30) is None:
    return {
        "status": "duplicate",
        "message": "这条内容已经保存过"
    }
```

建议第一版先不加，等主链路跑通后再加。

---

## 21. 失败处理

失败不要丢数据。

建议保留：

```text
xhs_capture_queue     正常队列
xhs_capture_failed    失败队列
```

Worker 失败后把原始 job、错误信息和 traceback 写入失败队列。

后续可以增加一个失败重试脚本：

```python
import redis

r = redis.Redis.from_url("redis://localhost:6379/0", decode_responses=True)

FAILED_QUEUE_NAME = "xhs_capture_failed"
QUEUE_NAME = "xhs_capture_queue"

while True:
    raw = r.rpop(FAILED_QUEUE_NAME)
    if raw is None:
        break
    r.lpush(QUEUE_NAME, raw)
```

也可以在失败时直接生成一条 fallback Markdown：

```markdown
---
source: xiaohongshu
status: failed
---

# 小红书保存失败

原始链接：...

分享文本：...

错误信息：...
```

---

## 22. 阿里云 ECS 部署步骤

以下以 Ubuntu 为例。

### 22.1 登录服务器

```bash
ssh root@你的公网IP
```

更新系统：

```bash
apt update && apt upgrade -y
```

---

### 22.2 安装 Docker

```bash
apt install -y ca-certificates curl gnupg
install -m 0755 -d /etc/apt/keyrings

curl -fsSL https://download.docker.com/linux/ubuntu/gpg \
  | gpg --dearmor -o /etc/apt/keyrings/docker.gpg

chmod a+r /etc/apt/keyrings/docker.gpg

echo \
"deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.gpg] \
https://download.docker.com/linux/ubuntu \
$(. /etc/os-release && echo "$VERSION_CODENAME") stable" \
> /etc/apt/sources.list.d/docker.list

apt update
apt install -y docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin

systemctl enable docker
systemctl start docker
```

验证：

```bash
docker --version
docker compose version
```

---

### 22.3 创建项目目录

```bash
mkdir -p /opt/xhs-to-obsidian
cd /opt/xhs-to-obsidian
```

将以下文件放入该目录：

```text
app.py
worker.py
extractor.py
llm.py
markdown_builder.py
github_writer.py
requirements.txt
Dockerfile
docker-compose.yml
.env
```

---

### 22.4 启动服务

```bash
cd /opt/xhs-to-obsidian
docker compose up -d --build
```

查看状态：

```bash
docker compose ps
```

查看日志：

```bash
docker compose logs -f api
docker compose logs -f worker
```

---

### 22.5 本机测试 API

```bash
curl -X POST http://127.0.0.1:8000/capture \
  -H "Content-Type: application/json" \
  -H "X-Capture-Token: 你的CAPTURE_TOKEN" \
  -d '{
    "platform": "xiaohongshu",
    "url": "https://www.xiaohongshu.com/",
    "share_text": "测试保存",
    "user_note": "这是一次部署测试"
  }'
```

成功返回：

```json
{
  "status": "queued",
  "job_id": "xhs_xxxxxxxx"
}
```

---

## 23. Nginx 配置

### 23.1 安装 Nginx

```bash
apt install -y nginx
```

### 23.2 创建站点配置

```bash
nano /etc/nginx/sites-available/xhs-capture
```

内容：

```nginx
server {
    listen 80;
    server_name capture.yourdomain.com;

    client_max_body_size 8m;

    location /capture {
        proxy_pass http://127.0.0.1:8000/capture;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
    }

    location /health {
        proxy_pass http://127.0.0.1:8000/health;
    }
}
```

启用：

```bash
ln -s /etc/nginx/sites-available/xhs-capture /etc/nginx/sites-enabled/xhs-capture
nginx -t
systemctl reload nginx
```

---

## 24. 域名与 HTTPS

### 24.1 DNS 设置

在域名 DNS 中添加 A 记录：

```text
capture.yourdomain.com → 你的阿里云公网 IP
```

测试：

```bash
curl http://capture.yourdomain.com/health
```

---

### 24.2 安装 Certbot

```bash
apt install -y certbot python3-certbot-nginx
```

申请证书：

```bash
certbot --nginx -d capture.yourdomain.com
```

测试 HTTPS：

```bash
curl https://capture.yourdomain.com/health
```

快捷指令最终使用：

```text
https://capture.yourdomain.com/capture
```

---

## 25. 阿里云安全组配置

在阿里云控制台：

```text
ECS 实例 → 安全组 → 入方向规则
```

建议开放：

| 端口 | 来源 | 用途 |
|---:|---|---|
| 22 | 你的固定 IP | SSH |
| 80 | 0.0.0.0/0 | HTTP / 证书 |
| 443 | 0.0.0.0/0 | HTTPS Webhook |

不开放：

| 端口 | 原因 |
|---:|---|
| 6379 | Redis 只供内部 Docker 网络访问 |
| 8000 | FastAPI 只供本机 Nginx 访问 |
| 3306 | 不需要 |
| 5432 | 不需要 |

---

## 26. GitHub 私有仓库配置

### 26.1 新建私有仓库

建议仓库名：

```text
obsidian-vault
```

设置为 Private。

### 26.2 创建目录

可以先在本地创建：

```text
00_Inbox/Xiaohongshu/
90_Assets/xiaohongshu/
Templates/
```

然后提交到 GitHub。

### 26.3 创建 GitHub Token

建议使用 Fine-grained personal access token。

权限只给目标仓库：

```text
Repository contents: Read and write
```

不要给全账号过大的权限。

将 token 放入 `.env`：

```bash
GITHUB_TOKEN=你的_github_pat
```

---

## 27. Obsidian 同步方案

### 27.1 推荐：Mac 本地 clone GitHub 仓库

```bash
cd ~/Documents
git clone git@github.com:你的GitHub用户名/obsidian-vault.git
```

然后在 Obsidian 中：

```text
Open folder as vault
→ 选择 ~/Documents/obsidian-vault
```

### 27.2 定时拉取

在 Mac 上设置 crontab：

```bash
crontab -e
```

添加：

```bash
*/5 * * * * cd ~/Documents/obsidian-vault && git pull
```

这样每 5 分钟同步一次。

### 27.3 iPhone 上同步

有三种方式：

1. 使用 Obsidian Sync
2. 使用 Obsidian Git 插件
3. 使用 iCloud Drive / 其他同步服务

最稳方案：

```text
GitHub 私有仓库
→ Mac 定时 git pull
→ Obsidian Sync 同步到 iPhone
```

---

## 28. 安全策略

必须做：

- Webhook 必须验证 `X-Capture-Token`
- OpenAI API Key 不放进快捷指令
- GitHub Token 不放进快捷指令
- Redis 不开放公网
- FastAPI 不开放公网，只走 Nginx
- Nginx 设置 `client_max_body_size`
- 截图上传前压缩
- HTTPS 必须启用
- GitHub Token 只给目标仓库写权限
- 阿里云安全组只开放 22、80、443

建议做：

- 给 `/capture` 加简单限流
- 日志中不要打印完整截图 Base64
- 对截图大小做限制
- 对请求体大小做限制
- 定期轮换 `CAPTURE_TOKEN`
- 定期轮换 GitHub Token

---

## 29. 小红书内容提取策略

采用三层兜底：

```text
第一层：分享链接
第二层：分享文案 / 页面 meta 信息
第三层：截图视觉识别
```

不建议做：

- 绕过登录
- 逆向签名
- 抓包
- 模拟 App 请求
- 批量采集推荐流
- 批量下载作者图片或视频
- 大规模监控账号

建议边界：

- 只保存你主动点击保存的内容
- 用于个人知识管理
- 保留来源链接
- 尊重原作者和平台规则
- 不对外分发抓取内容

---

## 30. MVP 实施顺序

建议严格按下面顺序做：

```text
第 1 步：准备 GitHub 私有仓库 obsidian-vault
第 2 步：准备阿里云 ECS
第 3 步：安装 Docker / Docker Compose
第 4 步：部署 FastAPI + Redis + Worker
第 5 步：先跑通 /capture 入队
第 6 步：先不接 LLM，测试写一条 Markdown 到 GitHub
第 7 步：接入 OpenAI，总结分享文本
第 8 步：接入截图 Base64 和图片理解
第 9 步：配置 Nginx + HTTPS
第 10 步：配置 iOS 分享快捷指令
第 11 步：配置截图快捷指令
第 12 步：配置 Obsidian 同步
第 13 步：加去重、失败队列、重试机制
第 14 步：优化 Prompt 和 Markdown 模板
```

---

## 31. 本地端到端测试流程

### 31.1 测试 API

```bash
curl -X POST http://127.0.0.1:8000/capture \
  -H "Content-Type: application/json" \
  -H "X-Capture-Token: 你的CAPTURE_TOKEN" \
  -d '{
    "platform": "xiaohongshu",
    "url": "https://www.xiaohongshu.com/",
    "share_text": "这是一条小红书测试分享",
    "user_note": "测试归档到 Obsidian"
  }'
```

### 31.2 查看 Worker 日志

```bash
docker compose logs -f worker
```

### 31.3 检查 GitHub

确认 GitHub 仓库出现：

```text
00_Inbox/Xiaohongshu/xxxx.md
```

### 31.4 检查 Obsidian

Mac 或 iPhone 上同步后，Obsidian 中应出现新笔记。

---

## 32. iOS 快捷指令上线检查

检查项：

- 分享表里能看到“保存小红书到 Obsidian”
- 点击后能拿到 URL
- 没有 URL 时能读取剪贴板
- 能输入备注
- POST 到 HTTPS Webhook
- 1 秒内提示“已入队”
- 后端日志中出现 job
- GitHub 中出现 Markdown
- Obsidian 中出现笔记

截图快捷指令检查项：

- 能截图
- 能压缩图片
- 能 Base64 编码
- 后端能收到 `screenshot_b64`
- LLM 能根据截图总结
- Markdown 中能引用截图

---

## 33. 后续增强方向

### 33.1 自动分类

根据内容自动分到：

```text
内容灵感
产品想法
AI 工具
生活技巧
旅行
美食
消费决策
职场
待实践
```

### 33.2 自动周报

每周生成：

```text
本周保存了哪些小红书内容
重复出现的主题
值得行动的建议
可以整理成文章的素材
```

### 33.3 语义搜索

后续可以把总结和原文做 embedding，支持：

```text
我之前保存过哪些关于日本旅行的小红书？
有哪些内容适合整理成选题？
我保存过哪些 AI 工具相关内容？
```

### 33.4 自动任务生成

如果 `action_items` 不为空，可以生成：

```markdown
- [ ] 尝试这个护肤流程
- [ ] 研究这个选题
- [ ] 加入下周内容计划
```

也可以同步到 Todoist、Notion、Apple Reminders。

---

## 34. 第一版验收标准

第一版完成后，应满足：

- iPhone 可以从小红书分享菜单触发
- API 能立即返回“已入队”
- 后台 Worker 能异步消费
- LLM 能生成总结和关键点
- Markdown 能提交到 GitHub 私有仓库
- Obsidian 能看到新笔记
- 失败任务不会丢失
- API Key 和 GitHub Token 不暴露在手机端
- Redis 和 FastAPI 不暴露公网
- HTTPS 可用

---

## 35. 最终结论

推荐第一版采用：

```text
iOS 快捷指令
→ 阿里云 ECS
→ Nginx HTTPS
→ FastAPI
→ Redis
→ Python Worker
→ OpenAI
→ GitHub 私有仓库
→ Obsidian
```

这套方案的优点：

- 成本低
- 可控性强
- 容易调试
- 不依赖复杂云产品
- 适合个人知识库自动化
- 后续可以平滑扩展到更复杂的内容管道

第一版不要追求“完美扒全文”，先跑通：

```text
一键保存 → 后台总结 → Markdown 入库 → Obsidian 可见
```

这条主链路跑通后，再逐步优化截图识别、去重、自动分类、周报和语义搜索。
