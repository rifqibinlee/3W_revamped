from app.auth import service as auth_service
from app.auth.models import Role
from app.chat import service


def _user(db_session, username: str):
    return auth_service.register_user(db_session, username, f"{username}@example.com", "password123", Role.STAFF)


def test_get_or_create_direct_conversation_is_idempotent(db_session) -> None:
    alice = _user(db_session, "alice_chat")
    bob = _user(db_session, "bob_chat")

    conv1 = service.get_or_create_direct_conversation(db_session, alice.id, bob.id)
    conv2 = service.get_or_create_direct_conversation(db_session, bob.id, alice.id)

    assert conv1.id == conv2.id
    assert conv1.is_group is False


def test_two_separate_pairs_get_separate_conversations(db_session) -> None:
    alice = _user(db_session, "alice2_chat")
    bob = _user(db_session, "bob2_chat")
    carol = _user(db_session, "carol2_chat")

    conv_ab = service.get_or_create_direct_conversation(db_session, alice.id, bob.id)
    conv_ac = service.get_or_create_direct_conversation(db_session, alice.id, carol.id)

    assert conv_ab.id != conv_ac.id


def test_send_and_list_messages(db_session) -> None:
    alice = _user(db_session, "alice3_chat")
    bob = _user(db_session, "bob3_chat")
    conv = service.get_or_create_direct_conversation(db_session, alice.id, bob.id)

    service.send_message(db_session, conv.id, alice.id, "hey")
    service.send_message(db_session, conv.id, bob.id, "hi back")

    messages = service.list_messages(db_session, conv.id, alice.id)
    assert [m.body for m in messages] == ["hey", "hi back"]


def test_non_participant_cannot_send_or_list(db_session) -> None:
    alice = _user(db_session, "alice4_chat")
    bob = _user(db_session, "bob4_chat")
    eve = _user(db_session, "eve4_chat")
    conv = service.get_or_create_direct_conversation(db_session, alice.id, bob.id)

    try:
        service.send_message(db_session, conv.id, eve.id, "intruding")
        assert False, "expected NotAParticipantError"
    except service.NotAParticipantError:
        pass

    try:
        service.list_messages(db_session, conv.id, eve.id)
        assert False, "expected NotAParticipantError"
    except service.NotAParticipantError:
        pass


def test_group_conversation_with_multiple_participants(db_session) -> None:
    alice = _user(db_session, "alice5_chat")
    bob = _user(db_session, "bob5_chat")
    carol = _user(db_session, "carol5_chat")

    conv = service.create_group_conversation(db_session, "Team chat", [alice.id, bob.id, carol.id])
    assert conv.is_group is True

    service.send_message(db_session, conv.id, carol.id, "team update")
    messages = service.list_messages(db_session, conv.id, bob.id)
    assert messages[0].body == "team update"


def test_unread_count_tracks_per_user(db_session) -> None:
    alice = _user(db_session, "alice6_chat")
    bob = _user(db_session, "bob6_chat")
    conv = service.get_or_create_direct_conversation(db_session, alice.id, bob.id)

    msg1 = service.send_message(db_session, conv.id, alice.id, "one")
    service.send_message(db_session, conv.id, alice.id, "two")

    assert service.unread_count(db_session, conv.id, bob.id) == 2
    service.mark_read(db_session, msg1.id, bob.id)
    assert service.unread_count(db_session, conv.id, bob.id) == 1


def test_mark_read_is_idempotent(db_session) -> None:
    alice = _user(db_session, "alice7_chat")
    bob = _user(db_session, "bob7_chat")
    conv = service.get_or_create_direct_conversation(db_session, alice.id, bob.id)
    msg = service.send_message(db_session, conv.id, alice.id, "hello")

    read1 = service.mark_read(db_session, msg.id, bob.id)
    read2 = service.mark_read(db_session, msg.id, bob.id)
    assert read1.id == read2.id


def test_list_my_conversations_excludes_others(db_session) -> None:
    alice = _user(db_session, "alice8_chat")
    bob = _user(db_session, "bob8_chat")
    eve = _user(db_session, "eve8_chat")
    conv_ab = service.get_or_create_direct_conversation(db_session, alice.id, bob.id)
    service.get_or_create_direct_conversation(db_session, bob.id, eve.id)

    conversations = service.list_my_conversations(db_session, alice.id)
    assert [c.id for c in conversations] == [conv_ab.id]


def test_list_my_conversations_orders_by_latest_message(db_session) -> None:
    alice = _user(db_session, "alice9_chat")
    bob = _user(db_session, "bob9_chat")
    carol = _user(db_session, "carol9_chat")
    conv_ab = service.get_or_create_direct_conversation(db_session, alice.id, bob.id)
    conv_ac = service.get_or_create_direct_conversation(db_session, alice.id, carol.id)

    service.send_message(db_session, conv_ab.id, alice.id, "first conversation, older")
    service.send_message(db_session, conv_ac.id, alice.id, "second conversation, newer")

    conversations = service.list_my_conversations(db_session, alice.id)
    assert [c.id for c in conversations] == [conv_ac.id, conv_ab.id]


def test_conversation_participant_ids(db_session) -> None:
    alice = _user(db_session, "alice10_chat")
    bob = _user(db_session, "bob10_chat")
    conv = service.get_or_create_direct_conversation(db_session, alice.id, bob.id)

    assert set(service.conversation_participant_ids(db_session, conv.id)) == {alice.id, bob.id}
