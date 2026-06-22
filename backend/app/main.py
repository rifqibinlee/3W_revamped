from fastapi import FastAPI

app = FastAPI(title="3W Revamped API")


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}
