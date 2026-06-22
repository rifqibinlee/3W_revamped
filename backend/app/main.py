from fastapi import FastAPI

from app.annotations.router import router as annotations_router
from app.auth.router import router as auth_router
from app.chat.router import router as chat_router

app = FastAPI(title="3W Revamped API")
app.include_router(auth_router)
app.include_router(annotations_router)
app.include_router(chat_router)


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}
