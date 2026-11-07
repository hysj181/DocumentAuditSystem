"""Minimal FastAPI application used to validate the unified environment."""

from __future__ import annotations

from fastapi import FastAPI


def create_app() -> FastAPI:
    """Create the minimal application; the full web UI is added later."""

    app = FastAPI(title="DocumentAuditSystem V2.0", version="0.1.0")

    @app.get("/health")
    def health() -> dict[str, str]:
        return {"status": "ok"}

    return app


app = create_app()
