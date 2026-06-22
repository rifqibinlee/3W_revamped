from fastapi import FastAPI

from app.annotations.router import router as annotations_router
from app.auth.router import router as auth_router

app = FastAPI(title="3W Revamped API")
app.include_router(auth_router)
app.include_router(annotations_router)


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}
