from datetime import datetime

from pydantic import BaseModel


class AnnotationCreate(BaseModel):
    title: str
    geometry: dict
    description: str | None = None
    priority: str | None = None
    assignee_id: str | None = None
    due_date: datetime | None = None


class AssignTaskRequest(BaseModel):
    assignee_id: str
    due_date: datetime


class RejectRequest(BaseModel):
    reason: str


class CommentCreate(BaseModel):
    body: str


class AnnotationOut(BaseModel):
    id: str
    creator_id: str
    title: str
    description: str | None
    geometry: dict
    priority: str | None
    assignee_id: str | None
    due_date: datetime | None
    status: str | None
    reviewed_by_id: str | None
    reviewed_at: datetime | None
    rejection_reason: str | None
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class CommentOut(BaseModel):
    id: str
    annotation_id: str
    author_id: str
    body: str
    created_at: datetime

    model_config = {"from_attributes": True}
