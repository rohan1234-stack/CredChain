# ---------------------------------------------------------------------------
# FastAPI application entrypoint.
#
# Phase 1: app wiring, CORS, and a health endpoint that confirms the API
# process is up AND can reach PostgreSQL. Route modules (auth, credentials,
# etc.) are added here with app.include_router(...) starting Phase 3.
# ---------------------------------------------------------------------------

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import text

from .config import settings
from .database import engine
from .routes import activity as activity_routes
from .routes import admin as admin_routes
from .routes import ai as ai_routes
from .routes import auth as auth_routes
from .routes import credentials as credential_routes
from .routes import companies as company_routes
from .routes import institutions as institution_routes
from .routes import jobs as job_routes
from .routes import notifications as notification_routes
from .routes import requests as request_routes
from .routes import sharing as sharing_routes
from .routes import students as student_routes
from .routes import verification as verification_routes

app = FastAPI(
    title="CredChain API",
    description="Backend for CredChain — a student-owned academic credential passport.",
    version="0.1.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins_list,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(auth_routes.router)
app.include_router(institution_routes.router)
app.include_router(student_routes.router)
app.include_router(credential_routes.router)
app.include_router(verification_routes.router)
app.include_router(request_routes.router)
app.include_router(sharing_routes.router)
app.include_router(sharing_routes.me_router)
app.include_router(ai_routes.router)
app.include_router(activity_routes.router)
app.include_router(notification_routes.router)
app.include_router(company_routes.router)
app.include_router(job_routes.router)
app.include_router(admin_routes.router)


@app.get("/api/health", tags=["health"])
def health_check() -> dict:
    """Liveness/readiness probe: confirms the API is running and the database is reachable."""
    try:
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
        database_status = "connected"
    except Exception:
        database_status = "unavailable"

    return {"status": "ok", "database": database_status}
