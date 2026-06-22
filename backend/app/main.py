from fastapi import FastAPI

from app.agent.router import router as agent_router
from app.analytics.router import router as analytics_router
from app.annotations.router import router as annotations_router
from app.auth.router import router as auth_router
from app.chat.router import router as chat_router
from app.pricing.router import router as pricing_router
from app.rag.router import router as rag_router
from app.reviews.router import router as reviews_router
from app.siteplanning.router import router as siteplanning_router

app = FastAPI(title="3W Revamped API")
app.include_router(auth_router)
app.include_router(annotations_router)
app.include_router(chat_router)
app.include_router(pricing_router)
app.include_router(reviews_router)
app.include_router(analytics_router)
app.include_router(siteplanning_router)
app.include_router(agent_router)
app.include_router(rag_router)


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}
