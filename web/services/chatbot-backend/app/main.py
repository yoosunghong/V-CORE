from contextlib import asynccontextmanager
import asyncio
import logging

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.infrastructure.container import AppContainer
from app.infrastructure.config import load_settings
from app.interfaces.http import router as http_router
from app.interfaces.ue5_ingest import router as ue5_http_router
from app.interfaces.ue5_ingest import ws_router as ue5_ws_router
from app.interfaces.websocket import router as websocket_router

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    container: AppContainer = app.state.container
    preload_task: asyncio.Task[None] | None = None

    async def preload_llm() -> None:
        # Retry indefinitely so a startup-ordering race (backend up before the local
        # llama.cpp/Ollama server) self-heals: the backend keeps "loading" and flips to
        # "ready" as soon as the model server is reachable — no manual restart needed.
        retry_seconds = 5.0
        container.set_llm_status("loading", "Loading local LLM model.")
        while True:
            try:
                await container.llm.preload()
                container.set_llm_status("ready", "LLM model is ready.")
                logger.info("LLM model preloaded for first chat response.")
                return
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                container.set_llm_status(
                    "loading", f"Waiting for LLM model server (retrying): {exc}"
                )
                logger.warning(
                    "LLM preload failed; retrying in %.0fs (chat stays loading until the model server is reachable): %s",
                    retry_seconds,
                    exc,
                )
                await asyncio.sleep(retry_seconds)

    if container.llm_status.get("status") == "loading":
        preload_task = asyncio.create_task(preload_llm())

    try:
        yield
    finally:
        if preload_task and not preload_task.done():
            preload_task.cancel()


def create_app() -> FastAPI:
    settings = load_settings()
    app = FastAPI(
        title="Virtual Process Chatbot Backend",
        version="0.1.0",
        description="Virtual Process digital-twin chatbot backend for the UE5 AGV cell.",
        lifespan=lifespan,
    )
    # When CORS_ALLOW_ORIGINS=* (ngrok / remote-proxy mode) credentials must be False.
    _wildcard = "*" in settings.cors_allow_origins
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"] if _wildcard else list(settings.cors_allow_origins),
        allow_credentials=not _wildcard,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    app.state.container = AppContainer()
    app.include_router(http_router)
    app.include_router(websocket_router)
    app.include_router(ue5_http_router)
    app.include_router(ue5_ws_router)
    return app


app = create_app()
