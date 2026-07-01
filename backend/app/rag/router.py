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


def _ingest_in_background(tmp_path: str, source_name: str, kind: str = "pdf") -> None:
    db = SessionLocal()
    try:
        if kind == "excel":
            count = service.ingest_excel(db, tmp_path, source_name)
        else:
            count = service.ingest_pdf(db, tmp_path, source_name)
        logger.info("Ingested %d chunks from %s", count, source_name)
    except Exception:
        logger.exception("Failed to ingest %s", source_name)
    finally:
        db.close()
        Path(tmp_path).unlink(missing_ok=True)


def _sync_s3_in_background() -> None:
    db = SessionLocal()
    try:
        results = service.sync_from_s3(db)
        for src, n in results.items():
            logger.info("S3 sync: ingested %d chunks from %s", n, src)
        logger.info("S3 sync complete: %d new files", len(results))
    except Exception:
        logger.exception("S3 sync failed")
    finally:
        db.close()


@router.post("/ingest", status_code=202)
async def ingest(
    file: UploadFile,
    background_tasks: BackgroundTasks,
    user: User = Depends(get_current_user),
) -> dict[str, str]:
    name = file.filename or "uploaded"
    suffix = Path(name).suffix.lower()
    kind = "excel" if suffix in (".xlsx", ".xls", ".xlsb", ".csv") else "pdf"
    tmp = tempfile.NamedTemporaryFile(suffix=suffix or ".pdf", delete=False)
    tmp.write(await file.read())
    tmp.close()
    background_tasks.add_task(_ingest_in_background, tmp.name, name, kind)
    return {"status": "accepted", "source": name}


@router.post("/sync-s3", status_code=202)
def sync_s3(
    background_tasks: BackgroundTasks,
    user: User = Depends(get_current_user),
) -> dict[str, str]:
    """Pulls new PDFs and Excel files from the S3 training-data prefixes
    and ingests any that aren't already in the knowledge base."""
    background_tasks.add_task(_sync_s3_in_background)
    return {"status": "accepted", "message": "S3 sync started in background"}


@router.post("/search", response_model=list[SearchResult])
def search(payload: SearchRequest, db: Session = Depends(get_db)) -> list[KnowledgeChunk]:
    return service.search(db, payload.query, payload.top_k)
