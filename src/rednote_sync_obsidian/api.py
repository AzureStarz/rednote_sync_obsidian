from __future__ import annotations

from typing import Any

from fastapi import FastAPI, Header, HTTPException
from fastapi.responses import JSONResponse

from .config import Settings, get_settings
from .jobs import build_job, serialize_job
from .models import CaptureRequest
from .queue import create_redis_client, enqueue_job
from .security import build_dedupe_key, resolve_capture_user


def create_app(settings: Settings | None = None, redis_client: Any | None = None) -> FastAPI:
    app = FastAPI(
        title="Rednote/Xiaohongshu to Obsidian Capture API",
        version="0.1.0",
        docs_url=None,
        redoc_url=None,
    )
    app.state.settings_override = settings
    app.state.redis_override = redis_client

    def current_settings() -> Settings:
        return app.state.settings_override or get_settings()

    def current_redis() -> Any:
        if app.state.redis_override is not None:
            return app.state.redis_override
        if not hasattr(app.state, "redis_client"):
            app.state.redis_client = create_redis_client(current_settings())
        return app.state.redis_client

    @app.get("/health")
    def health() -> dict[str, bool | str]:
        return {"ok": True, "service": "rednote-sync-obsidian"}

    @app.post("/capture")
    def capture(
        payload: CaptureRequest,
        x_capture_token: str | None = Header(default=None, alias="X-Capture-Token"),
    ) -> JSONResponse:
        settings_obj = current_settings()
        try:
            settings_obj.require_api()
        except RuntimeError as exc:
            raise HTTPException(status_code=500, detail=str(exc)) from exc

        try:
            capture_user = resolve_capture_user(
                x_capture_token,
                users_file=settings_obj.capture_users_file,
                fallback_token=settings_obj.capture_token,
            )
        except RuntimeError as exc:
            raise HTTPException(status_code=500, detail=str(exc)) from exc

        if capture_user is None:
            raise HTTPException(status_code=401, detail="Unauthorized")

        try:
            job = build_job(payload, settings_obj, owner=capture_user)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

        redis_obj = current_redis()
        dedupe_key = build_dedupe_key(job)

        if settings_obj.enable_dedupe:
            inserted = redis_obj.set(
                dedupe_key,
                job["job_id"],
                nx=True,
                ex=settings_obj.request_dedupe_ttl_seconds,
            )
            if inserted is None or inserted is False:
                existing_job_id = redis_obj.get(dedupe_key)
                return JSONResponse(
                    status_code=200,
                    content={
                        "status": "duplicate",
                        "job_id": existing_job_id,
                        "dedupe_key": dedupe_key,
                        "message": "This capture is already queued or processed within the dedupe window.",
                    },
                )

        enqueue_job(redis_obj, settings_obj, serialize_job(job))
        return JSONResponse(
            status_code=202,
            content={"status": "queued", "job_id": job["job_id"], "dedupe_key": dedupe_key},
        )

    return app


app = create_app()
