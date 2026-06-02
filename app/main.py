"""
AI Bridge — FastAPI Entry Point
─────────────────────────────────────────
Service ini menjadi jembatan antara:
  Frontend (SvelteKit) ↔ AI LLM (Groq/OpenAI-compatible) ↔ Database (PostgreSQL)

Jalankan:
  uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload
"""

from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.config import get_settings
from app.routers.chat import router as chat_router
from app.routers.fms_chat import router as fms_chat_router
from app.routers.anomaly import router as anomaly_router
from app.routers.dispatch import router as dispatch_router
from app.routers.maintenance import router as maintenance_router
from app.routers.scoring import router as scoring_router
from app.routers.trip_summary import router as trip_summary_router

settings = get_settings()


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Startup dan shutdown events."""
    # ── Startup ──────────────────────────────────────────
    print("=" * 50)
    print("🚀 AI Bridge Starting...")
    print(f"   Model    : {settings.llm_model}")
    print(f"   LLM URL  : {settings.llm_base_url}")
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
    description="Jembatan AI antara Frontend SvelteKit dan LLM Provider (OpenAI-compatible) dengan akses langsung ke PostgreSQL.",
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
app.include_router(chat_router, tags=["HRIS Chat"])
app.include_router(fms_chat_router, prefix="/fms", tags=["FMS Chat"])
app.include_router(anomaly_router, prefix="/fms", tags=["FMS Intelligence"])
app.include_router(dispatch_router, prefix="/fms", tags=["FMS Dispatch Intelligence"])
app.include_router(maintenance_router, prefix="/fms", tags=["FMS Maintenance Intelligence"])
app.include_router(scoring_router, prefix="/fms", tags=["FMS Driver Scoring"])
app.include_router(trip_summary_router, prefix="/fms", tags=["FMS Trip Summary"])


# ── Root Endpoint ────────────────────────────────────────────
@app.get("/")
async def root():
    return {
        "service": "AI Bridge — ERP BCS",
        "version": "1.0.0",
        "status": "running",
        "model": settings.llm_model,
        "docs": "/docs",
    }
