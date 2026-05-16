# Advanced Implementation Plan — Raw Rednote Capture + Obsidian Sync

## 1. Decision

The project now uses a raw-first capture architecture:

```text
iOS Shortcut -> FastAPI /capture -> Redis -> worker -> server raw bundle -> SSH/rsync -> local raw_rednote_post_vault
```

The worker no longer performs LLM summarization and no longer writes raw captures to GitHub. GitHub and LLM modules are retained only as optional/legacy building blocks for a later processed-note stage.

## 2. Why this replaces the previous design

Problems in the previous MVP:

1. The crawler extracted text for summarization but did not persist the original HTML.
2. The worker spent time/cost on LLM summarization in the ingestion path.
3. GitHub repository storage is a poor raw-asset target because HTML/images can grow quickly and hit repository-size or workflow constraints.

New design benefits:

- Raw evidence is preserved first: `source.html`, images, headers, manifest, and extraction report.
- Capture stays cheap and recoverable because LLM processing is decoupled.
- Server disk/object storage can scale independently from a processed Obsidian/GitHub note workflow.
- Local Obsidian receives a complete raw vault via rsync without exposing GitHub tokens or LLM keys.

## 3. Implemented pipeline

### API

- `POST /capture` still accepts URL/share text/user note/screenshot payloads.
- API validates `X-Capture-Token`, applies dedupe, and returns `202 queued`.
- iOS Shortcut contract remains compatible.

### Worker

For each job, the worker:

1. Extracts the URL from `share_text` if `url` is missing.
2. Fetches the page with configured `CRAWL_COOKIE`, `CRAWL_USER_AGENT`, timeout, and byte limits.
3. Saves the raw response as `source.html`.
4. Extracts page metadata and image candidates.
5. Downloads reachable images using the same Cookie/Referer context.
6. Saves any attached screenshot as `images/screenshot.jpg`.
7. Writes `request.json`, redacted `response_headers.json`, `extraction_report.json`, `manifest.json`, and `index.md`.
8. Commits the bundle atomically from `.tmp/` into `posts/YYYY/MM/DD/{job_id}/`.

### Storage

Server root defaults to:

```text
/data/rednote_raw
```

Per-capture bundle:

```text
posts/YYYY/MM/DD/xhs_xxxxx/
  index.md
  manifest.json
  source.html
  request.json
  response_headers.json
  extraction_report.json
  images/
```

### Sync

`scripts/sync_raw_vault.py` wraps rsync:

```bash
python scripts/sync_raw_vault.py \
  --server user@host \
  --remote-root /data/rednote_raw \
  --local-vault ~/Documents/raw_rednote_post_vault
```

Defaults are non-destructive: no local deletion unless `--prune` is explicitly passed.

## 4. Configuration

Required for API:

```bash
CAPTURE_TOKEN=...
REDIS_URL=redis://redis:6379/0
```

Required for worker:

```bash
REDIS_URL=redis://redis:6379/0
RAW_STORAGE_ROOT=/data/rednote_raw
```

Recommended crawler settings:

```bash
CRAWL_COOKIE=...
CRAWL_USER_AGENT=...
CRAWL_TIMEOUT_SECONDS=20
DOWNLOAD_IMAGES=true
MAX_IMAGES_PER_POST=50
MAX_IMAGE_BYTES=10485760
MAX_HTML_BYTES=10485760
RAW_INDEX_MARKDOWN=true
```

No longer required for raw capture:

```bash
LLM_API_KEY
GITHUB_TOKEN
GITHUB_REPO
```

## 5. Acceptance criteria

- Worker starts without LLM or GitHub credentials.
- A capture writes a server bundle under `RAW_STORAGE_ROOT/posts/...`.
- `source.html` always exists, even if empty on failed fetch.
- Image success/failure is recorded per candidate in `manifest.json`.
- Cookie/Set-Cookie/Authorization-like headers are redacted from persisted metadata.
- `index.md` is readable in Obsidian and links to raw files/images.
- `scripts/sync_raw_vault.py --dry-run` shows an rsync plan without writing files.
- Test suite passes.

## 6. Verification evidence

Current implementation verification:

```text
python -m pytest -q
26 passed

python -m compileall src tests scripts
success

docker-compose config
success
```
