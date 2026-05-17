"""
AI Bridge — FastAPI Entry Point
─────────────────────────────────────────
Service ini menjadi jembatan antara:
  Frontend (SvelteKit) ↔ AI (Openclaw) ↔ Database (PostgreSQL)

Jalankan:
  uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload
"""

from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.config import get_settings
from app.routers.chat import router as chat_router

settings = get_settings()


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Startup dan shutdown events."""
    # ── Startup ──────────────────────────────────────────
    print("=" * 50)
    print("🚀 AI Bridge Starting...")
    print(f"   Model    : {settings.openclaw_model}")
    print(f"   Openclaw : {settings.openclaw_base_url}")
    print(f"   Database : {settings.database_url.split('@')[1] if '@' in settings.database_url else 'configured'}")
    print("=" * 50)

    yield

    # ── Shutdown ─────────────────────────────────────────
    print("🛑 AI Bridge Shutting Down...")
    # Cleanup database connections
    from app.database import engine
    await engine.dispose()


app = FastAPI(
    title="AI Bridge — ERP BCS",
    description="Jembatan AI antara Frontend SvelteKit dan Openclaw LLM dengan akses langsung ke PostgreSQL.",
    version="1.0.0",
    lifespan=lifespan,
)

# ── CORS Middleware ──────────────────────────────────────────
# Izinkan SvelteKit (frontend) untuk memanggil service ini
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:5173",         # SvelteKit dev
        "http://localhost:3000",         # SvelteKit production
        "http://erp.bcslabs.tech",       # Production domain
        "https://erp.bcslabs.tech",
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ── Register Routers ────────────────────────────────────────
app.include_router(chat_router, tags=["Chat"])


# ── Root Endpoint ────────────────────────────────────────────
@app.get("/")
async def root():
    return {
        "service": "AI Bridge — ERP BCS",
        "version": "1.0.0",
        "status": "running",
        "model": settings.openclaw_model,
        "docs": "/docs",
    }
