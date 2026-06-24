import logging
import tempfile
from pathlib import Path

from fastapi import APIRouter, BackgroundTasks, Depends, UploadFile
from sqlalchemy.orm import Session

from app.auth.dependencies import get_current_user
from app.auth.models import User
from app.core.db import SessionLocal, get_db
from app.rag import service
from app.rag.models import KnowledgeChunk
from app.rag.schemas import SearchRequest, SearchResult

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/rag", tags=["rag"])


def _ingest_in_background(tmp_path: str, source_name: str) -> None:
    """Runs after the response is sent. Opens its own DB session — the
    request-scoped one from Depends(get_db) is already closed by the
    time a background task runs, same reasoning as every other module's
    'open your own connection' pattern in this codebase."""
    db = SessionLocal()
    try:
        count = service.ingest_pdf(db, tmp_path, source_name)
        logger.info("Ingested %d chunks from %s", count, source_name)
    except Exception:
        logger.exception("Failed to ingest %s", source_name)
    finally:
        db.close()
        Path(tmp_path).unlink(missing_ok=True)


@router.post("/ingest", status_code=202)
async def ingest(
    file: UploadFile,
    background_tasks: BackgroundTasks,
    user: User = Depends(get_current_user),
) -> dict[str, str]:
    tmp = tempfile.NamedTemporaryFile(suffix=".pdf", delete=False)
    tmp.write(await file.read())
    tmp.close()

    background_tasks.add_task(_ingest_in_background, tmp.name, file.filename or "uploaded.pdf")
    return {"status": "accepted", "source": file.filename or "uploaded.pdf"}


@router.post("/search", response_model=list[SearchResult])
def search(payload: SearchRequest, db: Session = Depends(get_db)) -> list[KnowledgeChunk]:
    return service.search(db, payload.query, payload.top_k)
