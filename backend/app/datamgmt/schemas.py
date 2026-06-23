from datetime import datetime

from pydantic import BaseModel


class CategoryOut(BaseModel):
    key: str
    label: str
    weekly: bool
    file_count: int


class FileOut(BaseModel):
    filename: str
    size_bytes: int
    modified_at: datetime


class PreviewOut(BaseModel):
    columns: list[str]
    rows: list[list[object]]
    truncated: bool


class PipelineRunOut(BaseModel):
    stages_run: list[str]
    stages_skipped: list[str]
