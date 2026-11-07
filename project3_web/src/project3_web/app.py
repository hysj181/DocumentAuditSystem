"""FastAPI web application for document upload, audit, and downloads."""

from __future__ import annotations

import logging
import os
import shutil
from pathlib import Path
from typing import Annotated, Any

from fastapi import BackgroundTasks, FastAPI, File, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from project3_web.services import (
    PROCESSING_STATUSES,
    STATUS_LABELS,
    process_task,
)
from project3_web.task_store import (
    TaskStore,
    new_task_id,
    safe_filename,
    sha256_file,
    unique_filename,
    utc_now_iso,
)

logger = logging.getLogger(__name__)

ALLOWED_SUFFIXES = {".docx", ".pdf"}
DEFAULT_MAX_UPLOAD_BYTES = 50 * 1024 * 1024


def _default_data_root() -> Path:
    configured = os.environ.get("DOCUMENT_AUDIT_DATA_DIR", "").strip()
    if configured:
        return Path(configured).expanduser().resolve()
    return Path(__file__).resolve().parents[2] / "data"


def _task_or_404(store: TaskStore, task_id: str) -> dict[str, Any]:
    task = store.load(task_id)
    if task is None:
        raise HTTPException(status_code=404, detail="审核任务不存在")
    return task


def _task_context(
    request: Request,
    store: TaskStore,
    task: dict[str, Any],
) -> dict[str, Any]:
    artifacts = task.get("artifacts") or {}
    artifact_items = (
        [
            {"id": artifact_id, **artifact}
            for artifact_id, artifact in artifacts.items()
            if isinstance(artifact, dict)
        ]
        if isinstance(artifacts, dict)
        else []
    )
    return {
        "request": request,
        "task": task,
        "status_label": STATUS_LABELS.get(
            str(task.get("status")),
            str(task.get("status")),
        ),
        "is_processing": task.get("status") in PROCESSING_STATUSES,
        "artifacts": list(artifacts.values()) if isinstance(artifacts, dict) else [],
        "artifact_items": artifact_items,
        "has_annotated_artifact": any(
            artifact.get("kind") in {"word", "pdf"}
            for artifact in artifact_items
        ),
    }


def _render_upload_error(
    request: Request,
    message: str,
    *,
    status_code: int = 400,
):
    return request.app.state.templates.TemplateResponse(
        request=request,
        name="upload.html",
        context={"error": message},
        status_code=status_code,
    )


def create_app(
    data_dir: str | Path | None = None,
    *,
    extraction_mode: str | None = None,
) -> FastAPI:
    """Create the full web application.

    ``data_dir`` is injectable for tests. Production defaults to
    ``project3_web/data`` or ``DOCUMENT_AUDIT_DATA_DIR``.
    """

    app = FastAPI(title="DocumentAuditSystem V2.0", version="0.2.0")
    data_root = Path(data_dir).expanduser().resolve() if data_dir else _default_data_root()
    store = TaskStore(data_root / "tasks")
    templates = Jinja2Templates(
        directory=str(Path(__file__).with_name("templates"))
    )

    app.state.data_root = data_root
    app.state.task_store = store
    app.state.templates = templates
    app.state.extraction_mode = extraction_mode
    app.state.max_upload_bytes = int(
        os.environ.get("DOCUMENT_AUDIT_MAX_UPLOAD_BYTES", DEFAULT_MAX_UPLOAD_BYTES)
    )

    static_dir = Path(__file__).with_name("static")
    if static_dir.is_dir():
        app.mount("/static", StaticFiles(directory=static_dir), name="static")

    @app.get("/health")
    def health() -> dict[str, str]:
        return {"status": "ok"}

    @app.get("/")
    def index(request: Request):
        tasks = store.list_tasks()[:5]
        return templates.TemplateResponse(
            request=request,
            name="index.html",
            context={"tasks": tasks, "status_labels": STATUS_LABELS},
        )

    @app.get("/upload")
    def upload_page(request: Request):
        return templates.TemplateResponse(
            request=request,
            name="upload.html",
            context={"error": request.query_params.get("error")},
        )

    @app.post("/upload")
    async def upload_documents(
        request: Request,
        background_tasks: BackgroundTasks,
        files: Annotated[list[UploadFile], File()],
    ):
        selected = [item for item in files if item.filename]
        if not selected:
            return _render_upload_error(request, "请选择至少一个 .docx 或 .pdf 文件。")

        for item in selected:
            suffix = Path(item.filename or "").suffix.casefold()
            if suffix not in ALLOWED_SUFFIXES:
                return _render_upload_error(
                    request,
                    f"不支持的文件类型：{item.filename}。仅支持 .docx 和 .pdf。",
                )

        task_id = new_task_id()
        task_dir = store.task_dir(task_id)
        if task_dir is None:
            return _render_upload_error(request, "无法创建审核任务。", status_code=500)
        upload_dir = task_dir / "uploads"
        uploads: list[dict[str, Any]] = []

        try:
            task_dir.mkdir(parents=True, exist_ok=False)
            upload_dir.mkdir(parents=True, exist_ok=True)
            for item in selected:
                stored = unique_filename(
                    upload_dir,
                    safe_filename(item.filename or "upload"),
                )
                size = 0
                with stored.open("wb") as handle:
                    while True:
                        chunk = await item.read(1024 * 1024)
                        if not chunk:
                            break
                        size += len(chunk)
                        if size > request.app.state.max_upload_bytes:
                            raise ValueError(
                                f"{item.filename} 超过大小限制 "
                                f"{request.app.state.max_upload_bytes} 字节。"
                            )
                        handle.write(chunk)
                if size == 0:
                    raise ValueError(f"{item.filename} 是空文件。")
                uploads.append(
                    {
                        "original_name": Path(item.filename or stored.name).name,
                        "stored_name": stored.name,
                        "content_type": item.content_type,
                        "size": size,
                        "sha256": sha256_file(stored),
                        "uploaded_at": utc_now_iso(),
                    }
                )
            store.create_task(task_id=task_id, uploads=uploads)
        except Exception as exc:
            logger.exception("upload failed")
            shutil.rmtree(task_dir, ignore_errors=True)
            return _render_upload_error(
                request,
                f"上传失败：{type(exc).__name__}: {exc}",
            )

        background_tasks.add_task(
            process_task,
            store,
            task_id,
            mode=request.app.state.extraction_mode,
        )
        return RedirectResponse(
            url=f"/tasks/{task_id}/status",
            status_code=303,
        )

    @app.get("/tasks")
    def task_list(request: Request):
        return templates.TemplateResponse(
            request=request,
            name="tasks.html",
            context={
                "tasks": store.list_tasks(),
                "status_labels": STATUS_LABELS,
            },
        )

    @app.get("/tasks/{task_id}/status")
    def task_status(request: Request, task_id: str):
        task = _task_or_404(store, task_id)
        return templates.TemplateResponse(
            request=request,
            name="task_status.html",
            context=_task_context(request, store, task),
        )

    @app.get("/tasks/{task_id}")
    def task_detail(request: Request, task_id: str):
        task = _task_or_404(store, task_id)
        return templates.TemplateResponse(
            request=request,
            name="task_detail.html",
            context=_task_context(request, store, task),
        )

    @app.get("/tasks/{task_id}/download/{artifact_id}")
    def download_artifact(request: Request, task_id: str, artifact_id: str):
        task = _task_or_404(store, task_id)
        path = store.artifact_path(task, artifact_id)
        if path is None:
            raise HTTPException(status_code=404, detail="下载文件不存在")
        return FileResponse(
            path,
            filename=store.artifact_filename(task, artifact_id),
        )

    return app


app = create_app()
