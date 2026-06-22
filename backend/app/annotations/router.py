from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.annotations import service
from app.annotations.models import Annotation
from app.annotations.schemas import (
    AnnotationCreate,
    AnnotationOut,
    AssignTaskRequest,
    CommentCreate,
    CommentOut,
    RejectRequest,
)
from app.auth.dependencies import get_current_user
from app.auth.models import User
from app.core.db import get_db

router = APIRouter(prefix="/annotations", tags=["annotations"])


def _get_or_404(db: Session, annotation_id: str) -> Annotation:
    try:
        return service.get_annotation(db, annotation_id)
    except service.NotFoundError as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Annotation not found") from exc


def _handle_domain_errors(fn, *args, **kwargs):
    try:
        return fn(*args, **kwargs)
    except service.InvalidTransitionError as exc:
        raise HTTPException(status.HTTP_409_CONFLICT, str(exc)) from exc
    except service.PermissionDeniedError as exc:
        raise HTTPException(status.HTTP_403_FORBIDDEN, str(exc)) from exc


@router.post("", response_model=AnnotationOut, status_code=status.HTTP_201_CREATED)
def create(payload: AnnotationCreate, user: User = Depends(get_current_user), db: Session = Depends(get_db)) -> Annotation:
    return service.create_annotation(
        db, user, payload.title, payload.geometry, payload.description,
        payload.priority, payload.assignee_id, payload.due_date,
    )


@router.get("/{annotation_id}", response_model=AnnotationOut)
def get(annotation_id: str, db: Session = Depends(get_db)) -> Annotation:
    return _get_or_404(db, annotation_id)


@router.post("/{annotation_id}/assign", response_model=AnnotationOut)
def assign(annotation_id: str, payload: AssignTaskRequest, db: Session = Depends(get_db)) -> Annotation:
    annotation = _get_or_404(db, annotation_id)
    return service.assign_task(db, annotation, payload.assignee_id, payload.due_date)


@router.post("/{annotation_id}/start", response_model=AnnotationOut)
def start(annotation_id: str, user: User = Depends(get_current_user), db: Session = Depends(get_db)) -> Annotation:
    annotation = _get_or_404(db, annotation_id)
    return _handle_domain_errors(service.start_progress, db, annotation, user)


@router.post("/{annotation_id}/submit", response_model=AnnotationOut)
def submit(annotation_id: str, user: User = Depends(get_current_user), db: Session = Depends(get_db)) -> Annotation:
    annotation = _get_or_404(db, annotation_id)
    return _handle_domain_errors(service.submit_for_review, db, annotation, user)


@router.post("/{annotation_id}/approve", response_model=AnnotationOut)
def approve(annotation_id: str, user: User = Depends(get_current_user), db: Session = Depends(get_db)) -> Annotation:
    annotation = _get_or_404(db, annotation_id)
    return _handle_domain_errors(service.approve, db, annotation, user)


@router.post("/{annotation_id}/reject", response_model=AnnotationOut)
def reject(annotation_id: str, payload: RejectRequest, user: User = Depends(get_current_user), db: Session = Depends(get_db)) -> Annotation:
    annotation = _get_or_404(db, annotation_id)
    return _handle_domain_errors(service.reject, db, annotation, user, payload.reason)


@router.post("/{annotation_id}/comments", response_model=CommentOut, status_code=status.HTTP_201_CREATED)
def add_comment(annotation_id: str, payload: CommentCreate, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    annotation = _get_or_404(db, annotation_id)
    return service.add_comment(db, annotation, user, payload.body)


@router.get("/gantt/rows", response_model=list[AnnotationOut])
def gantt(assignee_id: str | None = None, db: Session = Depends(get_db)) -> list[Annotation]:
    return service.gantt_rows(db, assignee_id)
