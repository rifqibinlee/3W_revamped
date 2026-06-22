from datetime import datetime

from pydantic import BaseModel


class GroupConversationCreate(BaseModel):
    title: str
    participant_ids: list[str]


class DirectConversationCreate(BaseModel):
    other_user_id: str


class MessageCreate(BaseModel):
    body: str


class ConversationOut(BaseModel):
    id: str
    is_group: bool
    title: str | None
    created_at: datetime

    model_config = {"from_attributes": True}


class MessageOut(BaseModel):
    id: str
    conversation_id: str
    sender_id: str
    body: str
    created_at: datetime

    model_config = {"from_attributes": True}
