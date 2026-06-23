from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.annotations import service
from app.annotations.models import Annotation, Project, Task
from app.annotations.schemas import (
    AnnotationCreate,
    AnnotationOut,
    AssignProjectRequest,
    CommentCreate,
    CommentOut,
    ProjectCreate,
    ProjectOut,
    RejectRequest,
    TaskCreate,
    TaskOut,
)
from app.auth.dependencies import get_current_user
from app.auth.models import User
from app.core.db import get_db

router = APIRouter(tags=["annotations"])


def _get_project_or_404(db: Session, project_id: str) -> Project:
    try:
        return service.get_project(db, project_id)
    except service.NotFoundError as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Project not found") from exc


def _get_task_or_404(db: Session, task_id: str) -> Task:
    try:
        return service.get_task(db, task_id)
    except service.NotFoundError as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Task not found") from exc


def _handle_domain_errors(fn, *args, **kwargs):
    try:
        return fn(*args, **kwargs)
    except service.InvalidTransitionError as exc:
        raise HTTPException(status.HTTP_409_CONFLICT, str(exc)) from exc
    except service.PermissionDeniedError as exc:
        raise HTTPException(status.HTTP_403_FORBIDDEN, str(exc)) from exc
    except service.NotAProjectError as exc:
        raise HTTPException(status.HTTP_409_CONFLICT, str(exc)) from exc


@router.post("/projects", response_model=ProjectOut, status_code=status.HTTP_201_CREATED)
def create_project(payload: ProjectCreate, user: User = Depends(get_current_user), db: Session = Depends(get_db)) -> Project:
    return service.create_project(db, user, payload.title, payload.description, payload.assignee_id)


@router.get("/projects", response_model=list[ProjectOut])
def list_projects(db: Session = Depends(get_db)) -> list[Project]:
    return service.list_projects(db)


@router.get("/projects/{project_id}", response_model=ProjectOut)
def get_project(project_id: str, db: Session = Depends(get_db)) -> Project:
    return _get_project_or_404(db, project_id)


@router.post("/projects/{project_id}/assign", response_model=ProjectOut)
def assign_project(project_id: str, payload: AssignProjectRequest, db: Session = Depends(get_db)) -> Project:
    project = _get_project_or_404(db, project_id)
    return service.assign_project(db, project, payload.assignee_id)


@router.post("/projects/{project_id}/annotations", response_model=AnnotationOut, status_code=status.HTTP_201_CREATED)
def add_annotation(project_id: str, payload: AnnotationCreate, user: User = Depends(get_current_user), db: Session = Depends(get_db)) -> Annotation:
    project = _get_project_or_404(db, project_id)
    return service.add_annotation(db, project, user, payload.geometry, payload.label)


@router.get("/projects/{project_id}/annotations", response_model=list[AnnotationOut])
def list_annotations(project_id: str, db: Session = Depends(get_db)) -> list[Annotation]:
    return service.list_annotations(db, project_id)


@router.post("/projects/{project_id}/tasks", response_model=TaskOut, status_code=status.HTTP_201_CREATED)
def create_task(project_id: str, payload: TaskCreate, user: User = Depends(get_current_user), db: Session = Depends(get_db)) -> Task:
    project = _get_project_or_404(db, project_id)
    return _handle_domain_errors(
        service.create_task, db, project, user, payload.title, payload.assignee_id, payload.due_date, payload.description,
    )


@router.post("/projects/{project_id}/comments", response_model=CommentOut, status_code=status.HTTP_201_CREATED)
def add_comment(project_id: str, payload: CommentCreate, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    project = _get_project_or_404(db, project_id)
    return service.add_comment(db, project, user, payload.body)


@router.get("/tasks/gantt/rows", response_model=list[TaskOut])
def gantt(assignee_id: str | None = None, db: Session = Depends(get_db)) -> list[Task]:
    return service.gantt_rows(db, assignee_id)


@router.post("/tasks/{task_id}/start", response_model=TaskOut)
def start(task_id: str, user: User = Depends(get_current_user), db: Session = Depends(get_db)) -> Task:
    task = _get_task_or_404(db, task_id)
    return _handle_domain_errors(service.start_progress, db, task, user)


@router.post("/tasks/{task_id}/submit", response_model=TaskOut)
def submit(task_id: str, user: User = Depends(get_current_user), db: Session = Depends(get_db)) -> Task:
    task = _get_task_or_404(db, task_id)
    return _handle_domain_errors(service.submit_for_review, db, task, user)


@router.post("/tasks/{task_id}/approve", response_model=TaskOut)
def approve(task_id: str, user: User = Depends(get_current_user), db: Session = Depends(get_db)) -> Task:
    task = _get_task_or_404(db, task_id)
    return _handle_domain_errors(service.approve, db, task, user)


@router.post("/tasks/{task_id}/reject", response_model=TaskOut)
def reject(task_id: str, payload: RejectRequest, user: User = Depends(get_current_user), db: Session = Depends(get_db)) -> Task:
    task = _get_task_or_404(db, task_id)
    return _handle_domain_errors(service.reject, db, task, user, payload.reason)
