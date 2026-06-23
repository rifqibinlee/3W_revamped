import logging

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, UploadFile, status

from app.auth.dependencies import require_roles
from app.auth.models import Role, User
from app.datamgmt import service
from app.datamgmt.schemas import CategoryOut, FileOut, PipelineRunOut, PreviewOut

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/data-management", tags=["data-management"])

_admin_only = Depends(require_roles(Role.ADMIN))


@router.get("/categories", response_model=list[CategoryOut])
def list_categories(user: User = _admin_only) -> list[dict]:
    return service.list_categories()


@router.get("/categories/{category}/weeks", response_model=list[str])
def list_weeks(category: str, user: User = _admin_only) -> list[str]:
    return service.list_weeks(category)


@router.get("/categories/{category}/files", response_model=list[FileOut])
def list_files(category: str, week: str | None = None, user: User = _admin_only) -> list[dict]:
    try:
        return service.list_files(category, week)
    except service.UnknownCategoryError as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Unknown category") from exc
    except service.InvalidWeekError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc)) from exc


@router.post("/categories/{category}/files", status_code=status.HTTP_201_CREATED)
async def upload_file(
    category: str,
    file: UploadFile,
    week: str | None = None,
    user: User = _admin_only,
) -> dict:
    content = await file.read()
    try:
        service.save_file(category, week, file.filename or "upload", content)
    except service.UnknownCategoryError as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Unknown category") from exc
    except service.InvalidWeekError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc)) from exc
    except service.UnsupportedFileTypeError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, f"Unsupported file type: {exc}") from exc
    return {"filename": file.filename, "status": "uploaded"}


@router.delete("/categories/{category}/files/{filename}", status_code=status.HTTP_204_NO_CONTENT)
def delete_file(category: str, filename: str, week: str | None = None, user: User = _admin_only) -> None:
    try:
        service.delete_file(category, week, filename)
    except service.UnknownCategoryError as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Unknown category") from exc
    except service.InvalidWeekError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc)) from exc


@router.get("/categories/{category}/files/{filename}/preview", response_model=PreviewOut)
def preview_file(category: str, filename: str, week: str | None = None, user: User = _admin_only) -> dict:
    try:
        return service.preview_file(category, week, filename)
    except service.UnknownCategoryError as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Unknown category") from exc
    except service.InvalidWeekError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc)) from exc
    except FileNotFoundError as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "File not found") from exc
    except service.UnsupportedFileTypeError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, f"Unsupported file type: {exc}") from exc


def _run_pipeline_in_background() -> None:
    try:
        result = service.run_pipeline()
        logger.info("ETL pipeline run complete: %s", result)
    except Exception:
        logger.exception("ETL pipeline run failed")


@router.post("/run-pipeline", response_model=PipelineRunOut)
def run_pipeline(background_tasks: BackgroundTasks, sync: bool = False, user: User = _admin_only) -> dict:
    """sync=True runs inline and returns the real result (useful for
    tests and for an admin who wants to see exactly what happened);
    the default fire-and-forget mode matches the RAG ingest endpoint's
    pattern for anything that might take a while."""
    if sync:
        return service.run_pipeline()
    background_tasks.add_task(_run_pipeline_in_background)
    return {"stages_run": [], "stages_skipped": ["pipeline queued — running in background"]}
