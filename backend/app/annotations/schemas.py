from datetime import datetime

from pydantic import BaseModel


class ProjectCreate(BaseModel):
    title: str
    description: str | None = None
    assignee_id: str | None = None


class AssignProjectRequest(BaseModel):
    assignee_id: str


class AnnotationCreate(BaseModel):
    geometry: dict
    label: str | None = None


class TaskCreate(BaseModel):
    title: str
    assignee_ids: list[str]
    due_date: datetime
    description: str | None = None


class RejectRequest(BaseModel):
    reason: str


class CommentCreate(BaseModel):
    body: str


class ProjectOut(BaseModel):
    id: str
    creator_id: str
    title: str
    description: str | None
    assignee_id: str | None
    conversation_id: str | None
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class AnnotationOut(BaseModel):
    id: str
    project_id: str
    creator_id: str
    label: str | None
    geometry: dict
    created_at: datetime

    model_config = {"from_attributes": True}


class TaskOut(BaseModel):
    id: str
    project_id: str
    creator_id: str
    title: str
    description: str | None
    assignee_ids: list[str]
    due_date: datetime
    status: str
    reviewed_by_id: str | None
    reviewed_at: datetime | None
    rejection_reason: str | None
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class CommentOut(BaseModel):
    id: str
    project_id: str
    author_id: str
    body: str
    created_at: datetime

    model_config = {"from_attributes": True}
