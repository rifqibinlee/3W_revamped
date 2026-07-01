from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from app.agent.router import router as agent_router
from app.analytics.router import router as analytics_router
from app.annotations.router import router as annotations_router
from app.auth.router import router as auth_router
from app.chat.router import router as chat_router
from app.core.config import settings
from app.datamgmt.router import router as datamgmt_router
from app.geoserver.router import router as geoserver_router
from app.pricing.router import router as pricing_router
from app.rag.router import router as rag_router
from app.reviews.router import router as reviews_router
from app.siteplanning.router import router as siteplanning_router


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Install DuckDB httpfs extension once per process. Doing this per-connection
    # causes catalog write-write conflicts when multiple workers start concurrently.
    from app.ingestion.parquet_store import install_httpfs
    install_httpfs()
    yield


app = FastAPI(title="3W Revamped API", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(auth_router)
app.include_router(annotations_router)
app.include_router(chat_router)
app.include_router(pricing_router)
app.include_router(reviews_router)
app.include_router(analytics_router)
app.include_router(siteplanning_router)
app.include_router(agent_router)
app.include_router(rag_router)
app.include_router(datamgmt_router)
app.include_router(geoserver_router)

Path(settings.avatar_dir).mkdir(parents=True, exist_ok=True)
app.mount("/avatars", StaticFiles(directory=settings.avatar_dir), name="avatars")


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}
