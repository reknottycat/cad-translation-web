#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Main FastAPI application for the CAD translation backend."""

from __future__ import annotations

from contextlib import asynccontextmanager
from datetime import datetime, timezone
from pathlib import Path

import structlog
import uvicorn
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from .config import get_settings
from .database import Base, engine
from .routers import files, projects, translation
from .services.celery_app import check_celery_health


structlog.configure(
    processors=[
        structlog.stdlib.filter_by_level,
        structlog.stdlib.add_logger_name,
        structlog.stdlib.add_log_level,
        structlog.stdlib.PositionalArgumentsFormatter(),
        structlog.processors.TimeStamper(fmt="iso"),
        structlog.processors.StackInfoRenderer(),
        structlog.processors.format_exc_info,
        structlog.processors.UnicodeDecoder(),
        structlog.processors.JSONRenderer(),
    ],
    context_class=dict,
    logger_factory=structlog.stdlib.LoggerFactory(),
    wrapper_class=structlog.stdlib.BoundLogger,
    cache_logger_on_first_use=True,
)
logger = structlog.get_logger(__name__)

settings = get_settings()
static_dir = settings.get_static_path()
upload_dir = settings.get_upload_path()
output_dir = settings.get_output_path()
repo_root = Path(__file__).resolve().parents[2]
frontend_dist_dir = repo_root / "frontend" / "dist"
frontend_assets_dir = frontend_dist_dir / "assets"
frontend_index_file = frontend_dist_dir / "index.html"


@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("backend_starting", base_dir=str(settings.BASE_DIR))
    Base.metadata.create_all(bind=engine)
    settings.get_temp_path()
    logger.info(
        "backend_directories_ready",
        static=str(static_dir),
        uploads=str(upload_dir),
        outputs=str(output_dir),
    )
    yield
    logger.info("backend_stopped")


app = FastAPI(
    title="CAD Translation Web API",
    description="CAD translation processing platform with unified model configuration.",
    version="1.0.0",
    lifespan=lifespan,
    docs_url="/api/docs",
    redoc_url="/api/redoc",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.ALLOWED_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.mount("/static", StaticFiles(directory=str(static_dir)), name="static")
app.mount("/uploads", StaticFiles(directory=str(upload_dir)), name="uploads")
app.mount("/outputs", StaticFiles(directory=str(output_dir)), name="outputs")
if frontend_assets_dir.exists():
    app.mount("/assets", StaticFiles(directory=str(frontend_assets_dir)), name="frontend_assets")

app.include_router(projects.router, prefix="/api/projects", tags=["projects"])
app.include_router(files.router, prefix="/api/files", tags=["files"])
app.include_router(translation.router, tags=["translation"])

try:
    from app.api.routes.cad import router as cad_router

    app.include_router(cad_router, tags=["cad"])
except ImportError as exc:
    logger.warning("cad_router_import_failed", error=str(exc))
except Exception as exc:  # pragma: no cover - defensive logging for optional route
    logger.warning("cad_router_registration_failed", error=str(exc))


@app.post("/api/translate")
async def simple_translate(request: dict):
    from .services.alibaba_ai_translation_service import AlibabaBailianTranslationService

    service = AlibabaBailianTranslationService()
    try:
        translated_text = service.translate_text(
            text=request.get("text", ""),
            source_lang=request.get("source_lang", "auto"),
            target_lang=request.get("target_lang", "zh"),
        )
        return {
            "success": True,
            "original_text": request.get("text", ""),
            "translated_text": translated_text,
            "source_lang": request.get("source_lang", "auto"),
            "target_lang": request.get("target_lang", "zh"),
        }
    except Exception as exc:
        return {
            "success": False,
            "error": str(exc),
            "original_text": request.get("text", ""),
            "translated_text": f"[translation_failed]{request.get('text', '')}",
            "source_lang": request.get("source_lang", "auto"),
            "target_lang": request.get("target_lang", "zh"),
        }


@app.get("/")
async def root():
    if frontend_index_file.exists():
        return FileResponse(frontend_index_file)
    return {
        "message": "CAD translation backend API",
        "version": "1.0.0",
        "docs": "/api/docs",
        "status": "running",
    }


@app.get("/api/health")
async def health_check():
    celery_info = check_celery_health()
    celery_healthy = celery_info["status"] == "healthy"

    return {
        "status": "healthy" if celery_healthy else "degraded",
        "celery": celery_info["mode"],
        "async_runtime": celery_info,
        "database": "connected",
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }


@app.exception_handler(HTTPException)
async def http_exception_handler(request, exc: HTTPException):
    logger.error("http_exception", status_code=exc.status_code, detail=exc.detail)
    return JSONResponse(
        status_code=exc.status_code,
        content={"error": exc.detail, "status_code": exc.status_code},
    )


@app.exception_handler(Exception)
async def general_exception_handler(request, exc: Exception):
    logger.error("unhandled_exception", error=str(exc), exc_info=True)
    return JSONResponse(
        status_code=500,
        content={"error": "internal server error", "status_code": 500},
    )


@app.get("/{path:path}")
async def frontend_fallback(path: str):
    if path in {"openapi.json"} or path.startswith(("api/", "static/", "uploads/", "outputs/")):
        raise HTTPException(status_code=404, detail="not found")
    if frontend_index_file.exists():
        return FileResponse(frontend_index_file)
    raise HTTPException(status_code=404, detail="not found")


if __name__ == "__main__":
    uvicorn.run(
        "app.main:app",
        host=settings.HOST,
        port=settings.PORT,
        reload=settings.DEBUG,
        log_level="debug" if settings.DEBUG else "info",
    )
