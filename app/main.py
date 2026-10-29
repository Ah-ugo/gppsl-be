"""GPPSL platform API. One FastAPI app, many small modules."""

from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from app.core.config import get_settings
from app.core.db import get_db, init_indexes
from app.core.storage import upload_folder
from app.modules.audit.router import router as audit_router
from app.modules.auth.router import router as auth_router, users_router
from app.modules.documents.files import router as files_router
from app.modules.notifications.router import router as notifications_router
from app.modules.settings.router import router as settings_router

# Routers for later phases are registered in app/routers.py (kept separate so each phase just adds a line).
from app.routers import extra_routers


@asynccontextmanager
async def lifespan(app: FastAPI):
    await init_indexes()
    scheduler = None
    if get_settings().enable_scheduler:
        from app.jobs.scheduler import start_scheduler

        scheduler = start_scheduler()
    yield
    if scheduler:
        scheduler.shutdown(wait=False)


def create_app() -> FastAPI:
    s = get_settings()
    app = FastAPI(title=s.app_name, version="1.0.0", lifespan=lifespan)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=s.cors_list,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    @app.get("/health", tags=["system"])
    async def health():
        await get_db().command("ping") if not s.use_mock_db else None
        return {
            "status": "ok",
            "app": s.app_name,
            "demo_mode": s.demo_mode,
            "ai": (
                "mistral" if s.mistral_api_key else "unavailable (no MISTRAL_API_KEY)"
            ),
            "storage": "cloudinary" if s.cloudinary_url else "local",
            "email": (
                "configured"
                if (s.resend_api_key or s.brevo_api_key or s.smtp_host)
                else "demo-logged"
            ),
        }

    for r in (
        auth_router,
        users_router,
        audit_router,
        notifications_router,
        settings_router,
        files_router,
        *extra_routers,
    ):
        app.include_router(r)

    folder = upload_folder()
    try:
        app.mount("/uploads", StaticFiles(directory=str(folder)), name="uploads")
    except RuntimeError:
        pass
    return app


app = create_app()
