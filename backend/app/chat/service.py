from datetime import datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.chat.models import Conversation, ConversationParticipant, Message, MessageRead


class NotAParticipantError(Exception):
    pass


def _participant_ids(db: Session, conversation_id: str) -> set[str]:
    return set(
        db.scalars(
            select(ConversationParticipant.user_id).where(
                ConversationParticipant.conversation_id == conversation_id
            )
        )
    )


def _require_participant(db: Session, conversation_id: str, user_id: str) -> None:
    if user_id not in _participant_ids(db, conversation_id):
        raise NotAParticipantError(f"user {user_id} is not a participant in conversation {conversation_id}")


def get_or_create_direct_conversation(db: Session, user_a_id: str, user_b_id: str) -> Conversation:
    """Finds an existing 1:1 conversation between exactly these two users,
    or creates one. Used both for ad-hoc DMs and to auto-create a task's
    chat room when it's assigned."""
    candidate_ids = db.scalars(
        select(ConversationParticipant.conversation_id)
        .where(ConversationParticipant.user_id.in_([user_a_id, user_b_id]))
        .where(Conversation.id == ConversationParticipant.conversation_id)
        .where(Conversation.is_group.is_(False))
    )
    for conversation_id in candidate_ids:
        if _participant_ids(db, conversation_id) == {user_a_id, user_b_id}:
            conversation = db.get(Conversation, conversation_id)
            assert conversation is not None, f"conversation {conversation_id} vanished between query and get"
            return conversation

    conversation = Conversation(is_group=False)
    db.add(conversation)
    db.flush()
    db.add_all([
        ConversationParticipant(conversation_id=conversation.id, user_id=user_a_id),
        ConversationParticipant(conversation_id=conversation.id, user_id=user_b_id),
    ])
    db.commit()
    db.refresh(conversation)
    return conversation


def create_group_conversation(db: Session, title: str, participant_ids: list[str]) -> Conversation:
    conversation = Conversation(is_group=True, title=title)
    db.add(conversation)
    db.flush()
    db.add_all(
        ConversationParticipant(conversation_id=conversation.id, user_id=uid) for uid in set(participant_ids)
    )
    db.commit()
    db.refresh(conversation)
    return conversation


def list_my_conversations(db: Session, user_id: str) -> list[Conversation]:
    """Conversations the user participates in, most-recently-active first
    (by last message, falling back to creation time for empty ones)."""
    conversation_ids = list(
        db.scalars(select(ConversationParticipant.conversation_id).where(ConversationParticipant.user_id == user_id))
    )
    if not conversation_ids:
        return []
    conversations = list(db.scalars(select(Conversation).where(Conversation.id.in_(conversation_ids))))

    last_message_at: dict[str, datetime | None] = {}
    for conversation_id in conversation_ids:
        last = db.scalar(
            select(Message.created_at)
            .where(Message.conversation_id == conversation_id)
            .order_by(Message.created_at.desc())
            .limit(1)
        )
        last_message_at[conversation_id] = last

    conversations.sort(key=lambda c: last_message_at.get(c.id) or c.created_at, reverse=True)
    return conversations


def conversation_participant_ids(db: Session, conversation_id: str) -> list[str]:
    return list(_participant_ids(db, conversation_id))


def send_message(db: Session, conversation_id: str, sender_id: str, body: str) -> Message:
    _require_participant(db, conversation_id, sender_id)
    message = Message(conversation_id=conversation_id, sender_id=sender_id, body=body)
    db.add(message)
    db.commit()
    db.refresh(message)
    return message


def list_messages(db: Session, conversation_id: str, user_id: str) -> list[Message]:
    _require_participant(db, conversation_id, user_id)
    stmt = (
        select(Message)
        .where(Message.conversation_id == conversation_id)
        .order_by(Message.created_at)
    )
    return list(db.scalars(stmt))


def mark_read(db: Session, message_id: str, user_id: str) -> MessageRead:
    existing = db.scalar(
        select(MessageRead).where(MessageRead.message_id == message_id, MessageRead.user_id == user_id)
    )
    if existing:
        return existing
    read = MessageRead(message_id=message_id, user_id=user_id)
    db.add(read)
    db.commit()
    db.refresh(read)
    return read


def unread_count(db: Session, conversation_id: str, user_id: str) -> int:
    _require_participant(db, conversation_id, user_id)
    all_message_ids = set(
        db.scalars(select(Message.id).where(Message.conversation_id == conversation_id))
    )
    read_message_ids = set(
        db.scalars(
            select(MessageRead.message_id).where(
                MessageRead.user_id == user_id, MessageRead.message_id.in_(all_message_ids)
            )
        )
    )
    return len(all_message_ids - read_message_ids)
