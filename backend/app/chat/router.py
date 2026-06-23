from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.auth.dependencies import get_current_user
from app.auth.models import User
from app.chat import service
from app.chat.models import Conversation, Message
from app.chat.schemas import (
    ConversationOut,
    DirectConversationCreate,
    GroupConversationCreate,
    MessageCreate,
    MessageOut,
)
from app.core.db import get_db

router = APIRouter(prefix="/chat", tags=["chat"])


@router.get("/conversations", response_model=list[ConversationOut])
def list_conversations(user: User = Depends(get_current_user), db: Session = Depends(get_db)) -> list[Conversation]:
    conversations = service.list_my_conversations(db, user.id)
    for c in conversations:
        c.participant_ids = service.conversation_participant_ids(db, c.id)  # type: ignore[attr-defined]
    return conversations


@router.post("/conversations/direct", response_model=ConversationOut, status_code=status.HTTP_201_CREATED)
def create_direct(payload: DirectConversationCreate, user: User = Depends(get_current_user), db: Session = Depends(get_db)) -> Conversation:
    return service.get_or_create_direct_conversation(db, user.id, payload.other_user_id)


@router.post("/conversations/group", response_model=ConversationOut, status_code=status.HTTP_201_CREATED)
def create_group(payload: GroupConversationCreate, user: User = Depends(get_current_user), db: Session = Depends(get_db)) -> Conversation:
    participant_ids = set(payload.participant_ids) | {user.id}
    return service.create_group_conversation(db, payload.title, list(participant_ids))


@router.post("/conversations/{conversation_id}/messages", response_model=MessageOut, status_code=status.HTTP_201_CREATED)
def send_message(conversation_id: str, payload: MessageCreate, user: User = Depends(get_current_user), db: Session = Depends(get_db)) -> Message:
    try:
        return service.send_message(db, conversation_id, user.id, payload.body)
    except service.NotAParticipantError as exc:
        raise HTTPException(status.HTTP_403_FORBIDDEN, str(exc)) from exc


@router.get("/conversations/{conversation_id}/messages", response_model=list[MessageOut])
def list_messages(conversation_id: str, user: User = Depends(get_current_user), db: Session = Depends(get_db)) -> list[Message]:
    try:
        return service.list_messages(db, conversation_id, user.id)
    except service.NotAParticipantError as exc:
        raise HTTPException(status.HTTP_403_FORBIDDEN, str(exc)) from exc


@router.post("/messages/{message_id}/read", status_code=status.HTTP_204_NO_CONTENT)
def mark_read(message_id: str, user: User = Depends(get_current_user), db: Session = Depends(get_db)) -> None:
    service.mark_read(db, message_id, user.id)


@router.get("/conversations/{conversation_id}/unread-count")
def unread_count(conversation_id: str, user: User = Depends(get_current_user), db: Session = Depends(get_db)) -> dict[str, int]:
    try:
        return {"unread": service.unread_count(db, conversation_id, user.id)}
    except service.NotAParticipantError as exc:
        raise HTTPException(status.HTTP_403_FORBIDDEN, str(exc)) from exc
