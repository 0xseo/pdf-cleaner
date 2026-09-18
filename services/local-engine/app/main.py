from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from .api.routes import router
from .config import ensure_runtime_dirs


@asynccontextmanager
async def lifespan(_: FastAPI):
    ensure_runtime_dirs()
    yield


app = FastAPI(
    title="PDF Cleaner Local Engine",
    version="0.1.0",
    description="Localhost-only PDF analysis and export engine.",
    lifespan=lifespan,
)
app.add_middleware(
    CORSMiddleware,
    allow_origin_regex=(
        r"^(?:https?://(?:localhost|127\.0\.0\.1)(?::\d+)?|"
        r"https://handwriting-eraser\.0xseo94\.com)$"
    ),
    allow_credentials=False,
    allow_methods=["GET", "POST", "PATCH", "DELETE", "OPTIONS"],
    allow_headers=["Content-Type"],
)
app.include_router(router)
