# Rednote/Xiaohongshu Raw Capture → Obsidian Raw Vault

This project captures Rednote/Xiaohongshu shares from iOS Shortcuts, stores the original page response plus reachable images/videos on your server, then syncs those raw bundles into a local Obsidian vault such as `raw_rednote_post_vault`.

The main pipeline is now raw-only:

```text
iOS Shortcut
  -> HTTPS POST /capture
  -> FastAPI validates X-Capture-Token and enqueues job
  -> Redis
  -> Worker fetches Rednote page with optional server-side Cookie
  -> Worker saves raw HTML, images, videos, manifest, and index.md on server disk
  -> Mac sync script pulls server files with SSH/rsync
  -> Obsidian opens raw_rednote_post_vault locally
```

No LLM summary is executed in the worker, and GitHub is no longer the storage target for raw captures.

## What is implemented

- FastAPI API: `POST /capture`, `GET /health`
- Token authentication via `X-Capture-Token`, with optional multi-user token routing
- Redis async queue + dedupe window
- Raw page fetch with optional server-side `CRAWL_COOKIE`
- Original `source.html` storage for every processed bundle
- Best-effort image URL extraction from meta tags, `img/srcset`, lazy image attributes, and HTML text
- Best-effort image download with Referer/Cookie headers
- Best-effort video extraction/download from `og:video` and Rednote `sns-video` MP4 URLs
- Attached screenshot preservation when `screenshot_b64` is provided
- Per-capture `manifest.json`, `request.json`, `response_headers.json`, `extraction_report.json`, and Obsidian-readable `index.md`
- Server-local raw storage volume in Docker Compose
- `scripts/sync_raw_vault.py` wrapper around SSH/rsync for per-user local Obsidian sync
- Optional legacy LLM/GitHub modules retained for future offline/processed-note workflows, but not required by the worker

## Repository layout

```text
src/rednote_sync_obsidian/
  api.py                # FastAPI app
  worker.py             # Redis consumer / raw capture pipeline
  config.py             # Environment settings
  models.py             # Request models
  jobs.py               # Job validation/serialization
  extractor.py          # URL, page fetch, metadata, image extraction/download
  raw_storage.py        # Atomic server-side raw bundle writer
  llm.py                # Optional legacy/offline summarizer
  markdown_builder.py   # Optional legacy processed-note Markdown builder
  github_writer.py      # Optional legacy GitHub Contents writer
  queue.py              # Redis helpers
  security.py           # token + dedupe helpers
scripts/
  requeue_failed.py
  sync_raw_vault.py
nginx/xhs-capture.conf
tests/
```

## Local verification

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements-dev.txt
pytest
python -m compileall src tests scripts
```

Expected: all tests pass and compileall exits with status 0.

## Configure `.env`

```bash
cp .env.example .env
openssl rand -hex 32
```

Minimum server configuration:

```bash
REDIS_URL=redis://redis:6379/0
RAW_STORAGE_ROOT=/data/rednote_raw
RAW_STORAGE_HOST_PATH=./data/rednote_raw
```

Single-user mode can use:

```bash
CAPTURE_TOKEN=<random token>
```

For Hongbin/Zhangyu isolation, prefer multi-user mode:

```bash
mkdir -p /opt/rednote_sync_obsidian/secrets
chmod 700 /opt/rednote_sync_obsidian/secrets
openssl rand -hex 32
openssl rand -hex 32
cat > /opt/rednote_sync_obsidian/secrets/capture_users.json <<'JSON'
{
  "hongbin": {
    "display_name": "Hongbin",
    "token": "replace_with_first_random_token"
  },
  "zhangyu": {
    "display_name": "Zhangyu",
    "token": "replace_with_second_random_token"
  }
}
JSON
chmod 600 /opt/rednote_sync_obsidian/secrets/capture_users.json
```

Then set:

```bash
CAPTURE_USERS_FILE=/opt/rednote_sync_obsidian/secrets/capture_users.json
```

When `CAPTURE_USERS_FILE` is set, it takes precedence over `CAPTURE_TOKEN`. The request body never includes the user id; the server derives `owner_id` from the token.

Optional but recommended for logged-in Rednote pages:

```bash
CRAWL_COOKIE=<your Rednote/Xiaohongshu browser Cookie copied to the server only>
CRAWL_USER_AGENT="Mozilla/5.0 ... Chrome/125.0 Safari/537.36"
DOWNLOAD_IMAGES=true
DOWNLOAD_VIDEOS=true
MAX_IMAGES_PER_POST=50
MAX_VIDEOS_PER_POST=5
MAX_IMAGE_BYTES=10485760
MAX_VIDEO_BYTES=209715200
MAX_HTML_BYTES=10485760
RAW_INDEX_MARKDOWN=true
```

Cookie safety:

- Keep `CRAWL_COOKIE` only in the server `.env`.
- Do not put it into iOS Shortcuts, GitHub, Obsidian, or logs.
- The app redacts Cookie/Set-Cookie-like headers from persisted response/request metadata.
- Rotate it when it expires or when you suspect exposure.

The worker does **not** require:

```bash
LLM_API_KEY
GITHUB_TOKEN
GITHUB_REPO
```

## Raw bundle format

Each capture writes an immutable-style bundle under `RAW_STORAGE_ROOT` inside the worker container. Docker Compose mounts host `RAW_STORAGE_HOST_PATH` there so your Mac can pull the same files over SSH:

```text
/data/rednote_raw/
  users/
    hongbin/
      posts/
        2026/
          05/
            16/
              xhs_abcd1234/
                index.md
                manifest.json
                source.html
                request.json
                response_headers.json
                extraction_report.json
                images/
                  screenshot.jpg
                  001.jpg
                  002.webp
                videos/
                  001.mp4
    zhangyu/
      posts/
        ...
```

Important files:

- `source.html` — raw HTML response bytes, truncated only if `MAX_HTML_BYTES` is exceeded.
- `manifest.json` — canonical machine-readable record with status, URLs, hashes, image results, and errors.
- `index.md` — non-LLM Obsidian index with source URL, metadata, raw file links, share text, note, and image embeds.
- `images/` — downloaded page images and any attached screenshot.
- `videos/` — downloaded MP4 video files when the page exposes a direct video URL.
- `extraction_report.json` — image candidate/download counts and page fetch errors.

Status meanings:

- `complete`: HTML saved, no page error, no image failures.
- `partial`: HTML or at least one image/screenshot saved, but page fetch or image extraction had failures.
- `failed`: no HTML and no image content could be saved; error details are preserved.

## Run locally with Docker Compose

```bash
docker compose up -d --build
docker compose ps
curl http://127.0.0.1:8000/health
```

Queue a test capture:

```bash
curl -X POST http://127.0.0.1:8000/capture \
  -H "Content-Type: application/json" \
  -H "X-Capture-Token: $CAPTURE_TOKEN" \
  -d '{
    "platform": "xiaohongshu",
    "url": "https://www.xiaohongshu.com/",
    "share_text": "本地测试：保存一条小红书原始内容",
    "user_note": "raw capture smoke test"
  }'
```

Watch processing:

```bash
docker compose logs -f api
docker compose logs -f worker
```

Inspect the raw volume:

```bash
docker compose exec worker find /data/rednote_raw -maxdepth 6 -type f | sort
find ./data/rednote_raw -maxdepth 6 -type f | sort
```

## Deploy on VPS / Aliyun ECS

Install Docker, copy the project to the server, create `.env`, then run:

```bash
cd /opt/rednote-sync-obsidian
docker compose up -d --build
docker compose ps
curl http://127.0.0.1:8000/health
```

Expose only Nginx/HTTPS publicly. Do **not** expose Redis or FastAPI directly.

Inbound firewall/security group:

| Port | Source | Why |
|---:|---|---|
| 22 | your IP if possible | SSH admin + rsync sync |
| 80 | 0.0.0.0/0 | Certbot HTTP challenge / redirect |
| 443 | 0.0.0.0/0 | iOS webhook |

Do **not** open 6379 or 8000 publicly.

## iOS Shortcut

Shortcut settings:

- Name: `保存小红书原始内容`
- Show in Share Sheet: enabled
- Accepted input: URL, Text, Rich Text, Images

Actions:

1. Get Shortcut Input.
2. Extract URL from input. If empty, get Clipboard and extract URL.
3. Ask for input: `我的备注（可选）`.
4. Dictionary:

   ```json
   {
     "platform": "xiaohongshu",
     "url": "<extracted URL>",
     "share_text": "<shortcut input text>",
     "user_note": "<your note>",
     "captured_at": "<current date ISO-ish>"
   }
   ```

5. Get Contents of URL:
   - URL: `https://capture.your-real-domain.com/capture`
   - Method: `POST`
   - Headers:
     - `Content-Type: application/json`
     - `X-Capture-Token: <personal token from capture_users.json or CAPTURE_TOKEN>`
   - Request Body: JSON dictionary
6. Show notification: `已入队` plus returned `job_id`.

Optional screenshot fallback: include `screenshot_b64` in the same JSON. The screenshot will be saved under `images/screenshot.jpg` in the raw bundle.

## Local permanent storage + one-month server cache

This is the no-OSS storage model:

```text
Server / VPS: temporary cache only, for example 30 days
Mac / local machine: permanent raw_rednote_post_vault
```

Important rule: **do not run an independent server-side cron that deletes old bundles.** Let the Mac sync script pull first, verify local hashes, and only then prune old server cache. This prevents data loss if your Mac was offline for a while.

### 1) Make server storage host-visible

Docker Compose mounts this host path into the worker container:

```bash
RAW_STORAGE_ROOT=/data/rednote_raw
RAW_STORAGE_HOST_PATH=./data/rednote_raw
```

If your project is deployed at `/opt/rednote_sync_obsidian`, the host-visible path for SSH/rsync is usually:

```text
/opt/rednote_sync_obsidian/data/rednote_raw
```

If you prefer an absolute host directory, set:

```bash
RAW_STORAGE_HOST_PATH=/data/rednote_raw
```

Then use `/data/rednote_raw` as `--remote-root`.

### 2) Dry-run sync from Mac

Install/use `rsync` and SSH access from your Mac to the server, then run:

```bash
python scripts/sync_raw_vault.py \
  --server user@your-server \
  --remote-root /opt/rednote_sync_obsidian/data/rednote_raw \
  --owner hongbin \
  --local-vault ~/Documents/raw_rednote_post_vault \
  --dry-run
```

### 3) Normal sync without deletion

```bash
python scripts/sync_raw_vault.py \
  --server user@your-server \
  --remote-root /opt/rednote_sync_obsidian/data/rednote_raw \
  --owner hongbin \
  --local-vault ~/Documents/raw_rednote_post_vault
```

For Zhangyu, use `--owner zhangyu` and a separate local vault path if desired.

The script verifies local bundle hashes from `manifest.json` after rsync. If verification fails, it exits non-zero.

### 4) Sync and keep only one month on the server

After you trust the dry-run, use:

```bash
python scripts/sync_raw_vault.py \
  --server user@your-server \
  --remote-root /opt/rednote_sync_obsidian/data/rednote_raw \
  --owner hongbin \
  --local-vault ~/Documents/raw_rednote_post_vault \
  --remote-cache-days 30
```

Behavior:

- Pulls server files into local permanent vault.
- Verifies local file hashes.
- Only if verification succeeds, deletes server bundles older than 30 days.
- Server `.tmp/` staging directories are excluded.
- Local files are never deleted unless you explicitly pass `--prune`, which is not recommended for permanent local storage.

If remote deletion needs root permissions, add:

```bash
--remote-prune-sudo
```

Open the synced folder in Obsidian:

```text
Open folder as vault -> ~/Documents/raw_rednote_post_vault
```

Optional macOS cron example, every 10 minutes:

```bash
*/10 * * * * cd /path/to/rednote_sync_obsidian && .venv/bin/python scripts/sync_raw_vault.py --server user@your-server --remote-root /opt/rednote_sync_obsidian/data/rednote_raw --owner hongbin --local-vault ~/Documents/raw_rednote_post_vault --remote-cache-days 30
```

## Operations

Check services:

```bash
docker compose ps
docker compose logs -f api
docker compose logs -f worker
```

Check Redis queues:

```bash
docker compose exec redis redis-cli LLEN xhs_capture_queue
docker compose exec redis redis-cli LLEN xhs_capture_failed
```

Requeue failed jobs:

```bash
docker compose run --rm worker python scripts/requeue_failed.py
```

Backfill images/videos for already-saved raw bundles after extractor fixes or Cookie updates:

```bash
python scripts/backfill_raw_images.py --root /data/rednote_raw --rebuild-images --rebuild-videos
```

For a local test storage root:

```bash
python scripts/backfill_raw_images.py --root data/rednote_raw --rebuild-images --rebuild-videos
```

Check server cache usage:

```bash
du -sh ./data/rednote_raw
find ./data/rednote_raw/users/hongbin/posts -type f | wc -l
find ./data/rednote_raw/users/zhangyu/posts -type f | wc -l
```

Recommended maintenance:

- Treat each user's local `raw_rednote_post_vault` as that user's permanent copy.
- Back up the local vault with Time Machine or another local backup if the data is important.
- Keep server cache deletion tied to successful Mac sync via `--remote-cache-days 30`; do not delete independently on the server.
- Monitor disk usage.
- Rotate per-user tokens in `capture_users.json` and rotate `CRAWL_COOKIE` periodically.
- Keep raw capture and processed/LLM summaries as separate stages.

## iOS Shortcut generator

Generate a Shortcut file that POSTs Rednote text/URL to `/capture`. The default mode is clipboard-based because Xiaohongshu may not expose the iOS system Share Sheet: tap Copy Link in Xiaohongshu, then run the Shortcut from the Shortcuts app, Home Screen, Siri, Back Tap, or widget.

Temporary HTTP endpoint before ICP approval. Run this on the Mac/local repo with a local ignored copy of `secrets/capture_users.json` containing the same tokens as the server file:

```bash
python scripts/make_ios_shortcut.py \
  --endpoint http://120.24.177.252:8080/capture \
  --users-file secrets/capture_users.json \
  --user hongbin \
  --name 保存小红书原始帖子-Hongbin \
  --input-source clipboard
```

Zhangyu's shortcut:

```bash
python scripts/make_ios_shortcut.py \
  --endpoint http://120.24.177.252:8080/capture \
  --users-file secrets/capture_users.json \
  --user zhangyu \
  --name 保存小红书原始帖子-Zhangyu \
  --input-source clipboard
```

Production endpoint after ICP approval:

```bash
python scripts/make_ios_shortcut.py \
  --endpoint https://capture.hbzhang.top/capture \
  --users-file secrets/capture_users.json \
  --user hongbin \
  --name 保存小红书原始帖子-Hongbin \
  --input-source clipboard
```

If another app exposes the iOS system Share Sheet and you want to use Share Sheet input instead of the clipboard, pass `--input-source share-sheet`.

The script reads the selected user's token from `--users-file`/`--user`, or falls back to `CAPTURE_TOKEN` when not using multi-user mode. It embeds that token into the generated Shortcut, so output defaults to ignored local storage under `data/shortcuts/`.

If macOS signing succeeds, open the printed `.shortcut` file on iPhone or AirDrop it to the phone and add it to Shortcuts. If signing times out, the script prints an unsigned `.shortcut`; create the shortcut manually or retry signing later with:

```bash
shortcuts sign --mode anyone \
  --input data/shortcuts/保存小红书原始帖子.unsigned.shortcut \
  --output data/shortcuts/保存小红书原始帖子.shortcut
```

Do not commit generated `.shortcut` files because they contain a capture token.
