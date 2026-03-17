from __future__ import annotations

from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI

from app.api import api_router
from app.config import Settings, get_settings
from app.logging import configure_logging


def ensure_runtime_dirs(settings: Settings) -> None:
    Path(settings.upload_dir).mkdir(parents=True, exist_ok=True)
    Path(settings.parsed_dir).mkdir(parents=True, exist_ok=True)


@asynccontextmanager
async def lifespan(_: FastAPI):
    settings = get_settings()
    configure_logging(settings.log_level)
    ensure_runtime_dirs(settings)
    yield


def create_app() -> FastAPI:
    application = FastAPI(title="AskMyDocs", version="0.1.0", lifespan=lifespan)
    application.include_router(api_router)
    return application


app = create_app()
